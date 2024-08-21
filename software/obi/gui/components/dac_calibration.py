import sys
import asyncio
import numpy as np

from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QProgressBar, QTabWidget,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton)
from PyQt6.QtGui import QFont
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop
import pyqtgraph as pg

from obi.transfer import TCPConnection
from obi.commands import VectorPixelCommand, OutputMode, SynchronizeCommand, FlushCommand, DACCodeRange
from obi.macros import RasterScanCommand
from .scan_parameters import ToggleButton


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

class ADCSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.addWidget(QLabel("ADC Reading:"))
        self.field = QLabel("")
        self.addWidget(self.field)


class XYDACSettings(QVBoxLayout):
    def __init__(self, conn):
        self.conn = conn
        self.synced = False
        super().__init__()
        self.addWidget(QLabel("✨✨✨welcome to the test and calibration interface✨✨✨"))

        self.tabs = QTabWidget()
        dac_tab = QWidget()
        adc_tab = QWidget()
        self.tabs.addTab(dac_tab, "DAC")
        self.tabs.addTab(adc_tab, "ADC")
        dac = QVBoxLayout()
        adc = QVBoxLayout()
        dac_tab.setLayout(dac)
        adc_tab.setLayout(adc)
        self.addWidget(self.tabs)

        self.x_settings = DACSettings("X")
        self.y_settings = DACSettings("Y")
        self.adc_settings = ADCSettings()
        self.start_btn = ToggleButton("Start", "Stop")
        self.start_btn.clicked.connect(self.toggle_live)

        self.scan_btn = QPushButton("scan")
        self.exp_btn = QPushButton("copy to clipboard 📋")
        self.scan_btn.clicked.connect(self.scan)
        self.exp_btn.clicked.connect(self.exp)

        self.pts = 1000
        self.data = np.ndarray(self.pts)
        #self.ptr = 0

        self.plot = pg.PlotWidget(enableMenu=False)
        self.plot.setYRange(0,16384)
        self.plot.setXRange(0,1000)
        
        self.plot_data = pg.PlotDataItem()
        self.plot.addItem(self.plot_data)
        self.plot_data.setData(self.data)
        self.plot.setMouseEnabled(x=False, y=True)
        self.plot.setLimits(xMin=0,xMax=self.pts, yMin=0,yMax=16383)

        self.data2 = np.ndarray(16384)

        self.plot2 = pg.PlotWidget()
        self.plot2.setYRange(0,16384)
        self.plot2.setXRange(0,16384)

        self.plot2_data = pg.PlotDataItem()
        self.plot2.addItem(self.plot2_data)
        self.plot2_data.setData(self.data2)
        self.plot2_data.setPen(width=2)
        self.plot2.setLimits(xMin=0,xMax=16383, yMin=0,yMax=16383)

        self.stop = None
        self.start = None
        self.text = pg.TextItem()
        self.plot2.addItem(self.text)
        self.text.setPos(8000, 4000)
        self.text.setFont(QFont('Arial', 18)) 

        dac.addWidget(self.plot)
        dac.addLayout(self.x_settings)
        dac.addLayout(self.y_settings)
        dac.addLayout(self.adc_settings)
        dac.addWidget(self.start_btn)

        adc.addWidget(self.plot2)
        adc.addWidget(self.scan_btn)
        adc.addWidget(self.exp_btn)

        
    
    def getvals(self):
        x_coord = int(self.x_settings.field.cleanText())
        y_coord = int(self.y_settings.field.cleanText())
        return x_coord, y_coord
    
    @asyncSlot()
    async def setvals(self):
        x_coord, y_coord = self.getvals()
        print(f"{x_coord=}, {y_coord=}")
        data = await self.conn.transfer(VectorPixelCommand(
            x_coord = x_coord, y_coord = y_coord, dwell_time=1))
        self.adc_settings.field.setText(f"{data[0]}")
        self.data[:self.pts-1] = self.data[1:self.pts]
        self.data[self.pts-1] = data[0]
        # if self.ptr+1 == self.pts:
        #     self.ptr = 0
        # else:
        #     self.ptr += 1
        self.plot_data.setData(self.data)
    
    @asyncSlot()
    async def toggle_live(self):
        stop = asyncio.Event()
        self.start_btn.to_live_state(stop.set)

        # cookie = await self.conn.transfer(SynchronizeCommand(raster=False, output=OutputMode.NoOutput, cookie=123))
        # print(f"{cookie=}")
        
        while not stop.is_set():
            await self.setvals()
        
        self.start_btn.to_paused_state(self.toggle_live)
        print("done")
    
    @asyncSlot()
    async def scan(self):
        if not self.start == None:
            self.plot2.removeItem(self.start)
        if not self.stop == None:
            self.plot2.removeItem(self.stop)
        self.text.setText("")
        x = DACCodeRange.from_resolution(16384)
        y = DACCodeRange(start=8192, count=1, step=1)
        print(f"{x, y}")
        cmd = RasterScanCommand(cookie=123,x_range=x, y_range=y, dwell_time=500)
        ptr = 0
        self.scan_btn.setEnabled(False)
        async for chunk in self.conn.transfer_multiple(cmd, latency=16384):
            l = len(chunk)
            self.data2[ptr:ptr+l] = chunk
            self.plot2_data.setData(self.data2)
            ptr += l
        
        x_start = 0
        x_stop = 16383
        for x in range(0, 16383):
            if self.data2[x] > 0:
                x_start = x
                break

        for x in range(16383,0,-1):
            if self.data2[x] < 16383:
                x_stop = x
                break
        
        try:
            text = ""
            text += f"linear region start: {x_start}\n"
            text += f"linear region stop: {x_stop}\n"

            slope, intercept = np.polyfit(np.array(range(x_start, x_stop)), self.data2[x_start:x_stop], 1)
            text += f"slope: {slope:0.05f}\n"
            text += f"y-intercept: {intercept:0.05f}\n"

            correlation = np.corrcoef(np.array(range(x_start, x_stop)), self.data2[x_start:x_stop])[0,1]
            text += f"R^2: {correlation}"

            self.start = pg.InfiniteLine(movable=False, angle=90)
            self.stop = pg.InfiniteLine(movable=False, angle=90)
            self.start.setPos([x_start,0])
            self.stop.setPos([x_stop,0])
            self.plot2.addItem(self.start)
            self.plot2.addItem(self.stop)
            self.text.setText(text)
        except:
            print("Could not fit line")
        self.scan_btn.setEnabled(True)
    
    def exp(self):
        exporter = pg.exporters.ImageExporter(self.plot2.plotItem)
        exporter.export("adc.png", copy=True)
    



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