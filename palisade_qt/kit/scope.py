"""Scope panel — PyQtGraph spectrum line + rolling waterfall (the PRISM well).

Reusable version of the de-risk spike: the app pushes (freqs, power_dbm) rows; the panel keeps
a rolling image. No threads here — the app's Worker emits rows to push() on the GUI thread.
"""
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets

from .. import theme


class ScopePanel(QtWidgets.QFrame):
    def __init__(self, bins=512, history=200, lo_mhz=430.0, hi_mhz=440.0,
                 mode="dark", parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
        tok = theme.tokens(mode)
        pg.setConfigOptions(antialias=False, imageAxisOrder="row-major")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self.bins, self.history = bins, history
        self.freqs = np.linspace(lo_mhz, hi_mhz, bins)
        self.buf = np.full((history, bins), -115.0, dtype=np.float32)

        self.spectrum = pg.PlotWidget()
        self.spectrum.setBackground(tok["well"])
        self.spectrum.setMaximumHeight(110)
        self.spectrum.setMenuEnabled(False)
        self.spectrum.setMouseEnabled(False, False)
        self.spectrum.setYRange(-115, -15)
        self.spectrum.getAxis("left").setTextPen(tok["muted"])
        self.spectrum.getAxis("bottom").setTextPen(tok["muted"])
        self.curve = self.spectrum.plot(pen=pg.mkPen(tok["accent"], width=1))
        lay.addWidget(self.spectrum)

        self.img = pg.ImageItem()
        view = pg.GraphicsLayoutWidget()
        view.setBackground(tok["well"])
        vb = view.addViewBox()
        vb.setMouseEnabled(False, False)
        vb.addItem(self.img)
        vb.setAspectLocked(False)
        self.img.setLookupTable(self._lut(tok))
        lay.addWidget(view, 1)
        self._refresh()

    @staticmethod
    def _lut(tok):
        stops = [(0.0, (9, 11, 14)), (0.45, (40, 36, 70)), (0.72, tuple(int(tok["accent"][i:i + 2], 16)
                 for i in (1, 3, 5))), (1.0, (240, 244, 255))]
        cm = pg.ColorMap([s[0] for s in stops], [s[1] + (255,) for s in stops])
        return cm.getLookupTable(0.0, 1.0, 256)

    def push(self, freqs, power):
        if len(power) != self.bins:
            power = np.interp(np.linspace(0, 1, self.bins), np.linspace(0, 1, len(power)), power)
        else:
            self.freqs = freqs
        self.buf = np.roll(self.buf, -1, axis=0)
        self.buf[-1] = power
        self.curve.setData(self.freqs, power)
        self._refresh()

    def _refresh(self):
        self.img.setImage(self.buf.T, autoLevels=False, levels=(-115, -15))
