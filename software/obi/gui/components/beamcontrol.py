from PyQt6.QtWidgets import (QLabel, QGridLayout,  QWidget, QFrame, QFileDialog, QCheckBox,
                             QSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit, QButtonGroup)
from PyQt6.QtCore import Qt
import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop


from obi.commands import BeamSelectCommand, BeamType, ExternalCtrlCommand
from obi.transfer import TCPConnection


class BeamButton(QPushButton):
    def __init__(self, beam_type: BeamType):
        self.beam_type = beam_type
        super().__init__(self.beam_type.name)

class BeamControl(QWidget):
    def __init__(self, conn, beams=[BeamType.Electron, BeamType.Ion]):
        super().__init__()
        self.conn = conn
        layout = QHBoxLayout()
        self.setLayout(layout)

        self.beams = QButtonGroup()
        for beam in beams:
            btn = BeamButton(beam)
            btn.setCheckable(True)
            self.beams.addButton(btn)
            layout.addWidget(btn)
        self.beams.idClicked.connect(self.beam_select)

        self.ext = QPushButton("Lock External Control")
        self.ext.setCheckable(True)
        self.ext.clicked.connect(self.toggle_ext)
        # layout.addWidget(self.ext)
    
    @asyncSlot(int)
    async def beam_select(self, b_id):
        btn = self.beams.button(b_id)
        await self.conn.transfer(BeamSelectCommand(beam_type=btn.beam_type))

    @asyncSlot()
    async def toggle_ext(self):
        enable=self.ext.isChecked()
        if enable:
            self.ext.setText("Release External Control")
        else:
            self.ext.setText("Lock External Control")
        await self.conn.transfer(ExternalCtrlCommand(enable=enable))


if __name__ == "__main__":
    import sys
    import asyncio
    app = QApplication(sys.argv)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    conn = TCPConnection('localhost', 2224)
    
    b = BeamControl(conn)
    b.show()

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())
