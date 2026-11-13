"""OPS — the situational home (also the first screen that proves the kit + shell + embedding).

Composed entirely from kit components: status header, a hero stat card, a callsign grid, and a
live mini-feed. In demo mode a Worker emits synthetic status + contacts so the screen is alive
without hardware.
"""
import math
import random
import time

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp
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
    """Synthetic situational feed: a drifting contact count, temperature, battery, and events."""

    def __init__(self, demo=True, parent=None):
        super().__init__(demo=demo, interval_ms=700, parent=parent)
        self._t0 = time.time()
        self._n = 0

    def step(self):
        t = time.time() - self._t0
        self._n += 1
        contacts = int(18 + 6 * math.sin(t * 0.2) + random.randint(0, 2))
        temp = 62 + 3 * math.sin(t * 0.1)
        batt = max(5, 96 - t * 0.02)
        self.status.emit({
            "contacts": contacts, "temp": temp, "batt": batt,
            "sdr": {"text": "SDR DEMO", "ok": True},
            "gps": {"text": "GPS 9", "ok": True},
            "pwr": {"text": "PWR %d%%" % batt, "ok": batt > 20},
        })
        kinds = ["ADS-B", "AIS", "APRS", "POCSAG", "ACARS", "ADS-B", "RDS"]
        self.row.emit({
            "time": time.strftime("%H:%M:%S"),
            "src": random.choice(kinds),
            "id": "%04X" % random.randint(0x1000, 0xFFFF),
            "note": random.choice(["new", "update", "alert", "faded"]),
        })


class OpsHome(PalisadeApp):
    TITLE = "OPS"
    LEASE = None                 # the home screen doesn't hold the radio

    launch = QtCore.Signal(str)  # a callsign tile was pressed

    def build_body(self):
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
        for name, sub in CALLSIGNS[1:]:
            nl.addWidget(self._tile(name, sub))
        grid.addWidget(nav, 1, 1, 1, 1)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 5)
        grid.setRowStretch(0, 4)
        grid.setRowStretch(1, 1)
        self._t0 = time.time()
        return body

    def _tile(self, name, sub):
        b = QtWidgets.QPushButton(name)
        b.setProperty("class", "tile")
        b.setMinimumHeight(40)
        b.setToolTip(sub)
        b.clicked.connect(lambda: self.launch.emit(name))
        return b

    def make_worker(self):
        return OpsWorker(demo=True)

    def on_row(self, row):
        self.feed.model.prepend(row, cap=200)
        self._show_event(row)

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
