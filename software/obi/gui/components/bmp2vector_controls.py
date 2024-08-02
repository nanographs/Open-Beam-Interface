from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QFrame, QFileDialog, QCheckBox,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton)
from PyQt6.QtCore import Qt
import os

from .scan_parameters import SettingBoxWithDefaults, QHLine


class BmpImport(QFileDialog):
    def __init__(self):
        super().__init__()
        self.setNameFilters(["Images (*.png *.jpg *.bmp)"])

class PatternImport(QVBoxLayout):
    def __init__(self):
        super().__init__()
        self.file_select_btn = QPushButton("Select Pattern")
        self.addWidget(self.file_select_btn)
        self.file_select_btn.clicked.connect(self.select_file)
        self.path_label = QLabel(" ")
        self.addWidget(self.path_label)
        self.path = None
    
    def select_file(self):
        file_path = QFileDialog.getOpenFileName()
        self.path_label.setText(os.path.basename(file_path[0]))
        self.path = file_path[0]

class PatternControls(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        self.importer = PatternImport()
        layout.addLayout(self.importer)
        layout.addWidget(QHLine())
        self.invert_selected = QCheckBox("Invert")
        layout.addWidget(self.invert_selected)
        self.resolution_settings = SettingBoxWithDefaults("Resolution", 256, 16384, 4096, defaults=["512", "1024", "2048", "4096", "8192", "16384", "Custom"])
        layout.addLayout(self.resolution_settings)
        self.dwell_time = SettingBoxWithDefaults("Dwell Time", 1, 65536, 8, defaults=["1", "2", "4", "8", "16", "32", "64", "Custom"])
        layout.addLayout(self.dwell_time)
        self.convert_btn = QPushButton("Convert to Vector")
        layout.addWidget(self.convert_btn)
        #self.convert_btn.setEnabled(False)
        self.write_btn = QPushButton("Write Pattern")
        layout.addWidget(self.write_btn)
        self.write_btn.setEnabled(False)

        self.setLayout(layout)

    def getvals(self):
        dwell_time = self.dwell_time.getval()
        resolution = self.resolution_settings.getval()
        invert = self.invert_selected.isChecked()
        return resolution, dwell_time, invert
