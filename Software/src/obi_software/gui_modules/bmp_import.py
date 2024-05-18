import asyncio
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont
import time
from multiprocessing import Pool

from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QFileDialog, QCheckBox,
                            QProgressBar,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit)
from PyQt6.QtCore import QThread, QObject, pyqtSignal as Signal, pyqtSlot as Slot
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop
import pyqtgraph as pg

from ..stream_interface import Connection, setup_logging
from ..base_commands import *
from .image_display import ImageDisplay


import logging
setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG})

FRACTIONAL_DWELL = True
# VectorPixel commands have a minimum dwell of 125 ns (6 48 MHz clock cycles)
# By adding a Delay command, the dwell time can be extended in units of 20.83 ns (one 48 MHz clock cycles)
# Delay commands are 3 bytes long and take 3 clock cycles to parse serially
# Therefore the fractional strategy might not be reliable between 125ns - 250ns
# Additional development in gateware is required to have more control over the smallest dwell times.
DEALWITHRGB = False
# if you want to do something specific to convert RGB images to grayscale,
# insert it in Worker.import_file, ~line 81

def setup(beam_type):
    seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
    #seq = CommandSequence(sync=False)
    seq.add(BlankCommand(enable=True))
    seq.add(BeamSelectCommand(beam_type=beam_type))
    seq.add(ExternalCtrlCommand(enable=True))
    seq.add(DelayCommand(5760))
    return seq

def teardown():
    #seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
    seq = CommandSequence(sync=False)
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
    process_img_output = Signal(str)
    file_import_completed = Signal(int)
    image_process_completed = Signal(int)
    vector_process_completed = Signal(int)

    @Slot(str)
    def import_file(self, img_path):
        if DEALWITHRGB:
            im = Image.open(img_path)
            arr = np.asarray(im)
            y_pix, x_pix, rgb = arr.shape
            newarr = np.zeros((y_pix, x_pix))
            for y in range(y_pix):
                for x in range(x_pix):
                    r, g, b = arr[y][x]
                    newarr[y][x] = r
            self.pattern_im = Image.fromarray(newarr).convert("L")
        else:
            self.pattern_im = im = Image.open(img_path).convert("L") ## 8 bit grayscale. 255 = longest dwell time, 0 = no dwell
        self.file_import_completed.emit(1)
    
    @Slot(list)
    def process_image(self, vars):
        dwell, dwell_steps, invert_checked, label_checked = vars
        self.max_dwell = dwell_steps #keep track of this value for scaling image display levels
        im = self.pattern_im 
        if invert_checked:
            im = ImageChops.invert(im) 

        ## scale dwell times 
        def level_adjust(pixel_value):
            return int((pixel_value/255)*self.max_dwell)
        pixel_range = im.getextrema()
        im = im.point(lambda p: level_adjust(p))
        print(f"{pixel_range=} -> scaled_pixel_range= (0,{self.max_dwell})")

        ## scale to 16384 x 16384
        x_pixels, y_pixels = im._size
        scale_factor = 16384/max(x_pixels, y_pixels)
        scaled_y_pixels = int(y_pixels*scale_factor)
        scaled_x_pixels = int(x_pixels*scale_factor)
        # https://pillow.readthedocs.io/en/stable/_modules/PIL/Image.html#Image.resize
        im = im.resize((scaled_x_pixels, scaled_y_pixels), resample = Image.Resampling.NEAREST)
        print(f"input image: {x_pixels=}, {y_pixels=} -> {scaled_x_pixels=}, {scaled_y_pixels=}")

        if label_checked:
            #font = ImageFont.truetype("Open-Beam-Interface/Software/src/obi_software/iAWriterQuattroV.ttf", size=500)
            if dwell*pow(10,9) > 1000: #the default font does not support "µ"
                label_text = f"{dwell*pow(10,6):.0f} us" 
            else:
                label_text = f"{dwell*pow(10,9):.0f} ns" 
            draw = ImageDraw.Draw(im)
            x_width = len(label_text)
            draw.rectangle([(0, 0),(x_width*270 + 10,450)], fill=0)
            draw.text([10,10], label_text, fill=self.max_dwell, anchor = "lt",font_size=500) 

        self.pattern_array = np.asarray(im)
        self.image_process_completed.emit(1)


    @Slot(BeamType)
    def process_to_vector(self, beam_type):
        scaled_y_pixels, scaled_x_pixels = self.pattern_array.shape
        #seq = CommandSequence(raster=False, output=OutputMode.NoOutput)
        seq = CommandSequence(sync=False)

        ## Unblank with beam at position 0,0
        seq.add(BeamSelectCommand(beam_type = beam_type))
        seq.add(BlankCommand(enable=False, inline=True))
        seq.add(VectorPixelCommand(x_coord=0, y_coord=0, dwell=1))

        seqbytes = bytearray(seq.message)
        pool = Pool()
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


class DwellSpinbox(pg.SpinBox):
    def __init__(self):
        if FRACTIONAL_DWELL:
            self.step = (125/6)*pow(10,-9) # 20.83 ns
            self.step_str = "20.83 ns"
        else:
            self.step = 125*pow(10,-9) # 125 ns
            self.step_str = "125 ns"
        super().__init__(value=80*125*pow(10,-9), suffix="s", 
                        siPrefix=True,
                        compactHeight=False, step=self.step)
        self.setMinimum(125*pow(10,-9))


class DwellSetting(QHBoxLayout):
    def __init__(self, step_label=False):
        self.step_label = step_label
        super().__init__()
        self.dlabel = QLabel("Max Dwell:")
        self.addWidget(self.dlabel)
        self.dbox = DwellSpinbox()
        self.addWidget(self.dbox)
        self.d_unit = QLabel("")
        self.addWidget(self.d_unit)
    def get_value(self):
        dwell = self.dbox.value()
        dwell_steps = int(dwell/self.dbox.step) #convert to "units" of dwell time, 125ns or 20.83ns
        if self.step_label:
            self.d_unit.setText(f"{dwell_steps} x {self.dbox.step_str}")
        return dwell, dwell_steps
    def set_value(self, dwell):
        self.dbox.setValue(dwell)
        dwell_steps = int(dwell/self.dbox.step) #convert to "units" of dwell time, 125ns or 20.83ns
        if self.step_label:
            self.d_unit.setText(f"{dwell_steps} x {self.dbox.step_str}")
    def hide(self):
        self.dlabel.hide()
        self.dbox.hide()
        self.d_unit.hide()
    def show(self):
        self.dlabel.show()
        self.dbox.show()
        if self.step_label:
            self.d_unit.show()


class PatternSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.ilabel = QLabel("Invert:")
        self.addWidget(self.ilabel)
        self.invert_check = QCheckBox()
        self.addWidget(self.invert_check)
        self.llabel = QLabel("Label Dwell In Pattern:")
        self.addWidget(self.llabel)
        self.label_check = QCheckBox() ## Label is added in Worker.process_image
        self.addWidget(self.label_check)
        self.dwell = DwellSetting(step_label=True)
        self.addLayout(self.dwell)
        self.process_btn = QPushButton("Resize and Process Image")
        self.addWidget(self.process_btn)

        
    def hide(self):
        self.ilabel.hide()
        self.llabel.hide()
        self.label_check.hide()
        self.dwell.hide()
        self.invert_check.hide()
        self.process_btn.hide()

    def show(self):
        self.ilabel.show()
        self.dwell.show()
        self.llabel.show()
        self.label_check.show()
        self.invert_check.show()
        self.process_btn.show()

    def get_settings(self):
        invertchecked = self.invert_check.isChecked()
        labelchecked = self.label_check.isChecked()
        dwell, dwell_steps = self.dwell.get_value()
        return dwell, dwell_steps, invertchecked, labelchecked


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

        self.dwell = DwellSetting()
        self.a.addLayout(self.dwell)
        # sigValueChanging is more responsive than valueChanged
        self.dwell.dbox.sigValueChanging.connect(self.calculate_exposure)

        self.a.addWidget(QLabel("Beam Current"))
        self.current = pg.SpinBox(value=.000001, suffix="A", siPrefix=True, step=.0000001, compactHeight=False)
        self.a.addWidget(self.current)
        self.current.sigValueChanging.connect(self.calculate_exposure)

        self.a.addWidget(QLabel("-----> Exposure:"))
        self.exposure = QLabel("      ")
        self.a.addWidget(self.exposure)

        self.b.addWidget(QLabel("HFOV:"))
        self.hfov = pg.SpinBox(value=.000001, suffix="m", siPrefix=True, step=.0000001, compactHeight=False)
        self.hfov.sigValueChanging.connect(self.calculate_exposure)
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
        dwell = self.dwell.dbox.interpret()
        current = self.current.interpret()
        if hfov and dwell and current:
            hfov = self.hfov.value()
            dwell = self.dwell.dbox.value()
            current = self.current.value()
            pixel_size = hfov/16384
            exposure = current*dwell/(pixel_size*pixel_size)
            self.pix_size.setText(f"{pg.siFormat(pixel_size, suffix="m")}")
            self.exposure.setText(f"{pg.siFormat(exposure, suffix="C/m^2")}") #1 GC/m^2 = 1 uC/cm^2
        
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
        self.param_data.dwell.dbox.sigValueChanging.connect(self.update_dwell_fromparamcalc)
        self.image_display = ImageDisplay(512, 512)
        self.addWidget(self.image_display)
        self.image_display.hide()

        self.file_import = FileImport()
        self.addLayout(self.file_import)
        self.file_import.file_btn.clicked.connect(self.file_dialog)

        self.pattern_settings = PatternSettings()
        self.addLayout(self.pattern_settings)
        self.pattern_settings.process_btn.clicked.connect(self.start_process_image)
        self.pattern_settings.dwell.dbox.sigValueChanging.connect(self.update_dwell_frompatternsettings)
        self.pattern_settings.hide()

        self.beam_settings = BeamSettings()
        self.addLayout(self.beam_settings)
        self.beam_settings.ctrl_btn.clicked.connect(self.toggle_ext_ctrl)

        self.vector_process = VectorProcessState()
        self.addLayout(self.vector_process)
        self.vector_process.convert_btn.clicked.connect(self.start_process_vector)

        self.pattern_btn = QPushButton("Write Pattern")
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
        dwell, dwell_steps = self.pattern_settings.dwell.get_value()
        self.param_data.dwell.set_value(dwell)

    def update_dwell_fromparamcalc(self):
        dwell, dwell_steps = self.param_data.dwell.get_value()
        self.pattern_settings.dwell.set_value(dwell)

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
        y, x = a.shape
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
        dwell, dwell_steps, invert_checked, label_checked = self.pattern_settings.get_settings()
        self.image_process_requested.emit([dwell, dwell_steps, invert_checked, label_checked])

    def complete_process_image(self):
        self.pattern_settings.process_btn.setText("Resize and Process Image")
        self.pattern_settings.process_btn.setEnabled(True)
        self.vector_process.convert_btn.show()
        y, x = self.worker.pattern_array.shape
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
        self.vector_process.convert_btn.setText("Convert to Vector Stream")
        self.vector_process.convert_btn.setEnabled(True)
        self.pattern_btn.setText("Write Pattern")
        self.pattern_btn.show()

    
    @asyncSlot()
    async def write_pattern(self):
        self.pattern_btn.setText("Writing pattern...")
        self.pattern_btn.setEnabled(False)
        self.beam_settings.ctrl_btn.setEnabled(False)
        self.beam_settings.beam_state.setText("Beam State: Writing pattern")
        await self.conn.transfer_bytes(self.worker.pattern_seq)
        self.beam_settings.beam_state.setText("Beam State: Blanked")
        self.pattern_btn.setEnabled(True)
        self.beam_settings.ctrl_btn.setEnabled(True)
        self.pattern_btn.setText("Write Pattern")




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
    
