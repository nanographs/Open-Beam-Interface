from PyQt6.QtWidgets import (QLabel, QGridLayout, QApplication, QWidget,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton)


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
            return int(self.spinbox.cleanText())
        else:
            return int(val)

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
    def __init__(self, name:str):
        super().__init__()
        self.rx = ResolutionSetting(name, 1024, ["512","1024", "Custom"])
        self.addLayout(self.rx)
        self.dwell = DwellSetting(name, 2, ["1","2", "4", "8", "16", "32", "Custom"])
        self.addLayout(self.dwell)
    def disable_input(self):
        self.rx.disable_input()
        self.dwell.disable_input()
    def enable_input(self):
        self.rx.enable_input()
        self.dwell.enable_input()


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    w = QWidget()
    s = ImageSettings("Live")
    w.setLayout(s)
    w.show()
    app.exec()


