
import pyqtgraph as pg

from PyQt6.QtWidgets import (QHBoxLayout, QGroupBox,QPushButton, QTextEdit,
                             QVBoxLayout, QWidget, QLabel, QSizePolicy, QApplication)
from PyQt6.QtCore import pyqtSignal, pyqtSlot as Slot, QProcess, QTimer
from PyQt6.QtGui import QTextCursor, QFont

import sys
import shlex


#https://stackoverflow.com/questions/22069321/realtime-output-from-a-subprogram-to-stdout-of-a-pyqt-widget
class ProcessConsole(QGroupBox): 
    sigProcessStarted = pyqtSignal(int)
    sigProcessStopped = pyqtSignal(int)
    def __init__(self, cmdstr:str="pdm run launch", name="Server"):
        self.name = name
        super(ProcessConsole, self).__init__(f"{name} - Not running")
        cmdlist = shlex.split(cmdstr)
        self.cmd = cmdlist[0]
        self.cmdargs = cmdlist[1:]

        layout = QVBoxLayout()
        self.runButton = QPushButton('Run')
        self.runButton.clicked.connect(self.callProgram)

        self.killButton = QPushButton("Kill")
        self.killButton.hide()

        self.showButton = QPushButton("Show Logs")
        self.showButton.setCheckable(True)
        self.showButton.clicked.connect(self.showLogs)
    
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        # self.output.setFixedWidth(800)
        font = QFont("Courier")
        self.output.setFont(font)
        self.output.hide()

        buttons = QHBoxLayout()
        buttons.addWidget(self.runButton)
        buttons.addWidget(self.killButton)
        buttons.addWidget(self.showButton)
        layout.addLayout(buttons)
        layout.addWidget(self.output)
        
        self.setLayout(layout)

        # QProcess object for external app
        self.process = QProcess(self)
        # don't merge stderr channel into stdout channel
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        # QProcess emits `readyRead[Stream]` when there is data to be read
        # self.process.readyRead[Stream].connect(self.[stream]Ready)
        self.process.readyReadStandardOutput.connect(self.dataReady)
        self.process.readyReadStandardError.connect(self.errorReady)
        self.process.stateChanged.connect(self.handle_state)

        self.killButton.clicked.connect(self.process.terminate)

        # Just to prevent accidentally running multiple times
        # Disable the button when process starts, and enable it when it finishes
        self.process.started.connect(lambda: self.runButton.hide())
        self.process.started.connect(lambda: self.killButton.show())
        self.process.finished.connect(lambda: self.runButton.show())
        self.process.finished.connect(lambda: self.killButton.hide())

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def showLogs(self):
        if self.showButton.isChecked():
            self.output.show()
            self.output.setMinimumSize(400, 200)
            self.showButton.setText("Hide Logs")
        else:
            self.output.setMinimumSize(0,0)
            self.output.resize(0,0)
            self.output.hide()
            self.showButton.setText("Show Logs")   
        #https://stackoverflow.com/questions/28660960/resize-qmainwindow-to-minimal-size-after-content-of-layout-changes
        QTimer.singleShot(10, lambda: self.window().adjustSize())    


    def dataReady(self):
        cursor = self.output.textCursor()

        # data is a QByteArray
        data = self.process.readAllStandardOutput().data()
        # print(f"\nSTDOUT: \n{data.decode()}\n")
        cursor.insertText(">" + data.decode())
        self.output.ensureCursorVisible()
    
    def errorReady(self):
        cursor = self.output.textCursor()

        data = self.process.readAllStandardError().data()
        # print(f"\nSTDERR: \n{data.decode()}\n")
        cursor.insertText("❌" + data.decode())
        self.output.ensureCursorVisible()

    def callProgram(self):
        # run the process
        # `start` takes the exec and a list of arguments
        self.process.start(self.cmd, self.cmdargs)
        self.sigProcessStarted.emit(1)

    def softkill(self):
        self.process.terminate()
        self.sigProcessStopped.emit(1)

    def handle_state(self, state):
        states = {
            QProcess.ProcessState.NotRunning: 'Not running',
            QProcess.ProcessState.Starting: 'Starting',
            QProcess.ProcessState.Running: 'Running',
        }
        state_name = states[state]
        print(f"\n{self.name}: State changed: {state_name}\n")
        self.setTitle(f"{self.name} - {state_name}")

        if state == QProcess.ProcessState.Running:
            self.sigProcessStarted.emit(1)
        
        if state == QProcess.ProcessState.NotRunning:
            self.sigProcessStopped.emit(1)

if __name__ == "__main__":

    app = QApplication(sys.argv)

    console=ProcessConsole()
    console.show()
    app.aboutToQuit.connect(console.process.terminate)
    sys.exit(app.exec())
