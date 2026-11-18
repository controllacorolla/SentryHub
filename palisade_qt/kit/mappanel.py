"""Map panel — PyQtGraph scatter with range rings over a satellite basemap.

Map styles are DARK SAT (default) or LIGHT SAT only (owner, 2026-11-17): one satellite fetch,
tinted. The imagery is resampled into the contacts' own frame (eventbus.to_xy), follows the view
(pan / zoom), and slides with small HOME moves (GPS follow). Tiles are fetched in a background
thread and cached under ~/.cache/palisade/tiles/.
"""
import math
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


def make_legend(parent, per_row=4, row=False):
    """The track-type legend overlay (ATLAS map and OPS scope): fixed colours on a dark plate, so it
    reads on DARK SAT and LIGHT SAT alike. The parent places it (bottom-left) on resize. row=True:
    one row of equal cells; the parent gives it the map's width (OPS strip along the bottom)."""
    from . import tracksym
    if row:
        return LegendRow(parent)
    html = tracksym.legend_html(per_row)
    lab = QtWidgets.QLabel(html, parent)
    lab.setObjectName("track_legend")
    lab.setTextFormat(QtCore.Qt.RichText)
    lab.setStyleSheet("QLabel#track_legend { background: rgba(0,0,0,170); "
                      "border: 1px solid #555; font-size: %dpx; padding: 2px 6px; }"
                      % (14 if row else 16))
    lab.adjustSize()
    return lab


class LegendRow(QtWidgets.QFrame):
    """The legend as one tight row of evenly spread items (OPS, owner 2026-11-18: "legend way too
    big, space it out across the bottom of the map, keep it tight"). The parent sets its width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from . import tracksym
        self.setObjectName("track_legend")
        self.setStyleSheet("QFrame#track_legend { background: rgba(0,0,0,170); "
                           "border: 1px solid #555; }")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 1, 6, 1)
        lay.setSpacing(4)
        self.items = []
        for i, (k, name) in enumerate(tracksym.LEGEND):
            if i:
                lay.addStretch(1)
            lab = QtWidgets.QLabel('<span style="color:%s; font-weight:600;">&#9632;</span>'
                                   '<span style="color:#DDD;">&nbsp;%s</span>'
                                   % (tracksym.CLASS_COLOR[k], name))
            lab.setTextFormat(QtCore.Qt.RichText)
            lab.setStyleSheet("font-size: 16px; background: transparent; border: none;")  # CL1 16 px floor
            lay.addWidget(lab)
            self.items.append(lab)
        self.adjustSize()

    def text(self):
        """The legend's entries as one string, like the QLabel legend (ATLAS) answers."""
        return " ".join(lab.text() for lab in self.items)


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
        self.tiles.imagery.connect(self._on_imagery)
        self.imagery = ("none", "")
        # device run 2026-11-18 ("maps don't load"): when imagery cannot be had, the map says why,
        # on the map, instead of staying black
        self.banner = QtWidgets.QLabel(plot)
        self.banner.setObjectName("map_banner")
        self.banner.setAlignment(QtCore.Qt.AlignCenter)
        self.banner.setCursor(QtCore.Qt.PointingHandCursor)
        self.banner.installEventFilter(self)
        self.banner.setStyleSheet("QLabel#map_banner { background: rgba(0,0,0,190); color: #F0C674;"
                                  " border: 1px solid #F0C674; border-radius: 6px;"
                                  " padding: 4px 10px; font-size: 16px; }")
        self.banner.hide()
        self._dismissed = False
        # owner 2026-11-18 (decision: "one-tap download on the map"): fetch this view's imagery
        # once while NET stays OFFLINE; logged as a granted request
        self.download_btn = QtWidgets.QPushButton("DOWNLOAD MAP", plot)
        self.download_btn.setObjectName("map_download")
        self.download_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.download_btn.setToolTip("download the satellite tiles for this view once and keep "
                                     "them (NET stays OFFLINE; the download is logged)")
        self.download_btn.setStyleSheet(
            "QPushButton#map_download { background: #F0C674; color: #111; border: none;"
            " border-radius: 6px; padding: 4px 12px; font-size: 16px; font-weight: 600; }")
        self.download_btn.clicked.connect(self.download)
        self.download_btn.hide()
        plot.installEventFilter(self)
        self.style = style
        self._raw = None
        self.shown_rect = None
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self.refresh)
        plot.getViewBox().sigRangeChanged.connect(lambda *_: self._timer.start())
        self.on_shown = None

    def eventFilter(self, obj, ev):
        if obj is self.plot and ev.type() == QtCore.QEvent.Resize:
            self._place_banner()
        elif obj is self.banner and ev.type() == QtCore.QEvent.MouseButtonPress:
            self.dismiss()                    # tap the strip to put it away (RA-S2 N2)
            return True
        return False

    @staticmethod
    def short_text(state, text):
        """One line for the strip; the full reason is its tooltip (RA-S2 N2/N3/N6)."""
        offline = "OFFLINE" in (text or "")
        if state == "offline":
            return "NO IMAGERY · NET OFFLINE"
        if state == "partial":
            return "PART IMAGERY · NET OFFLINE" if offline else "PART IMAGERY · SOME TILES FAILED"
        if "download failed" in (text or ""):
            return "NO IMAGERY · DOWNLOAD FAILED"
        return "NO IMAGERY FOR THIS AREA"

    def _place_banner(self):
        """A small strip in a corner of the map, never over its centre where HOME and the nearest
        contacts are (RA-S2 N2): the reason, and the button beside it. Top-right, else
        bottom-right, else top-left, whichever does not cover the map's own controls (OPS: FULL
        MAP + legend row; ATLAS: style, zoom and HOME at the top right, legend bottom-left)."""
        w, ph = self.plot.width(), self.plot.height()
        self.banner.adjustSize()
        self.download_btn.adjustSize()
        h = max(self.banner.sizeHint().height(), self.download_btn.sizeHint().height())
        self.banner.setFixedHeight(h)
        self.download_btn.setFixedHeight(h)
        btn = not self.download_btn.isHidden()
        total = self.banner.width() + ((self.download_btn.width() + 6) if btn else 0)
        busy = self._overlay_rects()
        # the outer bands only (top and bottom 30 %), right then left, nearest the edge first
        tops = list(range(8, max(9, int(ph * 0.3)), 6))
        bottoms = list(range(ph - 8 - h, int(ph * 0.7), -6))
        spots = [(w - 8 - total, y) for y in tops] + [(w - 8 - total, y) for y in bottoms] + \
                [(8, y) for y in tops] + [(8, y) for y in bottoms]
        x, y = w - 8 - total, 8
        for sx, sy in spots:
            r = QtCore.QRect(max(0, sx), sy, total, h).adjusted(-4, -4, 4, 4)
            if not any(r.intersects(b) for b in busy):
                x, y = sx, sy
                break
        x = max(8, x)
        self.banner.move(x, y)
        self.download_btn.move(x + self.banner.width() + 6, y)

    def _overlay_rects(self):
        """Rects (plot coordinates) of the small controls drawn over the map: its own children and
        the page's overlays that sit on top of it (ATLAS style / zoom / HOME, legends)."""
        host = self.plot.parentWidget() or self.plot
        g0 = self.plot.mapToGlobal(QtCore.QPoint(0, 0))
        area = self.plot.rect()
        out = []
        for c in host.findChildren(QtWidgets.QWidget):
            if c in (self.banner, self.download_btn, self.plot) or not c.isVisible():
                continue
            if c.isAncestorOf(self.plot):
                continue
            if self.plot.isAncestorOf(c) and c.parentWidget() is not self.plot:
                continue
            if c.width() * c.height() > area.width() * area.height() // 3:
                continue                          # a backdrop / the plot's own viewport
            r = QtCore.QRect(c.mapToGlobal(QtCore.QPoint(0, 0)) - g0, c.size())
            if r.intersects(area):
                out.append(r)
        return out

    def _on_imagery(self, state, text):
        changed = (state, text) != self.imagery
        self.imagery = (state, text)
        if changed:
            self._dismissed = False
        show = state in ("offline", "failed", "partial") and bool(text) and self.can_fetch \
            and not getattr(self, "_dismissed", False)
        self.banner.setText(self.short_text(state, text) + "  ✕")
        self.banner.setToolTip(text + "\n(tap to hide)")
        self.banner.setVisible(show)
        # the button where a tap can help: tiles the NET mode refused (DOWNLOAD MAP), or a
        # failed download (RETRY: the same one-shot, logged grant; RA-S2 N6)
        self.download_btn.setVisible(show and ((state in ("offline", "partial") and
                                                "OFFLINE" in text) or
                                               "download failed" in text or
                                               "some tiles failed" in text))
        self.download_btn.setEnabled(True)
        self.download_btn.setText("DOWNLOAD MAP" if "OFFLINE" in text else "RETRY")
        if show:
            self._place_banner()
            self.banner.raise_()
            self.download_btn.raise_()

    def dismiss(self):
        """Put the strip away until the imagery state changes (RA-S2 N2)."""
        self._dismissed = True
        self.banner.hide()
        self.download_btn.hide()

    def download(self):
        """One tap: this view's tiles, once, despite NET OFFLINE (TileLayer.download)."""
        if not self.can_fetch:
            return
        self.download_btn.setEnabled(False)
        self.download_btn.setText("DOWNLOADING…")
        self.tiles.view = self.view()
        self.tiles.download(FETCH_STYLE)

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

    SHIFT_MAX_NM = 5.0      # a HOME move this small slides the image; further, it is rebuilt

    def set_home(self, lat, lon):
        if lat is None or lon is None:
            return
        if self.can_fetch and (self.tiles.home_lat, self.tiles.home_lon) == (lat, lon):
            return
        self.can_fetch = True
        self.tiles.home_lat, self.tiles.home_lon = lat, lon
        built = getattr(self, "_built", None)
        if self._raw is not None and built is not None:
            # RA-UIPc M4: HOME follows GPS in small steps. Slide the imagery already built (its
            # rect is relative to the HOME it was built for) instead of blanking it, and re-fetch
            # only when it no longer covers the view or HOME has moved SHIFT_MAX_NM from it.
            from .. import eventbus
            dx, dy = eventbus.to_xy(built[0], built[1], home=(lat, lon))
            if math.hypot(dx, dy) < self.SHIFT_MAX_NM:
                r0 = self._rect0
                self._raw = (self._raw[0], r0.translated(dx, dy))
                self._show()
                if not self._covers(self._raw[1]):
                    self.refresh()
                return
        self._raw = None
        self.img.clear()
        self.refresh()

    def _covers(self, rect):
        x0, x1, y0, y1, _w = self.view()
        return (rect.x() <= x0 and rect.x() + rect.width() >= x1 and
                rect.y() <= y0 and rect.y() + rect.height() >= y1)

    def _on_tiles(self, arr, x0, y0, x1, y1, built=None):
        # RA-UIPd N2: the rect is relative to the HOME the build was made for, which may not be
        # HOME any more (a GPS move between the worker's emit and this queued delivery). Place it
        # by that HOME: slide it into the current frame, or drop it and rebuild if it is too far.
        cur = (self.tiles.home_lat, self.tiles.home_lon)
        built = tuple(built) if built is not None else cur
        rect0 = QtCore.QRectF(x0, y0, x1 - x0, y1 - y0)
        rect = QtCore.QRectF(rect0)
        if built != cur:
            from .. import eventbus
            dx, dy = eventbus.to_xy(built[0], built[1], home=cur)
            if math.hypot(dx, dy) >= self.SHIFT_MAX_NM:
                if self._raw is not None:     # else set_home's big-move path already re-fetched
                    self.refresh()            # (RA-UIPe E4: no second build)
                return
            rect = rect0.translated(dx, dy)
        self._rect0, self._built = rect0, built
        self._raw = (arr, rect)
        self._show()
        if built != cur and not self._covers(rect):
            self.refresh()

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
        self._trails = pg.PlotDataItem([], [], pen=pg.mkPen((230, 230, 230, 110), width=1.5))
        self._leaders = pg.PlotDataItem([], [], pen=pg.mkPen((255, 255, 255, 220), width=1.5))
        self.plot.addItem(self._trails)
        self.plot.addItem(self._leaders)
        self.leader_count = self.trail_count = 0
        self.track_spots = []
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
        self.legend = make_legend(self)
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
        self.legend.move(10, self.height() - self.legend.height() - 10)
        self.legend.raise_()
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

    def set_tracks(self, contacts, trails=None):
        """C2-style tracks (owner 2026-11-17): heading-oriented glyph coloured by type, velocity
        leader, history trail, data-block label. contacts: dicts with x, y, kind, id and optional
        track/spd/alt/label/mil/category/severity/trust; trails: {id: [(x, y), ...]}."""
        from . import tracksym
        spots = []
        for c in contacts:
            spots.append({"pos": (c["x"], c["y"]), "symbol": tracksym.glyph(c),
                          "size": tracksym.AIR_SIZE if c.get("kind") == "aircraft" else tracksym.OTHER_SIZE,
                          "brush": pg.mkBrush(tracksym.color(c)),
                          "pen": pg.mkPen("#000000", width=1.2), "data": c.get("id")})
        self.scatter.setData(spots)
        self.track_spots = spots
        lead = [ln for ln in (tracksym.leader(c) for c in contacts) if ln is not None]
        xs, ys = tracksym.segments(lead)
        self._leaders.setData(xs, ys, connect="pairs")
        tr = tracksym.trail_segments(trails or {}, [c.get("id") for c in contacts])
        xs, ys = tracksym.segments(tr)
        self._trails.setData(xs, ys, connect="pairs")
        self.leader_count, self.trail_count = len(lead), len(tr)
        self._place_labels([(c["x"], c["y"]) for c in contacts],
                           [tracksym.data_block(c) for c in contacts])

    def set_contacts(self, points, labels=None, colors=None):
        """points: iterable of (x_nm, y_nm). labels/colors: optional per-point lists."""
        pts = list(points)
        if colors:
            spots = [{"pos": (p[0], p[1]), "brush": pg.mkBrush(c), "size": 7, "pen": None}
                     for p, c in zip(pts, colors)]
            self.scatter.setData(spots)
        else:
            self.scatter.setData([p[0] for p in pts], [p[1] for p in pts])
        self._place_labels(pts, labels)

    def _place_labels(self, pts, labels):
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
