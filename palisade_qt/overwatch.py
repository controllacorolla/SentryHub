"""OVERWATCH — sky dome and satellite passes. Since CL1 these are sub-tabs of ATLAS (key 2); the
radio-director view moved to the shell's RADIOS panel (panels.RadiosPanel), unchanged.

Sub-views: SKY DOME / PASSES.
  * SKY DOME — a polar dome (zenith centre, horizon rim) with the sun + moon (pure astro math,
    always live) and satellite positions / pass arcs. Reuses overwatch.project/dome_r/compass and
    astro.sun_azel/moon_azel AS-IS.
  * PASSES — upcoming satellite passes from wxsat.predict (skyfield + TLE), scheduled via
    passsched.schedule/next_pass AS-IS; the next pass raises an alert on the OPS strip.

Honesty: the sun/moon backdrop is deterministic math, so it is always live. The satellite layer
needs a TLE — with none it shows "NO TLE — update required" and draws nothing in live mode; demo
draws clearly-flagged synthetic passes. Tests inject a fake TLE file and never fetch from network.
No orbital-mechanics change — UI + wiring only. OVERWATCH holds no lease of its own (LEASE=None).
"""
import math
import os
import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .app import PalisadeApp, _retain
from . import theme, eventbus
from .kit import FeedTable, micro
from .kit.components import note
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SUBVIEWS = ("SKY DOME", "PASSES")
HOME_LAT, HOME_LON = eventbus.HOME


def _offscreen():
    return bool(os.environ.get("PALISADE_OFFLINE") or
                os.environ.get("QT_QPA_PLATFORM") == "offscreen")


# ======================= the polar sky dome =======================

class SkyDome(QtWidgets.QFrame):
    """Zenith at the centre, horizon on the rim, north up. Paints sun / moon / satellites and their
    pass arcs. Projection reused from overwatch.project (dome_r gives the low sky more room)."""

    def __init__(self, tok, parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
        self._tok = tok
        self.setMinimumSize(160, 160)            # sized from the space it is given
        self._sun = None          # (az, el)
        self._moon = None         # (az, el, lit)
        self._sats = []           # [{label, az, el, demo}]
        self._arcs = []           # [[(az, el), ...], ...] pass tracks

    def set_sky(self, sun, moon, sats, arcs):
        self._sun, self._moon, self._sats, self._arcs = sun, moon, sats, arcs
        self.update()

    def _project(self, az, el, cx, cy, r):
        import overwatch as ow
        return ow.project(az, el, cx, cy, r)

    def paintEvent(self, ev):
        import overwatch as ow
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 24
        grid = QtGui.QColor(self._tok["hairline"])
        muted = QtGui.QColor(self._tok["muted"])
        # elevation rings (horizon, 30, 60) + zenith dot
        p.setPen(QtGui.QPen(grid, 1))
        for el in (0, 30, 60):
            rr = ow.dome_r(el, r)
            p.drawEllipse(QtCore.QPointF(cx, cy), rr, rr)
        # cardinal spokes + labels
        p.setPen(QtGui.QPen(muted, 1))
        for az, lab in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            x, y = self._project(az, 0, cx, cy, r)
            p.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(x, y))
            lx, ly = self._project(az, -6, cx, cy, r)
            p.drawText(QtCore.QRectF(lx - 10, ly - 8, 20, 16), QtCore.Qt.AlignCenter, lab)
        # pass arcs
        for arc in self._arcs:
            pts = [self._project(a, e, cx, cy, r) for a, e in arc if e >= 0]
            if len(pts) > 1:
                p.setPen(QtGui.QPen(QtGui.QColor(self._tok["accent"]), 1.5))
                path = QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts])
                p.drawPolyline(path)
        # sun
        if self._sun and self._sun[1] > -2:
            x, y = self._project(self._sun[0], max(0, self._sun[1]), cx, cy, r)
            p.setBrush(QtGui.QColor(self._tok["warn"]))
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(QtCore.QPointF(x, y), 9, 9)
            p.setPen(muted)
            p.drawText(QtCore.QRectF(x - 14, y + 9, 28, 14), QtCore.Qt.AlignCenter, "☉")
        # moon (fill reflects lit fraction)
        if self._moon and self._moon[1] > -2:
            x, y = self._project(self._moon[0], max(0, self._moon[1]), cx, cy, r)
            lit = self._moon[2]
            p.setBrush(QtGui.QColor(200, 205, 215, int(60 + 180 * lit)))
            p.setPen(QtGui.QPen(muted, 1))
            p.drawEllipse(QtCore.QPointF(x, y), 7, 7)
        # satellites
        for s in self._sats:
            if s["el"] < 0:
                continue
            x, y = self._project(s["az"], s["el"], cx, cy, r)
            col = QtGui.QColor(self._tok["live"] if not s.get("demo") else self._tok["muted"])
            p.setBrush(col)
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(QtCore.QPointF(x, y), 5, 5)
            p.setPen(QtGui.QColor(self._tok["text"]))
            p.drawText(self.label_rect(x, y, s["label"], p.fontMetrics()),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, s["label"])
        p.end()

    def label_rect(self, x, y, label, fm):
        """Where a satellite's label goes: sized from the font (a fixed 16 px box clipped the 18 px
        text, RA-CL1), right of the dot unless that runs off the dome, then left of it, and kept
        inside the widget top and bottom."""
        tw, th = fm.horizontalAdvance(label) + 2, fm.height()
        lx = x + 7 if x + 7 + tw <= self.width() - 2 else x - 7 - tw
        lx = max(2, lx)
        ly = min(max(2, y - th / 2), self.height() - th - 2)
        return QtCore.QRectF(lx, ly, tw, th)


# ======================= workers =======================

class SkyWorker(Worker):
    """Ticks the dome: sun + moon from pure astro (always live), satellites from the current passes
    (interpolated) or demo_orbiter. No network, no TLE here."""

    def __init__(self, demo=True, parent=None):
        super().__init__(demo=demo, interval_ms=1000, parent=parent)
        self._passes = []

    def set_passes(self, passes):
        self._passes = passes or []

    def step(self):
        import astro
        now = time.time()
        sun = astro.sun_azel(HOME_LAT, HOME_LON, now)
        moon = astro.moon_azel(HOME_LAT, HOME_LON, now)
        sats, arcs = self._sat_overlay(now)
        self.row.emit({"sun": sun, "moon": moon, "sats": sats, "arcs": arcs,
                       "daylight": astro.daylight(sun[1])})

    def _sat_overlay(self, now):
        if self.demo and not self._passes:
            import overwatch as ow
            d = ow.demo_orbiter(now)[0]
            sats = [{"label": d["label"], "az": d["az"], "el": d["el"], "demo": True}]
            arc = [(sats[0]["az"], max(0, sats[0]["el"]))]
            return sats, [arc]
        sats, arcs = [], []
        for p in self._passes:
            track = p.get("track", [])
            if track:
                arcs.append(track)
            if p["aos"] <= now <= p["los"] and track:
                frac = (now - p["aos"]) / max(1.0, (p["los"] - p["aos"]))
                az, el = track[min(len(track) - 1, int(frac * (len(track) - 1)))]
                sats.append({"label": p["sat"], "az": az, "el": el, "demo": p.get("demo", False)})
        return sats, arcs


class PassWorker(Worker):
    """Predicts satellite passes off the GUI thread (skyfield is slow). Live: wxsat.predict from the
    cached TLE; no TLE / no skyfield -> an honest NO-TLE/standby signal. Demo: synthetic passes."""

    RE_PREDICT_S = 3600                       # re-predict hourly so the horizon stays fresh

    def __init__(self, demo=True, tle_path=None, parent=None):
        super().__init__(demo=demo, interval_ms=60000, parent=parent)
        self._tle_path = tle_path
        self._last_predict = 0.0

    def step(self):
        now = time.time()
        if now - self._last_predict < self.RE_PREDICT_S:   # predict at open, then re-run hourly
            return
        self._last_predict = now
        passes, status = self._predict()
        self.row.emit({"passes": passes, "status": status})

    def _predict(self):
        if self.demo:
            return _demo_passes(time.time()), "demo"
        import wxsat
        # an explicitly-injected TLE path is a local file (no network) — honour it even offscreen;
        # otherwise the cached TLE is used only on a real device, never in tests/CI
        tle = self._tle_path or (None if _offscreen() else wxsat.TLE_PATH)
        if tle is None:
            return [], "offscreen"
        if not os.path.exists(tle):
            return [], "no-tle"
        try:
            s = dict(wxsat.DEFAULTS)
            s["satellites"] = s["satellites"] + [{"name": "ISS (ZARYA)", "norad": 25544,
                                                  "freq": 145.8}]
            passes = wxsat.predict(s, {"lat": HOME_LAT, "lon": HOME_LON, "alt_m": 50},
                                   hours=24, path=tle)
            return passes, "live"
        except ImportError:
            return [], "no-skyfield"
        except Exception as e:
            self.error.emit("predict: %s" % str(e)[:120])
            return [], "error"


def _demo_passes(now):
    """Two clearly-flagged synthetic passes (rising + descending arcs) so the layer is visible
    without TLEs. Never used in live mode."""
    out = []
    for i, (name, freq, t0, maxel, az0) in enumerate([
            ("NOAA-19 (demo)", 137.1, now + 300, 58.0, 200),
            ("ISS (demo)", 145.8, now + 2400, 31.0, 310)]):
        track = []
        for k in range(41):
            ph = k / 40.0
            el = maxel * math.sin(math.pi * ph)
            az = (az0 + 150 * ph) % 360
            track.append((az, el))
        out.append({"sat": name, "freq": freq, "aos": t0, "los": t0 + 720,
                    "max": maxel, "track": track, "dir": "southbound", "demo": True})
    return out


def _remap(p):
    """wxsat pass -> passsched keys (max->max_elev, freq->freq_mhz), preserving the rest."""
    q = dict(p)
    q["max_elev"] = p.get("max", 0)
    q["freq_mhz"] = p.get("freq", 0)
    return q


# ======================= the app =======================

class OverwatchApp(PalisadeApp):
    TITLE = "OVERWATCH"
    LEASE = None            # never holds a lease of its own
    SUBTABS = SUBVIEWS

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._view = "SKY DOME"
        self._next_alerted = None
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    def current_subtab(self):
        return self._view

    def switch_subtab(self, name):
        self._switch(name)

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.stack = QtWidgets.QStackedWidget()
        self._pages = {"SKY DOME": self._dome_page(), "PASSES": self._passes_page()}
        for v in SUBVIEWS:
            self.stack.addWidget(self._pages[v])
        lay.addWidget(self.stack, 1)
        self._sync_views()
        return body

    def _dome_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QHBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.dome = SkyDome(self._tok)
        pl.addWidget(self.dome, 3)
        right = QtWidgets.QVBoxLayout()
        self.sky_chip = note("")
        right.addWidget(self.sky_chip)
        right.addWidget(micro("OVERHEAD"))
        self.obj_feed = FeedTable([("name", "OBJECT"), ("el", "EL"), ("az", "AZ")])
        right.addWidget(self.obj_feed, 1)
        pl.addLayout(right, 2)
        return page

    def _passes_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.pass_note = note("")
        pl.addWidget(self.pass_note)
        self.pass_feed = FeedTable([("sat", "SATELLITE"), ("aos", "AOS"), ("max", "MAX EL"),
                                    ("freq", "FREQ"), ("decoder", "DECODER")])
        pl.addWidget(self.pass_feed, 1)
        return page

    # ---- sub-view switching ----
    def _switch(self, view):
        self._view = view
        self.stack.setCurrentWidget(self._pages[view])
        self._sync_views()

    def _sync_views(self):
        self._sync_rail()

    # ---- lifecycle ----
    def start(self):
        if self._started:
            return
        super().start()
        self._workers = []
        self._sky = SkyWorker(demo=self.demo)
        self._sky.row.connect(self._on_sky)
        self._sky.start()
        self._workers.append(self._sky)
        self._passw = PassWorker(demo=self.demo)
        self._passw.row.connect(self._on_passes)
        self._passw.error.connect(self.on_error)
        self._passw.start()
        self._workers.append(self._passw)

    def stop(self):
        if self._stopped:
            return
        for w in getattr(self, "_workers", []):
            w.stop()
            w.quit()
            w.wait(3000)
            _retain(w)
        self._workers = []
        super().stop()

    # ---- worker outputs ----
    def _on_sky(self, msg):
        sun, moon = msg["sun"], msg["moon"]
        sats, arcs = msg["sats"], msg["arcs"]
        self.dome.set_sky(sun, moon, sats, arcs)
        self.sky_chip.setText("%s · sun el %.0f°" % (msg["daylight"], sun[1]))
        rows = [{"name": "Sun", "el": "%.0f" % sun[1], "az": "%.0f" % sun[0]},
                {"name": "Moon", "el": "%.0f" % moon[1], "az": "%.0f" % moon[0]}]
        for s in sats:
            rows.append({"name": s["label"], "el": "%.0f" % s["el"], "az": "%.0f" % s["az"]})
        self.obj_feed.model.set_rows(rows)

    def _on_passes(self, msg):
        import passsched
        passes, status = msg["passes"], msg["status"]
        sky = getattr(self, "_sky", None)
        if sky is not None:
            sky.set_passes(passes)           # feed the dome the pass arcs
        standby = {"no-tle": "NO TLE — update required",
                   "no-skyfield": "Skyfield not installed — satellite passes unavailable",
                   "error": "pass prediction failed — standby",
                   "offscreen": "pass prediction unavailable (offscreen)"}
        if status in standby:                  # surface a failure honestly, not as a clear sky
            self.pass_note.setStyleSheet("color:%s;" % self._tok["warn"])
            self.pass_note.setText(standby[status])
            self.pass_feed.model.set_rows([])
            return
        sched = passsched.schedule([_remap(p) for p in passes], min_elev=15.0)
        chosen_keys = {(p["sat"], p["aos"]) for p in sched}
        rows = []
        for p in sorted(passes, key=lambda x: x["aos"]):
            dec = passsched.assign_decoder(p["sat"])
            rows.append({"sat": p["sat"] + (" ·DEMO" if p.get("demo") else ""),
                         "aos": time.strftime("%H:%M", time.localtime(p["aos"])),
                         "max": "%.0f°" % p.get("max", 0), "freq": "%.1f" % p.get("freq", 0),
                         "decoder": (dec or "—") + (" ◀record" if (p["sat"], p["aos"]) in chosen_keys
                                                    else ""),
                         "_colors": {"decoder": self._tok["live"]} if (p["sat"], p["aos"])
                         in chosen_keys else {}})
        self.pass_feed.model.set_rows(rows)
        tag = " (demo)" if status == "demo" else ""
        self.pass_note.setStyleSheet("color:%s;" % self._tok["muted"])
        self.pass_note.setText("%d passes in the next 24h%s" % (len(passes), tag))
        self._alert_next(passsched.next_pass(passes, time.time()), status)

    def _alert_next(self, nxt, status):
        if not nxt or status == "demo":                # real passes only to the OPS strip
            return
        key = (nxt["sat"], round(nxt["aos"]))
        if key == self._next_alerted:
            return
        self._next_alerted = key
        eventbus.bus.publish(eventbus.alert(
            "OVERWATCH", "next pass: %s at %s (max %.0f°, %.1f MHz)" % (
                nxt["sat"], time.strftime("%H:%M", time.localtime(nxt["aos"])),
                nxt.get("max", 0), nxt.get("freq", 0)),
            severity="info", sat=nxt["sat"], aos=nxt["aos"], max_el=nxt.get("max"),
            freq=nxt.get("freq")))
