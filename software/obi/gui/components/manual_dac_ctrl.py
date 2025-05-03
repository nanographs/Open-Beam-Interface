import sys
import asyncio
import numpy as np
import array

from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QProgressBar, QTabWidget, QCheckBox,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton, QSizePolicy)
from PyQt6.QtCore import pyqtSignal
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop
import pyqtgraph as pg

from obi.transfer import TCPConnection
from obi.commands import VectorPixelCommand, OutputMode, SynchronizeCommand, FlushCommand, DACCodeRange
from obi.macros import RasterScanCommand
from .scan_parameters import ToggleButton
from .waveform import WaveformViewer


class DACSettings(QHBoxLayout):
    """
    Interface for choosing a value between 0 and 16383, with shortcut buttons \
    for Maximum (16383), Midpoint (8191), and Minimum (0)

    Args:
        name (str): DAC identifier - either "X" or "Y"
    """
    def __init__(self, name: str):
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


class PointControl(QVBoxLayout):
    """
    Interface for
    """
    sigNewDataGenerated = pyqtSignal(array.array)
    def __init__(self, conn):
        self.conn = conn
        super().__init__()
        self.x_settings = DACSettings("X")
        self.y_settings = DACSettings("Y")
        
        self.adc_readout = QLabel("")
    
        self.start_btn = ToggleButton("Run", "Stop")
        self.start_btn.clicked.connect(self.toggle_live)

        self.wfm_display = WaveformViewer()

        self.addLayout(self.x_settings)
        self.addLayout(self.y_settings)
        
        h = QHBoxLayout()
        h.addWidget(self.start_btn)
        h.addWidget(QLabel("ADC Reading:"))
        h.addWidget(self.adc_readout)
        self.addLayout(h)

        self.addLayout(self.wfm_display)
        self.sigNewDataGenerated.connect(self.wfm_display.display_data)
        
        
    def getvals(self):
        x_coord = int(self.x_settings.field.cleanText())
        y_coord = int(self.y_settings.field.cleanText())
        return x_coord, y_coord
    
    @asyncSlot()
    async def setvals(self):
        x_coord, y_coord = self.getvals()
        cmd = VectorPixelCommand(x_coord = x_coord, y_coord = y_coord, dwell_time=100)
        data = await self.conn.transfer(cmd)
        self.adc_readout.setText(f"{data[0]}")
        self.sigNewDataGenerated.emit(data)

    @asyncSlot()
    async def toggle_live(self):
        stop = asyncio.Event()
        self.start_btn.to_live_state(stop.set)
        
        while not stop.is_set():
            await self.setvals()
        
        self.start_btn.to_paused_state(self.toggle_live)
        print("done")


class RampControl(QVBoxLayout):
    sigNewDataGenerated = pyqtSignal(array.array)
    def __init__(self, conn):
        self.conn = conn
        super().__init__()
        self.y_btn = QCheckBox("Ramp Y")
        self.scan_btn = QPushButton("Run")
        self.scan_btn.clicked.connect(self.scan)

        self.wfm_display = WaveformViewer(16384)
        # a square plot just feels better when looking for linearity
        self.wfm_display.plot.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)

        self.addWidget(self.y_btn)
        self.addWidget(self.scan_btn)
        self.addLayout(self.wfm_display)
        self.sigNewDataGenerated.connect(self.wfm_display.display_data)

    
    @asyncSlot()
    async def scan(self):
        self.wfm_display.reset()
        x = DACCodeRange.from_resolution(16384)
        y = DACCodeRange(start=8192, count=1, step=1)
        if self.y_btn.isChecked():
            cmd = RasterScanCommand(cookie=123,x_range=y, y_range=x, dwell_time=500)
        else:
            cmd = RasterScanCommand(cookie=123,x_range=x, y_range=y, dwell_time=500)
        ptr = 0
        async for chunk in self.conn.transfer_multiple(cmd, latency=16384):
            self.sigNewDataGenerated.emit(chunk)
    

class CombinedDACControl(QVBoxLayout):
    def __init__(self, conn):
        self.conn = conn
        super().__init__()
        self.tabs = QTabWidget()

        point_tab = QWidget()
        self.point_ctrl = PointControl(self.conn)
        point_tab.setLayout(self.point_ctrl)

        ramp_tab = QWidget()
        self.ramp_ctrl = RampControl(self.conn)
        ramp_tab.setLayout(self.ramp_ctrl)

        self.tabs.addTab(point_tab, "Point")
        self.tabs.addTab(ramp_tab, "Ramp")

        self.addWidget(self.tabs)



def run_gui():
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    conn = TCPConnection('localhost', 2224)
    s = CombinedDACControl(conn)
    w.setLayout(s)
    w.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())


if __name__ == "__main__":
    run_gui()

