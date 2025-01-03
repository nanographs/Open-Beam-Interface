import sys
import asyncio
import numpy as np

from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QProgressBar, QTabWidget,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton)
import pyqtgraph as pg


class WaveformViewer(QVBoxLayout):
    def __init__(self, pts: int = 1000):
        super().__init__()

        self.pts = pts
        self.data = np.zeros(self.pts)

        self.plot = pg.PlotWidget(enableMenu=False)
        self.plot.setYRange(0,16384)
        self.plot.setXRange(0,1000)
        
        self.plot_data = pg.PlotDataItem()
        self.plot.addItem(self.plot_data)
        self.plot_data.setData(self.data)
        self.plot.setMouseEnabled(x=False, y=True)
        self.plot.setLimits(xMin=0,xMax=self.pts, yMin=0,yMax=16383)

        mid = pg.InfiniteLine(movable=False, angle=0)
        mid.setPos([0,8191])
        self.plot.addItem(mid)

        self.addWidget(self.plot)
    
    def display_point(self, data: int):
        self.data[:self.pts-1] = self.data[1:self.pts]
        self.data[self.pts-1] = data
        self.plot_data.setData(self.data)

    def showTest(self):
        points = np.linspace(0, 16384, self.pts)
        for n in points:
            self.display_point(n)


if __name__ == "__main__":
    app = pg.mkQApp()
    w = QWidget()
    wfm_display = WaveformViewer()
    w.setLayout(wfm_display)
    wfm_display.showTest()
    w.show()
    
    pg.exec()