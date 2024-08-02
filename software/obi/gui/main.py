import sys
import asyncio
import logging
logger = logging.getLogger()

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QDialog, QProgressBar,
                             QMessageBox, QPushButton, QComboBox, QCheckBox,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QFileDialog, QLineEdit, QDialogButtonBox,
                             QDockWidget)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot
import pyqtgraph as pg

import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop

from obi.gui.components import ImageDisplay, CombinedScanControls, PatternControls

from obi.transfer import TCPConnection, setup_logging
from obi.macros import FrameBuffer, BitmapVectorPattern

from obi.commands import *

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



class PatternWorker(QObject):
    progress = pyqtSignal(int)
    process_requested = pyqtSignal(dict)
    process_completed = pyqtSignal(int)

    @Slot(dict)
    def process_to_vector(self, kwargs):
        path = kwargs["path"]
        resolution = kwargs["resolution"]
        max_dwell = kwargs["dwell_time"]
        invert = kwargs["invert"]

        bmp2vector = BitmapVectorPattern(path)
        progress_fn=lambda p:self.progress.emit(p)
        bmp2vector.rescale(resolution, max_dwell, invert)
        bmp2vector.vector_convert(progress_fn)
        self.pattern_seq = bmp2vector.pattern_seq

        self.process_completed.emit(1)


class Window(QMainWindow):
    _logger = logging.getLogger("GUI")
    vector_process_requested = pyqtSignal(dict)
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

        self.pattern_worker = PatternWorker()
        self.worker_thread = QThread()

        self.pattern_control.inner.convert_btn.clicked.connect(self.convert_pattern)
        self.pattern_control.inner.write_btn.clicked.connect(self.write_pattern)
        self.vector_process_requested.connect(self.pattern_worker.process_to_vector)
        self.pattern_worker.progress.connect(self.update_progress)
        self.pattern_worker.process_completed.connect(self.complete_process_vector)

        self.progress_bar = QProgressBar(maximum=100)
        self.pattern_control.inner.importer.addWidget(self.progress_bar)
        self.progress_bar.hide()

        # move worker to the worker thread
        self.pattern_worker.moveToThread(self.worker_thread)

        # start the thread
        self.worker_thread.start()

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
        self.pattern_control.inner.write_btn.setEnabled(False)
        self.progress_bar.show()
        resolution, dwell_time, invert = self.pattern_control.inner.getvals()
        self.vector_process_requested.emit({"path":self.pattern_control.inner.importer.path, "resolution":resolution, "dwell_time":dwell_time, "invert":invert})
    
    def update_progress(self, v):
        self.progress_bar.setValue(v)

    def complete_process_vector(self):
        self.progress_bar.hide()
        self.progress_bar.setValue(0)
        self.pattern_control.inner.write_btn.setText("Write Pattern")
        self.pattern_control.inner.write_btn.setEnabled(True)

    @asyncSlot()
    async def write_pattern(self):
        self.pattern_control.inner.write_btn.setText("Writing pattern...")
        self.pattern_control.inner.write_btn.setEnabled(False)
        await self.conn.transfer_bytes(self.pattern_worker.pattern_seq)
        cookie = await self.conn._stream.read(4)
        self.conn._synchronized = False
        self.pattern_control.inner.write_btn.setText("Write Pattern")
        self.pattern_control.inner.write_btn.setEnabled(True)


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