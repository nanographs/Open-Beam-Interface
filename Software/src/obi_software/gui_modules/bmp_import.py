import asyncio
import sys

import numpy as np
from PIL import Image, ImageChops
import time
from multiprocessing import Pool

from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QFileDialog, QCheckBox,
                            QProgressBar,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit)
from PyQt6.QtCore import QThread, QObject, pyqtSignal as Signal, pyqtSlot as Slot
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop
import pyqtgraph as pg

from ..stream_interface import Connection
from ..base_commands import *
from .image_display import ImageDisplay



def setup(beam_type):
    seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
    seq.add(BlankCommand(enable=True))
    seq.add(BeamSelectCommand(beam_type=beam_type))
    seq.add(ExternalCtrlCommand(enable=True))
    seq.add(DelayCommand(5760))
    return seq

def teardown():
    seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
    seq.add(ExternalCtrlCommand(enable=False))
    seq.add(DelayCommand(5760))
    return seq


def line(xarray):
    if xarray:
        y, xarray = xarray
        c = bytearray()
        for x in np.nonzero(xarray)[0]:
            c.extend(VectorPixelCommand(x_coord=x, y_coord = y, dwell=xarray[x]).message)
        # for x in range(len(xarray)):
        #     dwell = xarray[x]
        #     if dwell > 0:   
        return c


class Worker(QObject):
    progress = Signal(int)
    file_import_completed = Signal(int)
    image_process_completed = Signal(int)
    vector_process_completed = Signal(int)

    @Slot(str)
    def import_file(self, img_path):
        self.pattern_im = im = Image.open(img_path).convert("L") ## 8 bit grayscale. 255 = longest dwell time, 0 = no dwell
        self.file_import_completed.emit(1)
    
    @Slot(list)
    def process_image(self, vars):
        dwell, invert_checked = vars
        max_dwell = int((dwell*pow(10,9))/125) #convert to units of 125ns
        self.max_dwell = max_dwell #keep track of this value for scaling image display levels
        im = self.pattern_im 
        if invert_checked:
            im = ImageChops.invert(im) 

        ## scale dwell times 
        def level_adjust(pixel_value):
            return int(pixel_value*(max_dwell/255))
        pixel_range = im.getextrema()
        im = im.point(lambda p: level_adjust(p))
        print(f"{pixel_range=} -> scaled_pixel_range= (0,{max_dwell})")

        ## scale to 16384 x 16384
        x_pixels, y_pixels = im._size
        scale_factor = 16384/max(x_pixels, y_pixels)
        scaled_y_pixels = int(y_pixels*scale_factor)
        scaled_x_pixels = int(x_pixels*scale_factor)
        # https://pillow.readthedocs.io/en/stable/_modules/PIL/Image.html#Image.resize
        im = im.resize((scaled_x_pixels, scaled_y_pixels), resampling = Image.Resampling.NEAREST)
        print(f"input image: {x_pixels=}, {y_pixels=} -> {scaled_x_pixels=}, {scaled_y_pixels=}")

        self.pattern_array = np.asarray(im)
        self.image_process_completed.emit(1)

    @Slot(BeamType)
    def process_to_vector(self, beam_type):
        scaled_y_pixels, scaled_x_pixels = self.pattern_array.shape
        seq = CommandSequence(raster=False, output=OutputMode.NoOutput)

        ## Unblank with beam at position 0,0
        seq.add(BeamSelectCommand(beam_type = beam_type))
        seq.add(BlankCommand(enable=False, inline=True))
        seq.add(VectorPixelCommand(x_coord=0, y_coord=0, dwell=1))

        seq = CommandSequence(raster=False, output=OutputMode.NoOutput)
        seqbytes = bytearray(seq.message)
        pool = Pool()
        start = time.time()
        n = 0
        for i in pool.imap(line, enumerate(self.pattern_array)):
            seqbytes.extend(i)
            n += 1
            print(f"{n}")
            self.progress.emit(n)
        pool.close()

        seqbytes.extend(BlankCommand(enable=True).message)
        self.pattern_seq = seqbytes
        self.vector_process_completed.emit(1)

class PatternSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.ilabel = QLabel("Invert?")
        self.addWidget(self.ilabel)
        self.invert_check = QCheckBox()
        self.addWidget(self.invert_check)
        self.dlabel = QLabel("Max Dwell:")
        self.addWidget(self.dlabel)
        self.dwell = pg.SpinBox(value=80*125*pow(10,-9), suffix="s", siPrefix=True, step=125*pow(10,-9), compactHeight=False)
        self.addWidget(self.dwell)
        self.d_unit = QLabel("")
        self.addWidget(self.d_unit)
        self.process_btn = QPushButton("Resize and Process Image")
        self.addWidget(self.process_btn)
    def hide(self):
        self.ilabel.hide()
        self.dlabel.hide()
        self.dwell.hide()
        self.d_unit.hide()
        self.invert_check.hide()
        self.process_btn.hide()
    def show(self):
        self.ilabel.show()
        self.dlabel.show()
        self.dwell.show()
        self.d_unit.show()
        self.invert_check.show()
        self.process_btn.show()
    def get_settings(self):
        checked = self.invert_check.isChecked()
        return checked


class FileImport(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.file_btn = QPushButton("Choose File")
        self.addWidget(self.file_btn)
        self.img_path_label = QLabel("")
        self.addWidget(self.img_path_label)


class BeamSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.beam_type_menu = QComboBox()
        self.beam_type_menu.addItems(["Electron", "Ion"])
        self.addWidget(self.beam_type_menu)
        self.ctrl_btn = QPushButton("Take Control")
        self.ctrl_btn.setCheckable(True)
        self.addWidget(self.ctrl_btn)
        self.beam_state = QLabel("Beam State: Released")
        self.addWidget(self.beam_state)

    
    def get_beam_type(self):
        beam_type = self.beam_type_menu.currentText()
        if beam_type == "Electron":
            return BeamType.Electron
        elif beam_type == "Ion":
            return BeamType.Ion


class ParameterData(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.vl = QVBoxLayout()
        self.a = QHBoxLayout()
        self.b = QHBoxLayout()
        self.c = QHBoxLayout()
        self.vl.addLayout(self.a)
        self.vl.addLayout(self.b)
        self.vl.addLayout(self.c)

        self.a.addWidget(QLabel("Max Dwell:"))
        self.dwell = pg.SpinBox(value=80*125*pow(10,-9), suffix="s", siPrefix=True, step=125*pow(10,-9), compactHeight=False)
        self.a.addWidget(self.dwell)
        self.dwell.valueChanged.connect(self.calculate_exposure)

        self.a.addWidget(QLabel("Beam Current"))
        self.current = pg.SpinBox(value=.000001, suffix="A", siPrefix=True, step=.0000001, compactHeight=False)
        self.a.addWidget(self.current)
        self.current.valueChanged.connect(self.calculate_exposure)

        self.a.addWidget(QLabel("-----> Exposure:"))
        self.exposure = QLabel("      ")
        self.a.addWidget(self.exposure)

        self.b.addWidget(QLabel("HFOV:"))
        self.hfov = pg.SpinBox(value=.000001, suffix="m", siPrefix=True, step=.0000001, compactHeight=False)
        self.hfov.valueChanged.connect(self.calculate_exposure)
        self.b.addWidget(self.hfov)
        self.b.addWidget(QLabel(" ÷ 16384 -----> Pixel Size:"))
        self.pix_size = QLabel("      ")
        self.b.addWidget(self.pix_size)

        self.measure_btn = QPushButton("Measure")
        self.measure_btn.setCheckable(True)
        self.c.addWidget(self.measure_btn)
        self.measure_btn.hide()
        self.l_label = QLabel("Line Length:")
        self.c.addWidget(self.l_label)
        self.l_size = QLabel("       ")
        self.c.addWidget(self.l_size)
        self.l_size.hide()
        self.l_label.hide()
        

        self.addLayout(self.vl)
        self.calculate_exposure()

    def calculate_exposure(self):
        hfov = self.hfov.interpret()
        dwell = self.dwell.interpret()
        current = self.current.interpret()
        if hfov and dwell and current:
            hfov = self.hfov.value()
            dwell = self.dwell.value()
            current = self.current.value()
            pixel_size = hfov/16384
            exposure = current*dwell/(pixel_size*pixel_size)
            self.pix_size.setText(f"{pg.siFormat(pixel_size, suffix="m")}")
            self.exposure.setText(f"{pg.siFormat(exposure, suffix="C/m^2")}")
        
class VectorProcessState(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.convert_btn = QPushButton("Convert to Vector Stream")
        self.addWidget(self.convert_btn)
        self.convert_btn.hide()
        self.progress_bar = QProgressBar(maximum=16384)
        self.progress_bar.hide()
        self.addWidget(self.progress_bar)



class MainWindow(QVBoxLayout):
    file_import_requested = Signal(str)
    image_process_requested = Signal(list)
    vector_process_requested = Signal(BeamType)
    def __init__(self, conn, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.conn = conn
        self.addWidget(QLabel("Calculate Process Parameters:"))
        self.param_data = ParameterData()
        self.addLayout(self.param_data)
        self.param_data.measure_btn.clicked.connect(self.toggle_measure)
        self.param_data.dwell.valueChanged.connect(self.update_dwell_fromparamcalc)
        self.image_display = ImageDisplay(512, 512)
        self.addWidget(self.image_display)
        self.image_display.hide()

        self.file_import = FileImport()
        self.addLayout(self.file_import)
        self.file_import.file_btn.clicked.connect(self.file_dialog)

        self.pattern_settings = PatternSettings()
        self.addLayout(self.pattern_settings)
        self.pattern_settings.process_btn.clicked.connect(self.start_process_image)
        self.pattern_settings.dwell.valueChanged.connect(self.update_dwell_frompatternsettings)
        self.pattern_settings.hide()

        self.beam_settings = BeamSettings()
        self.addLayout(self.beam_settings)
        self.beam_settings.ctrl_btn.clicked.connect(self.toggle_ext_ctrl)

        self.vector_process = VectorProcessState()
        self.addLayout(self.vector_process)
        self.vector_process.convert_btn.clicked.connect(self.start_process_vector)

        self.pattern_btn = QPushButton("Write Pattern")
        self.pattern_btn.setCheckable(True)
        self.pattern_btn.setEnabled(False)
        self.addWidget(self.pattern_btn)
        self.pattern_btn.hide()
        self.pattern_btn.clicked.connect(self.write_pattern)

        self.worker = Worker()
        self.worker_thread = QThread()

        self.worker.progress.connect(self.update_progress)
        self.worker.file_import_completed.connect(self.complete_file_import)

        self.file_import_requested.connect(self.worker.import_file)

        self.worker.image_process_completed.connect(self.complete_process_image)

        self.image_process_requested.connect(self.worker.process_image)

        self.worker.vector_process_completed.connect(self.complete_process_vector)

        self.vector_process_requested.connect(self.worker.process_to_vector)

        # move worker to the worker thread
        self.worker.moveToThread(self.worker_thread)

        # start the thread
        self.worker_thread.start()
    
    def update_dwell_frompatternsettings(self):
        dwell = self.pattern_settings.dwell.value()
        max_dwell = int((dwell*pow(10,9))/125) #convert to units of 125ns
        self.pattern_settings.d_unit.setText(f"{max_dwell} x 125 ns")
        self.param_data.dwell.setValue(dwell)

    def update_dwell_fromparamcalc(self):
        dwell = self.param_data.dwell.value()
        max_dwell = int((dwell*pow(10,9))/125) #convert to units of 125ns
        self.pattern_settings.d_unit.setText(f"{max_dwell} x 125 ns")
        self.pattern_settings.dwell.setValue(dwell)

    @asyncSlot()
    async def toggle_ext_ctrl(self):
        if self.beam_settings.ctrl_btn.isChecked():
            cmds = setup(self.beam_settings.get_beam_type())
            await self.conn.transfer_raw(cmds)
            self.beam_settings.beam_state.setText("Beam State: Blanked")
            self.beam_settings.ctrl_btn.setText("Release Control")
            self.pattern_btn.setEnabled(True)
        else:
            cmds = teardown()
            await self.conn.transfer_raw(cmds)
            self.beam_settings.beam_state.setText("Beam State: Released")
            self.beam_settings.ctrl_btn.setText("Take Control")
            self.pattern_btn.setEnabled(False)

    @asyncSlot()
    async def file_dialog(self):
        img_path = QFileDialog.getOpenFileName()[0] #filter = "tr(Images (*.bmp))"
        self.file_import.img_path_label.setText(img_path)
        self.file_import_requested.emit(img_path)
        
    
    def complete_file_import(self, v):
        self.pattern_btn.setEnabled(True)
        self.pattern_settings.show()
        self.update_dwell_fromparamcalc()
        self.pattern_settings.process_btn.setEnabled(True)
        self.pattern_btn.hide()
        a = np.asarray(self.worker.pattern_im)
        x, y = a.shape
        self.image_display.setImage(y, x, a)
        self.image_display.show()
        self.param_data.measure_btn.show()
        

        
    def toggle_measure(self):
        if self.param_data.measure_btn.isChecked():
            self.param_data.l_label.show()
            self.param_data.l_size.show()
            self.image_display.add_line()
            self.image_display.line.sigRegionChanged.connect(self.measure)
            self.param_data.hfov.valueChanged.connect(self.measure)
            self.measure()
        else:
            self.image_display.remove_line()
            self.param_data.l_size.setText("      ")
            self.param_data.hfov.valueChanged.connect(self.measure)
            self.param_data.l_label.hide()
            self.param_data.l_size.hide()

    

    def measure(self):
        if not self.image_display.line == None:
            pixel_size = self.param_data.hfov.value()/16384
            line_length = self.image_display.get_line_length()
            line_actual_size = line_length*pixel_size
            line_label = pg.siFormat(line_actual_size, suffix="m")
            self.param_data.l_size.setText(line_label)

    def start_process_image(self):
        self.pattern_settings.process_btn.setText("Processing")
        self.pattern_settings.process_btn.setEnabled(False)
        invert_checked = self.pattern_settings.get_settings()
        dwell = self.param_data.dwell.value()
        self.image_process_requested.emit([dwell, invert_checked])

    def complete_process_image(self):
        self.pattern_settings.process_btn.setText("Process")
        self.pattern_settings.process_btn.setEnabled(True)
        self.vector_process.convert_btn.show()
        x, y = self.worker.pattern_array.shape
        self.image_display.setImage(y, x, self.worker.pattern_array)
        self.image_display.hist.setLevels(min=0, max=self.worker.max_dwell) # [black, white]

    def start_process_vector(self):
        self.vector_process.progress_bar.show()
        self.vector_process.convert_btn.setEnabled(False)
        self.vector_process.convert_btn.setText("Preparing pattern...")
        self.vector_process_requested.emit(self.beam_settings.get_beam_type())

    def update_progress(self, v):
        self.vector_process.progress_bar.setValue(v)

    def complete_process_vector(self):
        self.vector_process.progress_bar.hide()
        self.vector_process.convert_btn.hide()
        self.vector_process.convert_btn.setEnabled(True)
        self.pattern_btn.setText("Write Pattern")
        self.pattern_btn.setEnabled(True)
        self.pattern_btn.show()

    
    @asyncSlot()
    async def write_pattern(self):
        self.pattern_btn.setText("Writing pattern...")
        self.pattern_btn.setEnabled(False)
        self.beam_settings.beam_state.setText("Beam State: Writing pattern")
        await self.conn.transfer_bytes(self.worker.pattern_seq)
        self.beam_settings.beam_state.setText("Beam State: Blanked")
        self.pattern_btn.setEnabled(True)




async def _main():
    conn = Connection('localhost', 2224)
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    window = MainWindow(conn)
    w.setLayout(window)
    w.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())
    
    if window.worker.isRunning():
        window.worker.terminate()
        window.worker.wait()


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
    
