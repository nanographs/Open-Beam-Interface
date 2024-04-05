import sys
import argparse
import asyncio

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
from .gui import Window, Settings


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


class DebugWindow(Window):
    def __init__(self):
        super().__init__()
        self.debug_settings = DebugSettings()
        self.addLayout(self.debug_settings)
        self.debug_settings.connect_btn.clicked.connect(self.toggle_connection)
        self.debug_settings.sync_btn.clicked.connect(self.request_sync)
        self.debug_settings.freescan_btn.clicked.connect(self.free_scan)
        self.debug_settings.interrupt_btn.clicked.connect(self.interrupt)

    # @property
    def parameters(self):
        x_range, y_range, dwell, default_latency = super().parameters()
        latency = self.debug_settings.latency.getval()
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
    window = DebugWindow()
    w.setLayout(window)
    w.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())


if __name__ == "__main__":
    run_gui()
