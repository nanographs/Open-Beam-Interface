import threading
from queue import Queue, Empty, Full
import os
import argparse
import pathlib
import tomllib
import asyncio
import sys
import pyqtgraph as pg
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, 
                             QMessageBox, QPushButton,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QFileDialog, QLineEdit)
from PyQt6 import QtCore

import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop

from .beam_interface import *
from .ui_interface import *
from .threads import *
from .gui_modules.image_display import ImageDisplay
from .gui_modules.settings import SettingBox, SettingBoxWithDefaults

parser = argparse.ArgumentParser()
parser.add_argument('--config_path', required=True, 
                    type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
                    help='path to microscope.toml')
parser.add_argument("port")
parser.add_argument('--debug',action='store_true')
parser.add_argument('--window_size', type=int, nargs=2, help="GUI width in px, height in px")
args = parser.parse_args()
print(f"loading config from {args.config_path}")



class LiveSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.rx = SettingBoxWithDefaults("Live Resolution",128, 16384, 1024, ["512","1024", "2048", "4096", "8192", "16384", "Custom"])
        self.addLayout(self.rx)
        # self.ry = SettingBoxWithDefaults("Y Resolution",128, 16384, 512, ["512","1024", "2048", "4096", "8192", "16384", "Custom"])
        # self.addLayout(self.ry)
        self.dwell = SettingBoxWithDefaults("Live Scan Speed",0, 65536, 2, ["1","2", "4", "8", "16", "32", "Custom"])
        self.addLayout(self.dwell)
        # self.single_capture_btn = QPushButton("Acquire Photo")
        # self.addWidget(self.single_capture_btn)
        self.live_capture_btn = QPushButton("Start Live Scan")
        self.live_capture_btn.setCheckable(True)
        self.addWidget(self.live_capture_btn)
        self.save_btn = QPushButton("Save Live Image")
        self.addWidget(self.save_btn)
    def disable_input(self):
        self.rx.spinbox.setEnabled(False)
        self.rx.dropdown.setEnabled(False)
        # self.ry.spinbox.setEnabled(False)
        self.dwell.spinbox.setEnabled(False)
        self.dwell.dropdown.setEnabled(False)
        # self.single_capture_btn.setEnabled(False)
    def enable_input(self):
        self.rx.spinbox.setEnabled(True)
        self.rx.dropdown.setEnabled(True)
        # self.ry.spinbox.setEnabled(True)
        self.dwell.spinbox.setEnabled(True)
        self.dwell.dropdown.setEnabled(True)
        # self.single_capture_btn.setEnabled(True)

class PhotoSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.rx = SettingBoxWithDefaults("Photo Resolution",128, 16384, 4096, ["512","1024", "2048", "4096", "8192", "16384", "Custom"])
        self.addLayout(self.rx)
        # self.ry = SettingBoxWithDefaults("Y Resolution",128, 16384, 512, ["512","1024", "2048", "4096", "8192", "16384", "Custom"])
        # self.addLayout(self.ry)
        self.dwell = SettingBoxWithDefaults("Photo Scan Speed",0, 65536, 8, ["1","2", "4", "8", "16", "32", "Custom"])
        self.addLayout(self.dwell)
        self.single_capture_btn = QPushButton("Acquire Photo")
        self.addWidget(self.single_capture_btn)
        self.addWidget(QLabel(' '))
        # self.live_capture_btn = QPushButton("Start Live Scan")
        # self.live_capture_btn.setCheckable(True)
        # self.addWidget(self.live_capture_btn)
        # self.save_btn = QPushButton("Save Image")
        # self.addWidget(self.save_btn)
    def disable_input(self):
        self.rx.spinbox.setEnabled(False)
        self.rx.dropdown.setEnabled(False)
        # self.ry.spinbox.setEnabled(False)
        self.dwell.spinbox.setEnabled(False)
        self.dwell.dropdown.setEnabled(False)
    def enable_input(self):
        self.rx.spinbox.setEnabled(True)
        self.rx.dropdown.setEnabled(True)
        # self.ry.spinbox.setEnabled(True)
        self.dwell.spinbox.setEnabled(True)
        self.dwell.dropdown.setEnabled(True)

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
        # self.measure_btn = QPushButton("Measure")
        # self.measure_btn.setCheckable(True)
        # self.addWidget(self.measure_btn)
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
    def __init__(self,iface, frame_queue, debug=False):
        super().__init__()
        self.debug = debug
        self.config = tomllib.load(open(args.config_path, "rb") )
        self.conn = Connection('localhost', int(args.port))
        self.fb = FrameBuffer(self.conn)
        self.db = DisplayBuffer()
        self.frame_queue = frame_queue
        self.live_settings = LiveSettings()
        self.live_settings.live_capture_btn.clicked.connect(self.capture_live)

        self.photo_settings = PhotoSettings()
        self.photo_settings.single_capture_btn.clicked.connect(self.capture_single_frame)

        combined_settings = QHBoxLayout()
        combined_settings.addLayout(self.photo_settings)
        combined_settings.addLayout(self.live_settings)
        self.addLayout(combined_settings)
        
        self.live_settings.save_btn.clicked.connect(self.save_image)
        self.image_display = ImageDisplay(512,512)
        self.addWidget(self.image_display)
        self.dir_path = os.getcwd()
        self.image_data = ImageData()
        self.addLayout(self.image_data)
        # self.image_data.measure_btn.clicked.connect(self.toggle_measure)
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
    def live_parameters(self):
        x_res = self.live_settings.rx.getval()
        # y_res = self.settings.ry.getval()
        y_res = x_res
        dwell = self.live_settings.dwell.getval()
        if self.debug:
            latency = self.debug_settings.latency.getval()
        else:
            latency = 65536
        x_range = DACCodeRange(0, x_res, int((16384/x_res)*256))
        y_range = DACCodeRange(0, y_res, int((16384/y_res)*256))
        return x_range, y_range, dwell, latency
    
    @property
    def photo_parameters(self):
        x_res = self.photo_settings.rx.getval()
        # y_res = self.settings.ry.getval()
        y_res = x_res
        dwell = self.photo_settings.dwell.getval()
        if self.debug:
            latency = self.debug_settings.latency.getval()
        else:
            latency = 65536
        x_range = DACCodeRange(0, x_res, int((16384/x_res)*256))
        y_range = DACCodeRange(0, y_res, int((16384/y_res)*256))
        return x_range, y_range, dwell, latency
    
    def file_dialog(self):
        self.dir_path = QFileDialog().getExistingDirectory()
        self.save_settings.path_txt.setText(self.dir_path)
    
    def set_directory(self):
        print("Directory")
        # print(f"{directory=}")
    
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
        # full_fov_pixels = max(self.settings.rx.getval(), self.settings.ry.getval())
        full_fov_pixels = self.settings.rx.getval()
        pixel_size = cal_factor/mag/full_fov_pixels
        return pixel_size
    
    def get_hfov_m(self):
        mag = self.image_data.mag.getval()
        cal = self.config["mag_cal"]
        cal_factor = cal["m_per_FOV"]
        return cal_factor/mag

    def measure(self):
        if not self.image_display.line == None:
            pixel_size = self.get_pixel_size()
            line_length = self.image_display.get_line_length()
            line_actual_size = line_length*pixel_size
            self.image_data.measure_length.setText(si_prefix(line_actual_size))
        

    def display_image(self, array, y_ptr):
        x_width, y_height = array.shape
        print(array)
        print(f"{array.shape=}")
        try:
            self.image_display.setImage(y_height, x_width, array, y_ptr)
        except Exception as e:
            print(f"display error: {e}")
    
    def display_frame(self):
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(1)
    
    def update_frame(self):
        if not self.frame_queue.empty():
            frame = self.frame_queue.get()
            array = frame.as_uint8()
            x_width, y_height = array.shape
            self.image_display.setImage(y_height, x_width, array, frame.y_ptr)
            print(array)
            print(f"{array.shape=}")
            self.frame_queue.task_done()
        self.display_frame()



    def save_image(self):
        file_name = self.save_settings.file_name.text()
        if file_name == "":
            file_name = None
        if not self.fb.current_frame == None:
            self.fb.current_frame.saveImage_tifffile(save_dir=self.dir_path, img_name=file_name, 
                                                    scalebar_HFOV=self.get_hfov_m())

    def capture_single_frame(self):
        self.live_settings.save_btn.setEnabled(False)
        self.live_settings.live_capture_btn.setEnabled(False)
        self.photo_settings.single_capture_btn.setText("Acquiring...")
        self.photo_settings.single_capture_btn.setEnabled(False)
        self.photo_settings.disable_input()
        self.live_settings.disable_input()
        # await self.fb.set_ext_ctrl(1)
        # await self.capture_frame_photo()
        # await self.fb.set_ext_ctrl(0)
        print("Hello")
        x_range, y_range, dwell, latency = self.parameters
        self.db.prepare_display(x_range, y_range, dwell=dwell, latency=latency)
        submit_async(self.fb.capture_single_frame(x_range, y_range, dwell=dwell, latency=latency))
        print("submitted async")
        print("starting thread")
        threading.Thread(group=None, target=self.display_frame).start()
        
        self.save_image()
        self.live_settings.live_capture_btn.setEnabled(True)
        self.photo_settings.single_capture_btn.setEnabled(True)
        self.live_settings.save_btn.setEnabled(True)
        self.photo_settings.single_capture_btn.setText("Acquire Photo")
        self.photo_settings.enable_input()
        self.live_settings.enable_input()

    # async def capture_frame_live(self):
    #     x_range, y_range, dwell, latency = self.live_parameters
        async for frame in self.fb.capture_frame(x_range, y_range, dwell=dwell, latency=latency):
            self.display_image(frame.as_uint8())
    
    async def capture_frame_photo(self):
        x_range, y_range, dwell, latency = self.photo_parameters
    #     # async for frame in self.fb.capture_frame(x_range, y_range, dwell=dwell, latency=latency):
    #     #     self.display_image(frame.as_uint8())
    #     self.db.prepare_display(x_range, y_range, dwell=dwell, latency=latency)
    #     await self.fb.capture_frame(x_range, y_range, dwell=dwell, latency=latency)
    #     threading.Thread(group=None, target=self.display_frame).start()
    #     # self.display_frame()
    
    def display_frame(self):
        print("display_frame started")
        # while self.fb.queue.qsize() == 0:
        #     print(f"{self.fb.queue.qsize()=}, waiting")
        # while self.fb.queue.qsize() > 0:
        credit = "credit"
        for n in range(8):
            self.fb.credits.put(credit) ## fill the queue
        while not self.db._interrupt.is_set():
            if self.fb.queue.qsize() > 0:
                print(f"{self.fb.queue.qsize()=}, {self.fb.credits.qsize()=}")
                chunk = self.fb.queue.get()
                for frame in self.db.display_frame_partial(chunk):
                    # self.image_display.showTest()
                    self.display_image(frame.as_uint8(), frame.y_ptr)
                self.fb.credits.put("credit")
                self.fb.queue.task_done()
                print(f"put credit. {self.fb.queue.qsize()=}, {self.fb.credits.qsize()=}")
        print("display_frame interrupted")
        while not self.fb.credits.empty():
            print(f"{self.fb.queue.qsize()=}")
            chunk = self.fb.queue.get()
            for frame in self.db.display_frame_partial(chunk):
                # self.image_display.showTest()
                self.display_image(frame.as_uint8(), frame.y_ptr)
            self.fb.queue.task_done()
            print(f"~put credit. {self.fb.queue.qsize()=}, {self.fb.credits.qsize()=}")
        print("display_frame complete")

    def capture_live(self):
        if self.live_settings.live_capture_btn.isChecked():
            print("starting live scan")
            self.photo_settings.single_capture_btn.setEnabled(False)
            # self.fb._interrupt.clear()
            self.db._interrupt.clear()
            self.live_settings.disable_input()
            self.photo_settings.disable_input()
            x_range, y_range, dwell, latency = self.parameters
            self.db.prepare_display(x_range, y_range, dwell=dwell, latency=latency)
            submit_async(self.fb.capture_frames_continously(x_range, y_range, dwell=dwell, latency=latency))
            threading.Thread(group=None, target=self.display_frame).start()
            self.live_settings.live_capture_btn.setText("Stop Live Scan")
            # while True:
            #     await self.capture_frame_live()
            #     if self.fb._interrupt.is_set():
            #         break
            # await self.fb.set_ext_ctrl(0)
            self.photo_settings.single_capture_btn.setEnabled(True)
            self.live_settings.live_capture_btn.setEnabled(True)
            self.live_settings.live_capture_btn.setText("Start Live Scan")
            self.live_settings.enable_input()
            self.photo_settings.enable_input()
        else:
            # self.fb._interrupt.set()
            self.db._interrupt.set()
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


def run_gui_thread(in_queue, out_queue):
    print("run gui thread")
    loop = asyncio.new_event_loop()
    frame_queue = Queue()
    worker = UIThreadWorker(in_queue, out_queue, loop)
    iface = OBIInterface(worker, frame_queue)

    app = QApplication(sys.argv)

    # event_loop = QEventLoop(app)
    # asyncio.set_event_loop(event_loop)

    # app_close_event = asyncio.Event()
    # app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    window = Window(iface=iface, debug=args.debug, frame_queue=frame_queue)
    w.setLayout(window)
    if not args.window_size == None:
        w.resize(args.window_size[0], args.window_size[1])
    w.show()
    pg.exec()

    # with event_loop:
    #     event_loop.run_until_complete(app_close_event.wait())


def run_gui():
    ui_to_con = Queue()
    con_to_ui = Queue()

    # ui = threading.Thread(target = run_gui_thread, args = [con_to_ui, ui_to_con])
    con = threading.Thread(target = conn_thread, args = [ui_to_con, con_to_ui])

    # ui.start()
    con.start()
    run_gui_thread(con_to_ui, ui_to_con)
    

if __name__ == "__main__":
    run_gui()

