import sys
import asyncio
import numpy as np
import array

from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QProgressBar, QTabWidget,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton)
from PyQt6.QtCore import pyqtSignal
import pyqtgraph as pg


class WaveformViewer(QVBoxLayout):
    """
    A graphical waveform display.

    Args:
        pts (int, optional): Number of data points on the horizontal axis of the graph. Defaults to 1000.
    """
    def __init__(self, pts: int = 1000):
        super().__init__()

        self.initialize_points(pts)

        self.plot = pg.PlotWidget(enableMenu=False)
        self.plot.setYRange(0,16384)
        self.plot.setXRange(0,pts)
        
        self.plot_data = pg.PlotDataItem()
        self.plot.addItem(self.plot_data)
        self.plot_data.setData(self.data)
        self.plot.setMouseEnabled(x=False, y=True)
        self.plot.setLimits(xMin=0,xMax=self.pts, yMin=0,yMax=16383)

        mid = pg.InfiniteLine(movable=False, angle=0)
        mid.setPos([0,8191])
        self.plot.addItem(mid)

        self.exp_btn = QPushButton("copy to clipboard 📋")

        self.addWidget(self.plot)
        self.addWidget(self.exp_btn)

        self.reset()

    def initialize_points(self, pts: int):
        """
        Create a new buffer to hold the specified number of data points

        Args:
            pts (int): Number of data points on the horizontal axis of the graph
        """
        self.pts = pts
        self.data = np.zeros(self.pts)
    
    def reset(self):
        """
        Clear all data in the buffer and replace it with zeros, and then update the display to show that.
        """
        self.initialize_points(self.pts)
        self.plot_data.setData(self.data)
    
    def display_data(self, data: array.array):
        """
        Append an array of points to the end of the rolling display. If the \
        length of the array exceeds the size of the data buffer (self.pts), \
        the data will be truncated and only the last (and most recent) \
        self.pts points will be displayed.

        Args:
            data (array.array): Data points to add to waveform display
        """
        # if more data shows up than fits on the display, throw it out
        d_pts = min(len(data), self.pts) 
        d = np.asarray(data[len(data)-d_pts:], np.uint16)
        self.data[:self.pts-d_pts] = self.data[d_pts:self.pts]
        self.data[self.pts-d_pts:] = d
        self.plot_data.setData(self.data)

    def showTest(self):
        """
        Displays a ramp across the full range of the display
        """
        points = np.linspace(0, 16384, self.pts)
        self.display_data(array.array('B', points))
    
    def to_clipboard(self):
        """
        Saves the waveform display to the clipboard as wfm.png
        """
        exporter = pg.exporters.ImageExporter(self.plot.plotItem)
        exporter.export("wfm.png", copy=True)


if __name__ == "__main__":
    app = pg.mkQApp()
    w = QWidget()
    wfm_display = WaveformViewer()
    w.setLayout(wfm_display)
    wfm_display.showTest()
    w.show()
    
    pg.exec()