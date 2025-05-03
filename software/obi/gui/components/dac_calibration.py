import sys
import asyncio
import numpy as np

from PyQt6.QtWidgets import (QLabel, QWidget, QTabWidget,
                             QSpinBox, QHBoxLayout, QVBoxLayout, QPushButton)
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtCore import QSize

import qasync
from qasync import asyncSlot, QApplication, QEventLoop
import pyqtgraph as pg

from obi.transfer import TCPConnection
from obi.commands import VectorPixelCommand, OutputMode, SynchronizeCommand, FlushCommand, DACCodeRange
from obi.macros import RasterScanCommand
from .scan_parameters import ToggleButton

from .manual_dac_ctrl import PointControl, RampControl


def isolate_ramp(data):
    start = 0
    stop = 16383
    for x in range(0, 16383):
        if data[x] > 0:
            start = x
            break

    for x in range(16383,0,-1):
        if data[x] < 16383:
            stop = x
            break
    return (start, stop)


def linearity(data):
    slope, intercept = np.polyfit(np.array(range(0, len(data))), data, 1)
    correlation = np.corrcoef(np.array(range(0, len(data))), data)[0,1]

    return (slope, intercept, correlation)


class ADCTest(RampControl):
    def __init__(self, conn):
        self.conn = conn
        super().__init__(conn)

        self.scan_btn.setText("Linearity Test")
        self.scan_btn.clicked.disconnect(self.scan)
        self.scan_btn.clicked.connect(self.linearity_test)

        self.stop = None
        self.start = None
        self.text = pg.TextItem()
        self.wfm_display.plot.addItem(self.text)
        self.text.setPos(8000, 5000)
        self.text.setFont(QFont('Arial', 18)) 


    @asyncSlot()
    async def linearity_test(self):
        if not self.start == None:
            self.wfm_display.plot.removeItem(self.start)
        if not self.stop == None:
            self.wfm_display.plot.removeItem(self.stop)
        await self.scan()
        print("Scan complete")
        try:
            start, stop = isolate_ramp(self.wfm_display.data)
            slope, intercept, correlation = linearity(self.wfm_display.data)

            text = f"""
            linear region start: {start}
            linear region stop: {stop}
            slope: {slope:0.05f}
            y-intercept: {intercept:0.05f}
            R^2: {correlation}
            """

            self.start = pg.InfiniteLine(movable=False, angle=90)
            self.stop = pg.InfiniteLine(movable=False, angle=90)
            self.start.setPos([start,0])
            self.stop.setPos([stop,0])
            self.wfm_display.plot.addItem(self.start)
            self.wfm_display.plot.addItem(self.stop)
            
        except:
            text = "Error: Could not\ncalculate linearity"
        self.text.setText(text)


class RangeLineCtrl(QHBoxLayout):
    pen_normal = pg.mkPen(color = "#ff4f00", width = 1)
    pen_highlight = pg.mkPen(color = "#ee4b2b", width = 1)
    def __init__(self, name:str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.line = None
        self.set_btn = QPushButton(f"Set {name}")
        self.label = QLabel("")
        self.addWidget(self.set_btn)
        self.addWidget(self.label)
    def setLine(self, value):
        self.label.setText(f"{value}") 
        self.line = pg.InfiniteLine(movable=False, angle=0, pen = self.pen_normal)
        self.line.setPos([0,value])
        return self.line
    def highlightLine(self):
        self.line.setPen(self.pen_highlight)
    def getval(self):
        return int(self.label.text())

class PotTest(PointControl):
    def __init__(self, conn):
        super().__init__(conn)
        images = QHBoxLayout()
        adcimg = QLabel()
        adcimg.setPixmap(QPixmap("/Users/isabelburgos/Open-Beam-Interface/software/docs/source/_static/ADC_adjustment.png").scaled(QSize(350,100)))
        images.addWidget(adcimg)
        dacimg = QLabel()
        dacimg.setPixmap(QPixmap("/Users/isabelburgos/Open-Beam-Interface/software/docs/source/_static/DAC_adjustment.png").scaled(QSize(350,100)))
        images.addWidget(dacimg)
        self.addLayout(images)

        h = QHBoxLayout()
        self.maxrange = RangeLineCtrl("Max")
        self.maxrange.setLine(16383)
        h.addLayout(self.maxrange)
        self.maxrange.set_btn.clicked.connect(self.setMax)
        self.minrange = RangeLineCtrl("Min")
        self.minrange.setLine(0)
        h.addLayout(self.minrange)
        self.minrange.set_btn.clicked.connect(self.setMin)
        self.addLayout(h)

        self.start_range_btn = QPushButton("Start Test")
        self.exp_btn = QPushButton("copy to clipboard 📋")
        self.start_range_btn.clicked.connect(self.doTest)
        self.exp_btn.clicked.connect(self.exp)
        hh = QHBoxLayout()
        hh.addWidget(self.start_range_btn)
        hh.addWidget(self.exp_btn)
        self.addLayout(hh)
        
    def setLine(self, rangectrl:RangeLineCtrl):
        try:
            value = int(self.adc_settings.field.text())
            line = rangectrl.setLine(value)
            self.wfm_display.plot.addItem(line)
        except: 
            print("invalid value")

    def setMax(self):
        self.wfm_display.plot.removeItem(self.maxrange.line)
        self.setLine(self.maxrange)
    def setMin(self):
        self.wfm_display.plot.removeItem(self.minrange.line)
        self.setLine(self.minrange)
    
    @asyncSlot()
    async def toggle_live(self):
        self.start_range_btn.setEnabled(False)
        await super().toggle_live()
        self.start_range_btn.setEnabled(True)

    @asyncSlot()
    async def doTest(self):
        self.start_btn.setEnabled(False)
        self.start_range_btn.setEnabled(False)
        maxrange = self.maxrange.getval()
        minrange = self.minrange.getval()
        if not maxrange > minrange:
            print(f"Max {maxrange} is not greater than Min {minrange}")
            return
        n = 0
        wentOutOfRangeLow = False
        wentOutOfRangeHigh = False
        while n <= 4:
            self.start_range_btn.setText(f"In progress.... {n}")
            data = await self.setvals()
            datapoint = data[0]
            if minrange < datapoint < maxrange:
                self.display_data(data)
            else:
                if minrange >= datapoint:
                    self.minrange.line.setPen(self.minrange.pen_highlight)
                    if not wentOutOfRangeLow:
                        self.display_data(data)
                        n += 1
                        wentOutOfRangeLow = True
                        wentOutOfRangeHigh = False
                if maxrange <= datapoint:
                    self.maxrange.line.setPen(self.maxrange.pen_highlight)
                    if not wentOutOfRangeHigh:
                        self.display_data(data)
                        n += 1
                        wentOutOfRangeHigh = True
                        wentOutOfRangeLow = False


        self.start_range_btn.setEnabled(True)
        self.start_range_btn.setText("Start Test")
        self.start_btn.setEnabled(True)
    
    def exp(self):
        exporter = pg.exporters.ImageExporter(self.wfm_display.plot.plotItem)
        exporter.export("pots.png", copy=True)
    


class CombinedCalibrations(QVBoxLayout):
    def __init__(self, conn):
        self.conn = conn
        super().__init__()
        self.addWidget(QLabel("✨✨✨welcome to the test and calibration interface✨✨✨"))

        self.tabs = QTabWidget()
        dac_tab = QWidget()
        adc_tab = QWidget()
        pot_tab = QWidget()
        self.tabs.addTab(dac_tab, "DAC")
        self.tabs.addTab(adc_tab, "ADC")
        self.tabs.addTab(pot_tab, "POT")

        dac = PointControl(self.conn)
        pot = PotTest(self.conn)
        adc = ADCTest(self.conn)

        dac_tab.setLayout(dac)
        adc_tab.setLayout(adc)
        pot_tab.setLayout(pot)

        self.addWidget(self.tabs)
    

def run_gui():
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    conn = TCPConnection('localhost', 2224)
    s = CombinedCalibrations(conn)
    w.setLayout(s)
    w.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())


if __name__ == "__main__":
    run_gui()