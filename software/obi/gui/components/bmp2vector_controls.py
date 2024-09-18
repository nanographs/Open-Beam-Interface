from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QFrame, QFileDialog, QCheckBox,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton, QProgressBar)
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop

import os

from obi.macros import BitmapVectorPattern
from .scan_parameters import SettingBoxWithDefaults, QHLine
from .dose_calc import DoseCalcWidget


class PatternWorker(QObject):
    progress = pyqtSignal(int)
    process_requested = pyqtSignal(dict)
    process_completed = pyqtSignal(int)

    @Slot(dict)
    def process(self, kwargs):
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


class BmpImport(QFileDialog):
    def __init__(self):
        super().__init__()
        self.setNameFilters(["Images (*.png *.jpg *.bmp)"])

class PatternImport(QVBoxLayout):
    def __init__(self):
        super().__init__()
        self.file_select_btn = QPushButton("Select Pattern")
        self.addWidget(self.file_select_btn)
        self.path_label = QLabel(" ")
        self.addWidget(self.path_label)
        self.path = None
    
    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(
            caption = "Select Pattern File",
            filter = f"{self.tr('Images')} (*.bmp *.png *.jpeg *.jpg *.webp *.tiff)"
        )
        if not path:
            return
        self.path_label.setText(os.path.basename(path))
        self.path = path

class PatternParameters(QVBoxLayout):
    def __init__(self):
        super().__init__()
        self.invert_selected = QCheckBox("Invert")
        self.resolution_settings = SettingBoxWithDefaults("Resolution", 256, 16384, 4096, defaults=["512", "1024", "2048", "4096", "8192", "16384", "Custom"])
        self.dwell_time = SettingBoxWithDefaults("Dwell Time", 1, 65536, 8, defaults=["1", "2", "4", "8", "16", "32", "64", "Custom"])
        self.calc = QPushButton("🧮")
        self.dose = DoseCalcWidget()
        self.calc.clicked.connect(self.dose_fn)
        
        self.d = QHBoxLayout()
        self.addWidget(self.invert_selected)
        self.addLayout(self.resolution_settings)
        self.d.addLayout(self.dwell_time)
        self.d.addWidget(self.calc)
        self.addLayout(self.d)
    
    def dose_fn(self):
        self.dose.show()

    def getvals(self):
        dwell_time = self.dwell_time.getval()
        resolution = self.resolution_settings.getval()
        invert = self.invert_selected.isChecked()
        return resolution, dwell_time, invert

class PatternControlButtons(QVBoxLayout):
    def __init__(self):
        super().__init__()
        self.convert_btn = QPushButton("Convert to Vector")
        self.convert_btn.setEnabled(False)
        self.progress_bar = QProgressBar(maximum=100)
        self.write_btn = QPushButton("Write Pattern")
        self.write_btn.setEnabled(False)

        self.addWidget(self.convert_btn)
        self.addWidget(self.progress_bar)
        self.addWidget(self.write_btn)
        
    def setEnabled(self, enabled=True):
        self.write_btn.setEnabled(enabled)


class CombinedPatternControls(QWidget):
    process_requested = pyqtSignal(dict)
    def __init__(self, conn): #Connection
        self.conn = conn
        super().__init__()
        self.importer = PatternImport()
        self.params = PatternParameters()
        self.controls = PatternControlButtons()

        self.importer.file_select_btn.clicked.connect(self.import_file)
        self.controls.convert_btn.clicked.connect(self.convert_pattern)
        self.controls.write_btn.clicked.connect(self.write_pattern)

        layout = QVBoxLayout()
        layout.setSpacing(1)
        layout.addLayout(self.importer)
        layout.addWidget(QHLine())
        layout.addLayout(self.params)
        layout.addLayout(self.controls)
        self.setLayout(layout)

        self.worker = PatternWorker()
        self.process_requested.connect(self.worker.process)
        self.worker.progress.connect(self.update_progress)
        self.worker.process_completed.connect(self.complete_process)
        
        self.worker_thread = QThread()
        # move worker to the worker thread
        self.worker.moveToThread(self.worker_thread)
        # start the thread
        self.worker_thread.start()
    
    def setEnabled(self, enabled=True):
        self.controls.write_btn.setEnabled(enabled)
    
    def import_file(self):
        self.importer.select_file()
        self.controls.convert_btn.setEnabled(True)

    def convert_pattern(self):
        self.controls.write_btn.setEnabled(False)
        resolution, dwell_time, invert = self.params.getvals()
        self.process_requested.emit({"path":self.importer.path, "resolution":resolution, "dwell_time":dwell_time, "invert":invert})

    def update_progress(self, v):
        self.controls.progress_bar.setValue(v)

    def complete_process(self):
        self.controls.progress_bar.setValue(0)
        self.controls.write_btn.setText("Write Pattern")
        self.controls.write_btn.setEnabled(True)

    @asyncSlot()
    async def write_pattern(self):
        self.controls.write_btn.setText("Writing pattern...")
        self.controls.write_btn.setEnabled(False)
        await self.conn.transfer_bytes(self.worker.pattern_seq)
        self.conn._synchronized = False
        self.controls.write_btn.setText("Write Pattern")
        self.controls.write_btn.setEnabled(True)
    

if __name__ == "__main__":
    import sys
    import asyncio
    from obi.transfer import TCPConnection
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    conn = TCPConnection('localhost', 2224)
    
    b = CombinedPatternControls(conn)
    b.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())
    


