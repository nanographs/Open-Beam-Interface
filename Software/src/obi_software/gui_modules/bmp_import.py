import asyncio
import sys

import numpy as np
from PIL import Image, ImageChops
import time

from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget, QFileDialog, QCheckBox,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit)
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop
import pyqtgraph as pg

from ..stream_interface import Connection
from ..base_commands import *
from .image_display import ImageDisplay



def setup():
    seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
    seq.add(BlankCommand(enable=True))
    seq.add(BeamSelectCommand(beam_type=BeamType.Electron))
    seq.add(ExternalCtrlCommand(enable=True))
    seq.add(DelayCommand(5760))
    return seq

def teardown():
    seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
    seq.add(ExternalCtrlCommand(enable=False))
    seq.add(DelayCommand(5760))
    return seq

class PatternSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.ilabel = QLabel("Invert?")
        self.addWidget(self.ilabel)
        self.invert_check = QCheckBox()
        self.addWidget(self.invert_check)
        self.process_btn = QPushButton("Process")
        self.addWidget(self.process_btn)
    def hide(self):
        self.ilabel.hide()
        self.invert_check.hide()
        self.process_btn.hide()
    def show(self):
        self.ilabel.show()
        self.invert_check.show()
        self.process_btn.show()
    def get_settings(self):
        checked = self.invert_check.isChecked()
        return checked


class BmpSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.file_btn = QPushButton("Choose File")
        self.addWidget(self.file_btn)
        self.pattern_im = None
        self.pattern_array = None
        self.addWidget(QLabel("Image Path: "))
        self.img_path_label = QLabel("")
        self.addWidget(self.img_path_label)
        self.pattern_settings = PatternSettings()
        self.addLayout(self.pattern_settings)
        self.process_btn = self.pattern_settings.process_btn
        self.pattern_settings.hide()



class BeamSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.ctrl_btn = QPushButton("Take Control")
        self.ctrl_btn.setCheckable(True)
        self.addWidget(self.ctrl_btn)
        self.addWidget(QLabel("Beam State: "))
        self.beam_state = QLabel("Released")
        self.addWidget(self.beam_state)


class ParameterData(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.vl = QVBoxLayout()
        self.a = QHBoxLayout()
        self.b = QHBoxLayout()
        self.vl.addLayout(self.a)
        self.vl.addLayout(self.b)
        self.a.addWidget(QLabel("HFOV:"))
        self.hfov = pg.SpinBox(value=.000001, suffix="m", siPrefix=True, step=.0000001, compactHeight=False)
        self.a.addWidget(self.hfov)

        self.a.addWidget(QLabel("Beam Current"))
        self.current = pg.SpinBox(value=.000001, suffix="A", siPrefix=True, step=.0000001, compactHeight=False)
        self.a.addWidget(self.current)

        self.a.addWidget(QLabel("Max Dwell Time"))
        self.dwell = pg.SpinBox(value=80*125*pow(10,-9), suffix="s", siPrefix=True, step=125*pow(10,-9), compactHeight=False)
        self.a.addWidget(self.dwell)

        self.dwell.valueChanged.connect(self.calculate_exposure)
        self.hfov.valueChanged.connect(self.calculate_exposure)
        self.current.valueChanged.connect(self.calculate_exposure)
        self.b.addWidget(QLabel("Exposure:"))
        self.exposure = QLabel("      ")
        self.b.addWidget(self.exposure)
        self.b.addWidget(QLabel("Pixel Size:"))
        self.pix_size = QLabel("      ")
        self.b.addWidget(self.pix_size)

        self.addLayout(self.vl)
        self.calculate_exposure()

        self.measure_btn = QPushButton("Measure")
        self.measure_btn.setCheckable(True)
        self.addWidget(self.measure_btn)
        self.measure_btn.hide()
        self.l_label = QLabel("Line Length:")
        self.addWidget(self.l_label)
        self.l_size = QLabel("       ")
        self.addWidget(self.l_size)
        self.l_size.hide()
        self.l_label.hide()

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
        

class MainWindow(QVBoxLayout):
    def __init__(self, conn):
        self.conn = conn
        super().__init__()
        self.beam_settings = BeamSettings()
        self.bmp_settings = BmpSettings()
        self.addLayout(self.beam_settings)
        self.addLayout(self.bmp_settings)
        self.beam_settings.ctrl_btn.clicked.connect(self.toggle_ext_ctrl)
        self.bmp_settings.file_btn.clicked.connect(self.file_dialog)
        self.bmp_settings.process_btn.clicked.connect(self.process_image)
        self.pattern_btn = QPushButton("Write Pattern")
        self.pattern_btn.setCheckable(True)
        self.pattern_btn.setEnabled(False)
        self.addWidget(self.pattern_btn)
        self.pattern_btn.hide()
        self.pattern_btn.clicked.connect(self.run_pattern)
        self.param_data = ParameterData()
        self.addLayout(self.param_data)
        self.param_data.measure_btn.clicked.connect(self.toggle_measure)
        self.image_display = ImageDisplay(512, 512)
        self.addWidget(self.image_display)
        self.image_display.hide()
        

    @asyncSlot()
    async def toggle_ext_ctrl(self):
        print("Hello?")
        if self.beam_settings.ctrl_btn.isChecked():
            cmds = setup()
            await self.conn.transfer_raw(cmds)
            self.beam_settings.beam_state.setText("Blanked")
            self.beam_settings.ctrl_btn.setText("Release Control")
            self.pattern_btn.setEnabled(True)
        else:
            cmds = teardown()
            await self.conn.transfer_raw(cmds)
            self.beam_settings.beam_state.setText("Released")
            self.beam_settings.ctrl_btn.setText("Take Control")
            self.pattern_btn.setEnabled(False)

    @asyncSlot()
    async def file_dialog(self):
        img_path = QFileDialog.getOpenFileName()[0] #filter = "tr(Images (*.bmp))"
        self.bmp_settings.img_path_label.setText(img_path)
        self.bmp_settings.pattern_im = im = Image.open(img_path)
        print(f"loaded file from {img_path}")

        self.bmp_settings.pattern_settings.show()
        self.bmp_settings.process_btn.setEnabled(True)
        self.pattern_btn.hide()
        a = np.asarray(im)
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

    @asyncSlot()
    async def process_image(self):
        self.bmp_settings.process_btn.setText("Processing")
        self.bmp_settings.process_btn.setEnabled(False)
        invert_checked = self.bmp_settings.pattern_settings.get_settings()
        dwell = self.param_data.dwell.value()
        max_dwell = int((dwell*pow(10,9))/125) #convert to units of 125ns
        im = self.bmp_settings.pattern_im.convert("L") ## 8 bit grayscale. 255 = longest dwell time, 0 = no dwell
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
        im = im.resize((scaled_x_pixels, scaled_y_pixels))
        print(f"input image: {x_pixels=}, {y_pixels=} -> {scaled_x_pixels=}, {scaled_y_pixels=}")

        self.bmp_settings.pattern_array = np.asarray(im)
        
        self.bmp_settings.process_btn.setText("Process")
        self.bmp_settings.process_btn.setEnabled(True)
        self.pattern_btn.show()
        x, y = self.bmp_settings.pattern_array.shape
        self.image_display.setImage(y, x, self.bmp_settings.pattern_array)
    
        
    
    @asyncSlot()
    async def run_pattern(self):
        self.pattern_btn.setEnabled(False)
        self.pattern_btn.setText("Preparing pattern...")
        scaled_y_pixels, scaled_x_pixels = self.bmp_settings.pattern_array.shape
        seq = CommandSequence(raster=False, output=OutputMode.NoOutput)

        ## Unblank with beam at position 0,0
        seq.add(BlankCommand(enable=False, inline=True))
        seq.add(VectorPixelCommand(x_coord=0, y_coord=0, dwell=1))

        # start = time.time()
        # for y in range(scaled_y_pixels):
        #     for x in range(scaled_x_pixels):
        #         dwell = self.bmp_settings.pattern_array[y][x]
        #         if dwell > 0:
        #             seq.add(VectorPixelCommand(x_coord=x, y_coord = y, dwell=dwell))
        # stop = time.time()
        # print(f"for loop time: {stop-start:.4f}")

        start = time.time()
        print(f"{self.bmp_settings.pattern_array.shape=}")
        ay, ax = np.nonzero(self.bmp_settings.pattern_array)
        print(f"{len(ax)=}, {ax.shape=}, {len(ay)=}, {ay.shape=}")
        # for n in range(len(ax)):
        #     x = ax[n]
        #     y = ay[n]
        #     dwell = self.bmp_settings.pattern_array[y][x]
        #     print(f"{x=}, {y=}")
        #     #seq.add(VectorPixelCommand(x_coord=x+1, y_coord = y+1, dwell=dwell))
        stop = time.time()
        print(f"np.nonzero time: {stop-start:.4f}")
        
        seq.add(BlankCommand(enable=True))
        # self.pattern_btn.setText("Writing pattern...")
        # self.beam_settings.beam_state.setText("Writing pattern")
        # await self.conn.transfer_raw(seq)
        # self.beam_settings.beam_state.setText("Blanked")
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


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
    
