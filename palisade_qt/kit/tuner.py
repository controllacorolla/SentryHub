"""TunerScope — SDR++-style spectrum + waterfall with a VFO you click, drag and wheel.

The app pushes frames (dBFS per bin across [lo_hz, hi_hz]) with push(); the widget keeps the
waterfall history at full resolution, so zooming in or out redraws from what is already there.

Interaction (all emit `vfo_requested(hz)`; the app decides what tuning means):
  * click anywhere on the spectrum or waterfall  -> VFO to that frequency (snapped to the step)
  * drag the VFO line / passband on the spectrum -> VFO follows
  * mouse wheel over either view                 -> VFO up / down one step
The passband (VFO +/- bandwidth, SSB one-sided) is shaded on both views. Bookmarks in view are
drawn as labelled ticks. No threads here.
"""
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .. import theme

MAX_COLS = 1024          # display columns after max-pooling the visible bins
ZOOMS = (1, 2, 4, 8, 16, 32)


class _View(pg.ViewBox):
    """ViewBox that reports clicks / wheel in data coordinates instead of panning."""

    def __init__(self, owner):
        super().__init__(enableMenu=False)
        self._owner = owner
        self.setMouseEnabled(False, False)

    def mouseClickEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            p = self.mapSceneToView(ev.scenePos())
            self._owner._clicked(p.x())
            ev.accept()
        else:
            ev.ignore()

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() != QtCore.Qt.LeftButton:
            ev.ignore()
            return
        p = self.mapSceneToView(ev.scenePos())
        self._owner._clicked(p.x())                    # drag anywhere = sweep the VFO
        ev.accept()

    def wheelEvent(self, ev, axis=None):
        d = ev.delta() if hasattr(ev, "delta") else ev.angleDelta().y()
        self._owner.wheel_step.emit(1 if d > 0 else -1)
        ev.accept()


class TunerScope(QtWidgets.QFrame):
    vfo_requested = QtCore.Signal(int)     # Hz
    wheel_step = QtCore.Signal(int)        # +1 / -1

    def __init__(self, history=140, mode="dark", parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
        self.tok = tok = theme.tokens(mode)
        pg.setConfigOptions(antialias=False, imageAxisOrder="row-major")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)
        self.history = history
        self.lo_hz, self.hi_hz = 118e6, 120e6
        self.buf = None                    # (history, nbins) dBFS at full resolution
        self.last = None
        self.zoom = 1
        self.vfo_hz = 119e6
        self.bw_hz = 10000
        self.mode = "AM"
        self.step_hz = 25000
        self.levels = (-90.0, -20.0)
        self.bookmarks = []                # [(hz, label)]
        self._bm_items = []
        self.can_drag = True

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(tok["well"])
        lay.addWidget(self.glw)
        self.sv = _View(self)
        self.spec = self.glw.addPlot(row=0, col=0, viewBox=self.sv)
        self.glw.nextRow()
        self.wv = _View(self)
        self.wf = self.glw.addPlot(row=1, col=0, viewBox=self.wv)
        self.glw.ci.layout.setRowStretchFactor(0, 35)
        self.glw.ci.layout.setRowStretchFactor(1, 65)
        self.wf.setXLink(self.spec)
        tick_font = pg.QtGui.QFont()
        tick_font.setPixelSize(16)
        for p in (self.spec, self.wf):
            p.hideButtons()
            p.setMenuEnabled(False)
            for ax in ("left", "bottom"):
                a = p.getAxis(ax)
                a.setTextPen(tok["muted"])
                a.setPen(tok["hairline"])
                a.setTickFont(tick_font)
                a.setStyle(tickLength=-5)
            p.getAxis("left").setWidth(52)
        self.wf.getAxis("bottom").setStyle(showValues=False)
        self.wf.getAxis("left").setStyle(showValues=False)
        self.spec.getAxis("bottom").setLabel("MHz", color=tok["muted"])

        acc = tuple(int(tok["accent"][i:i + 2], 16) for i in (1, 3, 5))
        self.curve = self.spec.plot(pen=pg.mkPen(tok["accent"], width=1.5), fillLevel=-200,
                                    fillBrush=pg.mkBrush(acc[0], acc[1], acc[2], 30))
        self.peak = self.spec.plot(pen=pg.mkPen(tok["muted"], width=1,
                                                style=QtCore.Qt.DotLine))
        self.peak_hold = None
        self.img = pg.ImageItem()
        self.img.setLookupTable(self._lut(tok))
        self.wf.addItem(self.img)
        self.wf.invertY(True)

        live = tuple(int(tok["live"][i:i + 2], 16) for i in (1, 3, 5))
        self.band = pg.LinearRegionItem(movable=False,
                                        brush=pg.mkBrush(live[0], live[1], live[2], 45),
                                        pen=pg.mkPen(None))
        self.band_wf = pg.LinearRegionItem(movable=False,
                                           brush=pg.mkBrush(live[0], live[1], live[2], 35),
                                           pen=pg.mkPen(None))
        self.vline = pg.InfiniteLine(angle=90, movable=True,
                                     pen=pg.mkPen(tok["live"], width=2),
                                     hoverPen=pg.mkPen(tok["text"], width=3))
        self.vline_wf = pg.InfiniteLine(angle=90, movable=False,
                                        pen=pg.mkPen(tok["live"], width=1))
        self.vline.sigDragged.connect(lambda l: self._clicked(l.value()))
        self.spec.addItem(self.band)
        self.spec.addItem(self.vline)
        self.wf.addItem(self.band_wf)
        self.wf.addItem(self.vline_wf)
        self.sqline = pg.InfiniteLine(angle=0, movable=False,
                                      pen=pg.mkPen(tok["warn"], width=1, style=QtCore.Qt.DashLine))
        self.sqline.hide()
        self.spec.addItem(self.sqline)
        self._apply_levels()
        self._place_vfo()

    @staticmethod
    def _lut(tok):
        accent = tuple(int(tok["accent"][i:i + 2], 16) for i in (1, 3, 5))
        green = tuple(int(tok["live"][i:i + 2], 16) for i in (1, 3, 5))
        stops = [(0.0, (6, 8, 12)), (0.35, (30, 24, 60)), (0.6, accent), (0.82, green),
                 (1.0, (220, 255, 235))]
        cm = pg.ColorMap([s[0] for s in stops], [s[1] + (255,) for s in stops])
        return cm.getLookupTable(0.0, 1.0, 256)

    # ---------------- public API
    def set_vfo(self, hz, bw_hz=None, mode=None):
        self.vfo_hz = float(hz)
        if bw_hz is not None:
            self.bw_hz = float(bw_hz)
        if mode is not None:
            self.mode = mode
        self._place_vfo()
        if self.zoom > 1:
            self._redraw()

    def set_step(self, hz):
        self.step_hz = max(1.0, float(hz))

    def set_zoom(self, z):
        self.zoom = int(min(ZOOMS[-1], max(1, z)))
        self._redraw()

    def zoom_in(self):
        i = ZOOMS.index(self.zoom) if self.zoom in ZOOMS else 0
        self.set_zoom(ZOOMS[min(len(ZOOMS) - 1, i + 1)])

    def zoom_out(self):
        i = ZOOMS.index(self.zoom) if self.zoom in ZOOMS else 0
        self.set_zoom(ZOOMS[max(0, i - 1)])

    def set_levels(self, lo, hi):
        lo, hi = float(lo), float(hi)
        if hi - lo < 5:
            hi = lo + 5
        self.levels = (lo, hi)
        self._apply_levels()
        self._redraw()

    def auto_levels(self):
        """Floor a little below the median, top a little above the strongest bin (SDR++ auto)."""
        if self.last is None:
            return self.levels
        floor = float(np.median(self.last))
        top = float(np.max(self.last))
        self.set_levels(floor - 8, max(top + 6, floor + 30))
        return self.levels

    def set_squelch_line(self, db):
        if db is None:
            self.sqline.hide()
        else:
            self.sqline.setValue(float(db))
            self.sqline.show()

    def set_bookmarks(self, marks):
        self.bookmarks = list(marks)
        self._draw_bookmarks()

    def clear(self):
        self.buf = None
        self.last = None
        self.peak_hold = None
        self.curve.setData([], [])
        self.peak.setData([], [])

    def push(self, db, lo_hz, hi_hz):
        """One frame: dBFS per bin evenly spaced across [lo_hz, hi_hz]."""
        db = np.asarray(db, dtype=np.float32)
        if (self.buf is None or self.buf.shape[1] != db.size
                or abs(lo_hz - self.lo_hz) > 1 or abs(hi_hz - self.hi_hz) > 1):
            self.buf = np.full((self.history, db.size), self.levels[0], dtype=np.float32)
            self.lo_hz, self.hi_hz = float(lo_hz), float(hi_hz)
            self.peak_hold = None
            self._draw_bookmarks()
        self.buf = np.roll(self.buf, -1, axis=0)
        self.buf[-1] = db
        self.last = db
        self.peak_hold = db.copy() if self.peak_hold is None else np.maximum(
            db, self.peak_hold - 0.5)
        self._redraw()

    def window(self):
        """(lo_hz, hi_hz) currently shown: the full band at 1x, centred on the VFO when zoomed."""
        span = (self.hi_hz - self.lo_hz) / self.zoom
        if self.zoom == 1:
            return self.lo_hz, self.hi_hz
        c = min(max(self.vfo_hz, self.lo_hz + span / 2), self.hi_hz - span / 2)
        return c - span / 2, c + span / 2

    # ---------------- internals
    def _clicked(self, x_mhz):
        hz = float(x_mhz) * 1e6
        step = self.step_hz
        hz = round(hz / step) * step
        lo, hi = self.window()
        hz = min(max(hz, lo), hi)
        self.vfo_requested.emit(int(round(hz)))

    def _passband(self):
        v, bw = self.vfo_hz, self.bw_hz
        if self.mode == "USB":
            return v, v + bw
        if self.mode == "LSB":
            return v - bw, v
        return v - bw / 2, v + bw / 2

    def _place_vfo(self):
        a, b = self._passband()
        self.band.setRegion((a / 1e6, b / 1e6))
        self.band_wf.setRegion((a / 1e6, b / 1e6))
        self.vline.setValue(self.vfo_hz / 1e6)
        self.vline_wf.setValue(self.vfo_hz / 1e6)

    def _apply_levels(self):
        self.spec.setYRange(self.levels[0], self.levels[1], padding=0)
        self.curve.setFillLevel(self.levels[0])

    def _cols(self):
        """Slice of bins in the window, max-pooled to <= MAX_COLS. -> (db_rows, lo, hi)."""
        n = self.buf.shape[1]
        lo, hi = self.window()
        span = self.hi_hz - self.lo_hz
        i0 = int(max(0, np.floor((lo - self.lo_hz) / span * n)))
        i1 = int(min(n, np.ceil((hi - self.lo_hz) / span * n)))
        i1 = max(i1, i0 + 2)
        rows = self.buf[:, i0:i1]
        k = max(1, int(np.ceil(rows.shape[1] / MAX_COLS)))
        if k > 1:
            m = rows.shape[1] // k * k
            rows = rows[:, :m].reshape(rows.shape[0], m // k, k).max(axis=2)
        lo_b = self.lo_hz + i0 / n * span
        hi_b = self.lo_hz + (i0 + rows.shape[1] * k) / n * span
        return rows, lo_b, hi_b, i0, k

    def _redraw(self):
        if self.buf is None:
            return
        rows, lo, hi, i0, k = self._cols()
        x = np.linspace(lo, hi, rows.shape[1], endpoint=False) / 1e6 + (hi - lo) / rows.shape[1] / 2e6
        self.curve.setData(x, rows[-1])
        if self.peak_hold is not None:
            ph = self.peak_hold[i0:i0 + rows.shape[1] * k]
            if k > 1:
                ph = ph.reshape(-1, k).max(axis=1)
            self.peak.setData(x[:ph.size], ph)
        self.img.setImage(rows, autoLevels=False, levels=self.levels,
                          rect=QtCore.QRectF(lo / 1e6, 0, (hi - lo) / 1e6, self.history))
        self.spec.setXRange(lo / 1e6, hi / 1e6, padding=0)
        self.wf.setYRange(0, self.history, padding=0)

    def _draw_bookmarks(self):
        for it in self._bm_items:
            self.spec.removeItem(it)
        self._bm_items = []
        for hz, label in self.bookmarks[:60]:
            if not self.lo_hz <= hz <= self.hi_hz:
                continue
            ln = pg.InfiniteLine(pos=hz / 1e6, angle=90, movable=False,
                                 pen=pg.mkPen(self.tok["cyan"], width=1,
                                              style=QtCore.Qt.DotLine),
                                 label=(label or "")[:14],
                                 labelOpts={"position": 0.92, "color": self.tok["cyan"],
                                            "anchors": [(0, 0), (0, 0)]})
            self.spec.addItem(ln)
            self._bm_items.append(ln)
