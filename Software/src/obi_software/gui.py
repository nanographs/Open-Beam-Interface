import os
import argparse
import pathlib
import tomllib
import asyncio
import sys
import pyqtgraph as pg
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, 
                             QMessageBox, QPushButton, QComboBox,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QFileDialog, QLineEdit)

import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop

from .stream_interface import Connection, DACCodeRange, BeamType
from .frame_buffer import FrameBuffer
from .gui_modules.image_display import ImageDisplay
from .gui_modules.settings import SettingBox, SettingBoxWithDefaults, ImageSettings, BeamSettings

parser = argparse.ArgumentParser()
parser.add_argument('--config_path', required=True, 
                    type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
                    help='path to microscope.toml')
parser.add_argument("port")
parser.add_argument('--debug',action='store_true')
parser.add_argument('--window_size', type=int, nargs=2, help="GUI width in px, height in px")
args = parser.parse_args()
print(f"loading config from {args.config_path}")



class LiveSettings(ImageSettings):
    def __init__(self):
        super().__init__("Live")
        self.live_capture_btn = QPushButton("Start Live Scan")
        self.live_capture_btn.setCheckable(True)
        self.addWidget(self.live_capture_btn)
        self.save_btn = QPushButton("Save Live Image")
        self.addWidget(self.save_btn)

class PhotoSettings(ImageSettings):
    def __init__(self):
        super().__init__("Photo")
        self.single_capture_btn = QPushButton("Acquire Photo")
        self.addWidget(self.single_capture_btn)
        self.addWidget(QLabel(' '))
        # self.live_capture_btn = QPushButton("Start Live Scan")
        # self.live_capture_btn.setCheckable(True)
        # self.addWidget(self.live_capture_btn)
        # self.save_btn = QPushButton("Save Image")
        # self.addWidget(self.save_btn)

def si_prefix(distance:float):
    if 1 >= distance > pow(10, -3):
        return f"{distance*pow(10,3):.5f} mm"
    if pow(10, -3) >= distance > pow(10, -6):
        return f"{distance*pow(10,6):.5f} µm"
    if pow(10, -6) >= distance > pow(10, -9):
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

class SaveSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        cwd = os.getcwd()
        self.addWidget(QLabel("Save Path: "))
        self.path_txt = QLabel(cwd)
        self.addWidget(self.path_txt)
        self.file_btn = QPushButton("Change")
        self.addWidget(self.file_btn)
        self.file_name = QLineEdit()
        self.addWidget(QLabel("File Name: "))
        self.addWidget(self.file_name)
        

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

        self.live_settings = LiveSettings()
        self.live_settings.live_capture_btn.clicked.connect(self.capture_live)

        self.photo_settings = PhotoSettings()
        self.photo_settings.single_capture_btn.clicked.connect(self.capture_single_frame)

        combined_settings = QVBoxLayout()
        #self.beam_type_box = QComboBox()
        #self.beam_type_box.addItems(["Electron", "Ion"])
        #combined_settings.addWidget(self.beam_type_box)
        self.beam_settings = BeamSettings(self.conn)
        combined_settings.addLayout(self.beam_settings)
        combined_settings.addLayout(self.photo_settings)
        combined_settings.addLayout(self.live_settings)
        self.addLayout(combined_settings)

        
        self.live_settings.save_btn.clicked.connect(self.save_image)
        self.image_display = ImageDisplay(512,512)
        self.addWidget(self.image_display)
        self.dir_path = os.getcwd()
        self.image_data = ImageData()
        self.addLayout(self.image_data)
        self.image_data.measure_btn.clicked.connect(self.toggle_measure)
        self.save_settings = SaveSettings()
        self.save_settings.file_btn.clicked.connect(self.file_dialog)
        self.addLayout(self.save_settings)
        if self.debug:
            self.debug_settings = DebugSettings()
            self.addLayout(self.debug_settings)
            self.debug_settings.connect_btn.clicked.connect(self.toggle_connection)
            self.debug_settings.sync_btn.clicked.connect(self.request_sync)
            self.debug_settings.freescan_btn.clicked.connect(self.free_scan)
            self.debug_settings.interrupt_btn.clicked.connect(self.interrupt)

    @property
    def beam_type(self):
        return self.beam_settings.beam_type

    @property
    def live_parameters(self):
        x_res, y_res, dwell = self.live_settings.getval()
        if self.debug:
            latency = self.debug_settings.latency.getval()
        else:
            latency = 65536
        x_range = DACCodeRange(0, x_res, int((16384/x_res)*256))
        y_range = DACCodeRange(0, y_res, int((16384/y_res)*256))
        return x_range, y_range, dwell, latency
    
    @property
    def photo_parameters(self):
        x_res, y_res, dwell = self.photo_settings.getval()
        if self.debug:
            latency = self.debug_settings.latency.getval()
        else:
            latency = 65536
        x_range = DACCodeRange(0, x_res, int((16384/x_res)*256))
        y_range = DACCodeRange(0, y_res, int((16384/y_res)*256))
        return x_range, y_range, dwell, latency
    
    @property
    def hfov_m(self):
        if hasattr(self.config, "mag_cal"):
            mag = self.image_data.mag.getval()
            cal = self.config["mag_cal"]
            cal_factor = cal["m_per_FOV"]
            return cal_factor/mag
        else: 
            return None
    @property
    def pixel_size(self):
        mag = self.image_data.mag.getval()
        cal = self.config["mag_cal"]
        cal_factor = cal["m_per_FOV"]
        full_fov_pixels = max(self.fb.current_frame._x_count, self.fb.current_frame._y_count)
        pixel_size = cal_factor/mag/full_fov_pixels
        return pixel_size
    
    def file_dialog(self):
        self.dir_path = QFileDialog().getExistingDirectory()
        self.save_settings.path_txt.setText(self.dir_path)
    
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
    

    def measure(self):
        if not self.image_display.line == None:
            pixel_size = self.pixel_size
            line_length = self.image_display.get_line_length()
            line_actual_size = line_length*pixel_size
            self.image_data.measure_length.setText(si_prefix(line_actual_size))
        

    def display_image(self, array):
        x_width, y_height = array.shape
        self.image_display.setImage(y_height, x_width, array)


    def save_image(self):
        file_name = self.save_settings.file_name.text()
        if file_name == "":
            file_name = None
        if not self.fb.current_frame == None:
            if not self.hfov_m == None:
                self.fb.current_frame.saveImage_tifffile(save_dir=self.dir_path, img_name=file_name, bit_depth_8=True, scalebar_HFOV=self.hfov_m)
            else:
                self.fb.current_frame.saveImage_tifffile(save_dir=self.dir_path, img_name=file_name, bit_depth_8=True)


    @asyncSlot()
    async def capture_single_frame(self):
        self.live_settings.save_btn.setEnabled(False)
        self.live_settings.live_capture_btn.setEnabled(False)
        self.photo_settings.single_capture_btn.setText("Acquiring...")
        self.photo_settings.single_capture_btn.setEnabled(False)
        self.photo_settings.disable_input()
        self.live_settings.disable_input()
        self.beam_settings.disable_input()
        await self.fb.set_ext_ctrl(enable=1, beam_type=self.beam_type)
        print(f"{self.beam_type=}")
        await self.capture_frame_photo()
        await self.fb.set_ext_ctrl(enable=0, beam_type=self.beam_type)
        self.save_image()
        self.live_settings.live_capture_btn.setEnabled(True)
        self.photo_settings.single_capture_btn.setEnabled(True)
        self.live_settings.save_btn.setEnabled(True)
        self.photo_settings.single_capture_btn.setText("Acquire Photo")
        self.photo_settings.enable_input()
        self.live_settings.enable_input()
        self.beam_settings.enable_input()

    async def capture_frame_live(self):
        x_range, y_range, dwell, latency = self.live_parameters
        async for frame in self.fb.capture_frame(x_range, y_range, dwell=dwell, latency=latency):
            self.display_image(frame.as_uint8())
    
    async def capture_frame_photo(self):
        x_range, y_range, dwell, latency = self.photo_parameters
        async for frame in self.fb.capture_frame(x_range, y_range, dwell=dwell, latency=latency):
            self.display_image(frame.as_uint8())


    @asyncSlot()
    async def capture_live(self):
        if self.live_settings.live_capture_btn.isChecked():
            self.photo_settings.single_capture_btn.setEnabled(False)
            await self.fb.set_ext_ctrl(enable=1, beam_type=self.beam_type)
            self.fb._interrupt.clear()
            self.live_settings.disable_input()
            self.photo_settings.disable_input()
            self.beam_settings.disable_input()
            self.live_settings.live_capture_btn.setText("Stop Live Scan")
            while True:
                await self.capture_frame_live()
                if self.fb._interrupt.is_set():
                    break
            await self.fb.set_ext_ctrl(enable=0, beam_type=self.beam_type)
            self.photo_settings.single_capture_btn.setEnabled(True)
            self.live_settings.live_capture_btn.setEnabled(True)
            self.live_settings.live_capture_btn.setText("Start Live Scan")
            self.live_settings.enable_input()
            self.photo_settings.enable_input()
            self.beam_settings.enable_input()
        else:
            self.fb._interrupt.set()
            self.live_settings.live_capture_btn.setEnabled(False)
            self.live_settings.live_capture_btn.setText("Completing Frame...")
            
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
    if not args.window_size == None:
        w.resize(args.window_size[0], args.window_size[1])
    w.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())


if __name__ == "__main__":
    run_gui()

