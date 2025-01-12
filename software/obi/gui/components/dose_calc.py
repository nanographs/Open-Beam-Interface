from PyQt6.QtWidgets import (QLabel, QApplication, QWidget, QHBoxLayout, QVBoxLayout)
import pyqtgraph as pg


class DoseCalculator(QVBoxLayout):
    def __init__(self):
        super().__init__()
        self.hfov = pg.SpinBox(value=.000001, suffix="m", siPrefix=True, step=.0000001, compactHeight=False)
        self.resolution = pg.SpinBox(value=2048, suffix="px", siPrefix=False, step=1, bounds=(256,16384), compactHeight=False)
        self.pix_size = QLabel("      ")
        self.dwell = pg.SpinBox(value=.000002, suffix="s", siPrefix=True, step=.000000125, bounds=(.0000000125, .000000125*65536), compactHeight=False)
        self.current = pg.SpinBox(value=.000001, suffix="A", siPrefix=True, step=.0000001, compactHeight=False)
        self.pix_area = QLabel("      ")
        self.exposure = QLabel("      ")


        # sigValueChanging is more responsive than valueChanged
        self.dwell.sigValueChanging.connect(self.calculate_exposure)
        self.current.sigValueChanging.connect(self.calculate_exposure)
        self.hfov.sigValueChanging.connect(self.calculate_exposure)

        self.a = QHBoxLayout()
        self.b = QHBoxLayout()
        self.addLayout(self.a)
        self.addLayout(self.b)

        self.a.addWidget(QLabel("FOV Size:"))
        self.a.addWidget(self.hfov)
        self.a.addWidget(QLabel(" ÷ Resolution:"))
        self.a.addWidget(self.resolution)
        self.a.addWidget(QLabel("-----> Pixel Size:"))
        self.a.addWidget(self.pix_size)
        self.a.addStretch(stretch=2)

        self.b.addWidget(QLabel("Pixel Dwell:"))
        self.b.addWidget(self.dwell)
        self.b.addWidget(QLabel("x Beam Current"))
        self.b.addWidget(self.current)
        self.b.addWidget(QLabel(" ÷ Pixel Area:"))
        self.b.addWidget(self.pix_area)
        self.b.addWidget(QLabel("-----> Exposure:"))
        self.b.addWidget(self.exposure)
    
        self.calculate_exposure()

    def calculate_exposure(self):
        hfov = self.hfov.interpret()
        dwell = self.dwell.interpret()
        current = self.current.interpret()
        resolution = self.resolution.interpret()
        if hfov and dwell and current and resolution:
            hfov = self.hfov.value()
            dwell = self.dwell.value()
            current = self.current.value()
            resolution = self.resolution.value()
            pixel_size = hfov/resolution
            pixel_area = pixel_size*pixel_size
            exposure = current*dwell/pixel_area
            self.pix_size.setText(f"{pg.siFormat(pixel_size, suffix='m')}")
            self.pix_area.setText(f"{pg.siFormat(pixel_area, suffix='m^2')}")
            self.exposure.setText(f"{pg.siFormat(exposure/pow(10,6), suffix='C/cm^2')}") #1 GC/m^2 = 1 uC/cm^2
    

class DoseCalcWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.inner = DoseCalculator()
        self.setLayout(self.inner)


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    w = QWidget()
    p = DoseCalculator()
    w.setLayout(p)
    w.show()
    app.exec()
