import argparse
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
parser.add_argument("port")
args = parser.parse_args()


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

class ImageData(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.mag = SettingBox("Magnification",0, 0, 1000000)
        self.addLayout(self.mag)
        self.measure_btn = QPushButton("Measure")
        self.addWidget(self.measure_btn)
    def getdata(self):
        mag = self.mag.getval()
        return {"Magnification":mag}


class Window(QVBoxLayout):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.addLayout(self.settings)
        self.settings.single_capture_btn.clicked.connect(self.capture_single_frame)
        self.settings.live_capture_btn.clicked.connect(self.capture_live)
        self.settings.save_btn.clicked.connect(self.save_image)
        self.image_display = ImageDisplay(512,512)
        self.addWidget(self.image_display)
        self.conn = Connection('localhost', int(args.port))
        self.fb = FrameBuffer(self.conn)
        self.image_data = ImageData()
        self.addLayout(self.image_data)
    
    # @property
    def parameters(self):
        x_res = self.settings.rx.getval()
        y_res = self.settings.ry.getval()
        dwell = self.settings.dwell.getval()
        latency = 65536
        x_range = DACCodeRange(0, x_res, int((16384/x_res)*256))
        y_range = DACCodeRange(0, y_res, int((16384/y_res)*256))
        return x_range, y_range, dwell, latency
    
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
        x_range, y_range, dwell, latency = self.parameters()
        frame = await self.fb.capture_frame(x_range, y_range, dwell=dwell, latency=latency)
        self.display_image(frame.prepare_for_display())
    
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

        
    

def run_gui():
    app = QApplication(sys.argv)
    asyncio.set_event_loop(QEventLoop(app))

    w = QWidget()
    window = Window()
    w.setLayout(window)
    w.show()   
 
    app.exec_()


if __name__ == "__main__":
    run_gui()
