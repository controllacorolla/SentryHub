"""Map panel — PyQtGraph scatter with range rings and optional tile backgrounds.

Supports three map styles: scope (plain dark/light), dark (CartoDB dark_nolabels),
and satellite (Esri World Imagery). Tiles are fetched in a background thread and
cached locally under ~/.cache/palisade/tiles/.
"""
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from .. import theme
from .tiles import TileLayer

STYLES_DARK = ["scope", "dark", "satellite"]
STYLES_LIGHT = ["scope", "light", "satellite"]


class MapPanel(QtWidgets.QFrame):
    def __init__(self, span_nm=80, mode="dark", home_lat=47.6, home_lon=-122.3,
                 parent=None):
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

        self._tile_img = pg.ImageItem()
        self._tile_img.setZValue(-10)
        self.plot.addItem(self._tile_img)

        self._rings = []
        self._ring_labels = []
        self._cardinal_labels = []
        rings = [span_nm / 4, span_nm / 2, span_nm * 3 / 4, span_nm]
        for r in rings:
            circ = pg.QtWidgets.QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            circ.setPen(pg.mkPen(tok["hairline"], width=1))
            self.plot.addItem(circ)
            self._rings.append(circ)
        for r in rings[:-1]:
            lbl = pg.TextItem("%.0f" % r, color=tok["muted"], anchor=(0, 1))
            lbl.setPos(2, r)
            self.plot.addItem(lbl)
            self._ring_labels.append(lbl)
        for txt, x, y in [("N", 0, span_nm * 0.92), ("S", 0, -span_nm * 0.92),
                           ("E", span_nm * 0.92, 0), ("W", -span_nm * 0.92, 0)]:
            c = pg.TextItem(txt, color=tok["muted"], anchor=(0.5, 0.5))
            c.setPos(x, y)
            self.plot.addItem(c)
            self._cardinal_labels.append(c)

        self.scatter = pg.ScatterPlotItem(size=7, pen=None,
                                          brush=pg.mkBrush(tok["live"]))
        self.plot.addItem(self.scatter)
        self.home = pg.ScatterPlotItem([0], [0], size=9, symbol="+",
                                       pen=pg.mkPen(tok["accent"], width=2))
        self.plot.addItem(self.home)
        lay.addWidget(self.plot)

        self._styles = STYLES_DARK if mode == "dark" else STYLES_LIGHT
        self._combo = QtWidgets.QComboBox(self)
        tile_label = "DARK" if mode == "dark" else "LIGHT"
        self._combo.addItems(["SCOPE", tile_label, "SAT"])
        self._combo.setFixedWidth(72)
        if mode == "dark":
            self._combo.setStyleSheet(
                "QComboBox { background: rgba(0,0,0,160); color: #AAB; "
                "border: 1px solid #333; font-size: 10px; padding: 2px 4px; }"
                "QComboBox::drop-down { border: none; }"
                "QComboBox QAbstractItemView { background: #181C22; color: #AAB; "
                "selection-background-color: #2A2F38; }")
        else:
            self._combo.setStyleSheet(
                "QComboBox { background: rgba(255,255,255,200); color: #334; "
                "border: 1px solid #CCC; font-size: 10px; padding: 2px 4px; }"
                "QComboBox::drop-down { border: none; }"
                "QComboBox QAbstractItemView { background: #F4F5F7; color: #334; "
                "selection-background-color: #DEE1E6; }")
        self._combo.currentIndexChanged.connect(self._style_changed)
        self._combo.raise_()

        self._tiles = TileLayer(home_lat=home_lat, home_lon=home_lon,
                                span_nm=span_nm, parent=self)
        self._tiles.ready.connect(self._on_tiles)
        self._current_style = "scope"

        if mode == "dark":
            self._combo.setCurrentIndex(1)
        else:
            self._combo.setCurrentIndex(0)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._combo.move(self.width() - self._combo.width() - 10, 10)

    def _style_changed(self, idx):
        style = self._styles[idx]
        self._current_style = style
        if style == "scope":
            self._tile_img.clear()
            tok = theme.tokens(self._mode)
            self.plot.setBackground(tok["well"])
            self._set_overlay_colors(tok["hairline"], tok["muted"])
        else:
            self._tiles.fetch(style)

    def _on_tiles(self, arr, x0, y0, x1, y1):
        self._tile_img.setImage(arr)
        self._tile_img.setRect(QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))
        self.plot.setBackground("#000000")
        bright = self._current_style == "satellite"
        ring_color = (255, 255, 255, 90) if bright else (255, 255, 255, 50)
        text_color = "#DDD" if bright else "#888"
        self._set_overlay_colors(ring_color, text_color)

    def _set_overlay_colors(self, ring_color, text_color):
        pen = pg.mkPen(ring_color, width=1)
        for circ in self._rings:
            circ.setPen(pen)
        for lbl in self._ring_labels:
            lbl.setColor(text_color)
        for lbl in self._cardinal_labels:
            lbl.setColor(text_color)

    def set_contacts(self, points):
        """points: iterable of (x_nm, y_nm)."""
        pts = list(points)
        self.scatter.setData([p[0] for p in pts], [p[1] for p in pts])
