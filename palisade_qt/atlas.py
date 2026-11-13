"""ATLAS — live map (archetype: map + contact list + telemetry).

Absorbs the geo apps (ADS-B/sky, AIS, APRS, dronewatch, DF). Built from the kit: StatusHeader,
MapPanel (range rings + contact scatter), FeedTable (contacts), DetailCard (selected telemetry).
The worker emits contacts with range/bearing to home; demo flies synthetic tracks, on-device it
binds to the existing feeds (unchanged).
"""
import math
import random
import time

from PySide6 import QtWidgets

from .app import PalisadeApp
from . import theme
from .kit import MapPanel, FeedTable, DetailCard
from .worker import Worker


class _Track:
    def __init__(self):
        self.cs = random.choice(["UAL", "ASA", "DAL", "N", "FDX"]) + str(random.randint(100, 980))
        self.r = random.uniform(10, 70)
        self.brg = random.uniform(0, 360)
        self.hdg = random.uniform(0, 360)
        self.spd = random.uniform(180, 480)
        self.alt = random.randint(80, 390) * 100

    def step(self, dt):
        # move along heading; wrap range so contacts stay on-scope
        self.brg = (self.brg + self.spd / 3600.0 * dt * 2) % 360
        self.r += math.sin(time.time() * 0.1) * 0.3
        self.r = max(5, min(78, self.r))

    def xy(self):
        a = math.radians(self.brg)
        return self.r * math.sin(a), self.r * math.cos(a)


class ContactWorker(Worker):
    def __init__(self, demo=True, parent=None):
        super().__init__(demo=demo, interval_ms=500, parent=parent)
        self.tracks = [_Track() for _ in range(12)]
        self._t = time.time()

    def step(self):
        now = time.time()
        dt, self._t = now - self._t, now
        rows = []
        for tk in self.tracks:
            tk.step(dt)
            x, y = tk.xy()
            rows.append({"cs": tk.cs, "id": tk.cs, "rng": "%.0f" % tk.r,
                         "brg": "%03d" % int(tk.brg), "alt": "%d" % tk.alt,
                         "spd": "%d" % int(tk.spd), "x": x, "y": y})
        self.row.emit(rows)


class AtlasApp(PalisadeApp):
    TITLE = "ATLAS"
    LEASE = "ATLAS"

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        split = QtWidgets.QHBoxLayout(body)
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(10)

        self.map = MapPanel(span_nm=80, mode=self.mode)
        split.addWidget(self.map, 3)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        self.feed = FeedTable([("cs", "CALLSIGN"), ("rng", "NM"), ("brg", "BRG"), ("alt", "ALT")])
        self.feed.selected.connect(self._show)
        right.addWidget(self.feed, 3)
        self.detail = DetailCard("CONTACT")
        self.detail.set_hero("—", "select a contact")
        right.addWidget(self.detail, 2)
        split.addLayout(right, 2)
        return body

    def make_worker(self):
        return ContactWorker(demo=self.demo)

    def on_row(self, rows):
        self.map.set_contacts([(r["x"], r["y"]) for r in rows],
                              labels=[r["cs"] for r in rows])
        for r in rows:
            rng = float(r["rng"])
            if rng < 20:
                c = self._tok["live"]
            elif rng < 50:
                c = self._tok["text"]
            else:
                c = self._tok["muted"]
            r["_colors"] = {"rng": c}
        self.feed.model.set_rows(sorted(rows, key=lambda r: float(r["rng"])))
        self.header.set_chip("sdr", "%d CONTACTS" % len(rows), ok=True)

    def _show(self, row):
        self.detail.set_hero(row.get("cs", "—"), "contact")
        self.detail.set_rows([("RANGE", row.get("rng", "") + " nm"),
                              ("BEARING", row.get("brg", "") + "°"),
                              ("ALTITUDE", row.get("alt", "") + " ft"),
                              ("SPEED", row.get("spd", "") + " kt")])
