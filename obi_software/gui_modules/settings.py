from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton)
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop
from ..stream_interface import BeamType, _BeamSelectCommand, _ExternalCtrlCommand, _BlankCommand


class SettingBoxWithDefaults(QGridLayout):
    def __init__(self, label, lower_limit, upper_limit, initial_val, defaults=["Custom"]):
        super().__init__()
        self.name = label
        self.label = QLabel(label)
        self.addWidget(self.label,0,1)

        self.spinbox = QSpinBox()
        self.spinbox.setRange(lower_limit, upper_limit)
        self.spinbox.setSingleStep(1)
        self.spinbox.setValue(initial_val)
        self.addWidget(self.spinbox,2,1)
        self.spinbox.hide()

        self.dropdown = QComboBox()
        self.dropdown.addItems(defaults)
        self.addWidget(self.dropdown, 1, 1)
        self.dropdown.currentTextChanged.connect(self.process_input)
        self.dropdown.setCurrentText(str(initial_val))

    def getval(self):
        val = self.dropdown.currentText()
        if val == "Custom":
            return int(self.spinbox.cleanText())
        else:
            return int(val)

    def setval(self, val):
        self.spinbox.setValue(val)
    
    def process_input(self, value):
        if value == "Custom":
            self.spinbox.show()
        else:
            self.spinbox.hide()

class ResolutionSetting(QHBoxLayout):
    def __init__(self, name, initial_val, defaults=["Custom"]):
        super().__init__()
        self.name = name
        self.addWidget(QLabel(f"{self.name} Resolution"))

        self.rx = SettingBox("X",128, 16384, 1024)
        self.rx_w = QWidget()
        self.rx_w.setLayout(self.rx)

        self.ry = SettingBox("Y",128, 16384, 1024)
        self.ry_w = QWidget()
        self.ry_w.setLayout(self.ry)

        self.dropdown = QComboBox()
        self.dropdown.addItems(defaults)
        self.addWidget(self.dropdown)
        self.dropdown.currentTextChanged.connect(self.process_input)
        self.dropdown.setCurrentText(str(initial_val))

        self.addWidget(self.rx_w)
        self.rx_w.hide()
        self.addWidget(self.ry_w)
        self.ry_w.hide()   

    def getval(self):
        val = self.dropdown.currentText()
        if val == "Custom":
            return int(self.rx.spinbox.cleanText()), int(self.ry.spinbox.cleanText())
        else:
            return int(val), int(val)

    def setval(self, val):
        self.spinbox.setValue(val)
    
    def process_input(self, value):
        if value == "Custom":
            self.rx_w.show()
            self.ry_w.show()
        else:
            self.rx_w.hide()
            self.ry_w.hide()
    
    def disable_input(self):
        self.rx_w.setEnabled(False)
        self.ry_w.setEnabled(False)
        self.dropdown.setEnabled(False)
    
    def enable_input(self):
        self.rx_w.setEnabled(True)
        self.ry_w.setEnabled(True)
        self.dropdown.setEnabled(True)


class DwellSetting(QHBoxLayout):
    def __init__(self, name, initial_val, defaults=["Custom"]):
        super().__init__()
        self.name = name
        self.addWidget(QLabel(f"{self.name} Scan Speed"))

        self.dwell = SettingBox("",0, 65536, 2)
        self.d_w = QWidget()
        self.d_w.setLayout(self.dwell)

        self.dropdown = QComboBox()
        self.dropdown.addItems(defaults)
        self.addWidget(self.dropdown)
        self.dropdown.currentTextChanged.connect(self.process_input)
        self.dropdown.setCurrentText(str(initial_val))

        self.addWidget(self.d_w)
        self.d_w.hide()  

    def getval(self):
        val = self.dropdown.currentText()
        if val == "Custom":
            return int(self.spinbox.cleanText())
        else:
            return int(val)

    def setval(self, val):
        self.spinbox.setValue(val)
    
    def process_input(self, value):
        if value == "Custom":
            self.d_w.show()
        else:
            self.d_w.hide()
    
    def disable_input(self):
        self.d_w.setEnabled(False)
        self.dropdown.setEnabled(False)

    def enable_input(self):
        self.d_w.setEnabled(True)
        self.dropdown.setEnabled(True)




class SettingBox(QHBoxLayout):
    def __init__(self, label, lower_limit, upper_limit, initial_val):
        super().__init__()
        self.name = label
        self.label = QLabel(label)
        self.addWidget(self.label)

        self.spinbox = QSpinBox()
        self.spinbox.setRange(lower_limit, upper_limit)
        self.spinbox.setSingleStep(1)
        self.spinbox.setValue(initial_val)
        self.addWidget(self.spinbox)

    def getval(self):
        return int(self.spinbox.cleanText())

    def setval(self, val):
        self.spinbox.setValue(val)


class ImageSettings(QHBoxLayout):
    def __init__(self, name:str, default_res=1024, res_options=["512", "1024"], default_dwell=2, dwell_options=["1","2", "4", "8", "16", "32"]):
        super().__init__()
        self.res = ResolutionSetting(name, default_res, res_options + ["Custom"])
        self.addLayout(self.res)
        self.dwell = DwellSetting(name, default_dwell,  dwell_options + ["Custom"])
        self.addLayout(self.dwell)
    def disable_input(self):
        self.res.disable_input()
        self.dwell.disable_input()
    def enable_input(self):
        self.res.enable_input()
        self.dwell.enable_input()
    def getval(self):
        x, y = self.res.getval()
        d = self.dwell.getval()
        return x, y, d

class BeamSettings(QHBoxLayout):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.ext_ctrl_btn = QPushButton("Click to Enable External Ctrl")
        self.ext_ctrl_btn.setCheckable(True)
        self.ext_ctrl_btn.clicked.connect(self.toggle_ext_ctrl)
        self.addWidget(self.ext_ctrl_btn)
        self.blank_btn = QPushButton("Click to Blank")
        self.blank_btn.setCheckable(True)
        self.blank_btn.clicked.connect(self.toggle_blank)
        self.addWidget(self.blank_btn)
        self.beam_menu = QComboBox()
        self.beam_menu.addItems(["No Beam Selected", "Electron", "Ion"])
        self.beam_menu.currentIndexChanged.connect(self.beam_select)
        self.addWidget(self.beam_menu)
    
    @property
    def beam_type(self):
        beam_type = self.beam_menu.currentText()
        if beam_type == "Electron":
            return BeamType.Electron
        elif beam_type == "Ion":
            return BeamType.Ion
        else:
            return BeamType.NoBeam
    
    @asyncSlot()
    async def toggle_ext_ctrl(self):
        if self.ext_ctrl_btn.isChecked():
            await self.conn.transfer(_ExternalCtrlCommand(enable=True))
            self.ext_ctrl_btn.setText("Click to Disable External Ctrl")
        else:
            await self.conn.transfer(_ExternalCtrlCommand(enable=False))
            self.ext_ctrl_btn.setText("Click to Enable External Ctrl")
    @asyncSlot()
    async def toggle_blank(self):
        if self.blank_btn.isChecked():
            await self.conn.transfer(_BlankCommand(enable=True))
            self.blank_btn.setText("Click to Unblank")
        else:
            await self.conn.transfer(_BlankCommand(enable=False))
            self.blank_btn.setText("Click to Blank")
    @asyncSlot()
    async def beam_select(self):
        await self.conn.transfer(_BeamSelectCommand(beam_type=self.beam_type))
    def disable_input(self):
        self.ext_ctrl_btn.setEnabled(False)
        self.blank_btn.setEnabled(False)
        self.beam_menu.setEnabled(False)
    def enable_input(self):
        self.ext_ctrl_btn.setEnabled(True)
        self.blank_btn.setEnabled(True)
        self.beam_menu.setEnabled(True)

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    w = QWidget()
    s = ImageSettings("Live")
    w.setLayout(s)
    w.show()
    app.exec()


