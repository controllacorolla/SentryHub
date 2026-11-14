"""PpiScope — the OPS hero: a radar PPI (plan-position indicator).

North-up, home at centre, range rings, a slow sweep, and contacts fed from the event bus
(contact events) by OPS. Selected contact gets a violet ring. Severity colours the dot:
live=green, warn=amber, alert=red. Pure view — set_contacts() is the only input.
"""
import math

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .. import theme


class PpiScope(QtWidgets.QFrame):
    def __init__(self, span_nm=80, mode="dark", parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
        self._mode = mode
        self._span = span_nm
        tok = theme.tokens(mode)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(tok["well"])
        self.plot.setMenuEnabled(False)
        self.plot.setAspectLocked(True)
        self.plot.setMouseEnabled(False, False)
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.setXRange(-span_nm, span_nm)
        self.plot.setYRange(-span_nm, span_nm)
        lay.addWidget(self.plot)

        for r in (span_nm / 3, span_nm * 2 / 3, span_nm):
            c = pg.QtWidgets.QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            c.setPen(pg.mkPen(tok["hairline"], width=1))
            self.plot.addItem(c)
        for a in (0, 90, 180, 270):
            rad = math.radians(a)
            ln = pg.PlotDataItem([0, span_nm * math.sin(rad)], [0, span_nm * math.cos(rad)],
                                 pen=pg.mkPen(tok["hairline"], width=1))
            self.plot.addItem(ln)

        self._sweep = pg.PlotDataItem(pen=pg.mkPen(tok["accent"], width=1.3))
        self.plot.addItem(self._sweep)
        self.scatter = pg.ScatterPlotItem(size=6, pen=None)
        self.plot.addItem(self.scatter)
        self.sel_ring = pg.ScatterPlotItem(size=12, pen=pg.mkPen(tok["accent"], width=1.5),
                                           brush=None)
        self.plot.addItem(self.sel_ring)
        self.home = pg.ScatterPlotItem([0], [0], size=8, symbol="+",
                                       pen=pg.mkPen(tok["accent"], width=2))
        self.plot.addItem(self.home)
        self._labels = []

        self._angle = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._spin)
        self._timer.start(60)

    def stop(self):
        self._timer.stop()

    def _spin(self):
        self._angle = (self._angle + 4) % 360
        rad = math.radians(self._angle)
        self._sweep.setData([0, self._span * math.sin(rad)], [0, self._span * math.cos(rad)])

    def set_contacts(self, contacts, selected=None):
        """contacts: list of dicts with x, y, severity, label; selected: an id to ring."""
        tok = theme.tokens(self._mode)
        col = {"live": tok["live"], "warn": tok["warn"], "alert": tok["alert"], "info": tok["muted"]}
        spots, sel = [], []
        for lbl in self._labels:
            self.plot.removeItem(lbl)
        self._labels = []
        for c in contacts:
            x, y = c["x"], c["y"]
            spots.append({"pos": (x, y), "brush": pg.mkBrush(col.get(c.get("severity", "live"),
                                                                     tok["live"])), "size": 6})
            if selected is not None and c.get("id") == selected:
                sel.append((x, y))
                t = pg.TextItem(c.get("label", ""), color=tok["accent"], anchor=(0, 1))
                t.setPos(x + 1.5, y + 1.5)
                self.plot.addItem(t)
                self._labels.append(t)
        self.scatter.setData(spots)
        self.sel_ring.setData([p[0] for p in sel], [p[1] for p in sel])
