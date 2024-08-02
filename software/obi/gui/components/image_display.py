import datetime
import logging
import math
import numpy as np
import pyqtgraph as pg
from pyqtgraph.exporters import Exporter
from pyqtgraph.Qt import QtCore
from pyqtgraph.graphicsItems.TextItem import TextItem

from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow,
                             QMessageBox, QPushButton,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox)

logger = logging.getLogger()

class ImageDisplay(pg.GraphicsLayoutWidget):
    _logger = logger.getChild("ImageDisplay")
    def __init__(self, y_height, x_width, invertY=True, invertX=False):
        super().__init__()
        self.y_height = y_height
        self.x_width = x_width

        self.image_view = self.addViewBox(invertY = invertY, invertX=invertX)
        # self.plot = self.addPlot(viewBox = self.image_view)
        ## lock the aspect ratio so pixels are always square
        self.image_view.setAspectLocked(True)
        # self.image_view.setRange(QtCore.QRectF(0, 0, y_height, x_width))
        
        # self.image_view.setLimits(xMin=0, xMax=self.x_width, 
        #     minXRange=0, maxXRange=self.x_width, 
        #     yMin=0, yMax=self.x_width,
        #     minYRange=0, maxYRange=self.x_width)
        
        self.live_img = pg.ImageItem(border='w',axisOrder="row-major")
        self.live_img.setImage(np.full((y_height, x_width), 0, np.uint8), rect = (0,0,x_width, y_height), autoLevels=False, autoHistogramRange=True)
        self.image_view.addItem(self.live_img)
        

        self.data = np.zeros(shape = (y_height, x_width))

        # Contrast/color control
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.live_img)
        #self.hist.disableAutoHistogramRange()
        self.addItem(self.hist)

        self.hist.setLevels(min=0,max=255)

        self.roi = None
        self.line = None

        ### reverse the default LUT
        # lut = []
        # for n in range(0, 256):
        #     lut.append([255-n,255-n,255-n])
        
        # lut = np.array(lut, dtype = np.uint8)
        # self.live_img.setLookupTable(lut)

    def add_ROI(self):
        border = pg.mkPen(color = "#00ff00", width = 2)
        # Custom ROI for selecting an image region
        self.roi = pg.ROI([int(.25*self.x_width), int(.25*self.y_height)], [int(.5*self.x_width), int(.5*self.y_height)], pen = border, handlePen=border,
                        scaleSnap = True, translateSnap = True)
        self.roi.addScaleHandle([1, 1], [0, 0])
        self.roi.addScaleHandle([0, 0], [1, 1])
        self.image_view.addItem(self.roi)
        self.roi.maxBounds = QtCore.QRectF(0, 0, self.x_width, self.y_height)
        self.roi.setZValue(10)  # make sure ROI is drawn above image
    
    def add_line(self, start=None, end=None):
        if start == None:
            start  = [.25*self.x_width, .25*self.y_height]
        if end == None:
            end = [start[0] + .25*self.x_width, start[1]]
        border = pg.mkPen(color = "#00ff00", width = 2)
        self.line = pg.LineSegmentROI(positions = (start,end),
                        pen = border, handlePen=border,)
        self.image_view.addItem(self.line)
        self.line.setZValue(10)  # make sure line is drawn above image

    def remove_line(self):
        if not self.line == None:
            self.image_view.removeItem(self.line)
            self.line = None
    
    def get_line_length(self):
        # the pos() and size() functions for LinearROIRegion do not work
        p1, p2 = [point.pos() for point in self.line.endpoints]
        d = math.sqrt(pow(p1[0] - p2[0],2) + pow(p1[1] - p2[1],2))
        return d

    def remove_ROI(self):
        if not self.roi == None:
            self.image_view.removeItem(self.roi)
            self.roi = None

    def get_ROI(self):
        x_start, y_start = self.roi.pos() ## upper left corner
        x_count, y_count = self.roi.size()
        return int(x_start), int(x_count), int(y_start), int(y_count)
        

    def setImage(self, image: np.array(np.uint8)):
        ## image must be 2D np.array of np.uint8
        y_height, x_width = image.shape
        self.live_img.setImage(image, rect = (0,0, x_width, y_height), autoLevels=False)
        self.setRange(y_height, x_width)
        self.data = image
        
    def setRange(self, y_height, x_width):
        if (x_width != self.x_width) | (y_height != self.y_height):
            self.image_view.autoRange()
            if not self.roi == None:
                self.roi.maxBounds = QtCore.QRectF(0, 0, x_width, y_height)
        self.image_view.setRange(QtCore.QRectF(0, 0, x_width, y_height))
        self.x_width = x_width
        self.y_height = y_height
    
    def showTest(self):
        array = np.random.randint(0, 255,size = (self.y_height, self.x_width))
        array = array.astype(np.uint8)
        self.setImage(self.y_height, self.x_width, array)







if __name__ == "__main__":
    app = pg.mkQApp()
    image_display = ImageDisplay(512, 512)
    # image_display.showTest()
    # image_display.add_ROI()
    #image_display.remove_ROI()
    image_display.add_line()
    image_display.show()
    pg.exec()