"""Map panel — PyQtGraph scatter with range rings and optional tile backgrounds.

Map styles are DARK (CartoDB dark_nolabels) or SAT (Esri World Imagery) only — owner rule
(2026-11-15): "all maps need to be satellite or dark", in every theme including light and sun.
The plain black "scope" background is only the offline fallback until tiles arrive. Tiles are fetched in a background thread and
cached locally under ~/.cache/palisade/tiles/.
"""
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore, QtGui

from .. import theme
from .tiles import TileLayer, ATTRIBUTION

# owner decision 2026-11-17 (device notes): every map is satellite imagery under a DARK or a LIGHT
# tint, DARK by default (replaces the 2026-11-15 DARK / SAT pair).
STYLES = ["dark_sat", "light_sat"]
STYLES_DARK = STYLES
STYLES_LIGHT = STYLES
STYLE_LABEL = {"dark_sat": "DARK SAT", "light_sat": "LIGHT SAT"}
FETCH_STYLE = "satellite"               # both tints are drawn from the same imagery
MAX_NM = 600                            # pan / zoom-out limit, nm from HOME
MIN_SPAN_NM = 1.0                       # zoom-in limit (view width)


def tint(arr, style):
    """The imagery under its tint: DARK = 45 % brightness, LIGHT = 25 % wash toward white."""
    out = arr.copy()
    rgb = arr[..., :3].astype(np.float32)
    if style == "light_sat":
        rgb = rgb * 0.75 + 255 * 0.25
    else:
        rgb = rgb * 0.45
    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return out


class BaseMap(QtCore.QObject):
    """The tinted satellite basemap behind a plot (ATLAS map, OPS scope). The image item is
    row-major by construction (device 2026-11-17: the map drew rotated 90 degrees whenever ATLAS
    was opened before PRISM, because only PRISM's scope set pyqtgraph's global imageAxisOrder).
    The tiles follow the plot's view: pan / zoom / resize re-fetches what is on screen."""

    def __init__(self, plot, home_lat, home_lon, span_nm, style="dark_sat", parent=None):
        super().__init__(parent)
        self.plot = plot
        self.img = pg.ImageItem(axisOrder="row-major")
        self.img.setZValue(-10)
        plot.addItem(self.img)
        # N26: no HOME -> no basemap. Tiles are never requested for a placeholder origin.
        self.can_fetch = home_lat is not None and home_lon is not None
        self.tiles = TileLayer(home_lat=home_lat if self.can_fetch else 0.0,
                               home_lon=home_lon if self.can_fetch else 0.0,
                               span_nm=span_nm, parent=self)
        self.tiles.ready.connect(self._on_tiles)
        self.style = style
        self._raw = None
        self.shown_rect = None
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self.refresh)
        plot.getViewBox().sigRangeChanged.connect(lambda *_: self._timer.start())
        self.on_shown = None

    def view(self):
        vb = self.plot.getViewBox()
        (x0, x1), (y0, y1) = vb.viewRange()
        return (x0, x1, y0, y1, max(64, int(vb.width() or self.plot.width())))

    def refresh(self):
        if not self.can_fetch:
            return
        self.tiles.view = self.view()
        self.tiles.fetch(FETCH_STYLE)

    def set_style(self, style):
        self.style = style
        if self._raw is not None:
            self._show()
        else:
            self.refresh()

    def set_home(self, lat, lon):
        if lat is None or lon is None:
            return
        if not self.can_fetch or (self.tiles.home_lat, self.tiles.home_lon) != (lat, lon):
            self.can_fetch = True
            self.tiles.home_lat, self.tiles.home_lon = lat, lon
            self._raw = None
            self.img.clear()
            self.refresh()

    def _on_tiles(self, arr, x0, y0, x1, y1):
        self._raw = (arr, QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))
        self._show()

    def _show(self):
        arr, rect = self._raw
        self.img.setImage(tint(arr, self.style), autoLevels=False, levels=(0, 255))
        self.img.setRect(rect)
        self.shown_rect = rect
        if self.on_shown is not None:
            self.on_shown()


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
        # device notes 2026-11-17: the map pans (drag) and zooms (wheel, + / -, the corner buttons)
        self.plot.setMouseEnabled(True, True)
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.getViewBox().setLimits(xMin=-MAX_NM, xMax=MAX_NM, yMin=-MAX_NM, yMax=MAX_NM,
                                         minXRange=MIN_SPAN_NM, minYRange=MIN_SPAN_NM)
        self.plot.setXRange(-span_nm, span_nm)
        self.plot.setYRange(-span_nm, span_nm)

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
        self._combo.addItems([STYLE_LABEL[k] for k in STYLES])
        self._combo.setFixedWidth(138)
        self._combo.setToolTip("map: satellite imagery, dark or light tint. "
                               + ATTRIBUTION["satellite"])
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

        self._base = BaseMap(self.plot, home_lat, home_lon, span_nm, parent=self)
        self._base.on_shown = self._on_tiles
        self._tiles = self._base.tiles           # kept names: tests and callers read these
        self._tile_img = self._base.img
        self._current_style = "dark_sat"
        # black until tiles land: the offline fallback is dark in every theme, never light
        self.plot.setBackground("#000000")
        self._set_overlay_colors((255, 255, 255, 50), "#888")
        self._zoom_btns = self._make_zoom_buttons()
        self._combo.setCurrentIndex(0)
        self._style_changed(0)

    @property
    def _can_fetch(self):
        return self._base.can_fetch

    def _make_zoom_buttons(self):
        css = ("QPushButton { background: rgba(0,0,0,170); color: #DDD; border: 1px solid #555;"
               " font-size: 16px; padding: 2px 6px; min-height: 0; }"
               "QPushButton:focus { border: 3px solid #FFFFFF; }")
        out = []
        for text, tip, fn in (("−", "zoom out (−)", lambda: self.zoom(2.0)),
                              ("+", "zoom in (+)", lambda: self.zoom(0.5)),
                              ("HOME", "re-centre on HOME at the default range", self.recentre)):
            b = QtWidgets.QPushButton(text, self)
            b.setStyleSheet(css)
            b.setToolTip(tip)
            b.setFocusPolicy(QtCore.Qt.TabFocus)
            b.setMinimumWidth(34)
            b.clicked.connect(lambda _=False, f=fn: f())
            b.adjustSize()
            out.append(b)
        return out

    def zoom(self, factor):
        """factor < 1 zooms in. Centred on the middle of the view."""
        vb = self.plot.getViewBox()
        vb.scaleBy((factor, factor), center=vb.viewRect().center())

    def recentre(self):
        self.plot.setXRange(-self._span, self._span)
        self.plot.setYRange(-self._span, self._span)

    def view_span(self):
        """Visible (width, height) in nm."""
        (x0, x1), (y0, y1) = self.plot.getViewBox().viewRange()
        return x1 - x0, y1 - y0

    def set_home(self, lat, lon, known=True):
        """H5: re-centre the basemap on a new HOME (it was fixed at construction). known=False hides
        the HOME marker: the map is then relative to a provisional origin, not the operator."""
        self.home.setVisible(bool(known))
        self._base.set_home(lat, lon)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._combo.move(self.width() - self._combo.width() - 10, 10)
        x = self.width() - 10
        for b in reversed(self._zoom_btns):
            x -= b.width()
            b.move(x, 18 + self._combo.height())
            x -= 6

    def _style_changed(self, idx):
        style = self._styles[idx]
        self._current_style = style
        self._base.set_style(style)
        self._on_tiles()

    def current_style(self):
        return self._current_style

    def _on_tiles(self):
        """Overlay colours follow the tint once imagery is up: light rings / text on DARK SAT,
        dark ones on LIGHT SAT. Before any imagery the map is black (light overlays)."""
        self.plot.setBackground("#000000")
        light = self._current_style == "light_sat" and self._base.shown_rect is not None
        if light:
            self._set_overlay_colors((0, 0, 0, 120), "#222")
            self._label_color = "#111111"
        else:
            self._set_overlay_colors((255, 255, 255, 90), "#DDD")
            self._label_color = "#EEEEEE"

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
            # B6: declutter — a label whose box would overlap one already placed is skipped (the
            # dot stays; the table and the detail card name it). Boxes are in screen pixels.
            vb = self.plot.getViewBox()
            placed = []
            self.labels_skipped = 0
            for (x, y), txt in zip(pts, labels):
                t = pg.TextItem(txt, color=self._label_color, anchor=(0, 1))
                _f = t.textItem.font()
                _f.setPixelSize(16)
                t.setFont(_f)
                try:
                    sp = vb.mapViewToScene(QtCore.QPointF(x + 1.5, y + 1.5))
                    w = QtGui.QFontMetrics(_f).horizontalAdvance(str(txt)) + 4
                    box = QtCore.QRectF(sp.x(), sp.y() - 20, w, 20)
                except Exception:
                    box = None
                if box is not None and any(box.intersects(b) for b in placed):
                    self.labels_skipped += 1
                    continue
                if box is not None:
                    placed.append(box)
                t.setPos(x + 1.5, y + 1.5)
                self.plot.addItem(t)
                self._contact_labels.append(t)
