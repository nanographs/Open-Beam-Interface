import datetime
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

class ImageDisplay(pg.GraphicsLayoutWidget):
    def __init__(self, y_height, x_width, invertY=False):
        super().__init__()
        self.y_height = y_height
        self.x_width = x_width

        self.image_view = self.addViewBox(invertY = invertY)
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
        self.roi = pg.ROI([.25*self.x_width, .25*self.y_height], [.5*self.x_width, .5*self.y_height], pen = border,
                        scaleSnap = True, translateSnap = True)
        self.roi.addScaleHandle([1, 1], [0, 0])
        self.roi.addScaleHandle([0, 0], [1, 1])
        self.image_view.addItem(self.roi)
        self.roi.setZValue(10)  # make sure ROI is drawn above image
        self.roi.sigRegionChanged.connect(self.get_ROI)
    
    def add_line(self):
        border = pg.mkPen(color = "#00ff00", width = 2)
        self.line = pg.LineSegmentROI(positions = ([.25*self.x_width, .25*self.y_height],[.5*self.x_width, .25*self.y_height]))
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
        x0, y0 = self.roi.pos() ## upper left corner
        x1, y1 = self.roi.size()
        x_upper = int(x0)
        y_upper = int(y0)
        x_lower = int(x0 + x1)
        y_lower = int(y0 + y1)
        #print(x0, y0, x1, y1)
        print(x_upper, x_lower, y_upper, y_lower)
        return x_upper, x_lower, y_upper, y_lower
        

    def setImage(self, y_height, x_width, image):
        ## image must be 2D np.array of np.uint8
        self.live_img.setImage(image, rect = (0,0, x_width, y_height), autoLevels=False)
        if not self.roi == None:
            self.roi.maxBounds = QtCore.QRectF(0, 0, x_width, y_height)
        self.data = image
        self.image_view.autoRange()


    def setRange(self, y_height, x_width):
        self.image_view.setRange(QtCore.QRectF(0, 0, x_width, y_height))
    
    def showTest(self):
        # test_file = "software/glasgow/applet/video/scan_gen/output_formats/Nanographs Pattern Test Logo and Gradients.bmp"
        # bmp = bmp_import(test_file)
        # array = np.array(bmp).astype(np.uint8)
        array = np.random.randint(0, 255,size = (512,512))
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