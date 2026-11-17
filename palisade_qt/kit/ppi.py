"""PpiScope — the OPS hero: a radar PPI (plan-position indicator).

North-up, home at centre, range rings, and contacts fed from the event bus (contact events) by
OPS. Click a contact to select it (B5): it gets a violet ring and its label. Severity colours the
dot: live=green, warn=amber, alert=red. No decorative sweep line (B5): nothing on the scope moves
unless a contact moved.
"""
import math

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .. import theme


class PpiScope(QtWidgets.QFrame):
    resized = QtCore.Signal()       # the host keeps the scope square (no dead well either side)
    contact_clicked = QtCore.Signal(str)   # B5: the id of the contact the operator clicked

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.resized.emit()

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
        self.plot.setXRange(-span_nm, span_nm, padding=0.02)
        self.plot.setYRange(-span_nm, span_nm, padding=0.02)
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

        self.scatter = pg.ScatterPlotItem(size=10, pen=None, hoverable=False)
        self.scatter.sigClicked.connect(self._clicked)
        self.plot.addItem(self.scatter)
        self.sel_ring = pg.ScatterPlotItem(size=12, pen=pg.mkPen(tok["accent"], width=1.5),
                                           brush=None)
        self.plot.addItem(self.sel_ring)
        self.home = pg.ScatterPlotItem([0], [0], size=8, symbol="+",
                                       pen=pg.mkPen(tok["accent"], width=2))
        self.plot.addItem(self.home)
        self._labels = []

    def stop(self):
        pass                         # nothing animates any more (B5); kept for the page lifecycle

    def _clicked(self, _item, points, *_):
        for p in points or []:
            cid = p.data()
            if cid is not None:
                self.contact_clicked.emit(str(cid))
                return

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
                                                                     tok["live"])), "size": 10,
                          "data": c.get("id")})
            if selected is not None and c.get("id") == selected:
                sel.append((x, y))
                t = pg.TextItem(c.get("label", ""), color=tok["accent"], anchor=(0, 1))
                _f = t.textItem.font()
                _f.setPixelSize(16)
                t.setFont(_f)
                t.setPos(x + 1.5, y + 1.5)
                self.plot.addItem(t)
                self._labels.append(t)
        self.scatter.setData(spots)
        self.sel_ring.setData([p[0] for p in sel], [p[1] for p in sel])
