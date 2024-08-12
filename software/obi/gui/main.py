import sys
import asyncio
import logging
logger = logging.getLogger()

import numpy as np
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QDialog, QProgressBar,
                             QMessageBox, QPushButton, QComboBox, QCheckBox,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QFileDialog, QLineEdit, QDialogButtonBox, QToolBar,
                             QDockWidget)
import pyqtgraph as pg

import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop

from obi.gui.components import ImageDisplay, CombinedScanControls, CombinedPatternControls, BeamControl, MagCalWidget

from obi.transfer import TCPConnection, setup_logging
from obi.macros import FrameBuffer, BitmapVectorPattern
from obi.config.meta import ScopeSettings

from obi.commands import *

setup_logging({"Stream": logging.DEBUG, "Command": logging.DEBUG, "Connection": logging.DEBUG})

class ScanControlWidget(QDockWidget):
    def __init__(self):
        super().__init__(
            windowTitle="Picture Control", 
            features = QDockWidget.DockWidgetFeature.DockWidgetMovable |
                        QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.inner = CombinedScanControls()
        self.setWidget(self.inner)

class BeamStateWidget(QDockWidget):
    def __init__(self, conn, beams):
        super().__init__(
            windowTitle="Beam State", 
            features = QDockWidget.DockWidgetFeature.DockWidgetMovable |
                        QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.inner = BeamControl(conn, beams)
        self.setWidget(self.inner)


class PatternControlWidget(QDockWidget):
    def __init__(self, conn):
        super().__init__(
            windowTitle="Pattern Control", 
            features = QDockWidget.DockWidgetFeature.DockWidgetMovable |
                        QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.inner = CombinedPatternControls(conn)
        self.setWidget(self.inner)

class Tools(QToolBar):
    def __init__(self):
        super().__init__()
        self.calibrate = self.addAction("Calibrate")
        self.setFont(QFont('Arial', 14)) 
        

class Window(QMainWindow):
    _logger = logging.getLogger("GUI")
    beam_enum = {"electron": BeamType.Electron, "ion": BeamType.Ion}
    def __init__(self):
        super().__init__()
        self.conn = TCPConnection("localhost", 2224)
        self.scope_settings = ScopeSettings.from_toml_file()
        self.fb = FrameBuffer(self.conn)

        self.image_display = ImageDisplay(511, 511)
        self.setCentralWidget(self.image_display)

        self.toolbar = Tools()
        self.addToolBar(self.toolbar)
        self.toolbar.calibrate.triggered.connect(self.open_calibration)

        self.beam_control = BeamStateWidget(self.conn, self.scope_settings.beam_settings)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.beam_control)

        self.scan_control = ScanControlWidget()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.scan_control)

        self.pattern_control = PatternControlWidget(self.conn)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.pattern_control)

        self.scan_control.inner.live.start_btn.clicked.connect(self.toggle_live_scan)
        self.scan_control.inner.live.roi_btn.clicked.connect(self.toggle_roi_scan)
        self.scan_control.inner.photo.acq_btn.clicked.connect(self.acquire_photo)

        self.unique_controllers = [self.scan_control.inner.live, self.scan_control.inner.photo, self.pattern_control]

        ## Popup window
        self.mag_cal = MagCalWidget()
        self.mag_cal.inner.pass_toml(self.scope_settings)
        self.image_display.measure_lines.sigRegionChanged.connect(self.mag_cal.inner.get_measurement)
        self.image_display.sigResolutionChanged.connect(self.mag_cal.inner.get_resolution)
        self.beam_control.inner.sigBeamTypeChanged.connect(self.mag_cal.inner.set_beam)
        self.mag_cal.inner.sigRequestUpdateToml.connect(self.update_toml)
    
    @Slot(ScopeSettings)
    def update_toml(self, settings:ScopeSettings):
        self.scope_settings = settings
        self.scope_settings.to_toml_file() #write out to microscope.toml
    
    def open_calibration(self):
        self.mag_cal.inner.pass_toml(self.scope_settings)
        beam = self.beam_control.inner.get_current_beam()
        if beam is not None:
            self.mag_cal.inner.set_beam(beam)
        if self.fb.current_frame is not None:
            self.mag_cal.inner.resolution = max(self.fb.current_frame._x_count, self.fb.current_frame._y_count)
        self.mag_cal.inner.measure_btn.clicked.connect(self.image_display.add_double_line)
        self.mag_cal.show()
        
    def ensure_unique_control(self, control_item):
        for item in self.unique_controllers:
            if item != control_item:
                item.setEnabled(False)
    def enable_all_controls(self):
        for item in self.unique_controllers:
            item.setEnabled(True)

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


    async def capture_frame(self, resolution, dwell_time):
        if self.image_display.roi is not None:
            await self.capture_ROI(resolution, dwell_time)
        else:
            async for frame in self.fb.capture_full_frame(
                x_res=resolution, y_res=resolution, dwell_time=dwell_time, latency=65536
                ):
                self.image_display.setImage(frame.as_uint8())
                self._logger.debug("set image")
    
    @asyncSlot()
    async def acquire_photo(self):
        self.scan_control.inner.photo.acq_btn.to_live_state(self.fb.abort_scan)

        resolution, dwell_time = self.scan_control.inner.photo.getval()
        await self.capture_frame(resolution, dwell_time)
        self.scan_control.inner.photo.acq_btn.to_paused_state(self.acquire_photo)
        self.ensure_unique_control(self.scan_control.inner.photo)
        print(f"capture done! {self.fb.is_aborted=}")

        # if not self.fb.is_aborted:
        print("time to save the image!")
        path = self.scan_control.inner.photo.file.path()
        self.fb.current_frame.saveImage_tifffile(path)
        self.enable_all_controls()



    @asyncSlot()
    async def toggle_live_scan(self):
        self.scan_control.inner.live.start_btn.to_live_state(self.fb.abort_scan)
        self.ensure_unique_control(self.scan_control.inner.live)
        
        while not self.fb.is_aborted:
            resolution, dwell_time = self.scan_control.inner.live.getval()
            await self.capture_frame(resolution, dwell_time)
        
        self.scan_control.inner.live.start_btn.to_paused_state(self.toggle_live_scan)
        self.enable_all_controls()
        print("done")

    def toggle_roi_scan(self):
        if self.scan_control.inner.live.roi_btn.isChecked():
            self.image_display.add_ROI()
        else: 
            self.image_display.remove_ROI()




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