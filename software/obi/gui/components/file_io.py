from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QFrame, QFileDialog, QCheckBox,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit)
import os

class BrowseDirectory(QVBoxLayout):
    def __init__(self):
        super().__init__()
        upper = QHBoxLayout()
        lower = QHBoxLayout()
        self.name_box = QLineEdit()
        self.path_box = QLineEdit()
        self.path_str = os.getcwd()
        self.path_box.setText(self.path_str)
        self.path_box.setReadOnly(True)
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse)
        
        self.addLayout(upper)
        self.addLayout(lower)

        upper.addWidget(QLabel("Name:"))
        upper.addWidget(self.name_box)
        lower.addWidget(self.browse_btn)
        lower.addWidget(self.path_box)
    def path(self):
        filename = self.name_box.text()
        filepath = self.path_str
        return os.path.join(filepath, filename)
    def browse(self):
        path = QFileDialog.getExistingDirectory()
        if not path:
            return
        self.path_str = path[0]
        self.path_box.setText(path)