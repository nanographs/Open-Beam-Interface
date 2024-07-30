import sys
import asyncio
import pyqtgraph as pg
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QDialog,
                             QMessageBox, QPushButton, QComboBox,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QFileDialog, QLineEdit, QDialogButtonBox)

import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop


class Window(QMainWindow):
    def __init__(self):
        super().__init__()

def run_gui():
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    window = Window()
    # if not args.window_size == None:
    #     window.resize(args.window_size[0], args.window_size[1])
    window.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())


if __name__ == "__main__":
    run_gui()