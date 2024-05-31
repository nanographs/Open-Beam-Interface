import sys
import asyncio
from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton)
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop
from ..stream_interface import Connection, StreamVectorPixelCommand, OutputMode


class DACSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
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
        self.field.setValue(0)
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
        super().__init__()
        self.x_settings = DACSettings()
        self.y_settings = DACSettings()
        self.addLayout(self.x_settings)
        self.addLayout(self.y_settings)
        self.x_settings.field.valueChanged.connect(self.setvals)
        self.y_settings.field.valueChanged.connect(self.setvals)
    
    def getvals(self):
        x_coord = int(self.x_settings.field.cleanText())
        y_coord = int(self.y_settings.field.cleanText())
        return x_coord, y_coord
    
    @asyncSlot()
    async def setvals(self):
        x_coord, y_coord = self.getvals()
        print(f"{x_coord=}, {y_coord=}")
        await self.conn.transfer(StreamVectorPixelCommand(
            x_coord = x_coord, y_coord = y_coord, dwell=1), output_mode=OutputMode.NoOutput)




def run_gui():
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    conn = Connection('localhost', 2224)
    s = XYDACSettings(conn)
    w.setLayout(s)
    w.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())


if __name__ == "__main__":
    run_gui()
