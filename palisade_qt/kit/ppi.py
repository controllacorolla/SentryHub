"""PpiScope — the OPS hero: a radar PPI (plan-position indicator).

North-up, home at centre, range rings, and contacts fed from the event bus (contact events) by
OPS. Click a contact to select it (B5): it gets a violet ring and its label. Severity colours the
dot: live=green, warn=amber, alert=red. No decorative sweep line (B5): nothing on the scope moves
unless a contact moved.
"""
import math

import pyqtgraph as pg
from shiboken6 import isValid as shiboken_valid
from PySide6 import QtCore, QtWidgets

from .. import theme


class PpiScope(QtWidgets.QFrame):
    resized = QtCore.Signal()       # the host keeps the scope square (no dead well either side)
    contact_clicked = QtCore.Signal(str)   # B5: the id of the contact the operator clicked

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, "legend", None) is not None:
            self.place_legend()
        self.resized.emit()
        if getattr(self, "legend", None) is not None:
            # again once the host has re-fitted the scope square (_fit_scope resizes it again
            # from inside this event, and the inner placement was left at the old width)
            QtCore.QTimer.singleShot(0, self.place_legend)

    def place_legend(self):
        """One tight row across the bottom of the scope (see __init__)."""
        if not shiboken_valid(self):
            return
        w = max(120, self.width() - 16)
        self.legend.setFixedWidth(w)
        self.legend.setFixedHeight(self.legend.sizeHint().height())
        self.legend.move(8, self.height() - self.legend.height() - 8)
        self.legend.raise_()

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
        # owner 2026-11-17: the OPS scope sits on dark-tinted satellite imagery (no HOME -> none)
        from .mappanel import BaseMap
        self._base = BaseMap(self.plot, None, None, span_nm, style="dark_sat", parent=self)
        # the track-type legend on OPS too (device notes: symbols + legend on ATLAS and OPS)
        from .mappanel import make_legend
        # owner 2026-11-18 ("legend way too big, space it out across the bottom of the map, keep
        # it tight"): one row, as wide as the scope, on its bottom edge
        self.legend = make_legend(self, row=True)

        for r in (span_nm / 3, span_nm * 2 / 3, span_nm):
            c = pg.QtWidgets.QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            c.setPen(pg.mkPen(tok["hairline"], width=1))
            self.plot.addItem(c)
        for a in (0, 90, 180, 270):
            rad = math.radians(a)
            ln = pg.PlotDataItem([0, span_nm * math.sin(rad)], [0, span_nm * math.cos(rad)],
                                 pen=pg.mkPen(tok["hairline"], width=1))
            self.plot.addItem(ln)

        self._trails = pg.PlotDataItem([], [], pen=pg.mkPen((230, 230, 230, 110), width=1.5))
        self._leaders = pg.PlotDataItem([], [], pen=pg.mkPen((255, 255, 255, 220), width=1.5))
        self.plot.addItem(self._trails)
        self.plot.addItem(self._leaders)
        self.track_spots = []
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

    def set_home(self, lat, lon):
        """Centre the imagery on HOME (no-op when unchanged; None keeps it off)."""
        self._base.set_home(lat, lon)

    def stop(self):
        pass                         # nothing animates any more (B5); kept for the page lifecycle

    def _clicked(self, _item, points, *_):
        for p in points or []:
            cid = p.data()
            if cid is not None:
                self.contact_clicked.emit(str(cid))
                return

    def set_contacts(self, contacts, selected=None, trails=None):
        """contacts: list of dicts with x, y, kind, label, id (+ track/spd/alt/mil/category/
        severity); selected: an id to ring. Drawn as C2 track symbols coloured by type
        (owner 2026-11-17), with velocity leaders and history trails."""
        from . import tracksym
        tok = theme.tokens(self._mode)
        spots, sel = [], []
        for lbl in self._labels:
            self.plot.removeItem(lbl)
        self._labels = []
        for c in contacts:
            x, y = c["x"], c["y"]
            spots.append({"pos": (x, y), "symbol": tracksym.glyph(c),
                          "size": tracksym.AIR_SIZE if c.get("kind") == "aircraft" else tracksym.OTHER_SIZE,
                          "brush": pg.mkBrush(tracksym.color(c)),
                          "pen": pg.mkPen("#000000", width=1.2), "data": c.get("id")})
            if selected is not None and c.get("id") == selected:
                sel.append((x, y))
                t = pg.TextItem(tracksym.data_block(c), color=tok["accent"], anchor=(0, 1))
                _f = t.textItem.font()
                _f.setPixelSize(16)
                t.setFont(_f)
                t.setPos(x + 1.5, y + 1.5)
                self.plot.addItem(t)
                self._labels.append(t)
        lead = [ln for ln in (tracksym.leader(c) for c in contacts) if ln is not None]
        xs, ys = tracksym.segments(lead)
        self._leaders.setData(xs, ys, connect="pairs")
        tr = tracksym.trail_segments(trails or {}, [c.get("id") for c in contacts])
        xs, ys = tracksym.segments(tr)
        self._trails.setData(xs, ys, connect="pairs")
        self.track_spots = spots
        self.scatter.setData(spots)
        self.sel_ring.setData([p[0] for p in sel], [p[1] for p in sel])
