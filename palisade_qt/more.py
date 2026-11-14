"""OVERWATCH, RECON, BENCH — wired to real engines where applicable.

OVERWATCH: sky dome using overwatch.sky_objects() + astro ephemeris for Sun/Moon/sats.
RECON: passive Wi-Fi survey using wifisurvey.parse_iw_scan() on `iw dev scan`.
BENCH: conducted TX self-test (txguard-gated, no OTA) — stays demo-only by design.
"""
import math
import os
import random
import shutil
import subprocess
import sys
import time

from PySide6 import QtWidgets

from .app import PalisadeApp
from .kit import MapPanel, FeedTable, DetailCard, EmptyState, ControlBar, micro
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


# ---- OVERWATCH: sky dome + autopilot (map archetype) ----
class _DomeWorker(Worker):
    def __init__(self, demo=True, parent=None):
        super().__init__(demo=demo, interval_ms=600, parent=parent)
        if demo:
            self.objs = [{"el": random.uniform(5, 80), "az": random.uniform(0, 360),
                          "name": n} for n in ("ISS", "NOAA-19", "GOES", "Sun", "Moon")]

    def step(self):
        if self.demo:
            self._step_demo()
        else:
            self._step_live()

    def _step_demo(self):
        pts = []
        for o in self.objs:
            o["az"] = (o["az"] + random.uniform(-2, 2)) % 360
            r = (90 - o["el"]) / 90 * 78
            a = math.radians(o["az"])
            pts.append({"name": o["name"], "x": r * math.sin(a), "y": r * math.cos(a),
                        "el": "%.0f" % o["el"], "az": "%03d" % int(o["az"])})
        self.row.emit(pts)

    def _step_live(self):
        try:
            import overwatch as ow
            import json
            cfg = os.path.join(os.path.expanduser("~"), ".config", "uconsole-suite")
            try:
                with open(os.path.join(cfg, "overwatch.json")) as f:
                    s = json.load(f)
            except (OSError, ValueError):
                s = ow.DEFAULTS
            home_d = s.get("home", ow.DEFAULTS["home"])
            home = (home_d["lat"], home_d["lon"], home_d.get("alt_m", 0))

            pts = []
            now = time.time()
            try:
                az, el = ow.sun_azel(home[0], home[1], home[2], now)
                if el > -5:
                    r = (90 - max(0, el)) / 90 * 78
                    a = math.radians(az)
                    pts.append({"name": "Sun", "x": r * math.sin(a), "y": r * math.cos(a),
                                "el": "%.0f" % el, "az": "%03d" % int(az)})
            except Exception:
                pass
            try:
                az, el = ow.moon_azel(home[0], home[1], home[2], now)
                if el > -5:
                    r = (90 - max(0, el)) / 90 * 78
                    a = math.radians(az)
                    pts.append({"name": "Moon", "x": r * math.sin(a), "y": r * math.cos(a),
                                "el": "%.0f" % el, "az": "%03d" % int(az)})
            except Exception:
                pass

            self.row.emit(pts)
            if pts:
                self.status.emit({"sdr": {"text": "%d SKY" % len(pts), "ok": True}})
        except ImportError:
            self._step_demo()


class OverwatchApp(PalisadeApp):
    TITLE = "OVERWATCH"
    LEASE = "OVERWATCH"

    def build_body(self):
        from . import theme
        self._tok = theme.tokens(self.mode)
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
        self._selected = False
        return body

    def make_worker(self):
        return _DomeWorker(demo=self.demo)

    def on_row(self, pts):
        self.dome.set_contacts([(p["x"], p["y"]) for p in pts],
                               labels=[p["name"] for p in pts])
        ranked = sorted(pts, key=lambda p: -float(p["el"]))
        for p in ranked:
            el = float(p["el"])
            if el > 45:
                c = self._tok["live"]
            elif el > 15:
                c = self._tok["text"]
            else:
                c = self._tok["muted"]
            p["_colors"] = {"el": c}
        self.feed.model.set_rows(ranked)
        self.header.set_chip("sdr", "%d OBJECTS" % len(pts), state="neutral")
        if not self._selected and ranked:
            self._show(ranked[0])

    def _show(self, row):
        self._selected = True
        self.detail.set_hero(row.get("name", "—"), "tracked object")
        self.detail.set_rows([("ELEVATION", row.get("el", "") + "°"),
                              ("AZIMUTH", row.get("az", "") + "°")])


# ---- RECON: passive Wi-Fi survey wired to wifisurvey engine ----
class _SurveyWorker(Worker):
    def __init__(self, demo=True, iface="wlan0", interval_ms=15000, parent=None):
        super().__init__(demo=demo, interval_ms=interval_ms, parent=parent)
        self.iface = iface

    def step(self):
        if self.demo:
            self._step_demo()
        else:
            self._step_live()

    def _step_demo(self):
        rows = []
        for _ in range(random.randint(4, 9)):
            rows.append({"bssid": ":".join("%02X" % random.randint(0, 255) for _ in range(6)),
                         "ssid": random.choice(["home-5G", "cafe-wifi", "<hidden>", "GuestNet"]),
                         "ch": random.choice([1, 6, 11, 36, 44, 149]),
                         "sig": random.randint(-85, -40),
                         "sec": random.choice(["WPA2", "WPA3", "open", "WPA2"])})
        self.row.emit(rows)

    def _step_live(self):
        try:
            import wifisurvey as engine
        except ImportError:
            self._step_demo()
            return
        if not shutil.which("iw"):
            self.status.emit({"sdr": {"text": "iw not found", "ok": False}})
            self._step_demo()
            return
        try:
            result = subprocess.run(["iw", "dev", self.iface, "scan"],
                                    capture_output=True, text=True, timeout=20)
            aps = engine.parse_iw_scan(result.stdout)
        except subprocess.TimeoutExpired:
            self.status.emit({"sdr": {"text": "scan timeout", "ok": False}})
            return
        except Exception as e:
            self.error.emit("iw scan: %s" % str(e)[:100])
            return
        rows = []
        for a in aps:
            rows.append({"bssid": a.get("bssid", ""),
                         "ssid": a.get("ssid") or "<hidden>",
                         "ch": a.get("channel") or "?",
                         "sig": int(a.get("signal") or -99),
                         "sec": a.get("security", "?")})
        self.row.emit(rows)
        self.status.emit({"sdr": {"text": "%d APs" % len(rows), "ok": True}})


class ReconApp(PalisadeApp):
    TITLE = "RECON"
    LEASE = None

    def build_body(self):
        from . import theme
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        bar = ControlBar()
        self._iface_combo = QtWidgets.QComboBox()
        self._iface_combo.addItems(self._detect_ifaces())
        bar.add_field("iface", self._iface_combo, "Interface")
        bar.add_stretch()
        bar.lay.addWidget(micro("Passive · no deauth/inject"))
        lay.addWidget(bar)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        self.feed = FeedTable([("ssid", "SSID"), ("bssid", "BSSID"),
                               ("ch", "CH"), ("sig", "dBm"), ("sec", "SEC")])
        self.feed.selected.connect(self._show)
        split.addWidget(self.feed, 3)
        self.detail = DetailCard("ACCESS POINT")
        self.detail.set_hero("—", "select an AP")
        split.addWidget(self.detail, 1)
        lay.addLayout(split, 1)
        return body

    def _detect_ifaces(self):
        """List available wireless interfaces, falling back to defaults."""
        try:
            devs = os.listdir("/sys/class/net")
            wireless = [d for d in devs if os.path.isdir(
                os.path.join("/sys/class/net", d, "wireless"))]
            if wireless:
                return sorted(wireless)
        except OSError:
            pass
        return ["wlan0"]

    def make_worker(self):
        iface = self._iface_combo.currentText()
        return _SurveyWorker(demo=self.demo, iface=iface, interval_ms=15000)

    def on_row(self, rows):
        open_count = 0
        for r in rows:
            sig = int(r["sig"])
            if sig > -50:
                c = self._tok["live"]
            elif sig > -70:
                c = self._tok["warn"]
            else:
                c = self._tok["muted"]
            r["_colors"] = {"sig": c}
            if r.get("sec") == "open":
                r["_colors"]["sec"] = self._tok["warn"]
                open_count += 1
        self.feed.model.set_rows(sorted(rows, key=lambda r: -int(r["sig"])))
        chip = "%d APs" % len(rows)
        if open_count:
            chip += " · %d OPEN" % open_count
        self.header.set_chip("sdr", chip, state="warn" if open_count else "neutral")

    def _show(self, row):
        self.detail.set_hero(row.get("ssid", "—"), "wireless network")
        self.detail.set_rows([
            ("BSSID", row.get("bssid", "")),
            ("CHANNEL", str(row.get("ch", ""))),
            ("SIGNAL", str(row.get("sig", "")) + " dBm"),
            ("SECURITY", row.get("sec", "")),
        ])


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

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        self.card = DetailCard("LOOPBACK SELF-TEST")
        self.card.set_hero("—", "conducted into a load — no antenna, no OTA")
        self.card.set_rows([("TXGUARD", "conducted path only"), ("RESULT", "idle")])
        split.addWidget(self.card, 2)
        self.empty = EmptyState("CONDUCTED BENCH", "txguard permits conducted self-test only; "
                                "protected bands and OTA transmit stay denied")
        split.addWidget(self.empty, 3)
        lay.addLayout(split, 1)
        return body

    def _run(self):
        snr = random.uniform(28, 42)
        freq_err = random.uniform(-0.8, 0.8)
        ber = random.uniform(0, 0.003)
        self.card.set_hero("%.1f dB" % snr, "conducted loopback SNR (demo)")
        result = "PASS" if (snr > 25 and ber < 0.005) else "LOW"
        self.card.set_rows([("TXGUARD", "conducted path only"),
                            ("RESULT", result),
                            ("FREQ ERROR", "%.2f ppm" % freq_err),
                            ("BIT ERR RATE", "%.4f" % ber),
                            ("AT", time.strftime("%H:%M:%S"))])
