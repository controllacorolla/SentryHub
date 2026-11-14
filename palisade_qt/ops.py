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
from .worker import Worker

# callsigns + nav grouping (the shell builds the rail from GROUPS)
CALLSIGNS = [
    ("OPS", "Situational home"), ("OVERWATCH", "Sky dome + autopilot"),
    ("ATLAS", "Live map"), ("BABEL", "Universal decoder"),
    ("PRISM", "Spectrum + waterfall"), ("PROWL", "Scanner / tuner"),
    ("FORGE", "Hardware & IO bench"), ("RECON", "Network + RF survey"),
    ("BENCH", "Conducted TX self-test"),
]
GROUPS = [("OVERVIEW", ["OPS", "OVERWATCH"]),
          ("SENSE", ["ATLAS", "BABEL", "PRISM", "PROWL"]),
          ("FIELD", ["FORGE", "RECON", "BENCH"])]

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
                                                 "%04X" % random.randint(0x1000, 0xFFFF), summ))
        if random.random() < 0.12:
            kind, sev, src = random.choice([
                ("Drone Remote-ID", "alert", "ATLAS"),
                ("Open AP · linksys", "warn", "RECON"),
                ("MIL contact inbound", "info", "ATLAS")])
            eventbus.bus.publish(eventbus.alert(src, kind, severity=sev))
        batt = max(5, 96 - (now - self._t0) * 0.02)
        eventbus.bus.publish(eventbus.make_event("decode", "OPS", {
            "kind": "telemetry", "temp": 62 + 3 * math.sin((now - self._t0) * 0.1),
            "batt": batt, "gps": 9}, severity="info"))
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
        self.note.setProperty("class", "micro")
        head.addWidget(self.note)
        v.addLayout(head)
        self.body = QtWidgets.QVBoxLayout()
        self.body.setSpacing(3)
        v.addLayout(self.body)
        v.addStretch(1)
        self._standby = QtWidgets.QLabel("STANDBY · no feed")
        self._standby.setProperty("class", "micro")
        self.body.addWidget(self._standby)
        self._live = False

    def set_note(self, text):
        self.note.setText(text)

    def clear_body(self):
        while self.body.count():
            it = self.body.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def standby(self, msg="STANDBY · no feed"):
        self.clear_body()
        lbl = QtWidgets.QLabel(msg)
        lbl.setProperty("class", "micro")
        self.body.addWidget(lbl)
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
        self._alerts = []

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
        tick = QtWidgets.QLabel("◆")
        tick.setProperty("class", "accent")
        tick.setStyleSheet("font-size:8px;")
        hhead.addWidget(tick)
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
        self.sub.setProperty("class", "micro")
        col.addWidget(self.sub)
        stat.addLayout(col)
        stat.addStretch(1)
        hv.addLayout(stat)
        self.ppi = PpiScope(span_nm=80, mode=self.mode)
        hv.addWidget(self.ppi, 1)
        row.addWidget(hero, 1)

        # rail: PRISM / BABEL / ALERTS / minis
        rail = QtWidgets.QWidget()
        rail.setFixedWidth(372)
        rv = QtWidgets.QVBoxLayout(rail)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(9)
        self.card_prism = RailCard("PRISM · SPECTRUM", self.mode)
        self.card_prism.standby("PRISM offline · open PRISM")
        rv.addWidget(self.card_prism)
        self.card_babel = RailCard("BABEL · LATEST DECODES", self.mode)
        rv.addWidget(self.card_babel, 1)
        self.card_alert = RailCard("ALERTS · EVENT BUS", self.mode)
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
        val.setStyleSheet("font-size:15px;")
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
        elif et == "alert":
            self._alerts.insert(0, (src, ev["severity"], pl.get("text", "")))
            self._alerts = self._alerts[:3]
            self._render_alerts()

    def _telemetry(self, pl):
        batt = pl.get("batt")
        if batt is not None:
            self.mini_pwr[1].setText("%d%%" % batt)

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
            b.setProperty("class", "micro")
            r.addWidget(a)
            r.addStretch(1)
            r.addWidget(b)
            w = QtWidgets.QWidget()
            w.setLayout(r)
            self.card_babel.body.addWidget(w)

    def _render_alerts(self):
        self.card_alert.clear_body()
        self.card_alert.set_note("%d new" % len(self._alerts))
        sevc = {"alert": self._tok["alert"], "warn": self._tok["warn"],
                "info": self._tok["accent"], "live": self._tok["live"]}
        for src, sev, text in self._alerts:
            r = QtWidgets.QHBoxLayout()
            dot = QtWidgets.QLabel("●")
            dot.setStyleSheet("color:%s; font-size:9px;" % sevc.get(sev, self._tok["muted"]))
            t = QtWidgets.QLabel(text)
            s = QtWidgets.QLabel(src)
            s.setProperty("class", "micro")
            r.addWidget(dot)
            r.addWidget(t)
            r.addStretch(1)
            r.addWidget(s)
            w = QtWidgets.QWidget()
            w.setLayout(r)
            self.card_alert.body.addWidget(w)

    def stop(self):
        try:
            eventbus.bus.published.disconnect(self._on_event)
        except (RuntimeError, TypeError):
            pass
        if hasattr(self, "_prune"):
            self._prune.stop()
        if hasattr(self, "ppi"):
            self.ppi.stop()
        super().stop()
