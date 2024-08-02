import sys
import asyncio
import logging
logger = logging.getLogger()

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QDialog, QProgressBar,
                             QMessageBox, QPushButton, QComboBox,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QFileDialog, QLineEdit, QDialogButtonBox,
                             QDockWidget)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot
import pyqtgraph as pg

import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop

from obi.gui.components import ImageDisplay, CombinedScanControls, PatternControls

from obi.transfer import TCPConnection, setup_logging
from obi.macros import FrameBuffer

setup_logging({"GUI": logging.DEBUG, "FrameBuffer": logging.DEBUG})

class ScanControlWidget(QDockWidget):
    def __init__(self):
        super().__init__(
            windowTitle="Picture Control", 
            features = QDockWidget.DockWidgetFeature.DockWidgetMovable |
                        QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.inner = CombinedScanControls()
        self.setWidget(self.inner)

class PatternControlWidget(QDockWidget):
    def __init__(self):
        super().__init__(
            windowTitle="Pattern Control", 
            features = QDockWidget.DockWidgetFeature.DockWidgetMovable |
                        QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.inner = PatternControls()
        self.setWidget(self.inner)

class Window(QMainWindow):
    _logger = logging.getLogger("GUI")
    def __init__(self):
        super().__init__()
        self.conn = TCPConnection("localhost", 2224)
        self.fb = FrameBuffer(self.conn)

        self.image_display = ImageDisplay(511, 511)
        self.setCentralWidget(self.image_display)

        self.scan_control = ScanControlWidget()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.scan_control)

        self.pattern_control = PatternControlWidget()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.pattern_control)

        self.scan_control.inner.live.start_btn.clicked.connect(self.toggle_live_scan)
        self.scan_control.inner.live.roi_btn.clicked.connect(self.toggle_roi_scan)

        self.pattern_control.inner.importer.convert_btn.clicked.connect(self.convert_pattern)

    async def capture_ROI(self, resolution, dwell_time):
        x_start, x_count, y_start, y_count = self.image_display.get_ROI()
        print(f"{x_start=}, {x_count=}, {y_start=}, {y_count=}")
        async for frame in self.fb.capture_frame_roi(
            x_res=resolution, y_res=resolution,
            x_start = x_start, x_count = x_count, y_start = y_start, y_count = y_count,
            dwell_time=dwell_time, latency=65536
        ):
            self.image_display.setImage(frame.as_uint8())
            self._logger.debug("set image ROI")


    async def capture_frame(self):
        resolution, dwell_time = self.scan_control.inner.live.getval()
        if self.image_display.roi is not None:
            await self.capture_ROI(resolution, dwell_time)
        else:
            async for frame in self.fb.capture_full_frame(
                x_res=resolution, y_res=resolution, dwell_time=dwell_time, latency=65536
                ):
                self.image_display.setImage(frame.as_uint8())
                self._logger.debug("set image")


    @asyncSlot()
    async def toggle_live_scan(self):
        self.scan_control.inner.live.start_btn.setEnabled(False)

        stop_scan = asyncio.Event()
        self.scan_control.inner.live.start_btn.clicked.disconnect(self.toggle_live_scan)
        self.scan_control.inner.live.start_btn.clicked.connect(self.fb.abort_scan)
        self.scan_control.inner.live.start_btn.setText("Stop Live Scan")

        self.scan_control.inner.live.start_btn.setEnabled(True)
        
        while not self.fb.is_aborted:
            await self.capture_frame()
        
        self.scan_control.inner.live.start_btn.setText("Start Live Scan")
        self.scan_control.inner.live.start_btn.clicked.connect(self.toggle_live_scan)

        self.scan_control.inner.live.start_btn.setEnabled(True)
        print("done")

    def toggle_roi_scan(self):
        if self.scan_control.inner.live.roi_btn.isChecked():
            self.image_display.add_ROI()
        else: 
            self.image_display.remove_ROI()

    def convert_pattern(self):
        self.progress_bar = QProgressBar(maximum=1000)
        self.pattern_control.inner.addWidget(self.progress_bar)


class PatternWorker(QObject):
    progress = pyqtSignal(int)
    process_completed = pyqtSignal()

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