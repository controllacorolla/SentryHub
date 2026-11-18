"""OPS — the situational command dashboard (per plan/concept/ops-command-dashboard.html).

OPS is a pure CONSUMER of the event bus: the PPI hero, the decode card, and the alert strip all
render whatever the callsign backends publish. It fakes nothing itself.

- demo mode: a DemoFeedWorker stands in for the backends and publishes typed events to the bus,
  so the dashboard is alive and the SDR-DEMO chip makes that honest.
- live mode: only real device telemetry is published; every card that has no backend up shows a
  clear STANDBY state and lights up when that backend lands. No demo numbers dressed as real.
"""
import math
import os
import random
import time
from collections import deque

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp
from . import theme, eventbus
from .kit import card, micro, PpiScope
from .kit.components import note, Cover
from .kit import tracksym
from .worker import Worker
from .timebase import zulu

# The page keys, in rail / digit-key order (SYSTEM last since 2026-11-18), each with the function label shown under the callsign
# in the top strip (owner decision 2026-11-15, plan/audit/AUDIT_INDEX.md · D7). BABEL is folded into
# PROWL, OVERWATCH's sky views into ATLAS, BENCH into SYSTEM; SWEEP is promoted from RECON/COUNTER.
ALL_CALLSIGNS = [
    ("OPS", "home"), ("ATLAS", "map"), ("PRISM", "spectrum"), ("PROWL", "listen"),
    ("SWEEP", "sweep"), ("RECON", "survey"), ("FORGE", "hardware"),
    ("ASSISTANT", "ask"), ("MESH", "lora"),
    ("SYSTEM", "settings"),            # last in the rail (owner, device run 2026-11-18)
]
# v0.1 launch line (owner, 2026-11-16): SWEEP is hidden until CL7 validates its detectors.
# Its code stays; the strip, the keys and the palette do not offer it.
from .release import HIDDEN_PAGES  # noqa: E402
CALLSIGNS = [c for c in ALL_CALLSIGNS if c[0] not in HIDDEN_PAGES]

STALE_S = 12.0          # a contact not refreshed within this drops off the scope


# ---------------------------------------------------------------- demo / live feeds
class DemoFeedWorker(Worker):
    """Demo stand-in for the NON-map backends: publishes decode / alert / telemetry to the bus.
    Contacts are ATLAS's domain now (one stream, two views), so OPS no longer fabricates them."""

    def __init__(self, parent=None):
        super().__init__(demo=True, interval_ms=500, parent=parent)
        self._t0 = time.time()
        self._decodes = [("ADS-B", "DAL1241 · FL340"), ("AIS", "WAVE RUNNER · 8kn"),
                         ("POCSAG", "page · fire disp"), ("ACARS", "POS RPT"), ("RDS", "KEXP")]

    def step(self):
        now = time.time()
        if random.random() < 0.5:
            proto, summ = random.choice(self._decodes)
            eventbus.bus.publish(eventbus.decode("BABEL", proto,
                                                 "%04X" % random.randint(0x1000, 0xFFFF), summ,
                                                 demo=True))
        if random.random() < 0.12:
            kind, sev, src = random.choice([
                ("Drone Remote-ID", "alert", "ATLAS"),
                ("Open AP · linksys", "warn", "RECON"),
                ("MIL contact inbound", "info", "ATLAS")])
            eventbus.bus.publish(eventbus.alert(src, kind, severity=sev, demo=True))
        batt = max(5, 96 - (now - self._t0) * 0.02)
        eventbus.bus.publish(eventbus.make_event("decode", "OPS", {
            "kind": "telemetry", "temp": 62 + 3 * math.sin((now - self._t0) * 0.1),
            "batt": batt, "gps": 9}, severity="info", demo=True))
        self.status.emit({"sdr": {"text": "SDR DEMO", "state": "neutral"},
                          "gps": {"text": "GPS 9 SV", "state": "neutral"}})
        # battery: the top strip's BAT slot (shell), not a bare PWR on the page (2026-11-18)


def sdr_chip(sys_root="/sys"):
    """H6: the SDR chip from the USB ID and the bound kernel driver, and who holds it (the radio
    arbiter) — not from /dev/swradio0, which appears exactly when the kernel's DVB driver has bound
    the dongle and the SDR tools usually cannot claim it."""
    from . import radios, radio_arbiter
    st = radios.sdr_state(sys_root)
    if st["present"] is None:
        return {"text": "SDR ?", "state": "neutral"}             # no USB sysfs here: cannot tell
    if not st["present"]:
        return {"text": "SDR ABSENT", "state": "warn"}
    if not st["usable"]:
        return {"text": "SDR BLOCKED — %s bound" % st["driver"], "state": "alert"}
    owner = radio_arbiter.owner_label()
    if owner:
        return {"text": "SDR HELD · %s" % owner, "state": "neutral"}
    return {"text": "SDR PRESENT", "state": "neutral"}


class LiveStatusWorker(Worker):
    """Live mode: publish only real device telemetry; backends publish their own feeds."""

    # the strip's BAT slot and SDR presence come from here on every page, not only OPS (RA-S1 F1):
    # a sysfs read every 2 s, so it runs while OPS is hidden
    PAUSE_WHEN_HIDDEN = False

    def __init__(self, parent=None, sys_root="/sys"):
        super().__init__(demo=False, interval_ms=2000, parent=parent)
        self._sys_root = sys_root

    def step(self):
        temp = _read_cpu_temp()
        batt = _read_battery()
        eventbus.bus.publish(eventbus.make_event("decode", "OPS", {
            "kind": "telemetry", "temp": temp, "batt": batt,
            "gps": _read_gps_sats()}, severity="info"))
        self.status.emit({"sdr": sdr_chip(self._sys_root)})   # battery: the strip's BAT slot


def _read_cpu_temp():
    for p in ("/sys/class/thermal/thermal_zone0/temp", "/sys/class/hwmon/hwmon0/temp1_input"):
        try:
            with open(p) as f:
                return int(f.read().strip()) / 1000.0
        except (OSError, ValueError):
            continue
    return None


def _read_battery():
    base = "/sys/class/power_supply"
    for name in ("axp20x-battery", "battery", "BAT0"):
        try:
            with open(os.path.join(base, name, "capacity")) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            continue
    return None


def _read_gps_sats():
    return None          # TODO(wire-ui): gpsd satellites-in-use when OVERWATCH/field GPS lands


# ---------------------------------------------------------------- rail card
class _ClickFilter(QtCore.QObject):
    """Makes a card a button: a left click anywhere on it (its labels included) calls fn."""

    def __init__(self, target, fn):
        super().__init__(target)
        self._fn = fn
        target.installEventFilter(self)
        for w in target.findChildren(QtWidgets.QWidget):
            w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.MouseButtonRelease and \
                ev.button() == QtCore.Qt.LeftButton:
            self._fn()
            return True
        return False


def make_clickable(widget, fn, tip):
    """Owner 2026-11-18 ("OPS does nothing"): every OPS card opens the page it summarises."""
    widget.setCursor(QtCore.Qt.PointingHandCursor)
    widget.setToolTip(tip)
    widget.setProperty("clickable", True)
    widget._click = _ClickFilter(widget, fn)
    return widget


class RailCard(QtWidgets.QFrame):
    """A titled rail card with a content area that can fall back to a STANDBY state."""

    def __init__(self, title, mode="dark", parent=None):
        super().__init__(parent)
        self.setProperty("class", "card2")
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(11, 9, 11, 9)
        v.setSpacing(6)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(micro(title))
        head.addStretch(1)
        self.note = QtWidgets.QLabel("")
        self.note.setProperty("class", "note")
        head.addWidget(self.note)
        v.addLayout(head)
        self.body = QtWidgets.QVBoxLayout()
        self.body.setSpacing(3)
        v.addLayout(self.body)
        v.addStretch(1)
        self._standby = note("STANDBY · no feed")
        self.body.addWidget(self._standby)
        self._live = False

    def set_note(self, text):
        self.note.setText(text)

    def clear_body(self):
        click = getattr(self, "_click", None)
        if click is not None:            # new body labels are part of the button too
            QtCore.QTimer.singleShot(0, lambda: [w.installEventFilter(click) for w in
                                                 self.findChildren(QtWidgets.QWidget)])
        while self.body.count():
            it = self.body.takeAt(0)
            w = it.widget()
            if w:
                # hide now: deleteLater only runs when the event loop gets to it, and until then
                # the old label was painted under the new one (RA-CL1 render: overlapping alert row)
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def standby(self, msg="STANDBY · no feed"):
        self.clear_body()
        self.body.addWidget(note(msg))
        self.set_note("")
        self._live = False


# ---------------------------------------------------------------- OPS
class OpsHome(PalisadeApp):
    TITLE = "OPS"
    LEASE = None
    launch = QtCore.Signal(str)

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        self._contacts = {}
        self._selected = None
        self._decodes = []
        self._trails = {}
        self._decode_times = deque()          # H14: real decode timestamps, last 60 s

        body = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        # hero: situation + PPI scope
        hero = QtWidgets.QWidget()
        hv = QtWidgets.QVBoxLayout(hero)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(8)
        # device notes 2026-11-17 (maps too small): the caption sits on the count's row instead of
        # a row of its own, so the scope gets that height back
        # owner 2026-11-18: a bare big "0" left of "CONTACTS LIVE" read as a logo. The caption now
        # comes first and names the number: "CONTACTS ON MAP 19", the reason under it.
        stat = QtWidgets.QHBoxLayout()
        stat.setSpacing(10)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(1)
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(10)
        self.big_cap = micro("Contacts on map")
        row1.addWidget(self.big_cap, 0, QtCore.Qt.AlignVCenter)
        self.big = QtWidgets.QLabel("—")
        self.big.setProperty("class", "value")
        self.big.setToolTip("contacts on the OPS map now: aircraft, vessels, APRS, drones, sondes")
        row1.addWidget(self.big, 0, QtCore.Qt.AlignVCenter)
        row1.addStretch(1)
        col.addLayout(row1)
        self.sub = QtWidgets.QLabel("standby")
        self.sub.setProperty("class", "note")
        col.addWidget(self.sub)
        stat.addLayout(col, 1)
        # short: the sub-line beside it needs the room (RA-UIP L1)
        feeds = micro("All feeds")
        feeds.setToolTip("this map merges every contact feed (ADS-B, AIS, APRS, Remote-ID, sondes)")
        stat.addWidget(feeds, 0, QtCore.Qt.AlignTop)
        hv.addLayout(stat)
        self.ppi = PpiScope(span_nm=80, mode=self.mode)
        self._home_cover = Cover(self.ppi, "offline", "HOME NOT SET",
                                 "Range rings need your position — set HOME in SYSTEM › SETTINGS")
        self._home_cover.show(not self.demo and not eventbus.home_set())
        hv.addWidget(self.ppi, 1)
        row.addWidget(hero, 1)
        # the scope is round: keep its column only as wide as it is tall, and give the rest of
        # the width to the rail instead of a dead well either side (D3 / RA-CL1)
        self._hero = hero
        self.ppi.resized.connect(self._fit_scope)
        self.ppi.contact_clicked.connect(self.select_contact)          # B5

        # rail: PRISM / BABEL / ALERTS / minis
        rail = QtWidgets.QWidget()
        rail.setMinimumWidth(380)
        rail.setMaximumWidth(16777215)
        rv = QtWidgets.QVBoxLayout(rail)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(9)
        self.card_prism = RailCard("PRISM · SPECTRUM", self.mode)
        self.card_prism.standby("PRISM offline · open PRISM")
        rv.addWidget(self.card_prism)
        self.card_babel = RailCard("DECODES · latest", self.mode)
        rv.addWidget(self.card_babel, 1)
        self.card_alert = RailCard("ALERTS · A = history + ack", self.mode)
        rv.addWidget(self.card_alert, 1)
        two = QtWidgets.QHBoxLayout()
        two.setSpacing(9)
        self.mini_pass = self._mini("NEXT PASS", "—")
        self._next_pass = None
        # POWER moved to the strip's BAT slot; this card says where HOME (the map centre) comes from
        self.mini_pwr = self._mini("HOME", self._home_text())
        two.addWidget(self.mini_pass[0])
        two.addWidget(self.mini_pwr[0])
        rv.addLayout(two)
        # owner 2026-11-18 ("OPS does nothing"): each card is the way into its page
        go = self._go
        make_clickable(self.card_prism, lambda: go("PRISM"), "open PRISM (spectrum)")
        make_clickable(self.card_babel, lambda: go("PROWL", "DECODE"), "open PROWL › DECODE")
        make_clickable(self.card_alert, lambda: self.request.emit("open_panel", "alerts"),
                       "open the alert history (acknowledge there)")
        make_clickable(self.mini_pass[0], lambda: go("ATLAS", "PASSES"),
                       "open ATLAS › PASSES (satellite passes for HOME)")
        make_clickable(self.mini_pwr[0], lambda: go("SYSTEM", "SETTINGS"),
                       "where the map centre (HOME) comes from — set it in SYSTEM › SETTINGS")
        make_clickable(self.big, lambda: go("ATLAS"), "open ATLAS (the full contact map)")
        self.mini_pass[1].setText(self._pass_text())
        row.addWidget(rail)
        self._rail_w = rail
        # F / the corner toggle hides the rail: the scope then runs the full width (more of the
        # picture east-west; the rings are sized by height)
        self.make_collapsible(self.ppi, [rail])

        eventbus.bus.published.connect(self._on_event)
        from . import panels
        self._alert_store = panels.alert_store()          # history kept until acknowledged (D10)
        self._alert_store.changed.connect(self._render_alerts)
        self._render_alerts()
        self._prune = QtCore.QTimer(self)
        self._prune.timeout.connect(self._refresh_ppi)
        self._prune.start(700)
        return body

    def _go(self, callsign, subtab=None):
        self.request.emit("open", (callsign, subtab))

    def _pass_text(self):
        """NEXT PASS card: the next real pass OVERWATCH announced, else why there is none."""
        p = self._next_pass
        if p:
            return "%s %s" % (p["sat"], zulu(p["aos"], secs=False))
        if self.demo:
            return "demo"
        st = self.pass_state() if callable(self.pass_state) else None
        return {"no-tle": "NO TLE", "no-home": "HOME NOT SET", "no-skyfield": "no skyfield",
                "error": "predict failed", "offscreen": "—",
                "live": "none in 24 h"}.get(st, "predicting…")

    pass_state = None             # the shell sets it: OVERWATCH's last prediction status

    # the reason the map is empty comes from ATLAS's feed health (the shell sets this: a callable
    # returning ATLAS's layer summary, e.g. "ADS-B NO FEED · APRS —", or None when ATLAS is off)
    feed_summary = None

    def _empty_reason(self):
        if self.demo:
            return "standby"
        if not eventbus.home_set():
            return "no contacts · HOME NOT SET"
        fs = self.feed_summary() if callable(self.feed_summary) else None
        if not fs:
            return "no contacts · contact feeds not running (open ATLAS)"
        return "no contacts · %s" % fs

    def _mini(self, label, value):
        f = card(2)
        v = QtWidgets.QVBoxLayout(f)
        v.setContentsMargins(11, 8, 11, 8)
        v.setSpacing(3)
        v.addWidget(micro(label))
        val = QtWidgets.QLabel(value)
        val.setProperty("class", "value")
        v.addWidget(val)
        return f, val

    def make_worker(self):
        return DemoFeedWorker() if self.demo else LiveStatusWorker()

    # OPS consumes the bus — it does not generate its own display data
    def _on_event(self, ev):
        et, src, pl = ev["type"], ev["source"], ev["payload"]
        if et == "contact":
            # geo-native contact -> local nm frame shared with ATLAS's map
            x, y = eventbus.to_xy(pl["lat"], pl["lon"])
            self._contacts[pl["id"]] = {
                "id": pl["id"], "x": x, "y": y, "lat": pl["lat"], "lon": pl["lon"],
                "label": pl.get("label", pl["id"]),
                "severity": ev["severity"], "_ts": ev["ts"], "rng": math.hypot(x, y),
                "mil": pl.get("mil", False), "kind": pl.get("kind"), "track": pl.get("track"),
                "spd": pl.get("spd"), "alt": pl.get("alt"), "category": pl.get("category"),
                "dbflags": pl.get("dbflags"), "trust": pl.get("trust"),
                "course": pl.get("course"), "emergency": pl.get("emergency")}
            tracksym.push_trail(self._trails, pl["id"], x, y)
        elif et == "alert" and src == "OVERWATCH" and pl.get("aos"):
            # the next real pass (OVERWATCH announces it on the bus; demo passes never are)
            self._next_pass = {"sat": pl.get("sat", "?"), "aos": pl["aos"]}
            self.mini_pass[1].setText(self._pass_text())
        elif et == "decode" and pl.get("kind") == "telemetry":
            self._telemetry(pl)
        elif et == "decode":
            self._decodes.insert(0, (src, pl.get("proto", ""), pl.get("summary", "")))
            self._decodes = self._decodes[:3]
            self._decode_times.append(ev["ts"])
            self._render_decodes()

    def _telemetry(self, pl):
        pass                        # battery: the strip's BAT slot (shell._on_bus)

    def _home_text(self):
        src = eventbus.HOME_SOURCE
        if not eventbus.home_set() and not self.demo:
            return "NOT SET"
        return {"gps": "GPS fix", "settings": "typed", "demo": "demo"}.get(src, src or "—")

    def side_changed(self, hidden):
        if hidden:
            self._hero.setMaximumWidth(16777215)
        else:
            self._fit_scope()

    def _fit_scope(self):
        if self.side_hidden():
            return
        side = self.ppi.height()
        if side > 0 and self._hero.maximumWidth() != max(360, side):
            self._hero.setMaximumWidth(max(360, side))

    def select_contact(self, cid):
        """B5: select a contact on the scope (click again to clear): violet ring + its label."""
        self._selected = None if cid == self._selected or cid not in self._contacts else cid
        self._refresh_ppi()

    def _refresh_ppi(self):
        now = time.time()
        live = [c for c in self._contacts.values() if now - c.get("_ts", 0) < STALE_S]
        self._contacts = {c["id"]: c for c in live}
        self._trails = {k: v for k, v in self._trails.items() if k in self._contacts}
        if self._selected not in self._contacts:
            self._selected = None
        frame = eventbus.home()
        if frame != getattr(self, "_frame", frame):
            # HOME moved (GPS follow, or SETTINGS): re-project what is known, restart the trails
            for c in live:
                if c.get("lat") is not None:
                    x, y = eventbus.to_xy(c["lat"], c["lon"])
                    c.update(x=x, y=y, rng=math.hypot(x, y))
            self._trails = {}
        self._frame = frame
        self.mini_pwr[1].setText(self._home_text())
        no_home = not self.demo and not eventbus.home_set()
        self._home_cover.show(no_home)               # N26: no rings from a guessed origin
        h = eventbus.home() or (self.demo and eventbus.DEMO_HOME) or None
        if h and not no_home:
            self.ppi.set_home(h[0], h[1])            # imagery under the scope (no-op if unchanged)
        self.ppi.set_contacts([] if no_home else live, selected=self._selected,
                              trails=self._trails)
        n = len(live)
        if n:
            self.big.setText(str(n))
            parts = []
            if self.demo:                 # H15: only demo tracks carry a military flag; live has
                parts.append("%d military (demo)" % sum(1 for c in live if c.get("mil")))
            if eventbus.home_set():       # H5: no range from a guessed HOME
                parts.append("nearest %.0f NM" % min(c.get("rng", 999) for c in live))
            else:
                parts.append("HOME NOT SET")
            self.sub.setText(" · ".join(parts))
        else:
            self.big.setText("0")
            self.sub.setText(self._empty_reason())       # owner 2026-11-18: say WHY it is empty
        if self._next_pass and self._next_pass["aos"] < now - 900:     # that pass is over
            self._next_pass = None
        self.mini_pass[1].setText(self._pass_text())

    def decode_rate(self, now=None):
        """H14: decodes actually received in the last 60 s (it was min(60, n * 6): one decode
        ever read "6/min")."""
        now = time.time() if now is None else now
        while self._decode_times and now - self._decode_times[0] > 60.0:
            self._decode_times.popleft()
        return len(self._decode_times)

    def _render_decodes(self):
        self.card_babel.clear_body()
        self.card_babel.set_note("%d in the last min" % self.decode_rate())
        for src, proto, summ in self._decodes:
            r = QtWidgets.QHBoxLayout()
            a = QtWidgets.QLabel(proto)
            a.setStyleSheet("color:%s;" % self._tok["text"])
            b = QtWidgets.QLabel(summ)
            b.setProperty("class", "note")
            r.addWidget(a)
            r.addStretch(1)
            r.addWidget(b)
            w = QtWidgets.QWidget()
            w.setLayout(r)
            self.card_babel.body.addWidget(w)

    def _render_alerts(self):
        """The newest alerts, unacknowledged first. Nothing scrolls away: the full history and the
        acknowledge action are in the alerts drawer (A). Severity is a word and a shape, not only a
        colour."""
        items = self._alert_store.items
        self.card_alert.clear_body()
        if not items:
            self.card_alert.standby("no alerts since launch")
            return
        n = self._alert_store.unacked()
        self.card_alert.set_note("%d unacknowledged" % n if n else "all acknowledged")
        sevc = {"alert": self._tok["alert"], "warn": self._tok["warn"],
                "info": self._tok["accent"], "live": self._tok["live"]}
        mark = {"alert": "■", "warn": "▲", "info": "●", "live": "●"}
        shown = sorted(items, key=lambda a: a["acked"])[:4]
        for a in shown:
            col = self._tok["muted"] if a["acked"] else sevc.get(a["severity"], self._tok["muted"])
            t = QtWidgets.QLabel("%s %s  %s · %s" % (mark.get(a["severity"], "●"),
                                                    a["severity"].upper(), a["text"], a["source"]))
            t.setProperty("class", "note")
            t.setWordWrap(True)
            t.setStyleSheet("color:%s;" % col)
            self.card_alert.body.addWidget(t)

    def primary_action(self):
        self.request.emit("open_panel", "alerts")
        return True

    def stop(self):
        try:
            eventbus.bus.published.disconnect(self._on_event)
        except (RuntimeError, TypeError):
            pass
        try:
            self._alert_store.changed.disconnect(self._render_alerts)
        except (RuntimeError, TypeError, AttributeError):
            pass
        if hasattr(self, "_prune"):
            self._prune.stop()
        if hasattr(self, "ppi"):
            self.ppi.stop()
        super().stop()
