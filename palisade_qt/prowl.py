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

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp
from . import theme
from .kit import ControlBar, FeedTable, DetailCard, micro, card
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
        if self.demo:
            self._run_demo()
        elif not shutil.which("rtl_fm"):
            self._run_standby()        # live + no rtl_fm: honest standby, never synthesise hits
        else:
            self._run_live()

    def _run_standby(self):
        """Live mode without rtl_fm: list the bank's channels all-quiet and publish NO fake hits.
        Live shows only real activity (zero with no hardware); demo is the only synthetic path."""
        import scanner as engine
        s, _ = _load_scanner_settings(engine)
        channels = (engine.bank_channels(self._bank, s.get("custom", []))
                    or engine.bank_channels("NOAA Wx", []))
        scan = {"on": False, "pause": False, "idx": 0, "rms": 0.0}
        while not self._stop:
            self._emit_state(channels, {}, scan)   # channels listed, all quiet, no fabricated hits
            # re-assert STANDBY *after* the rows so on_row's "N CH" chip doesn't mask it
            self.status.emit({"sdr": {"text": "SCAN STANDBY — no rtl_fm", "ok": False},
                              "standby": True})
            waited = 0
            while waited < 1000 and not self._stop:
                self.msleep(20)
                waited += 20

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

        fdb = card(2)
        fl = QtWidgets.QVBoxLayout(fdb)
        fl.setContentsMargins(11, 9, 11, 9)
        fl.setSpacing(5)
        fl.addWidget(micro("Frequency DB"))
        self.fdb_input = QtWidgets.QLineEdit()
        self.fdb_input.setPlaceholderText("MHz, or search a service…")
        self.fdb_input.returnPressed.connect(self._fdb_query)
        self.fdb_input.textChanged.connect(self._fdb_query)
        fl.addWidget(self.fdb_input)
        self.fdb_results = QtWidgets.QLabel("")
        self.fdb_results.setProperty("class", "micro")
        self.fdb_results.setWordWrap(True)
        self.fdb_results.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        fl.addWidget(self.fdb_results)
        right.addWidget(fdb, 2)

        split.addLayout(right, 1)
        lay.addLayout(split, 1)
        return body

    def _fdb_query(self):
        """A bare number = MHz -> lookup/describe; text -> freqdb.search. Pure, no radio."""
        term = self.fdb_input.text().strip()
        if not term:
            self.fdb_results.setText("")
            return
        try:
            import freqdb
        except ImportError:
            self.fdb_results.setText("freqdb unavailable")
            return
        lines = []
        try:
            mhz = float(term)
            for lo, hi, svc, note in freqdb.lookup(int(mhz * 1e6))[:5]:
                lines.append("%.3f–%.3f  %s%s" % (lo / 1e6, hi / 1e6, svc,
                                                  " · " + note if note else ""))
            if not lines:
                lines = ["%.3f MHz — unallocated" % mhz]
        except ValueError:
            for lo, hi, svc, note in freqdb.search(term)[:6]:
                lines.append("%.3f–%.3f  %s" % (lo / 1e6, hi / 1e6, svc))
            if not lines:
                lines = ["no match for %r" % term]
        self.fdb_results.setText("\n".join(lines))

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

    def on_status(self, status):
        super().on_status(status)
        if status.get("standby"):            # live + no device: say so, don't imply a live scan
            self.active.setText("standby — no device")
            self.active.setProperty("class", "value")
            self.active.style().unpolish(self.active)
            self.active.style().polish(self.active)

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
            ("ALLOCATION", _describe_mhz(row.get("freq", ""))),      # freqdb cross-reference
        ])


def _describe_mhz(freq_mhz_str):
    """freqdb.describe for an 'MHz' string, reused as-is. 'unallocated' if unknown/unparseable."""
    try:
        import freqdb
        return freqdb.describe(int(float(freq_mhz_str) * 1e6))
    except Exception:
        return "—"
