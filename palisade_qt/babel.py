"""BABEL — universal decoder feed (archetype: table + detail + status rail).

Absorbs the distinct decoders (AIS, ACARS/VDL2, POCSAG, RDS, CW, RTTY, …) under one feed view
with a mode selector. Built from the kit: StatusHeader, ControlBar (mode), FeedTable (+model),
DetailCard. The worker emits decoded messages to the GUI thread; demo synthesises per-mode
traffic, on-device each mode binds to its existing suite decoder (unchanged — UI only).
"""
import random
import time

from PySide6 import QtWidgets

from .app import PalisadeApp
from .kit import ControlBar, FeedTable, DetailCard
from .worker import Worker

MODES = ["AIS", "ACARS", "POCSAG", "RDS", "CW", "RTTY"]


def _synth(mode):
    now = time.strftime("%H:%M:%S")
    if mode == "AIS":
        mmsi = random.randint(200000000, 775000000)
        return {"time": now, "proto": "AIS", "id": str(mmsi), "summary": "pos report",
                "detail": [("MMSI", mmsi), ("LAT", "%.4f" % random.uniform(47, 48)),
                           ("LON", "%.4f" % random.uniform(-123, -122)),
                           ("SOG", "%.1f kn" % random.uniform(0, 22)),
                           ("COG", "%d°" % random.randint(0, 359))]}
    if mode == "ACARS":
        fl = random.choice(["UAL", "DAL", "ASA", "FDX"]) + str(random.randint(100, 2999))
        lbl = random.choice(["H1", "Q0", "5Z", "80"])
        return {"time": now, "proto": "ACARS", "id": fl, "summary": "label %s" % lbl,
                "detail": [("FLIGHT", fl), ("LABEL", lbl), ("MODE", "2"),
                           ("TEXT", "POS N47.5 W122.3 FL%d" % random.randint(300, 400))]}
    if mode == "POCSAG":
        cap = random.randint(100000, 2000000)
        return {"time": now, "proto": "POCSAG", "id": str(cap), "summary": "alpha msg",
                "detail": [("CAPCODE", cap), ("BAUD", random.choice([512, 1200, 2400])),
                           ("TEXT", random.choice(["CALL CONTROL", "UNIT 7 RESPOND", "TEST PAGE"]))]}
    if mode == "RDS":
        pi = "%04X" % random.randint(0x1000, 0xFFFF)
        ps = random.choice(["KEXP", "KUOW", "KISW", "JACK-FM"])
        return {"time": now, "proto": "RDS", "id": pi, "summary": ps,
                "detail": [("PI", pi), ("PS", ps), ("PTY", random.randint(0, 31)),
                           ("RT", "Now playing — demo stream")]}
    if mode == "CW":
        return {"time": now, "proto": "CW", "id": "%d WPM" % random.randint(12, 28),
                "summary": random.choice(["CQ CQ DE", "599 TU", "QRZ?"]),
                "detail": [("WPM", random.randint(12, 28)), ("TONE", "700 Hz")]}
    rt = "RYRY " + "".join(random.choice("0123456789") for _ in range(4))
    return {"time": now, "proto": "RTTY", "id": "45 baud", "summary": rt,
            "detail": [("BAUD", 45.45), ("SHIFT", "170 Hz"), ("TEXT", rt)]}


class DecoderWorker(Worker):
    def __init__(self, demo=True, mode="AIS", parent=None):
        super().__init__(demo=demo, interval_ms=600, parent=parent)
        self.mode = mode
        self._n = 0

    def set_mode(self, mode):
        self.mode = mode

    def step(self):
        self._n += 1
        self.row.emit(_synth(self.mode))
        if self._n % 3 == 0:
            self.status.emit({"sdr": {"text": "SDR DEMO", "ok": True},
                              "msgs": self._n})


class BabelApp(PalisadeApp):
    TITLE = "BABEL"
    LEASE = "BABEL"

    def build_body(self):
        body = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.bar = ControlBar()
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(MODES)
        self.mode.currentTextChanged.connect(self._set_mode)
        self.bar.add_field("mode", self.mode, "Decoder")
        self.bar.add_stretch()
        self.count = QtWidgets.QLabel("0 msgs")
        self.count.setProperty("class", "value")
        self.bar.lay.addWidget(self.count)
        outer.addWidget(self.bar)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        self.feed = FeedTable([("time", "TIME"), ("proto", "PROTO"),
                               ("id", "ID"), ("summary", "MESSAGE")])
        self.feed.selected.connect(self._show)
        split.addWidget(self.feed, 3)
        self.detail = DetailCard("MESSAGE")
        split.addWidget(self.detail, 1)
        outer.addLayout(split, 1)
        self._count = 0
        return body

    def _set_mode(self, mode):
        self.feed.model.set_rows([])
        if self._worker is not None:
            self._worker.set_mode(mode)

    def make_worker(self):
        return DecoderWorker(demo=self.demo, mode=self.mode.currentText())

    def on_row(self, row):
        self.feed.model.prepend(row, cap=400)
        self._count += 1
        self.count.setText("%d msgs" % self._count)
        if self._count == 1:
            self._show(row)

    def _show(self, row):
        self.detail.set_hero(row.get("id", "—"), row.get("proto", ""))
        self.detail.set_rows([("TIME", row.get("time", ""))] + row.get("detail", []))
