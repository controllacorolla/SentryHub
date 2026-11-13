"""OVERWATCH, RECON, BENCH — the remaining callsigns as kit compositions.

Kept lean on purpose: each proves its archetype shape and opens as an embedded Qt page. Real
per-module engine wiring happens in the per-cluster sweep; this is UI-only scaffolding with
demo feeds, like the other archetypes.
"""
import random
import time

from PySide6 import QtWidgets

from .app import PalisadeApp
from .kit import MapPanel, FeedTable, DetailCard, EmptyState, ControlBar, micro
from .worker import Worker


# ---- OVERWATCH: sky dome + autopilot (map archetype) ----
class _DomeWorker(Worker):
    def __init__(self, demo=True, parent=None):
        super().__init__(demo=demo, interval_ms=600, parent=parent)
        self.objs = [{"el": random.uniform(5, 80), "az": random.uniform(0, 360),
                      "name": n} for n in ("ISS", "NOAA-19", "GOES", "Sun", "Moon")]

    def step(self):
        pts = []
        for o in self.objs:
            o["az"] = (o["az"] + random.uniform(-2, 2)) % 360
            import math
            r = (90 - o["el"]) / 90 * 78
            a = math.radians(o["az"])
            pts.append({"name": o["name"], "x": r * math.sin(a), "y": r * math.cos(a),
                        "el": "%.0f" % o["el"], "az": "%03d" % int(o["az"])})
        self.row.emit(pts)


class OverwatchApp(PalisadeApp):
    TITLE = "OVERWATCH"
    LEASE = "OVERWATCH"

    def build_body(self):
        body = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.dome = MapPanel(span_nm=90, mode=self.mode)
        lay.addWidget(self.dome, 3)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        self.feed = FeedTable([("name", "OBJECT"), ("el", "EL"), ("az", "AZ")])
        self.feed.selected.connect(self._show)
        right.addWidget(self.feed, 2)
        self.detail = DetailCard("OBJECT")
        self.detail.set_hero("—", "select an object")
        right.addWidget(self.detail, 1)
        lay.addLayout(right, 2)
        return body

    def make_worker(self):
        return _DomeWorker(demo=self.demo)

    def on_row(self, pts):
        self.dome.set_contacts([(p["x"], p["y"]) for p in pts])
        self.feed.model.set_rows(sorted(pts, key=lambda p: -float(p["el"])))

    def _show(self, row):
        self.detail.set_hero(row.get("name", "—"), "tracked object")
        self.detail.set_rows([("ELEVATION", row.get("el", "") + "°"),
                              ("AZIMUTH", row.get("az", "") + "°")])


# ---- RECON: network + RF survey (decoder-feed archetype) ----
class _SurveyWorker(Worker):
    def step(self):
        rows = []
        for _ in range(random.randint(4, 9)):
            rows.append({"bssid": ":".join("%02X" % random.randint(0, 255) for _ in range(6)),
                         "ssid": random.choice(["home-5G", "cafe-wifi", "<hidden>", "GuestNet"]),
                         "ch": random.choice([1, 6, 11, 36, 44, 149]),
                         "sig": random.randint(-85, -40),
                         "sec": random.choice(["WPA2", "WPA3", "open", "WPA2"])})
        self.row.emit(rows)


class ReconApp(PalisadeApp):
    TITLE = "RECON"
    LEASE = None

    def build_body(self):
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        bar = ControlBar()
        bar.add_field("iface", self._iface(), "Interface")
        bar.add_stretch()
        bar.lay.addWidget(micro("Passive · no deauth/inject"))
        lay.addWidget(bar)
        self.feed = FeedTable([("ssid", "SSID"), ("bssid", "BSSID"),
                               ("ch", "CH"), ("sig", "dBm"), ("sec", "SEC")])
        lay.addWidget(self.feed, 1)
        return body

    def _iface(self):
        c = QtWidgets.QComboBox()
        c.addItems(["wlan0 (demo)", "wlan1", "mon0"])
        return c

    def make_worker(self):
        return _SurveyWorker(demo=self.demo, interval_ms=1500)

    def on_row(self, rows):
        self.feed.model.set_rows(sorted(rows, key=lambda r: -int(r["sig"])))
        self.header.set_chip("sdr", "%d APs" % len(rows), ok=True)


# ---- BENCH: conducted TX self-test, txguard-gated (status archetype, NO OTA) ----
class BenchApp(PalisadeApp):
    TITLE = "BENCH"
    LEASE = None

    def build_body(self):
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        bar = ControlBar()
        bar.add_stretch()
        bar.lay.addWidget(micro("Gate"))
        self.gate = QtWidgets.QLabel("TX SAFE · conducted-only")
        self.gate.setProperty("class", "value live")
        bar.lay.addWidget(self.gate)
        self.run = bar.add_button("Run self-test", self._run)
        lay.addWidget(bar)

        self.card = DetailCard("LOOPBACK SELF-TEST")
        self.card.set_hero("—", "conducted into a load — no antenna, no OTA")
        self.card.set_rows([("TXGUARD", "conducted path only"), ("RESULT", "idle")])
        lay.addWidget(self.card, 1)
        self.empty = EmptyState("CONDUCTED BENCH", "txguard permits conducted self-test only; "
                                "protected bands and OTA transmit stay denied")
        lay.addWidget(self.empty, 1)
        return body

    def _run(self):
        # demo: a synthetic conducted loopback measurement. No transmit path is exercised here;
        # the real bench routes through txguard's conducted gate and loopback engine.
        snr = random.uniform(28, 42)
        self.card.set_hero("%.1f dB" % snr, "conducted loopback SNR (demo)")
        self.card.set_rows([("TXGUARD", "conducted path only"),
                            ("RESULT", "PASS" if snr > 25 else "LOW"),
                            ("AT", time.strftime("%H:%M:%S"))])
