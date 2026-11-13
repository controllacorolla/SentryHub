"""PROWL — scanner / tuner (archetype: channel list + tuner + squelch).

Absorbs scanner, fm, freqdb. Built from the kit: StatusHeader, ControlBar (squelch + scan/hold),
FeedTable (channels with last-heard + signal), a signal/active readout. The worker reports which
channel is active and its level; demo synthesises hits, on-device it drives the scanner engine.
"""
import random
import time

from PySide6 import QtWidgets

from .app import PalisadeApp
from . import theme
from .kit import ControlBar, FeedTable, DetailCard, micro
from .worker import Worker

CHANNELS = [
    ("162.400", "NOAA WX1"), ("154.265", "Fire Disp"), ("155.340", "EMS"),
    ("121.500", "Aircraft Guard"), ("146.520", "2m Call"), ("462.5625", "FRS 1"),
    ("453.212", "City PD"), ("159.480", "Rail"),
]


class ScanWorker(Worker):
    def __init__(self, demo=True, squelch=-70, parent=None):
        super().__init__(demo=demo, interval_ms=350, parent=parent)
        self.squelch = squelch

    def step(self):
        rows = []
        active = None
        for freq, label in CHANNELS:
            hot = random.random() < 0.12
            sig = random.randint(-55, -35) if hot else random.randint(-115, -95)
            if hot and sig > self.squelch:
                active = (freq, label, sig)
            rows.append({"freq": freq, "label": label,
                         "sig": "%d" % sig,
                         "last": time.strftime("%H:%M:%S") if hot else "",
                         "_hot": hot})
        self.row.emit({"rows": rows, "active": active})


class ProwlApp(PalisadeApp):
    TITLE = "PROWL"
    LEASE = "PROWL"

    def build_body(self):
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self._tok = theme.tokens(self.mode)

        self.bar = ControlBar()
        self.squelch = QtWidgets.QSpinBox()
        self.squelch.setRange(-120, -20)
        self.squelch.setValue(-70)
        self.squelch.setSuffix(" dBm")
        self.squelch.valueChanged.connect(self._sq)
        self.bar.add_field("squelch", self.squelch, "Squelch")
        self.bar.add_stretch()
        self.bar.lay.addWidget(micro("Active"))
        self.active = QtWidgets.QLabel("—  scanning")
        self.active.setProperty("class", "value")
        self.bar.lay.addWidget(self.active)
        lay.addWidget(self.bar)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        self.feed = FeedTable([("freq", "FREQUENCY"), ("label", "CHANNEL"),
                               ("sig", "dBm"), ("last", "LAST")])
        self.feed.selected.connect(self._show)
        split.addWidget(self.feed, 3)
        self.detail = DetailCard("CHANNEL")
        self.detail.set_hero("—", "select a channel")
        split.addWidget(self.detail, 1)
        lay.addLayout(split, 1)
        return body

    def _sq(self, v):
        if self._worker is not None:
            self._worker.squelch = v

    def make_worker(self):
        return ScanWorker(demo=self.demo, squelch=self.squelch.value())

    def _sig_color(self, sig, hot):
        if hot:
            return self._tok["live"]
        if sig > -60:
            return self._tok["warn"]
        return self._tok["muted"]

    def on_row(self, msg):
        rows = msg["rows"]
        for r in rows:
            sig = int(r["sig"])
            c = self._sig_color(sig, r.get("_hot", False))
            r["_colors"] = {"sig": c}
            if r.get("_hot"):
                r["_colors"]["label"] = self._tok["live"]
                r["_colors"]["freq"] = self._tok["live"]
        self.feed.model.set_rows(rows)
        act = msg.get("active")
        if act:
            self.active.setText("%s  %s  %d dBm" % (act[0], act[1], act[2]))
            self.active.setProperty("class", "value live")
            self._show({"freq": act[0], "label": act[1], "sig": str(act[2]),
                         "last": time.strftime("%H:%M:%S"), "_hot": True})
        else:
            self.active.setText("—  scanning")
            self.active.setProperty("class", "value")
        self.active.style().unpolish(self.active)
        self.active.style().polish(self.active)

    def _show(self, row):
        self.detail.set_hero(row.get("label", "—"), row.get("freq", "") + " MHz")
        self.detail.set_rows([
            ("SIGNAL", row.get("sig", "") + " dBm"),
            ("LAST HEARD", row.get("last", "—")),
            ("STATUS", "ACTIVE" if row.get("_hot") else "quiet"),
        ])
