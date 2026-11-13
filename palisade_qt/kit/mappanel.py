"""Map panel — PyQtGraph scatter with range rings (the ATLAS well).

Minimal for the kit: contacts as points with range rings around home. Real tile rendering
(ImageItem tiles vs a Qt map widget) is deferred to the ATLAS archetype per the decision memo.
"""
import pyqtgraph as pg
from PySide6 import QtWidgets

from .. import theme


class MapPanel(QtWidgets.QFrame):
    def __init__(self, span_nm=80, mode="dark", parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
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
        rings = [span_nm / 4, span_nm / 2, span_nm * 3 / 4, span_nm]
        for r in rings:
            circ = pg.QtWidgets.QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            circ.setPen(pg.mkPen(tok["hairline"], width=1))
            self.plot.addItem(circ)
        for r in rings[:-1]:
            lbl = pg.TextItem("%.0f" % r, color=tok["muted"], anchor=(0, 1))
            lbl.setPos(2, r)
            self.plot.addItem(lbl)
        for txt, x, y in [("N", 0, span_nm * 0.92), ("S", 0, -span_nm * 0.92),
                           ("E", span_nm * 0.92, 0), ("W", -span_nm * 0.92, 0)]:
            c = pg.TextItem(txt, color=tok["muted"], anchor=(0.5, 0.5))
            c.setPos(x, y)
            self.plot.addItem(c)
        self.scatter = pg.ScatterPlotItem(size=7, pen=None, brush=pg.mkBrush(tok["live"]))
        self.plot.addItem(self.scatter)
        self.home = pg.ScatterPlotItem([0], [0], size=9, symbol="+",
                                       pen=pg.mkPen(tok["accent"], width=2))
        self.plot.addItem(self.home)
        lay.addWidget(self.plot)

    def set_contacts(self, points):
        """points: iterable of (x_nm, y_nm)."""
        pts = list(points)
        self.scatter.setData([p[0] for p in pts], [p[1] for p in pts])
