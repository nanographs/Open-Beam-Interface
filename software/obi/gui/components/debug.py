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
from .manual_dac_ctrl import PointControl, RampControl



class DACControl(QVBoxLayout):
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

        # self.wfm_display = WaveformViewer()

        self.tabs.addTab(point_tab, "Point")
        self.tabs.addTab(ramp_tab, "Ramp")

        self.addWidget(self.tabs)
        # self.addLayout(self.wfm_display)





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
