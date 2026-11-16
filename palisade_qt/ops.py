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

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp
from . import theme, eventbus
from .kit import card, micro, PpiScope
from .kit.components import note
from .worker import Worker

# The eight page keys, in key order (1-8), each with the function label shown beside the callsign
# in the top strip (owner decision 2026-11-15, plan/audit/AUDIT_INDEX.md · D7). BABEL is folded into
# PROWL, OVERWATCH's sky views into ATLAS, BENCH into SYSTEM; SWEEP is promoted from RECON/COUNTER.
CALLSIGNS = [
    ("OPS", "home"), ("ATLAS", "map"), ("PRISM", "spectrum"), ("PROWL", "listen"),
    ("SWEEP", "sweep"), ("RECON", "survey"), ("FORGE", "hardware"),
    ("SYSTEM", "settings"),
]

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
                          "gps": {"text": "GPS 9 SV", "state": "neutral"},
                          "pwr": {"text": "PWR %d%%" % batt,
                                  "state": "alert" if batt <= 10 else "warn" if batt <= 20
                                  else "neutral"}})


class LiveStatusWorker(Worker):
    """Live mode: publish only real device telemetry; backends publish their own feeds."""

    def __init__(self, parent=None):
        super().__init__(demo=False, interval_ms=2000, parent=parent)

    def step(self):
        temp = _read_cpu_temp()
        batt = _read_battery()
        sdr_ok = os.path.exists("/dev/swradio0") or os.path.exists("/dev/rtlsdr0")
        eventbus.bus.publish(eventbus.make_event("decode", "OPS", {
            "kind": "telemetry", "temp": temp, "batt": batt,
            "gps": _read_gps_sats()}, severity="info"))
        self.status.emit({
            "sdr": {"text": "SDR OK" if sdr_ok else "SDR —",
                    "state": "live" if sdr_ok else "neutral"},
            "pwr": {"text": "PWR %d%%" % batt if batt is not None else "PWR —",
                    "state": ("alert" if batt is not None and batt <= 10
                              else "warn" if batt is not None and batt <= 20 else "neutral")}})


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

        body = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        # hero: situation + PPI scope
        hero = QtWidgets.QWidget()
        hv = QtWidgets.QVBoxLayout(hero)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(8)
        hhead = QtWidgets.QHBoxLayout()
        hhead.addWidget(micro("Situation · all feeds"))
        hhead.addStretch(1)
        hv.addLayout(hhead)
        stat = QtWidgets.QHBoxLayout()
        self.big = QtWidgets.QLabel("—")
        self.big.setProperty("class", "hero")
        stat.addWidget(self.big)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(micro("Contacts live"))
        self.sub = QtWidgets.QLabel("standby")
        self.sub.setProperty("class", "note")
        col.addWidget(self.sub)
        stat.addLayout(col)
        stat.addStretch(1)
        hv.addLayout(stat)
        self.ppi = PpiScope(span_nm=80, mode=self.mode)
        hv.addWidget(self.ppi, 1)
        row.addWidget(hero, 1)
        # the scope is round: keep its column only as wide as it is tall, and give the rest of
        # the width to the rail instead of a dead well either side (D3 / RA-CL1)
        self._hero = hero
        self.ppi.resized.connect(self._fit_scope)

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
        self.card_alert = RailCard("ALERTS · press A for history + acknowledge", self.mode)
        rv.addWidget(self.card_alert, 1)
        two = QtWidgets.QHBoxLayout()
        two.setSpacing(9)
        self.mini_pass = self._mini("NEXT PASS", "—")
        self.mini_pwr = self._mini("POWER", "—")
        two.addWidget(self.mini_pass[0])
        two.addWidget(self.mini_pwr[0])
        rv.addLayout(two)
        row.addWidget(rail)

        eventbus.bus.published.connect(self._on_event)
        from . import panels
        self._alert_store = panels.alert_store()          # history kept until acknowledged (D10)
        self._alert_store.changed.connect(self._render_alerts)
        self._render_alerts()
        self._prune = QtCore.QTimer(self)
        self._prune.timeout.connect(self._refresh_ppi)
        self._prune.start(700)
        return body

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
                "id": pl["id"], "x": x, "y": y, "label": pl.get("label", pl["id"]),
                "severity": ev["severity"], "_ts": ev["ts"], "rng": math.hypot(x, y),
                "mil": pl.get("mil", False)}
        elif et == "decode" and pl.get("kind") == "telemetry":
            self._telemetry(pl)
        elif et == "decode":
            self._decodes.insert(0, (src, pl.get("proto", ""), pl.get("summary", "")))
            self._decodes = self._decodes[:3]
            self._render_decodes()

    def _telemetry(self, pl):
        batt = pl.get("batt")
        if batt is not None:
            self.mini_pwr[1].setText("%d%%" % batt)

    def _fit_scope(self):
        side = self.ppi.height()
        if side > 0 and self._hero.maximumWidth() != max(360, side):
            self._hero.setMaximumWidth(max(360, side))

    def _refresh_ppi(self):
        now = time.time()
        live = [c for c in self._contacts.values() if now - c.get("_ts", 0) < STALE_S]
        self._contacts = {c["id"]: c for c in live}
        if self._selected not in self._contacts:
            self._selected = None
        self.ppi.set_contacts(live, selected=self._selected)
        n = len(live)
        mil = sum(1 for c in live if c.get("mil"))
        if n:
            nearest = min(c.get("rng", 999) for c in live)
            self.big.setText(str(n))
            self.sub.setText("%d military · nearest %.0f NM" % (mil, nearest))
        else:
            self.big.setText("0")
            self.sub.setText("no contacts" if not self.demo else "standby")

    def _render_decodes(self):
        self.card_babel.clear_body()
        self.card_babel.set_note("%d/min" % min(60, len(self._decodes) * 6))
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
