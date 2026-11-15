"""OVERWATCH — sky dome, satellite passes, and the radio-director dashboard.

Sub-views: SKY DOME / RADIO / PASSES / SENTINEL.
  * SENTINEL — autonomous, receive-only RF watch: capture a baseline of the RF environment +
    device inventory, then re-scan on an interval and diff against it (new/gone/changed → OPS
    alerts + a forensic JSONL log). Reuses noisefloor/wifisurvey/blescan; spectrum sweeps go
    through the radio_arbiter lease. OPSEC never gates it (RX-only). See sentinel.py.
  * SKY DOME — a polar dome (zenith centre, horizon rim) with the sun + moon (pure astro math,
    always live) and satellite positions / pass arcs. Reuses overwatch.project/dome_r/compass and
    astro.sun_azel/moon_azel AS-IS.
  * RADIO — the operator's view into the one-owner dongle: who holds the radio_arbiter lease, the
    acquire/release history (from the arbiter's `changed` signal), and a manual HAND-OVER that frees
    the current holder so the next layer can take it. This is the seed of the radio director.
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
import threading
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .app import PalisadeApp
from . import theme, eventbus, radio_arbiter
from .kit import FeedTable, DetailCard, micro
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SUBVIEWS = ("SKY DOME", "RADIO", "PASSES", "SENTINEL")
HOME_LAT, HOME_LON = eventbus.HOME


def _offscreen():
    return bool(os.environ.get("PALISADE_OFFLINE") or
                os.environ.get("QT_QPA_PLATFORM") == "offscreen")


def _fmt_dur(secs):
    secs = int(secs or 0)
    return "%dm%02ds" % (secs // 60, secs % 60) if secs >= 60 else "%ds" % secs


def _short_path(path):
    home = os.path.expanduser("~")
    p = path.replace(home, "~") if path.startswith(home) else path
    return ("…" + p[-26:]) if len(p) > 28 else p


# ======================= the polar sky dome =======================

class SkyDome(QtWidgets.QFrame):
    """Zenith at the centre, horizon on the rim, north up. Paints sun / moon / satellites and their
    pass arcs. Projection reused from overwatch.project (dome_r gives the low sky more room)."""

    def __init__(self, tok, parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
        self._tok = tok
        self.setMinimumSize(360, 360)
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
            p.drawText(QtCore.QRectF(x + 7, y - 8, 120, 16), QtCore.Qt.AlignLeft, s["label"])
        p.end()


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


# ======================= SENTINEL — autonomous RF watch =======================

class SentinelWorker(Worker):
    """The autonomous watch loop as a long-running QThread. Idle until commanded: CAPTURE BASELINE
    runs one full sweep and saves it to disk; START WATCH re-scans on the interval and diffs against
    the baseline, publishing events to OPS and a forensic JSONL log. Receive-only — OPSEC does not
    gate it. The spectrum sweep takes the radio_arbiter lease 'SENTINEL-SWEEP' for the sweep only and
    releases it between sweeps, so other layers can use the single dongle; a busy radio is recorded
    honestly (no fabricated spectrum) and the watch keeps running Wi-Fi/BLE."""

    NAME = "SENTINEL-SWEEP"

    def __init__(self, demo=True, config=None, parent=None):
        super().__init__(demo=demo, interval_ms=400, parent=parent)
        import sentinel
        self._sentinel = sentinel
        self._cfg = dict(sentinel.DEFAULTS)
        self._cfg.update(config or {})
        self._lock = threading.Lock()
        self._cmds = []
        self._mode = "idle"                 # idle | watch
        self._baseline = None
        self._ws = None
        self._log = None
        self._demo_gen = sentinel.Demo() if demo else None
        self._storage = sentinel.resolve_dir(self._cfg)
        self._watch_start = None
        self._last_sweep = 0.0
        self._sweeps = 0
        self._events = []
        self._rtl_proc = None

    # -- command queue from the GUI thread --
    def cmd(self, c):
        with self._lock:
            self._cmds.append(c)

    def _take_cmd(self):
        with self._lock:
            return self._cmds.pop(0) if self._cmds else None

    def storage(self):
        return self._storage

    def _stopf(self):
        return self._stop

    # -- live seams: spectrum wraps the arbiter lease; every blocking seam honours the stop flag so
    #    a close interrupts an in-flight sweep and the thread joins within wait(3000) --
    def _seams(self):
        s = self._sentinel.real_seams()
        s["spectrum"] = self._spectrum_leased
        s["wifi"] = lambda c: self._sentinel.real_wifi(c, stop=self._stopf)
        s["ble"] = lambda c: self._sentinel.real_ble(c, stop=self._stopf)
        return s

    def _spectrum_leased(self, config):
        if not radio_arbiter.arbiter.request(self.NAME):     # another layer holds the dongle
            return self._sentinel._domain(False, "radio-busy", owner=radio_arbiter.owner_label())
        try:
            return self._sentinel.real_spectrum_bins(config, stop=self._stopf,
                                                     on_proc=self._set_rtl_proc)
        finally:
            radio_arbiter.arbiter.release(self.NAME)          # free it between sweeps

    def _set_rtl_proc(self, proc):
        self._rtl_proc = proc            # handle so stop() can terminate a wedged rtl_power read

    def stop(self):
        super().stop()                   # _stop = True -> the blocking seams short-circuit
        p = self._rtl_proc
        if p is not None:
            try:
                p.terminate()            # unblock a wedged rtl_power so the read loop returns
            except Exception:
                pass
        try:
            radio_arbiter.arbiter.release(self.NAME)   # owner-guarded; free the dongle on close
        except Exception:
            pass

    def _progress(self, domain, phase):
        self.status.emit({"progress": {"domain": domain, "phase": phase}})

    # -- loop --
    def step(self):
        cmd = self._take_cmd()
        if cmd == "baseline":
            self._do_baseline()
        elif cmd == "start":
            self._do_start()
        elif cmd == "stop":
            self._do_stop()
        if self._mode == "watch":
            now = time.time()
            if now - self._last_sweep >= float(self._cfg.get("interval_s", 60)):
                self._do_sweep(now)

    def _do_baseline(self):
        now = time.time()
        self.row.emit({"kind": "capturing"})
        if self.demo:
            for d in self._sentinel.DOMAINS:        # show per-domain progress for the demo too
                self._progress(d, "scanning")
            base = self._demo_gen.baseline(self._cfg, now)
        else:
            base = self._sentinel.capture_baseline(self._cfg, self._seams(), now=now,
                                                   on_progress=self._progress, stop=self._stopf)
        self._baseline = base
        self._ws = self._sentinel.WatchState(base, self._cfg)
        if self.demo:                               # demo never writes the real forensic store
            self.row.emit({"kind": "baseline", "baseline": base, "saved": False,
                           "path": "(demo — not written to disk)", "demo": True})
        else:
            ok, info = self._sentinel.save_baseline(self._storage, base)
            self.row.emit({"kind": "baseline", "baseline": base, "saved": ok, "path": info,
                           "demo": False})

    def _do_start(self):
        if self._baseline is None:
            self.row.emit({"kind": "notice", "text": "capture a baseline first"})
            return
        if self.demo:                               # demo keeps an in-memory watch; no disk I/O
            self._log = None
            disk, logpath = "demo (not logged to disk)", "(demo)"
        else:
            ok, msg = self._sentinel.disk_gate(self._storage)
            if not ok:
                self.row.emit({"kind": "notice", "text": msg})
                return
            self._sentinel.ensure_dir(self._storage)
            session = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            self._log = self._sentinel.SentinelLog(
                os.path.join(self._storage, "sentinel_log_%s.jsonl" % session),
                rotate_bytes=int(self._cfg.get("rotate_mb", 100)) * 1024 * 1024)
            disk, logpath = msg, self._log.path
        self._mode = "watch"
        self._watch_start = time.time()
        self._last_sweep = 0.0
        self._sweeps = 0
        self._events = []
        self.row.emit({"kind": "watch", "state": "running", "disk": disk, "log": logpath})

    def _do_stop(self):
        if self._mode != "watch":
            return
        self._mode = "idle"
        dur = time.time() - (self._watch_start or time.time())
        summary = self._sentinel.summarize(self._events, dur, self._sweeps)
        summary["log"] = self._log.path if self._log else None
        self.row.emit({"kind": "summary", "summary": summary})

    def _do_sweep(self, now):
        self._last_sweep = now
        self._sweeps += 1
        if self.demo:
            scan = self._demo_gen.scan(self._cfg, now)
        else:
            scan = self._sentinel.scan_once(self._cfg, self._seams(), now=now,
                                            on_progress=self._progress, stop=self._stopf)
        gps = scan.get("gps")
        if self._log:
            self._log.append({"t": now, "type": "scan", "sweep": self._sweeps,
                              "demo": bool(scan.get("demo")),      # heartbeat is self-describing
                              "domains": {k: {"available": v.get("available"),
                                              "status": v.get("status")}
                                          for k, v in scan["domains"].items()}, "gps": gps})
        for e in (self._ws.observe(scan, now) if self._ws else []):
            self._events.append(e)
            if self._log:
                self._log.append(dict(e, type="event"))
            eventbus.bus.publish(eventbus.alert("SENTINEL", e["detail"], severity=e["severity"],
                                                kind=e["kind"], domain=e["domain"], id=e["id"]))
            self.row.emit({"kind": "event", "event": e})
        self.status.emit({"sweep": self._sweeps,
                          "duration": time.time() - (self._watch_start or now),
                          "domains": {k: v.get("available") for k, v in scan["domains"].items()},
                          "busy": scan["domains"]["spectrum"].get("owner"),
                          "disk": self._sentinel.disk_status(self._storage)})   # statvfs off the GUI thread

    def run(self):
        super().run()
        try:
            radio_arbiter.arbiter.release(self.NAME)     # free the dongle if we stopped mid-lease
        except Exception:
            pass


# ======================= the app =======================

class OverwatchApp(PalisadeApp):
    TITLE = "OVERWATCH"
    LEASE = None            # OVERWATCH directs the arbiter; it never holds a lease of its own

    def __init__(self, demo=False, mode="dark", parent=None):
        self._view = "SKY DOME"
        self._history = []
        self._next_alerted = None
        self._sentinel_holds = False
        super().__init__(demo=demo, mode=mode, parent=parent)

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)
        self._view_btns = {}
        for v in SUBVIEWS:
            b = QtWidgets.QPushButton(v)
            b.setCheckable(True)
            b.setFixedWidth(110)
            b.clicked.connect(lambda _=False, vv=v: self._switch(vv))
            self._view_btns[v] = b
            top.addWidget(b)
        top.addStretch(1)
        self.sky_chip = QtWidgets.QLabel("")
        self.sky_chip.setProperty("class", "micro")
        top.addWidget(self.sky_chip)
        lay.addLayout(top)

        self.stack = QtWidgets.QStackedWidget()
        self._pages = {"SKY DOME": self._dome_page(), "RADIO": self._radio_page(),
                       "PASSES": self._passes_page(), "SENTINEL": self._sentinel_page()}
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
        right.addWidget(micro("OVERHEAD"))
        self.obj_feed = FeedTable([("name", "OBJECT"), ("el", "EL"), ("az", "AZ")])
        right.addWidget(self.obj_feed, 1)
        pl.addLayout(right, 2)
        return page

    def _radio_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.holder = DetailCard("RADIO DIRECTOR · single-SDR owner")
        self.holder.set_hero("—", "radio free")
        pl.addWidget(self.holder)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(micro("Hand over / free"))
        self.takeover_btn = QtWidgets.QPushButton("FREE THE RADIO (release holder)")
        self.takeover_btn.clicked.connect(self._free_radio)
        row.addWidget(self.takeover_btn)
        row.addStretch(1)
        pl.addLayout(row)
        pl.addWidget(micro("Acquire / release history"))
        self.hist_feed = FeedTable([("t", "TIME"), ("event", "EVENT"), ("owner", "LAYER")])
        pl.addWidget(self.hist_feed, 1)
        return page

    def _passes_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.pass_note = QtWidgets.QLabel("")
        self.pass_note.setProperty("class", "micro")
        pl.addWidget(self.pass_note)
        self.pass_feed = FeedTable([("sat", "SATELLITE"), ("aos", "AOS"), ("max", "MAX EL"),
                                    ("freq", "FREQ"), ("decoder", "DECODER")])
        pl.addWidget(self.pass_feed, 1)
        return page

    def _sentinel_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        # controls + storage/free-space chip
        ctl = QtWidgets.QHBoxLayout()
        ctl.setSpacing(8)
        self.sent_baseline_btn = QtWidgets.QPushButton("CAPTURE BASELINE")
        self.sent_baseline_btn.clicked.connect(lambda: self._sentinel_cmd("baseline"))
        self.sent_start_btn = QtWidgets.QPushButton("START WATCH")
        self.sent_start_btn.clicked.connect(lambda: self._sentinel_cmd("start"))
        self.sent_start_btn.setEnabled(False)
        self.sent_stop_btn = QtWidgets.QPushButton("STOP WATCH")
        self.sent_stop_btn.clicked.connect(lambda: self._sentinel_cmd("stop"))
        self.sent_stop_btn.setEnabled(False)
        for b in (self.sent_baseline_btn, self.sent_start_btn, self.sent_stop_btn):
            ctl.addWidget(b)
        ctl.addStretch(1)
        self.sent_storage_chip = QtWidgets.QLabel("storage —")
        self.sent_storage_chip.setProperty("class", "micro")
        ctl.addWidget(self.sent_storage_chip)
        pl.addLayout(ctl)
        # status cards + per-domain scan progress
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        self.sent_baseline_card = DetailCard("BASELINE")
        self.sent_baseline_card.set_hero("—", "not captured")
        row.addWidget(self.sent_baseline_card, 2)
        self.sent_watch_card = DetailCard("WATCH")
        self.sent_watch_card.set_hero("STOPPED", "idle")
        row.addWidget(self.sent_watch_card, 2)
        dbox = QtWidgets.QVBoxLayout()
        dbox.setSpacing(3)
        dbox.addWidget(micro("SCAN DOMAINS"))
        self.sent_domain_lbls = {}
        for d in ("spectrum", "wifi", "ble", "cellular"):
            lbl = QtWidgets.QLabel("%s · —" % d)
            lbl.setProperty("class", "micro")
            self.sent_domain_lbls[d] = lbl
            dbox.addWidget(lbl)
        dbox.addStretch(1)
        dw = QtWidgets.QWidget()
        dw.setLayout(dbox)
        row.addWidget(dw, 1)
        pl.addLayout(row)
        # live event feed
        pl.addWidget(micro("WATCH EVENTS · baseline deviations (also on the OPS alert strip)"))
        self.sent_feed = FeedTable([("t", "TIME"), ("sev", "SEV"), ("domain", "DOMAIN"),
                                    ("detail", "EVENT")])
        pl.addWidget(self.sent_feed, 1)
        self._sent_events = []
        return page

    def _sentinel_cmd(self, c):
        w = getattr(self, "_sentinel_worker", None)
        if w is not None:
            w.cmd(c)

    def _on_sentinel_row(self, msg):
        kind = msg.get("kind")
        if kind == "capturing":
            self.sent_baseline_card.set_hero("CAPTURING…", "sweeping domains")
            self.sent_baseline_btn.setEnabled(False)
        elif kind == "baseline":
            b = msg["baseline"]
            avail = [d for d, v in b.get("domains", {}).items() if v.get("available")]
            tag = " ·DEMO" if msg.get("demo") else ""
            self.sent_baseline_card.set_hero("CAPTURED" + tag, b.get("captured_iso", "") + "Z")
            self.sent_baseline_card.set_rows([
                ("DOMAINS", ", ".join(avail) or "none available (standby)"),
                ("SAVED", "yes" if msg.get("saved") else "no — " + str(msg.get("path"))[:40]),
                ("FILE", os.path.basename(str(msg.get("path"))) if msg.get("saved") else "—")])
            self.sent_baseline_btn.setEnabled(True)
            self.sent_start_btn.setEnabled(True)
            self._update_storage_chip()
        elif kind == "watch":
            self.sent_watch_card.set_hero("RUNNING", msg.get("disk", ""))
            self.sent_watch_card.set_rows([("LOG", os.path.basename(str(msg.get("log"))))])
            self.sent_start_btn.setEnabled(False)
            self.sent_stop_btn.setEnabled(True)
        elif kind == "event":
            e = msg["event"]
            col = self._tok["warn"] if e["severity"] == "warn" else self._tok["accent"]
            self._sent_events.insert(0, {
                "t": time.strftime("%H:%M:%S", time.localtime(e["t"])),
                "sev": ("DEMO " if e.get("demo") else "") + e["severity"].upper(),
                "domain": e["domain"], "detail": e["detail"], "_colors": {"sev": col}})
            self._sent_events = self._sent_events[:200]
            self.sent_feed.model.set_rows(self._sent_events)
        elif kind == "summary":
            s = msg["summary"]
            self.sent_watch_card.set_hero("STOPPED", "%d events · %s · %d sweeps" % (
                s["events"], _fmt_dur(s["duration_s"]), s["sweeps"]))
            self.sent_watch_card.set_rows([("DEVIATION", str(s["deviation_score"])),
                                           ("LOG", os.path.basename(str(s.get("log"))))])
            self.sent_start_btn.setEnabled(True)
            self.sent_stop_btn.setEnabled(False)
        elif kind == "notice":
            self.sent_watch_card.set_hero("STOPPED", msg.get("text", ""))

    def _on_sentinel_status(self, status):
        if "progress" in status:
            p = status["progress"]
            lbl = self.sent_domain_lbls.get(p["domain"])
            if lbl is not None:
                lbl.setText("%s · %s" % (p["domain"], p["phase"]))
        if "sweep" in status:
            busy = status.get("busy")
            sub = "sweep %d · %s" % (status["sweep"], _fmt_dur(status.get("duration", 0)))
            if busy:
                sub += " · RADIO BUSY (%s)" % busy
            self.sent_watch_card.set_hero("RUNNING", sub)
            for d, avail in (status.get("domains") or {}).items():
                lbl = self.sent_domain_lbls.get(d)
                if lbl is not None:
                    lbl.setText("%s · %s" % (d, "ok" if avail else "standby"))
            self._update_storage_chip(status.get("disk"))   # worker-computed; no statvfs on GUI

    def _update_storage_chip(self, disk=None):
        w = getattr(self, "_sentinel_worker", None)
        if w is None:
            return
        if disk is None:                 # one-off (page build) — per-sweep uses the worker's value
            import sentinel
            disk = sentinel.disk_status(w.storage())
        self.sent_storage_chip.setText("%s · %.0f%% free" % (_short_path(w.storage()), disk["pct_free"]))
        self.sent_storage_chip.setStyleSheet(
            "color:%s;" % (self._tok["warn"] if disk["warn"] else self._tok["muted"]))

    # ---- sub-view switching ----
    def _switch(self, view):
        self._view = view
        self.stack.setCurrentWidget(self._pages[view])
        self._sync_views()
        if view == "RADIO":
            self._refresh_holder()

    def _sync_views(self):
        for v, b in self._view_btns.items():
            b.setChecked(v == self._view)

    # ---- radio director ----
    def _on_arbiter_change(self, owner):
        # SENTINEL re-leases the dongle every sweep; keep its high-frequency churn out of the
        # director history (the live holder view still shows it via _refresh_holder).
        if owner == SentinelWorker.NAME:
            self._sentinel_holds = True
            return
        if not owner and self._sentinel_holds:
            self._sentinel_holds = False
            return
        now = time.strftime("%H:%M:%S")
        if owner:
            lbl = radio_arbiter.OWNER_LABELS.get(owner, owner)
            self._history.insert(0, {"t": now, "event": "ACQUIRE", "owner": lbl})
        else:
            self._history.insert(0, {"t": now, "event": "RELEASE", "owner": "—"})
        self._history = self._history[:200]
        self.hist_feed.model.set_rows(self._history)
        self._refresh_holder()

    def _refresh_holder(self):
        owner = radio_arbiter.arbiter.owner()
        if owner:
            self.holder.set_hero(radio_arbiter.owner_label() or owner, "holds the single SDR")
            self.holder.set_rows([("LEASE", owner), ("STATE", "BUSY — one owner at a time")])
            self.takeover_btn.setEnabled(True)
        else:
            self.holder.set_hero("—", "radio free")
            self.holder.set_rows([("STATE", "FREE — any layer may acquire")])
            self.takeover_btn.setEnabled(False)

    def _free_radio(self):
        owner = radio_arbiter.arbiter.owner()
        if owner:
            radio_arbiter.arbiter.release(owner)      # free the dongle; the next layer acquires it
        self._refresh_holder()

    # ---- lifecycle ----
    def start(self):
        if self._started:
            return
        super().start()
        radio_arbiter.arbiter.changed.connect(self._on_arbiter_change)
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
        # SENTINEL autonomous watch (idle until commanded; receive-only, so OPSEC never gates it)
        self._sentinel_worker = SentinelWorker(
            demo=self.demo, config={"interval_s": 2, "grace_s": 6} if self.demo else None)
        self._sentinel_worker.row.connect(self._on_sentinel_row)
        self._sentinel_worker.status.connect(self._on_sentinel_status)
        self._sentinel_worker.error.connect(self.on_error)
        self._sentinel_worker.start()
        self._workers.append(self._sentinel_worker)
        self._update_storage_chip()
        if self.demo:                       # demo is self-driving: synthetic baseline + live events
            self._sentinel_worker.cmd("baseline")
            self._sentinel_worker.cmd("start")
        self._refresh_holder()

    def stop(self):
        if self._stopped:
            return
        try:
            radio_arbiter.arbiter.changed.disconnect(self._on_arbiter_change)
        except (TypeError, RuntimeError):
            pass
        for w in getattr(self, "_workers", []):
            w.stop()
            w.quit()
            w.wait(3000)
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
