"""ATLAS — one layered live map (the first wired backend).

Every source publishes typed `contact` events to the event bus with a geo-native payload
(lat/lon/alt/kind); ATLAS's map AND the OPS PPI both consume that one stream, so a contact shows
in both places. Layers (aircraft / ships / APRS / drones / DF / balloons) toggle on the map.

Honesty (CLAUDE.md): demo mode flies synthetic tracks, flagged by the SDR-DEMO chip; LIVE mode
runs the real engine adapters, which publish nothing until they're wired — so a live ATLAS with
no backend shows zero contacts rather than inventing them. UI + wiring only; no decoding/radio
behaviour changes here.
"""
import math
import random
import time

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp
from . import theme, eventbus
from .kit import MapPanel, FeedTable, DetailCard, micro
from .worker import Worker

# kind -> (legend label, theme colour token). Severity "alert" overrides the colour to red.
KINDS = [("aircraft", "AIRCRAFT", "accent"), ("ship", "SHIPS", "live"),
         ("aprs", "APRS", "warn"), ("drone", "DRONES", "alert"),
         ("df", "DF", "text"), ("balloon", "BALLOONS", "muted")]
KIND_LABEL = {k: lbl for k, lbl, _ in KINDS}
KIND_TOKEN = {k: tok for k, _, tok in KINDS}
STALE_S = 12.0


# ------------------------------------------------------------------ demo tracks
def _offset(lat, lon, d_nm, brg_deg):
    b = math.radians(brg_deg)
    return (lat + d_nm / 60.0 * math.cos(b),
            lon + d_nm / 60.0 * math.sin(b) / max(0.2, math.cos(math.radians(lat))))


class _Track:
    _SPD = {"aircraft": (160, 480), "ship": (4, 22), "aprs": (0, 55), "drone": (8, 40),
            "df": (0, 0), "balloon": (6, 30)}
    _ALT = {"aircraft": (6000, 39000), "drone": (60, 400), "balloon": (30000, 90000)}

    def __init__(self, kind):
        self.kind = kind
        home = eventbus.HOME
        self.lat, self.lon = _offset(home[0], home[1], random.uniform(5, 68),
                                     random.uniform(0, 360))
        self.hdg = random.uniform(0, 360)
        self.spd = random.uniform(*self._SPD[kind])
        self.alt = random.randint(*self._ALT[kind]) if kind in self._ALT else None
        self.id = self._mkid(kind)
        self.mil = kind == "aircraft" and random.random() < 0.18

    @staticmethod
    def _mkid(kind):
        if kind == "aircraft":
            return random.choice(["UAL", "ASA", "DAL", "FDX", "N"]) + str(random.randint(100, 980))
        if kind == "ship":
            return str(random.randint(200000000, 775000000))        # MMSI
        if kind == "aprs":
            return random.choice(["KD7", "W7", "N0", "KE7"]) + random.choice("ABCXYZ") + \
                str(random.randint(1, 9))
        if kind == "drone":
            return "RID-%06X" % random.randint(0, 0xFFFFFF)
        if kind == "df":
            return "BRG-%03d" % random.randint(0, 359)
        return "BAL-%04d" % random.randint(1, 9999)

    def step(self, dt):
        if self.spd:
            d = self.spd / 3600.0 * dt
            self.lat, self.lon = _offset(self.lat, self.lon, d, self.hdg)

    def event(self):
        sev = "alert" if (self.mil or self.kind == "drone") else "live"
        return eventbus.contact("ATLAS", self.id, self.lat, self.lon, alt=self.alt,
                                kind=self.kind, severity=sev, spd=round(self.spd), mil=self.mil)


class AtlasDemoWorker(Worker):
    """Synthetic multi-layer traffic, published to the bus (demo only)."""
    _COUNT = {"aircraft": 6, "ship": 4, "aprs": 3, "drone": 2, "df": 1, "balloon": 1}

    def __init__(self, parent=None):
        super().__init__(demo=True, interval_ms=600, parent=parent)
        self.tracks = [_Track(k) for k, n in self._COUNT.items() for _ in range(n)]
        self._t = time.time()

    def step(self):
        now = time.time()
        dt, self._t = now - self._t, now
        for tk in self.tracks:
            tk.step(dt)
            eventbus.bus.publish(tk.event())
        self.status.emit({"sdr": {"text": "SDR DEMO", "state": "neutral"}})


_EMERG_SQ = {"7500", "7600", "7700"}


def adsb_to_contact(a):
    """Adapt ONE sky_app aircraft dict -> a typed contact event. The decoding is sky_app's and is
    left unchanged; this only reshapes its output. Returns None for an aircraft with no position."""
    lat, lon = a.get("lat"), a.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    cid = (a.get("flight") or "").strip() or str(a.get("hex", "")).upper()
    alt = a.get("alt_baro")
    if not isinstance(alt, (int, float)):
        alt = a.get("alt_geom")
    spd = a.get("gs")
    sq = str(a.get("squawk") or "")
    emerg = a.get("emergency")
    sev = "alert" if (emerg and emerg not in ("", "none")) or sq in _EMERG_SQ else "live"
    return eventbus.contact("ADS-B", cid, lat, lon,
                            alt=int(alt) if isinstance(alt, (int, float)) else None,
                            kind="aircraft", severity=sev,
                            spd=int(spd) if isinstance(spd, (int, float)) else None,
                            track=a.get("track"), hexid=a.get("hex"))


def adsb_contacts(aircraft):
    """Typed contact events for a sky_app aircraft snapshot (aircraft with a position only)."""
    return [ev for ev in (adsb_to_contact(a) for a in aircraft) if ev is not None]


class AtlasLiveWorker(Worker):
    """Live mode: pull real aircraft from sky_app's ADS-B engine (readsb/dump1090 aircraft.json)
    and publish them as typed contacts. No radio is opened and no lease is taken — readsb runs as
    its own service and owns its radio; we only read its output, so decoding/radio behaviour is
    unchanged and the autopilot is undisturbed. Other layers (AIS/APRS/dronewatch/DF/balloons)
    are still stubbed; with no engine up this publishes ZERO contacts. Device-only: real RTL
    capture is validated on the uConsole."""

    def __init__(self, parent=None):
        super().__init__(demo=False, interval_ms=1000, parent=parent)
        self._adsb = None
        self._adsb_tried = False

    def _ensure_adsb(self):
        if self._adsb_tried:
            return
        self._adsb_tried = True
        try:
            import sky_app
            srcs = sky_app.DEFAULT_SETTINGS.get("adsb_sources") or ["/run/readsb"]
            self._adsb = sky_app.AdsbFeed(list(srcs))
        except Exception as e:       # no engine / no deps in this env: stay at zero, surface once
            self.error.emit("ADS-B engine unavailable: %s" % str(e)[:120])
            self._adsb = None

    def step(self):
        self._ensure_adsb()
        for ev in self._adsb_contacts():
            eventbus.bus.publish(ev)

    def _adsb_contacts(self):
        if self._adsb is None:
            return []
        try:
            aircraft, _trails, _status, _rcv = self._adsb.snapshot()
        except Exception:
            return []
        return adsb_contacts(aircraft)

    def run(self):
        super().run()
        if self._adsb is not None:
            self._adsb.stopped = True        # stop the feed's poll thread on close


# ------------------------------------------------------------------ app
class AtlasApp(PalisadeApp):
    TITLE = "ATLAS"
    # ADS-B reads readsb's aircraft.json (readsb owns its radio); no 2nd radio, no lease.
    # A dongle-using layer (AIS on 162 MHz) will take the lease when it is wired.
    LEASE = None

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        self._contacts = {}
        self._selected = None
        self._layers = {k for k, _, _ in KINDS}      # all layers on by default

        body = QtWidgets.QWidget()
        split = QtWidgets.QHBoxLayout(body)
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(10)

        self.map = MapPanel(span_nm=80, mode=self.mode,
                            home_lat=eventbus.HOME[0], home_lon=eventbus.HOME[1])
        split.addWidget(self.map, 3)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._legend())
        self.feed = FeedTable([("label", "CONTACT"), ("kind", "TYPE"),
                               ("rng", "NM"), ("alt", "ALT")])
        self.feed.selected.connect(self._show)
        right.addWidget(self.feed, 3)
        self.detail = DetailCard("CONTACT")
        self.detail.set_hero("—", "select a contact")
        right.addWidget(self.detail, 2)
        split.addLayout(right, 2)

        eventbus.bus.published.connect(self._on_event)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._render)
        self._timer.start(700)
        return body

    def _legend(self):
        f = QtWidgets.QFrame()
        f.setProperty("class", "card2")
        lay = QtWidgets.QHBoxLayout(f)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(6)
        lay.addWidget(micro("Layers"))
        self._layer_btns = {}
        for k, lbl, tok in KINDS:
            b = QtWidgets.QPushButton(lbl)
            b.setCheckable(True)
            b.setChecked(True)
            b.setStyleSheet("QPushButton { color:%s; padding:2px 7px; font-size:10px;"
                            " border:1px solid %s; border-radius:6px; }"
                            " QPushButton:!checked { color:%s; border-color:%s; }"
                            % (self._tok[tok], self._tok["hairline"],
                               self._tok["muted"], self._tok["hairline"]))
            b.clicked.connect(lambda on, kk=k: self._toggle(kk, on))
            lay.addWidget(b)
            self._layer_btns[k] = b
        lay.addStretch(1)
        return f

    def _toggle(self, kind, on):
        self._layers.add(kind) if on else self._layers.discard(kind)
        self._render()

    def make_worker(self):
        return AtlasDemoWorker() if self.demo else AtlasLiveWorker()

    def _color(self, kind, severity):
        return self._tok["alert"] if severity == "alert" else self._tok[KIND_TOKEN.get(kind, "text")]

    def _on_event(self, ev):
        if ev["type"] != "contact":
            return
        pl = ev["payload"]
        x, y = eventbus.to_xy(pl["lat"], pl["lon"])
        self._contacts[pl["id"]] = {
            "id": pl["id"], "label": pl.get("label", pl["id"]), "kind": pl.get("kind", "air"),
            "x": x, "y": y, "alt": pl.get("alt"), "spd": pl.get("spd"),
            "severity": ev["severity"], "_ts": ev["ts"],
            "rng": math.hypot(x, y), "brg": math.degrees(math.atan2(x, y)) % 360}

    def _render(self):
        now = time.time()
        self._contacts = {c["id"]: c for c in self._contacts.values() if now - c["_ts"] < STALE_S}
        shown = [c for c in self._contacts.values() if c["kind"] in self._layers]
        self.map.set_contacts([(c["x"], c["y"]) for c in shown],
                              labels=[c["label"] for c in shown],
                              colors=[self._color(c["kind"], c["severity"]) for c in shown])
        rows = []
        for c in sorted(shown, key=lambda c: c["rng"]):
            rows.append({"label": c["label"], "kind": KIND_LABEL.get(c["kind"], c["kind"]),
                         "rng": "%.0f" % c["rng"], "alt": "%d" % c["alt"] if c["alt"] else "—",
                         "_src": c, "_colors": {"rng": self._color(c["kind"], c["severity"])}})
        self.feed.model.set_rows(rows)
        self.set_chip("sdr", ("%d CONTACTS" % len(shown)) if (self.demo or shown) else "NO FEED",
                      state="neutral")

    def _show(self, row):
        c = row.get("_src", {})
        self._selected = c.get("id")
        self.detail.set_hero(c.get("label", "—"), KIND_LABEL.get(c.get("kind"), ""))
        self.detail.set_rows([
            ("TYPE", KIND_LABEL.get(c.get("kind"), "—")),
            ("ALTITUDE", "%d ft" % c["alt"] if c.get("alt") else "—"),
            ("SPEED", "%d kt" % c["spd"] if c.get("spd") else "—"),
            ("RANGE", "%.0f nm" % c.get("rng", 0)),
            ("BEARING", "%03d°" % c.get("brg", 0))])

    def stop(self):
        try:
            eventbus.bus.published.disconnect(self._on_event)
        except (RuntimeError, TypeError):
            pass
        if hasattr(self, "_timer"):
            self._timer.stop()
        super().stop()
