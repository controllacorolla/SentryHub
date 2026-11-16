"""Map panel — PyQtGraph scatter with range rings and optional tile backgrounds.

Map styles are DARK (CartoDB dark_nolabels) or SAT (Esri World Imagery) only — owner rule
(2026-11-15): "all maps need to be satellite or dark", in every theme including light and sun.
The plain black "scope" background is only the offline fallback until tiles arrive. Tiles are fetched in a background thread and
cached locally under ~/.cache/palisade/tiles/.
"""
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from .. import theme
from .tiles import TileLayer

STYLES = ["dark", "satellite"]          # owner rule: satellite or dark, nothing else
STYLES_DARK = STYLES
STYLES_LIGHT = STYLES


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
            _f = lbl.textItem.font()
            _f.setPixelSize(16)
            lbl.setFont(_f)
            lbl.setPos(2, r)
            self.plot.addItem(lbl)
            self._ring_labels.append(lbl)
        for txt, x, y in [("N", 0, span_nm * 0.92), ("S", 0, -span_nm * 0.92),
                           ("E", span_nm * 0.92, 0), ("W", -span_nm * 0.92, 0)]:
            c = pg.TextItem(txt, color=tok["muted"], anchor=(0.5, 0.5))
            _f = c.textItem.font()
            _f.setPixelSize(16)
            c.setFont(_f)
            c.setPos(x, y)
            self.plot.addItem(c)
            self._cardinal_labels.append(c)

        self.scatter = pg.ScatterPlotItem(size=7, pen=None,
                                          brush=pg.mkBrush(tok["live"]))
        self.plot.addItem(self.scatter)
        self.home = pg.ScatterPlotItem([0], [0], size=9, symbol="+",
                                       pen=pg.mkPen(tok["accent"], width=2))
        self.plot.addItem(self.home)
        self._contact_labels = []
        self._label_color = tok["text"]          # legible on every theme (was a fixed light grey)
        lay.addWidget(self.plot)

        self._styles = STYLES
        self._combo = QtWidgets.QComboBox(self)
        self._combo.addItems(["DARK", "SAT"])
        self._combo.setFixedWidth(104)
        self._combo.setToolTip("map tiles: dark or satellite (owner rule)")
        self._combo.setStyleSheet(
            "QComboBox { background: rgba(0,0,0,170); color: #DDD; "
            "border: 1px solid #555; font-size: 16px; padding: 2px 4px; }"
            # the map is dark in every theme, so the focus ring is white on it (RA-CL1)
            "QComboBox:focus { border: 3px solid #FFFFFF; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #181C22; color: #DDD; "
            "selection-background-color: #2A2F38; }")
        self._combo.currentIndexChanged.connect(self._style_changed)
        self._combo.raise_()

        self._tiles = TileLayer(home_lat=home_lat, home_lon=home_lon,
                                span_nm=span_nm, parent=self)
        self._tiles.ready.connect(self._on_tiles)
        self._current_style = "dark"
        # black until tiles land: the offline fallback is dark in every theme, never light
        self.plot.setBackground("#000000")
        self._set_overlay_colors((255, 255, 255, 50), "#888")
        self._combo.setCurrentIndex(0)
        self._style_changed(0)

    def set_home(self, lat, lon, known=True):
        """H5: re-centre the basemap on a new HOME (it was fixed at construction). known=False hides
        the HOME marker: the map is then relative to a provisional origin, not the operator."""
        self.home.setVisible(bool(known))
        if lat is None or lon is None:
            return
        if (self._tiles.home_lat, self._tiles.home_lon) != (lat, lon):
            self._tiles.home_lat, self._tiles.home_lon = lat, lon
            self._tile_img.clear()
            self._tiles.fetch(self._current_style)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._combo.move(self.width() - self._combo.width() - 10, 10)

    def _style_changed(self, idx):
        style = self._styles[idx]
        self._current_style = style
        self._tiles.fetch(style)

    def current_style(self):
        return self._current_style

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

    def set_contacts(self, points, labels=None, colors=None):
        """points: iterable of (x_nm, y_nm). labels/colors: optional per-point lists."""
        pts = list(points)
        if colors:
            spots = [{"pos": (p[0], p[1]), "brush": pg.mkBrush(c), "size": 7, "pen": None}
                     for p, c in zip(pts, colors)]
            self.scatter.setData(spots)
        else:
            self.scatter.setData([p[0] for p in pts], [p[1] for p in pts])
        for lbl in self._contact_labels:
            self.plot.removeItem(lbl)
        self._contact_labels.clear()
        if labels:
            for (x, y), txt in zip(pts, labels):
                t = pg.TextItem(txt, color=self._label_color, anchor=(0, 1))
                _f = t.textItem.font()
                _f.setPixelSize(16)
                t.setFont(_f)
                t.setPos(x + 1.5, y + 1.5)
                self.plot.addItem(t)
                self._contact_labels.append(t)
