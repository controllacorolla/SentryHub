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
from .kit import card, micro, DetailCard, FeedTable
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

        # left: the hero stat (the one glanceable number) + two small readouts
        self.hero = DetailCard("CONTACTS IN RANGE")
        self.hero.set_hero("—", "live across all feeds")
        self.hero.set_rows([("SoC TEMP", "—"), ("BATTERY", "—"), ("UPTIME", "0s")])
        grid.addWidget(self.hero, 0, 0, 2, 1)

        # center: the callsign grid
        nav = card(1)
        nl = QtWidgets.QVBoxLayout(nav)
        nl.setContentsMargins(12, 10, 12, 12)
        nl.addWidget(micro("Callsigns"))
        tiles = QtWidgets.QGridLayout()
        tiles.setSpacing(8)
        for i, (name, sub) in enumerate(CALLSIGNS):
            tiles.addWidget(self._tile(name, sub), i // 3, i % 3)
        nl.addLayout(tiles)
        grid.addWidget(nav, 0, 1, 1, 1)

        # bottom: live mini-feed
        self.feed = FeedTable([("time", "TIME"), ("src", "SRC"), ("id", "ID"), ("note", "")])
        grid.addWidget(self.feed, 1, 1, 1, 1)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 5)
        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 2)
        self._t0 = time.time()
        return body

    def _tile(self, name, sub):
        # QPushButton eats "&" as a mnemonic; escape it so "Hardware & IO" renders literally
        b = QtWidgets.QPushButton(("%s\n%s" % (name, sub)).replace("&", "&&"))
        b.setProperty("class", "tile")
        b.setMinimumHeight(52)
        b.clicked.connect(lambda: self.launch.emit(name))
        return b

    def make_worker(self):
        return OpsWorker(demo=True)

    def on_row(self, row):
        self.feed.model.prepend(row, cap=200)

    def on_status(self, status):
        super().on_status(status)
        self.hero.set_hero(status.get("contacts", "—"), "live across all feeds")
        up = int(time.time() - self._t0)
        self.hero.set_rows([
            ("SoC TEMP", "%.0f °C" % status.get("temp", 0)),
            ("BATTERY", "%d %%" % status.get("batt", 0)),
            ("UPTIME", "%dm %02ds" % (up // 60, up % 60)),
        ])
