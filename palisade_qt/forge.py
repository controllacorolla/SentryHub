"""FORGE — hardware & IO bench (archetype: serial/console + controls).

Absorbs hwlab, buslab, canbus, proxmark, flipper. Built from the kit: StatusHeader, ControlBar
(port + baud + send), a console well (read-only stream) + a value readout. No SDR lease — this
is the serial/I2C/GPIO bench. The worker streams device lines; demo synthesises an ESP32-style
boot + sensor stream, on-device it reads the real serial port (engine unchanged).
"""
import random

from PySide6 import QtGui, QtWidgets

from .app import PalisadeApp
from . import theme
from .kit import ControlBar, micro
from .worker import Worker

BOOT = ["ets Jun  8 2016 00:22:57", "rst:0x1 (POWERON_RESET)", "mode:DIO, clock div:1",
        "[boot] FORGE bench firmware v0.4 (demo)", "[i2c] BME280 @ 0x76", "ready >"]


class SerialWorker(Worker):
    def __init__(self, demo=True, parent=None):
        super().__init__(demo=demo, interval_ms=500, parent=parent)
        self._boot = list(BOOT)
        self._n = 0

    def step(self):
        if self._boot:
            self.row.emit({"line": self._boot.pop(0), "kind": "sys"})
            return
        self._n += 1
        self.row.emit({"line": "[%6d] temp=%.1fC hum=%d%% pres=%.1fhPa" % (
            self._n * 1000, 21 + random.random() * 2, 40 + self._n % 8,
            1012 + random.random()), "kind": "rx", "temp": 21 + random.random() * 2})


class ForgeApp(PalisadeApp):
    TITLE = "FORGE"
    LEASE = None            # serial/I2C/GPIO bench — never holds the SDR

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.bar = ControlBar()
        port = QtWidgets.QComboBox()
        port.addItems(["/dev/ttyUSB0 (demo)", "/dev/ttyACM0", "I2C bus 1", "CAN can0"])
        self.bar.add_field("port", port, "Port")
        baud = QtWidgets.QComboBox()
        baud.addItems(["115200", "9600", "57600", "250000"])
        self.bar.add_field("baud", baud, "Baud")
        self.bar.add_stretch()
        self.bar.lay.addWidget(micro("Last temp"))
        self.readout = QtWidgets.QLabel("—")
        self.readout.setProperty("class", "value")
        self.bar.lay.addWidget(self.readout)
        self._lines = QtWidgets.QLabel("0 lines")
        self._lines.setProperty("class", "micro")
        self.bar.lay.addSpacing(12)
        self.bar.lay.addWidget(self._lines)
        lay.addWidget(self.bar)

        well = QtWidgets.QFrame()
        well.setProperty("class", "well")
        wl = QtWidgets.QVBoxLayout(well)
        wl.setContentsMargins(8, 8, 8, 8)
        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background:transparent; border:none;")
        self.console.setMaximumBlockCount(500)
        wl.addWidget(self.console)
        lay.addWidget(well, 1)
        self._line_count = 0
        return body

    def make_worker(self):
        return SerialWorker(demo=self.demo)

    def on_row(self, msg):
        prefix = "" if msg["kind"] == "sys" else "  "
        line = prefix + msg["line"]
        cursor = self.console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        fmt = cursor.charFormat()
        if msg["kind"] == "sys":
            fmt.setForeground(QtGui.QColor(self._tok["muted"]))
        else:
            fmt.setForeground(QtGui.QColor(self._tok["text"]))
        cursor.insertText(line + "\n", fmt)
        self.console.setTextCursor(cursor)
        self.console.ensureCursorVisible()
        self._line_count += 1
        self._lines.setText("%d lines" % self._line_count)
        self.header.set_chip("sdr", "%d LINES" % self._line_count, ok=True)
        if "temp" in msg:
            self.readout.setText("%.1f °C" % msg["temp"])
