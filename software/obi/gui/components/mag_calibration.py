import datetime
import os

from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QFrame, QFileDialog, QCheckBox, 
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit, QSizePolicy)
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot
from PyQt6.QtGui import QFont
from PyQt6 import QtCore

import pyqtgraph as pg
import numpy as np

from obi.config.meta import ScopeSettings, BeamSettings, MagCal


class MagCalTable(pg.TableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs,
            sortable=False, editable=True)
        self.setFont(QFont('Arial', 14)) 
    def to_dict(self):
        rows = list(range(self.rowCount()))
        columns = range(2)
        d = {}

        for r in rows:
            mag = self.item(r, 0).value
            fov = self.item(r, 1).value
            d.update({int(mag):float(fov)})
            
        return d
    # def sizeHint(self):
    #     h = super().sizeHint()
    #     height, width = h.height(), h.width()
    #     return QtCore.QSize(width*2, height*2)
    def sizePolicy(self):
        return QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)


class MagCalibration(QHBoxLayout):
    sigRequestUpdateToml = pyqtSignal(ScopeSettings)
    sigToggleMeasureLines = pyqtSignal(bool)
    def __init__(self):
        super().__init__()
        self.mag = pg.SpinBox()
        self.mag.setOpts(int=True)
        self.mag.setMinimum(1)
        self.length = pg.SpinBox()
        self.length.setSuffix("m")
        self.length.setOpts(siPrefix=True)
        self.fov_length = pg.SpinBox()
        self.fov_length.setSuffix("m")
        self.fov_length.setOpts(siPrefix=True)
        self.fov_length.setReadOnly(True)
        self.measure_btn = QPushButton("📏")
        self.measure_btn.setCheckable(True)
        self.measure_btn.clicked.connect(self.toggle_measure)
        self.update_btn = QPushButton("Update Calibration Curve 📍")
        self.to_file_btn = QPushButton("Save Calibration to File")
        self.from_file_btn = QPushButton("Load Calibration from File")

        self.update_btn.clicked.connect(self.save_point)
        self.to_file_btn.clicked.connect(self.save_to_file)
        self.from_file_btn.clicked.connect(self.load_from_file)
        self.mag.sigValueChanging.connect(self.calculate_fov_length)
        self.length.sigValueChanging.connect(self.calculate_fov_length)

        self.table = MagCalTable()
        self.table.cellClicked.connect(self.table_fn)
        
        self.plot = pg.PlotWidget(enableMenu=False)
        self.plot.setMouseEnabled(False)
        self.plot.setMenuEnabled(False)

        al = pg.AxisItem(orientation="left", units="m", unitPrefix="m", text="FOV size")
        ab = pg.AxisItem(orientation="bottom", text="Magnification")
        self.plot.setAxisItems({"bottom": ab, "left": al})
        self.plot.setLogMode(x=True, y=True)
        for ax in (al, ab):
            ax.showLabel(True)
            ax.setStyle(hideOverlappingLabels=True)        
        self.plot_data = pg.PlotDataItem()
        self.plot_data.setSymbol("o")
        self.plot.addItem(self.plot_data)

        left = QVBoxLayout()
        left.addWidget(QLabel("Magnification"))
        left.addWidget(self.mag)
        left.addWidget(QLabel("Measured Length"))
        measure = QHBoxLayout()
        measure.addWidget(self.length)
        measure.addWidget(self.measure_btn)
        measure.setSpacing(1)
        left.addLayout(measure)
        left.addWidget(QLabel("↓↓"))
        left.addWidget(QLabel("HFOV Length"))
        left.addWidget(self.fov_length)
        left.addWidget(self.update_btn)
        left.setAlignment(self, Qt.AlignmentFlag.AlignTop)
        left.addStretch(stretch=2)
        left.addWidget(self.table)
        left.addWidget(self.to_file_btn)
        left.addWidget(self.from_file_btn)
        left.setSpacing(1)
        self.addLayout(left)

        right = QVBoxLayout()
        
        right.addWidget(self.plot)
        self.addLayout(right)

        self.scope_settings = None
        self.beam_name = None
        self.line_px = None
        self.resolution = None
        self.m_per_fov = None

    def table_fn(self, row, column):
        print(f"clicked {row=}, {column=}")
    
    def toggle_measure(self):
        measure = self.measure_btn.isChecked()
        self.sigToggleMeasureLines.emit(measure)


    @Slot(str)
    def set_beam(self, beam_name):
        if beam_name is not None:
            self.beam_name = beam_name
            beam_settings = self.scope_settings.beam_settings.get(self.beam_name)
            if beam_settings.mag_cal is not None:
                self.m_per_fov = beam_settings.mag_cal.m_per_fov
            else:
                self.m_per_fov = {}
        else:
            self.beam_name = None
            self.m_per_fov = {}
        self.display_data()
        
    
    def display_data(self):
        if self.m_per_fov is not None:
            self.show_data(self.m_per_fov)
            self.table.resize(self.table.sizeHint()) ## show all of the rows
            self.table.updateGeometry()

    def save_point(self):
        if self.m_per_fov is not None:
            self.calculate_fov_length()
            m_per_fov = self.fov_length.value()
            mag = self.mag.value()
            self.m_per_fov.update({mag:m_per_fov})
            self.m_per_fov = dict(sorted(self.m_per_fov.items()))
            self.display_data()
        
    def write_path_to_toml(self, path):
        self.scope_settings.beam_settings[f"{self.beam_name}"].mag_cal = mag_cal = MagCal.from_csv(path)
        self.m_per_fov = mag_cal.m_per_fov
        self.display_data()
        self.sigRequestUpdateToml.emit(self.scope_settings)

    def save_to_file(self):
        path, _ = QFileDialog.getSaveFileName(
            caption = "Save Calibration",
            filter = f"{self.tr('Comma-separated values')} (*.csv)"
        )
        if not path:
            return
        mag_cal = MagCal(
            path = path,
            m_per_fov = self.table.to_dict()
        )
        now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        header = f"Beam,{self.beam_name}\nDate,{now}\n"
        data = header + mag_cal.to_csv()
        with open(fileName, 'w') as fd:
            fd.write(data)
        self.write_path_to_toml(path)

    def load_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            # self,
            caption = "Load Calibration",
            filter = f"{self.tr('TableWidget', 'Comma-separated values')} (*.csv)"
        )
        if not path:
            return
        self.write_path_to_toml(path)

    def pass_toml(self, settings:ScopeSettings):
        self.scope_settings = settings

    @staticmethod
    def format_mag_data(data:dict):
        graph_data = np.array([[k,v] for k,v in data.items()])
        table_data = np.array([(k,v) for k,v in data.items()], dtype=[("Magnification", int), ("FOV (m)", float)])
        return graph_data, table_data

    def show_data(self, data:dict):
        graph_data, table_data = self.format_mag_data(data)
        self.table.setData(table_data)
        self.plot_data.setData(graph_data)
    
    def calculate_fov_length(self):
        actual_m = self.length.value()
        if self.line_px is not None:
            if self.resolution is not None:
                m_per_fov = actual_m*(self.resolution/self.line_px)
                self.fov_length.setValue(m_per_fov)
    
    @Slot(float)
    def get_measurement(self, line_px: float):
        self.line_px = line_px
        self.calculate_fov_length()
    
    @Slot(tuple)
    def get_resolution(self, res):
        y_height, x_width = res
        self.resolution = max(y_height, x_width)
        self.calculate_fov_length()
    

                

class MagCalWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Magnification Calibration")
        self.inner = MagCalibration()
        self.setLayout(self.inner)
    def closeEvent(self, event):
        self.inner.sigToggleMeasureLines.emit(False)
        self.inner.measure_btn.setChecked(False)
        event.accept()

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)

    scope = ScopeSettings.from_toml_file()
    w = MagCalWidget()
    w.inner.pass_toml(scope)
    w.inner.set_beam("electron")
    w.show()
    app.exec()