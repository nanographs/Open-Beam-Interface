import sys

from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QDialog, QProgressBar,
                             QMessageBox, QPushButton, QComboBox, QCheckBox,
                             QVBoxLayout, QWidget, QLabel, QGridLayout, QTextEdit, QPlainTextEdit,
                             QSpinBox, QFileDialog, QLineEdit, QDialogButtonBox, QToolBar,
                             QDockWidget, QSizePolicy, QApplication)

from obi.gui.components.console import ProcessConsole


class Base(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("OBI Launcher")

        self.servcon = ProcessConsole("pdm run launch", "Server")
        self.guicon = ProcessConsole("pdm run gui", "GUI")

        layout = QVBoxLayout()
        hlayout = QHBoxLayout()
        hlayout.addWidget(QLabel("Welcome to Open Beam Interface 🔬✨"))
        hlayout.addStretch(stretch=2)
        layout.addLayout(hlayout)
        split_layout = QHBoxLayout()
        split_layout.addWidget(self.servcon)
        split_layout.addWidget(self.guicon)
        layout.addLayout(split_layout)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    
    def terminate_all(self):
        self.servcon.process.terminate()
        self.guicon.process.terminate()

if __name__ == "__main__":

    app = QApplication(sys.argv)

    base = Base()
    base.show()

    app.aboutToQuit.connect(base.terminate_all)
    sys.exit(app.exec())
