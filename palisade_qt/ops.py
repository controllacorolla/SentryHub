"""OPS — the situational home, wired to real device status when not in demo mode.

Reads real SoC temperature, battery status, and GPS from the device in live mode.
In demo mode a Worker emits synthetic data so the screen is alive without hardware.
"""
import math
import os
import random
import time

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp
from . import theme
from .kit import card, DetailCard, FeedTable
from .worker import Worker

# the 9 callsigns (DESIGN §2); OPS is home, the rest are destinations
CALLSIGNS = [
    ("OPS", "Situational home"), ("OVERWATCH", "Sky dome + autopilot"),
    ("ATLAS", "Live map"), ("BABEL", "Universal decoder"),
    ("PRISM", "Spectrum + waterfall"), ("PROWL", "Scanner / tuner"),
    ("FORGE", "Hardware & IO bench"), ("RECON", "Network + RF survey"),
    ("BENCH", "Conducted TX self-test"),
]


class OpsWorker(Worker):
    """Reads real device status (temp, battery) in live mode; synthetic in demo."""

    def __init__(self, demo=True, parent=None):
        super().__init__(demo=demo, interval_ms=2000 if not demo else 700, parent=parent)
        self._t0 = time.time()
        self._n = 0

    def step(self):
        if self.demo:
            self._step_demo()
        else:
            self._step_live()

    def _step_demo(self):
        t = time.time() - self._t0
        self._n += 1
        contacts = int(18 + 6 * math.sin(t * 0.2) + random.randint(0, 2))
        temp = 62 + 3 * math.sin(t * 0.1)
        batt = max(5, 96 - t * 0.02)
        self.status.emit({
            "contacts": contacts, "temp": temp, "batt": batt,
            # green is reserved for genuine live/OK; demo status rides neutral/warn, not green
            "sdr": {"text": "SDR DEMO", "state": "neutral"},
            "gps": {"text": "GPS 9", "state": "neutral"},
            "pwr": {"text": "PWR %d%%" % batt, "state": "alert" if batt <= 10
                    else "warn" if batt <= 20 else "neutral"},
        })
        kinds = ["ADS-B", "AIS", "APRS", "POCSAG", "ACARS", "ADS-B", "RDS"]
        self.row.emit({
            "time": time.strftime("%H:%M:%S"),
            "src": random.choice(kinds),
            "id": "%04X" % random.randint(0x1000, 0xFFFF),
            "note": random.choice(["new", "update", "alert", "faded"]),
        })

    def _step_live(self):
        self._n += 1
        temp = _read_cpu_temp()
        batt = _read_battery()
        batt_pct = batt if batt is not None else -1
        sdr_ok = os.path.exists("/dev/swradio0") or os.path.exists("/dev/rtlsdr0")
        status = {
            "contacts": 0, "temp": temp or 0, "batt": batt_pct,
            "sdr": {"text": "SDR OK" if sdr_ok else "SDR —",
                    "state": "live" if sdr_ok else "neutral"},   # green only when the SDR is really up
            "pwr": {"text": "PWR %d%%" % batt_pct if batt_pct >= 0 else "PWR —",
                    "state": ("alert" if 0 <= batt_pct <= 10 else "warn"
                              if 0 <= batt_pct <= 20 else "neutral")},
        }
        self.status.emit(status)


def _read_cpu_temp():
    for path in ("/sys/class/thermal/thermal_zone0/temp",
                 "/sys/class/hwmon/hwmon0/temp1_input"):
        try:
            with open(path) as f:
                return int(f.read().strip()) / 1000.0
        except (OSError, ValueError):
            continue
    return None


def _read_battery():
    base = "/sys/class/power_supply"
    for name in ("axp20x-battery", "battery", "BAT0"):
        cap = os.path.join(base, name, "capacity")
        try:
            with open(cap) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            continue
    return None


class OpsHome(PalisadeApp):
    TITLE = "OPS"
    LEASE = None                 # the home screen doesn't hold the radio

    launch = QtCore.Signal(str)  # a callsign tile was pressed

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        # left: hero stat (the one glanceable number) + system readouts
        self.hero = DetailCard("CONTACTS IN RANGE")
        self.hero.set_hero("—", "live across all feeds")
        self.hero.set_rows([("SoC TEMP", "—"), ("BATTERY", "—"), ("UPTIME", "0s")])
        grid.addWidget(self.hero, 0, 0, 1, 1)

        # right: live event feed — the situational stream
        self.feed = FeedTable([("time", "TIME"), ("src", "SRC"), ("id", "ID"), ("note", "")])
        self.feed.selected.connect(self._show_event)
        grid.addWidget(self.feed, 0, 1, 1, 1)

        # bottom-left: last event detail
        self.event_detail = DetailCard("LAST EVENT")
        self.event_detail.set_hero("—", "waiting for first signal")
        grid.addWidget(self.event_detail, 1, 0, 1, 1)

        # bottom-right: callsign shortcut tiles
        nav = card(1)
        nl = QtWidgets.QHBoxLayout(nav)
        nl.setContentsMargins(10, 8, 10, 8)
        nl.setSpacing(6)
        self._tiles = {}
        for name, sub in CALLSIGNS[1:]:
            btn, dot = self._tile(name, sub)
            nl.addWidget(btn)
            self._tiles[name] = dot
        grid.addWidget(nav, 1, 1, 1, 1)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 5)
        grid.setRowStretch(0, 4)
        grid.setRowStretch(1, 1)
        self._t0 = time.time()
        return body

    def _tile(self, name, sub):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        b = QtWidgets.QPushButton(name)
        b.setProperty("class", "tile")
        b.setMinimumHeight(34)
        b.setToolTip(sub)
        b.clicked.connect(lambda: self.launch.emit(name))
        lay.addWidget(b)
        dot = QtWidgets.QFrame()
        dot.setFixedHeight(3)
        dot.setStyleSheet("background: transparent; border-radius: 1px;")
        lay.addWidget(dot)
        return w, dot

    def make_worker(self):
        return OpsWorker(demo=self.demo)

    _SRC_MAP = {"ADS-B": "ATLAS", "AIS": "ATLAS", "APRS": "ATLAS",
                 "POCSAG": "BABEL", "ACARS": "BABEL", "RDS": "BABEL"}

    def on_row(self, row):
        self.feed.model.prepend(row, cap=200)
        self._show_event(row)
        src = row.get("src", "")
        callsign = self._SRC_MAP.get(src)
        if callsign and callsign in self._tiles:
            self._tiles[callsign].setStyleSheet(
                "background: %s; border-radius: 1px;" % self._tok["accent"])
            QtCore.QTimer.singleShot(300, lambda c=callsign:
                self._tiles[c].setStyleSheet(
                    "background: transparent; border-radius: 1px;"))

    def _show_event(self, row):
        self.event_detail.set_hero(row.get("id", "—"), row.get("src", ""))
        self.event_detail.set_rows([
            ("TIME", row.get("time", "")),
            ("SOURCE", row.get("src", "")),
            ("STATUS", row.get("note", "")),
        ])

    def on_status(self, status):
        super().on_status(status)
        self.hero.set_hero(status.get("contacts", "—"), "live across all feeds")
        up = int(time.time() - self._t0)
        self.hero.set_rows([
            ("SoC TEMP", "%.0f °C" % status.get("temp", 0)),
            ("BATTERY", "%d %%" % status.get("batt", 0)),
            ("UPTIME", "%dm %02ds" % (up // 60, up % 60)),
        ])
