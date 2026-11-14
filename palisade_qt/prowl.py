"""PROWL — scanner / tuner wired to the real scanner engine.

In live mode, cycles through the selected frequency bank using scanner.listen_channel() — the
same per-channel rtl_fm + squelch logic the original Tk scanner uses. Reports channel list,
active channel, and signal level to the Qt GUI thread. In demo mode, generates synthetic hits.
"""
import os
import shutil
import sys
import random
import time

from PySide6 import QtWidgets

from .app import PalisadeApp
from . import theme
from .kit import ControlBar, FeedTable, DetailCard, micro
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

DEMO_CHANNELS = [
    ("162.400", "NOAA WX1"), ("154.265", "Fire Disp"), ("155.340", "EMS"),
    ("121.500", "Aircraft Guard"), ("146.520", "2m Call"), ("462.5625", "FRS 1"),
    ("453.212", "City PD"), ("159.480", "Rail"),
]


class ScanWorker(Worker):
    def __init__(self, demo=True, bank="NOAA Wx", squelch=-70, parent=None):
        super().__init__(demo=demo, interval_ms=350, parent=parent)
        self.squelch = squelch
        self.hold = False
        self._bank = bank
        self._proc = None

    def set_bank(self, bank):
        self._bank = bank

    def run(self):
        if self.demo or not shutil.which("rtl_fm"):
            self._run_demo()
        else:
            self._run_live()

    def _run_demo(self):
        while not self._stop:
            rows = []
            active = None
            for freq, label in DEMO_CHANNELS:
                hot = random.random() < 0.12
                sig = random.randint(-55, -35) if hot else random.randint(-115, -95)
                if hot and sig > self.squelch:
                    active = (freq, label, sig)
                rows.append({"freq": freq, "label": label,
                             "sig": "%d" % sig,
                             "last": time.strftime("%H:%M:%S") if hot else "",
                             "_hot": hot})
            self.row.emit({"rows": rows, "active": active})
            if not active:
                self.status.emit({"sdr": {"text": "SCAN DEMO", "ok": True}})
            waited = 0
            while waited < self.interval_ms and not self._stop:
                self.msleep(10)
                waited += 10

    def _run_live(self):
        import scanner as engine
        s, _ = _load_scanner_settings(engine)
        channels = engine.bank_channels(self._bank, s.get("custom", []))
        if not channels:
            channels = engine.bank_channels("NOAA Wx", [])

        scan = {"on": True, "pause": False, "idx": 0, "rms": 0.0}
        hits = {}
        self.status.emit({"sdr": {"text": "SCAN LIVE", "ok": True}})

        while not self._stop:
            if not channels:
                self.msleep(500)
                continue

            if self.hold:
                self._emit_state(channels, hits, scan, held=True)
                self.msleep(300)
                continue

            idx = scan["idx"] % len(channels)
            freq, label, mode = channels[idx]
            scan["rms"] = 0.0

            result = engine.listen_channel(freq, mode, s, scan, self._make_post(freq, hits),
                                           clock=time.time)
            if self._stop:
                break

            if result:
                hits[freq] = time.strftime("%H:%M:%S")

            self._emit_state(channels, hits, scan)
            scan["idx"] = (idx + 1) % len(channels)

    def _make_post(self, freq, hits):
        def post(msg):
            kind = msg[0] if isinstance(msg, tuple) else msg
            if kind == "hit":
                hits[freq] = time.strftime("%H:%M:%S")
        return post

    def _emit_state(self, channels, hits, scan, held=False):
        rows = []
        active = None
        for freq, label, mode in channels:
            hot = freq in hits and (time.time() - _parse_time(hits.get(freq, "")) < 30)
            rms = scan.get("rms", 0)
            sig = int(-40 - (1.0 - min(1.0, rms / 8000.0)) * 80) if hot else -100
            last = hits.get(freq, "")
            if hot and not held:
                active = (str(freq), label, sig)
            rows.append({"freq": "%.4f" % freq, "label": label, "sig": "%d" % sig,
                         "last": last, "_hot": hot})
        self.row.emit({"rows": rows, "active": active})

    def stop(self):
        super().stop()
        if self._proc and self._proc.poll() is None:
            import signal as sig
            try:
                os.killpg(self._proc.pid, sig.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass


def _load_scanner_settings(engine):
    import json
    cfg = os.path.join(os.path.expanduser("~"), ".config", "uconsole-suite")
    path = os.path.join(cfg, "scanner.json")
    try:
        with open(path) as f:
            s = json.load(f)
        if isinstance(s, dict):
            for k, v in engine.DEFAULTS.items():
                s.setdefault(k, v)
            return s, path
    except (OSError, ValueError):
        pass
    return dict(engine.DEFAULTS), path


def _parse_time(s):
    """Parse HH:MM:SS into a rough timestamp for today (for recency check)."""
    try:
        parts = s.split(":")
        return time.mktime(time.localtime()[:3] + (int(parts[0]), int(parts[1]), int(parts[2]), 0, 0, -1))
    except (ValueError, IndexError):
        return 0


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

        self.bank_combo = QtWidgets.QComboBox()
        try:
            import scanner as engine
            banks = engine.BANK_ORDER
        except ImportError:
            banks = ["NOAA Wx", "CB", "GMRS/FRS", "Marine VHF", "Airband"]
        self.bank_combo.addItems(banks)
        self.bank_combo.setCurrentText("NOAA Wx")
        self.bar.add_field("bank", self.bank_combo, "Bank")

        self.hold_btn = self.bar.add_button("SCAN", self._toggle_hold)
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

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(8)
        self.detail = DetailCard("CHANNEL")
        self.detail.set_hero("—", "select a channel")
        right.addWidget(self.detail, 3)
        self.sig_bar = QtWidgets.QProgressBar()
        self.sig_bar.setRange(0, 100)
        self.sig_bar.setValue(0)
        self.sig_bar.setTextVisible(False)
        self.sig_bar.setFixedHeight(8)
        accent = self._tok["accent"]
        self.sig_bar.setStyleSheet(
            "QProgressBar { background: %s; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: %s; border-radius: 3px; }"
            % (self._tok["well"], accent))
        right.addWidget(self.sig_bar)
        split.addLayout(right, 1)
        lay.addLayout(split, 1)
        return body

    def _toggle_hold(self):
        if self._worker is not None:
            self._worker.hold = not self._worker.hold
            self.hold_btn.setText("HOLD" if self._worker.hold else "SCAN")

    def _sq(self, v):
        if self._worker is not None:
            self._worker.squelch = v

    def make_worker(self):
        return ScanWorker(demo=self.demo, bank=self.bank_combo.currentText(),
                          squelch=self.squelch.value())

    def _sig_color(self, sig, hot):
        if hot:
            return self._tok["live"]
        if sig > -60:
            return self._tok["warn"]
        return self._tok["muted"]

    def on_row(self, msg):
        rows = msg["rows"]
        hot_count = 0
        for r in rows:
            sig = int(r["sig"])
            c = self._sig_color(sig, r.get("_hot", False))
            r["_colors"] = {"sig": c}
            if r.get("_hot"):
                r["_colors"]["label"] = self._tok["live"]
                r["_colors"]["freq"] = self._tok["live"]
                hot_count += 1
        self.feed.model.set_rows(rows)
        self.header.set_chip("sdr", "%d CH" % len(rows), state="neutral")
        act = msg.get("active")
        if act:
            self.active.setText("%s  %s  %d dBm" % (act[0], act[1], act[2]))
            self.active.setProperty("class", "value live")
            pct = max(0, min(100, int((act[2] + 120) * 100 / 80)))
            self.sig_bar.setValue(pct)
            self._show({"freq": act[0], "label": act[1], "sig": str(act[2]),
                         "last": time.strftime("%H:%M:%S"), "_hot": True})
        else:
            self.active.setText("—  scanning")
            self.active.setProperty("class", "value")
            self.sig_bar.setValue(0)
        self.active.style().unpolish(self.active)
        self.active.style().polish(self.active)

    def _show(self, row):
        self.detail.set_hero(row.get("label", "—"), row.get("freq", "") + " MHz")
        self.detail.set_rows([
            ("SIGNAL", row.get("sig", "") + " dBm"),
            ("LAST HEARD", row.get("last", "—")),
            ("STATUS", "ACTIVE" if row.get("_hot") else "quiet"),
        ])
