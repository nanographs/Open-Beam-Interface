import sys
import asyncio
from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton)
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop
from obi.transfer import TCPConnection
from obi.commands import VectorPixelCommand, OutputMode, SynchronizeCommand, FlushCommand


class DACSettings(QHBoxLayout):
    def __init__(self, name):
        super().__init__()
        self.addWidget(QLabel(name))
        self.max_btn = QPushButton("Max")
        self.max_btn.clicked.connect(self.maxClicked)
        self.addWidget(self.max_btn)
        self.mid_btn = QPushButton("Mid")
        self.mid_btn.clicked.connect(self.midClicked)
        self.addWidget(self.mid_btn)
        self.min_btn = QPushButton("Min")
        self.min_btn.clicked.connect(self.minClicked)
        self.addWidget(self.min_btn)
        self.field = QSpinBox()
        self.field.setRange(0, 16383)
        self.field.setSingleStep(1)
        self.field.setValue(1)
        self.addWidget(self.field)

    def maxClicked(self):
        self.field.setValue(16383)
    
    def midClicked(self):
        self.field.setValue(8191)
    
    def minClicked(self):
        self.field.setValue(0)


class XYDACSettings(QVBoxLayout):
    def __init__(self, conn):
        self.conn = conn
        self.synced = False
        super().__init__()
        self.addWidget(QLabel("✨✨✨welcome to the test and calibration interface✨✨✨"))
        self.x_settings = DACSettings("X")
        self.y_settings = DACSettings("Y")
        self.addLayout(self.x_settings)
        self.addLayout(self.y_settings)
        self.x_settings.field.valueChanged.connect(self.setvals)
        self.y_settings.field.valueChanged.connect(self.setvals)
    
    def getvals(self):
        x_coord = int(self.x_settings.field.cleanText())
        y_coord = int(self.y_settings.field.cleanText())
        return x_coord, y_coord
    
    async def sync(self):
        await self.conn.transfer(SynchronizeCommand(raster=False, output=OutputMode.NoOutput, cookie=123))
        await self.conn.transfer(FlushCommand())
        await self.conn._stream.read(4)
        self.synced = True

    @asyncSlot()
    async def setvals(self):
        x_coord, y_coord = self.getvals()
        print(f"{x_coord=}, {y_coord=}")
        if not self.synced:
            await self.sync()
        await self.conn.transfer(VectorPixelCommand(
            x_coord = x_coord, y_coord = y_coord, dwell_time=1))




def run_gui():
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    conn = TCPConnection('localhost', 2224)
    s = XYDACSettings(conn)
    w.setLayout(s)
    w.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())


if __name__ == "__main__":
    run_gui()