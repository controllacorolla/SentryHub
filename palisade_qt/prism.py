"""PRISM — spectrum + waterfall (the first migrated archetype).

Archetype: recessed scope well + a control bar. Built entirely from the kit: StatusHeader,
ControlBar (centre / span / gain), ScopePanel (PyQtGraph spectrum line + rolling waterfall).
The worker sweeps and emits (freqs, power_dbm) rows to the GUI thread; demo synthesises them,
on-device it drives `rtl_power` (guarded, falls back to demo).

UI-only: this reuses the existing suite engines' data shape; it adds no new DSP.
"""
import math
import shutil
import subprocess
import time

import numpy as np
from PySide6 import QtWidgets

from .app import PalisadeApp
from .kit import ControlBar, ScopePanel, micro
from .worker import Worker

BINS = 512


class SweepWorker(Worker):
    def __init__(self, demo=True, lo=430.0, hi=440.0, parent=None):
        super().__init__(demo=demo, interval_ms=50, parent=parent)
        self.lo, self.hi = lo, hi
        self._t0 = time.time()
        self._use_rtl = (not demo) and bool(shutil.which("rtl_power"))

    def set_band(self, lo, hi):
        self.lo, self.hi = lo, hi

    def _demo_row(self):
        freqs = np.linspace(self.lo, self.hi, BINS)
        t = time.time() - self._t0
        p = -108 + 4 * np.random.randn(BINS)
        for base, drift, pwr, w in ((0.21, 0.4, 48, 1.4), (0.65, -0.2, 32, 0.8)):
            cf = self.lo + (self.hi - self.lo) * base + drift * math.sin(t * 0.3)
            p += pwr * np.exp(-((freqs - cf) ** 2) / (2 * ((w * (self.hi - self.lo) / 100) ** 2)))
        return freqs, p

    def _rtl_row(self):
        step = int((self.hi - self.lo) * 1e6 / BINS)
        cmd = ["rtl_power", "-f", "%fM:%fM:%d" % (self.lo, self.hi, step), "-i", "1", "-1"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        powers = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) > 6:
                powers += [float(x) for x in parts[6:] if x]
        if not powers:
            return None
        return np.linspace(self.lo, self.hi, len(powers)), np.array(powers)

    def step(self):
        row = self._rtl_row() if self._use_rtl else None
        if row is None:
            row = self._demo_row()
            self._use_rtl = False
        self.row.emit(row)


class PrismApp(PalisadeApp):
    TITLE = "PRISM"
    LEASE = "PRISM"              # holds the SDR; base acquires on show, releases on close

    def __init__(self, demo=False, mode="dark", parent=None):
        self._lo, self._hi = 430.0, 440.0
        super().__init__(demo=demo, mode=mode, parent=parent)

    def build_body(self):
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.bar = ControlBar()
        self.centre = QtWidgets.QDoubleSpinBox()
        self.centre.setRange(24, 1766)
        self.centre.setValue((self._lo + self._hi) / 2)
        self.centre.setSuffix(" MHz")
        self.centre.setDecimals(2)
        self.span = QtWidgets.QDoubleSpinBox()
        self.span.setRange(0.5, 40)
        self.span.setValue(self._hi - self._lo)
        self.span.setSuffix(" MHz")
        self.gain = QtWidgets.QSpinBox()
        self.gain.setRange(0, 49)
        self.gain.setValue(30)
        self.gain.setSuffix(" dB")
        self.bar.add_field("centre", self.centre, "Centre")
        self.bar.add_field("span", self.span, "Span")
        self.bar.add_field("gain", self.gain, "Gain")
        self.bar.add_stretch()
        self.readout = QtWidgets.QLabel("—")
        self.readout.setProperty("class", "value")
        self.bar.lay.addWidget(micro("PEAK"))
        self.bar.lay.addWidget(self.readout)
        self.centre.valueChanged.connect(self._retune)
        self.span.valueChanged.connect(self._retune)
        lay.addWidget(self.bar)

        self.scope = ScopePanel(bins=BINS, history=120, lo_mhz=self._lo, hi_mhz=self._hi,
                                mode=self.mode)
        lay.addWidget(self.scope, 1)
        return body

    def _retune(self):
        c, s = self.centre.value(), self.span.value()
        self._lo, self._hi = c - s / 2, c + s / 2
        if self._worker is not None:
            self._worker.set_band(self._lo, self._hi)

    def make_worker(self):
        return SweepWorker(demo=self.demo, lo=self._lo, hi=self._hi)

    def on_row(self, row):
        freqs, power = row
        self.scope.push(freqs, power)
        peak = float(np.max(power))
        pf = float(freqs[int(np.argmax(power))])
        self.readout.setText("%.0f dBm @ %.2f MHz" % (peak, pf))
