import argparse
import pathlib
import tomllib
import asyncio
import sys
import pyqtgraph as pg
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow,
                             QMessageBox, QPushButton,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox)

import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop

from .beam_interface import Connection, DACCodeRange
from .frame_buffer import FrameBuffer
from .gui_modules.image_display import ImageDisplay

parser = argparse.ArgumentParser()
parser.add_argument('--config_path', required=True, 
                    type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
                    help='path to microscope.toml')
parser.add_argument("port")
parser.add_argument('--debug',action='store_true')
args = parser.parse_args()
print(f"loading config from {args.config_path}")

class SettingBox(QGridLayout):
    def __init__(self, label, lower_limit, upper_limit, initial_val):
        super().__init__()
        self.name = label
        self.label = QLabel(label)
        self.addWidget(self.label,0,1)

        self.spinbox = QSpinBox()
        self.spinbox.setRange(lower_limit, upper_limit)
        self.spinbox.setSingleStep(1)
        self.spinbox.setValue(initial_val)
        self.addWidget(self.spinbox,1,1)

    def getval(self):
        return int(self.spinbox.cleanText())

    def setval(self, val):
        self.spinbox.setValue(val)

class Settings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.rx = SettingBox("X Resolution",128, 16384, 512)
        self.addLayout(self.rx)
        self.ry = SettingBox("Y Resolution",128, 16384, 512)
        self.addLayout(self.ry)
        self.dwell = SettingBox("Dwell Time",0, 65536, 2)
        self.addLayout(self.dwell)
        self.single_capture_btn = QPushButton("Single Capture")
        self.addWidget(self.single_capture_btn)
        self.live_capture_btn = QPushButton("Start Live Scan")
        self.live_capture_btn.setCheckable(True)
        self.addWidget(self.live_capture_btn)
        self.save_btn = QPushButton("Save Image")
        self.addWidget(self.save_btn)
    def disable_input(self):
        self.rx.spinbox.setEnabled(False)
        self.ry.spinbox.setEnabled(False)
        self.dwell.spinbox.setEnabled(False)
        self.single_capture_btn.setEnabled(False)
    def enable_input(self):
        self.rx.spinbox.setEnabled(True)
        self.ry.spinbox.setEnabled(True)
        self.dwell.spinbox.setEnabled(True)
        self.single_capture_btn.setEnabled(True)

def si_prefix(distance:float):
    if pow(10, -3) >= distance > pow(10, -6):
        return f"{distance*pow(10,3):.5f} mm"
    if pow(10, -6) >= distance > pow(10, -9):
        return f"{distance*pow(10,6):.5f} µm"
    if pow(10, -9) >= distance > pow(10, -12):
        return f"{distance*pow(10,9):.5f} nm"
    else:
        return f"{distance:.5f} m"

class ImageData(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.mag = SettingBox("Magnification",1, 1000000, 1)
        self.addLayout(self.mag)
        self.measure_btn = QPushButton("Measure")
        self.measure_btn.setCheckable(True)
        self.addWidget(self.measure_btn)
        self.measure_length = QLabel("      ")
        self.addWidget(self.measure_length)
class DebugSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCheckable(True)
        self.addWidget(self.connect_btn)
        self.sync_btn = QPushButton("Sync")
        self.latency = SettingBox("Latency",0, pow(2,28), pow(2,16))
        self.addLayout(self.latency)
        self.freescan_btn = QPushButton("Free Scan")
        self.addWidget(self.freescan_btn)
        self.interrupt_btn = QPushButton("Interrupt")
        self.addWidget(self.interrupt_btn)


class Window(QVBoxLayout):
    def __init__(self,debug=False):
        super().__init__()
        self.debug = debug
        self.config = tomllib.load(open(args.config_path, "rb") )
        self.conn = Connection('localhost', int(args.port))
        self.fb = FrameBuffer(self.conn)

        self.settings = Settings()
        self.addLayout(self.settings)
        self.settings.single_capture_btn.clicked.connect(self.capture_single_frame)
        self.settings.live_capture_btn.clicked.connect(self.capture_live)
        self.settings.save_btn.clicked.connect(self.save_image)
        self.image_display = ImageDisplay(512,512)
        self.addWidget(self.image_display)
        self.image_data = ImageData()
        self.addLayout(self.image_data)
        self.image_data.measure_btn.clicked.connect(self.toggle_measure)
        if self.debug:
            self.debug_settings = DebugSettings()
            self.addLayout(self.debug_settings)
            self.debug_settings.connect_btn.clicked.connect(self.toggle_connection)
            self.debug_settings.sync_btn.clicked.connect(self.request_sync)
            self.debug_settings.freescan_btn.clicked.connect(self.free_scan)
            self.debug_settings.interrupt_btn.clicked.connect(self.interrupt)

    @property
    def parameters(self):
        x_res = self.settings.rx.getval()
        y_res = self.settings.ry.getval()
        dwell = self.settings.dwell.getval()
        if self.debug:
            latency = self.debug_settings.latency.getval()
        else:
            latency = 65536
        x_range = DACCodeRange(0, x_res, int((16384/x_res)*256))
        y_range = DACCodeRange(0, y_res, int((16384/y_res)*256))
        return x_range, y_range, dwell, latency
    
    def toggle_measure(self):
        if self.image_data.measure_btn.isChecked():
            self.image_display.add_line()
            self.image_display.line.sigRegionChanged.connect(self.measure)
            self.image_data.mag.spinbox.valueChanged.connect(self.measure)
            self.settings.rx.spinbox.valueChanged.connect(self.measure)
            self.settings.ry.spinbox.valueChanged.connect(self.measure)
            self.measure()
        else:
            self.image_display.remove_line()
            self.image_data.measure_length.setText("      ")
            self.image_data.mag.spinbox.valueChanged.disconnect(self.measure)
            self.settings.rx.spinbox.valueChanged.disconnect(self.measure)
            self.settings.ry.spinbox.valueChanged.disconnect(self.measure)

    def get_pixel_size(self):
        mag = self.image_data.mag.getval()
        cal = self.config["mag_cal"]
        cal_factor = cal["m_per_FOV"]
        full_fov_pixels = max(self.settings.rx.getval(), self.settings.ry.getval())
        pixel_size = cal_factor/mag/full_fov_pixels
        return pixel_size

    def measure(self):
        if not self.image_display.line == None:
            pixel_size = self.get_pixel_size()
            line_length = self.image_display.get_line_length()
            line_actual_size = line_length*pixel_size
            self.image_data.measure_length.setText(si_prefix(line_actual_size))
        

    def display_image(self, array):
        x_width, y_height = array.shape
        self.image_display.setImage(y_height, x_width, array)

    def save_image(self):
        self.fb.current_frame.saveImage_tifffile()

    @asyncSlot()
    async def capture_single_frame(self):
        await self.fb.set_ext_ctrl(1)
        await self.capture_frame()
        await self.fb.set_ext_ctrl(0)

    async def capture_frame(self):
        x_range, y_range, dwell, latency = self.parameters
        if self.debug:
            async for frame in self.fb.capture_frame(x_range, y_range, dwell=dwell, latency=latency):
                self.display_image(frame.as_uint8())
        else:
            frame = await self.fb.capture_frame(x_range, y_range, dwell=dwell, latency=latency)
            self.display_image(frame.as_uint8())

    @asyncSlot()
    async def capture_live(self):
        if self.settings.live_capture_btn.isChecked():
            await self.fb.set_ext_ctrl(1)
            self.fb._interrupt.clear()
            self.settings.disable_input()
            self.settings.live_capture_btn.setText("Stop Live Scan")
            while True:
                await self.capture_frame()
                if self.fb._interrupt.is_set():
                    break
            await self.fb.set_ext_ctrl(0)
        else:
            self.fb._interrupt.set()
            self.settings.live_capture_btn.setText("Start Live Scan")
            self.settings.enable_input()

    def interrupt(self):
        self.fb._interrupt.set()
        if self.debug:
            self.conn._interrupt_scan()

    #### Debug settings
    @asyncSlot()
    async def toggle_connection(self):
        if self.debug_settings.connect_btn.isChecked():
            await self.conn._connect()
            self.debug_settings.connect_btn.setText("Disconnect")
        else:
            self.conn._disconnect()
            self.debug_settings.connect_btn.setText("Connect")

    @asyncSlot()
    async def request_sync(self):
        await self.conn._synchronize()

    @asyncSlot()
    async def free_scan(self):
        x_range, y_range, dwell, latency = self.parameters
        await self.fb.set_ext_ctrl(1)
        async for frame in self.fb.free_scan(x_range, y_range, dwell=dwell, latency=latency):
            print("Got frame")
            self.display_image(frame.as_uint8())
        print("Concluded gui.free_scan")


def run_gui():
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    window = Window(debug=args.debug)
    w.setLayout(window)
    w.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())


if __name__ == "__main__":
    run_gui()
