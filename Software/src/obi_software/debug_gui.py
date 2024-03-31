import asyncio
import sys
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow,
                             QMessageBox, QPushButton,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox)

from beam_interface import Connection, DACCodeRange
from frame_buffer import FrameBuffer
from gui_modules.image_display import ImageDisplay

import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop



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
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCheckable(True)
        self.addWidget(self.connect_btn)
        self.sync_btn = QPushButton("Sync")
        self.addWidget(self.sync_btn)
        self.rx = SettingBox("X Resolution",128, 16384, 512)
        self.addLayout(self.rx)
        self.ry = SettingBox("Y Resolution",128, 16384, 512)
        self.addLayout(self.ry)
        self.dwell = SettingBox("Dwell Time",0, 65536, 2)
        self.addLayout(self.dwell)
        self.latency = SettingBox("Latency",0, pow(2,28), pow(2,16))
        self.addLayout(self.latency)
        self.capture_btn = QPushButton("Capture 1")
        self.addWidget(self.capture_btn)
        self.capture_live_btn = QPushButton("Capture Live")
        self.addWidget(self.capture_live_btn)
        self.freescan_btn = QPushButton("Free Scan")
        self.addWidget(self.freescan_btn)
        self.interrupt_btn = QPushButton("Interrupt")
        self.addWidget(self.interrupt_btn)


class Window(QVBoxLayout):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.addLayout(self.settings)
        self.settings.connect_btn.clicked.connect(self.toggle_connection)
        self.settings.sync_btn.clicked.connect(self.request_sync)
        self.settings.capture_btn.clicked.connect(self.capture_single_frame)
        self.settings.capture_live_btn.clicked.connect(self.capture_live)
        self.settings.freescan_btn.clicked.connect(self.free_scan)
        self.settings.interrupt_btn.clicked.connect(self.interrupt)
        self.image_display = ImageDisplay(512,512)
        self.addWidget(self.image_display)
        self.conn = Connection('localhost', 2223)
        self.fb = FrameBuffer(self.conn)
    
    @property
    def parameters(self):
        x_res = self.settings.rx.getval()
        y_res = self.settings.ry.getval()
        dwell = self.settings.dwell.getval()
        latency = self.settings.latency.getval()
        x_range = DACCodeRange(0, x_res, int((16384/x_res)*256))
        y_range = DACCodeRange(0, y_res, int((16384/y_res)*256))
        return x_range, y_range, dwell, latency

    @asyncSlot()
    async def toggle_connection(self):
        if self.settings.connect_btn.isChecked():
            await self.conn._connect()
            self.settings.connect_btn.setText("Disconnect")
        else:
            self.conn._disconnect()
            self.settings.connect_btn.setText("Connect")

    @asyncSlot()
    async def request_sync(self):
        await self.conn._synchronize()
    
    def display_image(self, array):
        x_width, y_height = array.shape
        self.image_display.setImage(y_height, x_width, array)
    
    @asyncSlot()
    async def capture_single_frame(self):
        x_range, y_range, dwell, latency = self.parameters
        await self.fb.capture_frame(x_range, y_range, dwell=dwell, latency=latency)
        self.display_image(self.fb.output_ndarray(x_range, y_range))
    
    @asyncSlot()
    async def capture_live(self):
        x_range, y_range, dwell, latency = self.parameters
        # async for frame in self.fb.capture_continous(x_range, y_range, dwell=dwell, latency=latency):
        while not self.fb._interrupt.set():
            await self.capture_single_frame()
    
    @asyncSlot()
    async def free_scan(self):
        x_range, y_range, dwell, latency = self.parameters
        async for frame in self.fb.free_scan(x_range, y_range, dwell=dwell, latency=latency):
            self.display_image(self.fb.output_ndarray(x_range, y_range))
    
    def interrupt(self):
        self.fb._interrupt.set()
        self.conn._interrupt_scan()

        
    

def run_gui():
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    window = Window()
    w.setLayout(window)
    w.show() 

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())

    return window

if __name__ == "__main__":
    run_gui()





