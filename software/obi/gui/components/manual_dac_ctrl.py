import sys
import asyncio
import numpy as np

from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QProgressBar, QTabWidget,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton)
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop
import pyqtgraph as pg

from obi.transfer import TCPConnection
from obi.commands import VectorPixelCommand, OutputMode, SynchronizeCommand, FlushCommand, DACCodeRange
from obi.macros import RasterScanCommand
from .scan_parameters import ToggleButton
from .waveform import WaveformViewer



class ADCReading(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.addWidget(QLabel("ADC Reading:"))
        self.field = QLabel("")
        self.addWidget(self.field)

class DACSettings(QHBoxLayout):
    def __init__(self, name):
        super().__init__()
        self.addWidget(QLabel(name))
        self.max_btn = QPushButton("Max")
        self.max_btn.clicked.connect(self.maxClicked)
        self.mid_btn = QPushButton("Mid")
        self.mid_btn.clicked.connect(self.midClicked)
        self.min_btn = QPushButton("Min")
        self.min_btn.clicked.connect(self.minClicked)

        self.field = QSpinBox()
        self.field.setRange(0, 16383)
        self.field.setSingleStep(1)
        self.field.setValue(1)

        self.addWidget(self.max_btn)
        self.addWidget(self.mid_btn)
        self.addWidget(self.min_btn)
        self.addWidget(self.field)

    def maxClicked(self):
        self.field.setValue(16383)
    
    def midClicked(self):
        self.field.setValue(8191)
    
    def minClicked(self):
        self.field.setValue(0)


class DACControl(QVBoxLayout):
    def __init__(self, conn):
        self.conn = conn
        super().__init__()
        self.x_settings = DACSettings("X")
        self.y_settings = DACSettings("Y")
        self.adc_settings = ADCReading()
        self.start_btn = ToggleButton("Run", "Stop")
        self.start_btn.clicked.connect(self.toggle_live)
        self.wfm_display = WaveformViewer()

        self.addLayout(self.x_settings)
        self.addLayout(self.y_settings)
        self.addLayout(self.adc_settings)
        self.addWidget(self.start_btn)
        self.addLayout(self.wfm_display)
    
        
    def getvals(self):
        x_coord = int(self.x_settings.field.cleanText())
        y_coord = int(self.y_settings.field.cleanText())
        return x_coord, y_coord
    
    @asyncSlot()
    async def setvals(self):
        x_coord, y_coord = self.getvals()
        print(f"{x_coord=}, {y_coord=}")
        cmd = VectorPixelCommand(x_coord = x_coord, y_coord = y_coord, dwell_time=100)
        data_array = await self.conn.transfer(cmd)
        self.adc_settings.field.setText(f"{data[0]}")
        self.wfm_display.sigNewDataPoint.emit(data[0])

    @asyncSlot()
    async def toggle_live(self):
        stop = asyncio.Event()
        self.start_btn.to_live_state(stop.set)
        
        while not stop.is_set():
            await self.setvals()
        
        self.start_btn.to_paused_state(self.toggle_live)
        print("done")


def run_gui():
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    conn = TCPConnection('localhost', 2224)
    s = DACControl(conn)
    w.setLayout(s)
    w.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())


if __name__ == "__main__":
    run_gui()

