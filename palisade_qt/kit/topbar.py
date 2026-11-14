"""TopBar — the app-wide chrome strip: logo + wordmark + status chips + volume + DTG clock.

One bar for the whole window (lives in the shell; standalone windows get their own). Chips are
divider-separated text (not boxed), coloured by state: green=live/OK, amber=warn, red=alert,
muted otherwise. Exposes set_chip(key, text, state=, ok=) matching the old StatusHeader so pages
route their status here unchanged.
"""
from PySide6 import QtCore, QtWidgets

from .logomark import LogoMark

_STATE = {"neutral": "hchip", "ok": "hchip hchip_live", "live": "hchip hchip_live",
          "warn": "hchip hchip_warn", "alert": "hchip hchip_alert", "accent": "hchip hchip_accent"}


class TopBar(QtWidgets.QFrame):
    def __init__(self, mode="dark", parent=None):
        super().__init__(parent)
        self.setObjectName("top_bar")
        self.setFixedHeight(44)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 16, 0)
        lay.setSpacing(10)

        lay.addWidget(LogoMark(height=20, mode=mode))
        word = QtWidgets.QLabel("PALISADE")
        word.setObjectName("wordmark")
        lay.addWidget(word)
        lay.addSpacing(6)

        self.chips = {}
        for i, (key, text) in enumerate((("sdr", "SDR"), ("tx", "TX SAFE"),
                                         ("gps", "GPS"), ("pwr", "PWR"))):
            c = QtWidgets.QLabel(text)
            c.setProperty("class", "hchip hchip_live" if key == "tx" else "hchip")
            if i == 0:
                c.setStyleSheet("border-left: none;")
            self.chips[key] = c
            lay.addWidget(c)
        lay.addStretch(1)

        vol = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        vol.setFixedWidth(84)
        vol.setRange(0, 100)
        vol.setValue(72)
        vol.setObjectName("vol")
        self.volume = vol
        lay.addWidget(vol)

        self.clock = QtWidgets.QLabel("—")
        self.clock.setObjectName("dtg")
        lay.addWidget(self.clock)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self):
        self.clock.setText(QtCore.QDateTime.currentDateTimeUtc().toString("HHmm'Z'"))

    def set_chip(self, key, text=None, state=None, ok=None):
        c = self.chips.get(key)
        if c is None:
            return
        if text is not None:
            c.setText(text)
        if state is None:
            state = "ok" if ok else "neutral"
        c.setProperty("class", _STATE.get(state, "hchip"))
        if key == "sdr":
            c.setStyleSheet("border-left: none;")
        c.style().unpolish(c)
        c.style().polish(c)
