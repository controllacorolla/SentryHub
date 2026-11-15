"""BENCH — conducted TX self-test.

The whole point of this callsign: TX only into a cable (dummy load / attenuator / a receiver's
antenna port), never an antenna, every key-up gated by txguard. Two parts, both reused AS-IS:

  * loopback.software_selftests() — pure in-software encode→decode round-trips (CW / RTTY / AIS /
    OpenDroneID). No radio, always runnable, hermetic — the honest "does the DSP chain work" check.
  * bench.preflight()/bench.transmit() — the conducted key-up, gated by txguard's bench policy
    (needs TX enabled AND an explicit per-session conducted-only acknowledgment). The gate state is
    shown live: TX SAFE when a conducted burst is permitted, TX GATED (with the reason) when not.

No OTA ever leaves BENCH. `run` is a hermetic seam so tests never spawn a transmitter.
"""
import os
import sys

from PySide6 import QtWidgets

from .app import PalisadeApp
from . import theme
from .kit import ControlBar, FeedTable, DetailCard, micro
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# conducted bench targets (band is irrelevant — nothing radiates — but the operator picks a freq)
BANDS = [("20 m CW (ham)", 14_060_000), ("2 m (ham)", 144_390_000),
         ("70 cm (ham)", 433_920_000), ("915 MHz ISM", 915_000_000),
         ("Aviation 121.5 (protected)", 121_500_000)]
MODES = ["conducted-replay"]


def _offscreen():
    return bool(os.environ.get("PALISADE_OFFLINE") or
                os.environ.get("QT_QPA_PLATFORM") == "offscreen")


class SelfTestWorker(Worker):
    """Runs loopback.software_selftests() once off the GUI thread (pure DSP, no radio)."""

    def step(self):
        import loopback
        results = loopback.software_selftests()
        self.row.emit({"results": results, "all_pass": loopback.all_pass(results)})
        self._stop = True          # one-shot


class BenchApp(PalisadeApp):
    TITLE = "BENCH"
    LEASE = None            # conducted bench — never holds the SDR arbiter lease

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.bar = ControlBar()
        self.band = QtWidgets.QComboBox()
        for label, _ in BANDS:
            self.band.addItem(label)
        self.band.currentIndexChanged.connect(self._refresh_gate)
        self.bar.add_field("band", self.band, "Band")
        self.power = QtWidgets.QSpinBox()
        self.power.setRange(-30, 10)
        self.power.setValue(0)
        self.power.setSuffix(" dBm")
        self.bar.add_field("power", self.power, "Power (attenuated)")
        self.modebox = QtWidgets.QComboBox()
        self.modebox.addItems(MODES)
        self.bar.add_field("mode", self.modebox, "Modulation")
        self.ack = QtWidgets.QCheckBox("conducted-only (into a load, not an antenna)")
        self.ack.toggled.connect(self._refresh_gate)
        self.bar.lay.addWidget(self.ack)
        self.bar.add_stretch()
        self.bar.lay.addWidget(micro("Gate"))
        self.gate = QtWidgets.QLabel("")
        self.bar.lay.addWidget(self.gate)
        lay.addWidget(self.bar)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(micro("SOFTWARE SELF-TEST · encode→decode round-trips (no radio)"))
        self.feed = FeedTable([("name", "CHECK"), ("ok", "RESULT"), ("detail", "DETAIL")])
        left.addWidget(self.feed, 1)
        self.run_btn = QtWidgets.QPushButton("RUN SELF-TEST")
        self.run_btn.clicked.connect(self._run_selftest)
        left.addWidget(self.run_btn)
        split.addWidget(self._wrap(left), 3)

        self.card = DetailCard("CONDUCTED TX")
        self.card.set_hero("—", "conducted into a load — no antenna, no OTA")
        # honest: loopback has no VSWR/return-loss/power meter, so nothing is measured or invented
        self.card.set_rows([("TXGUARD", "idle"), ("MEASURE", "software self-test only (no VSWR meter)"),
                            ("RESULT", "—")])
        right = QtWidgets.QVBoxLayout()
        right.addWidget(self.card, 1)
        self.tx_btn = QtWidgets.QPushButton("KEY CONDUCTED TX (confirm)")
        self.tx_btn.clicked.connect(self._tx)
        right.addWidget(self.tx_btn)
        split.addWidget(self._wrap(right), 2)
        lay.addLayout(split, 1)
        self._refresh_gate()
        try:
            import opsec
            opsec.subscribe(self._refresh_gate)      # reflect OPSEC arm/disarm live
        except Exception:
            pass
        return body

    def _wrap(self, lay):
        w = QtWidgets.QWidget()
        w.setLayout(lay)
        return w

    def _band_freq(self):
        return BANDS[self.band.currentIndex()][1]

    def _settings(self):
        import bench
        s = dict(bench.DEFAULTS)
        s["tx_enabled"] = True
        s["bench_conducted_ack"] = self.ack.isChecked()
        s["freq_hz"] = self._band_freq()
        s["tx_gain"] = 0                       # conducted paths use external attenuation
        return s

    def _refresh_gate(self, *_):
        import bench
        import opsec
        ok, why = bench.preflight(self._settings(), self._band_freq())
        opsec_armed = opsec.is_armed()
        self.tx_btn.setEnabled(ok)
        if ok:
            self.gate.setText("TX SAFE · conducted")
            self.gate.setStyleSheet("color:%s; font-weight:600;" % self._tok["live"])
        elif opsec_armed:
            self.gate.setText("TX BLOCKED BY OPSEC")
            self.gate.setStyleSheet("color:%s; font-weight:700;" % self._tok["alert"])
        else:
            self.gate.setText("TX GATED")
            self.gate.setStyleSheet("color:%s; font-weight:600;" % self._tok["warn"])
        txg = "SAFE — conducted" if ok else ("BLOCKED — OPSEC" if opsec_armed else "GATED")
        self.card.set_rows([("TXGUARD", txg), ("REASON", why), ("RESULT", "—")])

    def make_worker(self):
        return None             # the self-test runs on demand, not continuously

    def _run_selftest(self):
        self._stw = SelfTestWorker()
        self._stw.row.connect(self._on_results)
        self._stw.start()

    def _on_results(self, msg):
        rows = []
        for name, ok, detail in msg["results"]:
            rows.append({"name": name, "ok": "PASS" if ok else "FAIL", "detail": detail,
                         "_colors": {"ok": self._tok["live"] if ok else self._tok["warn"]}})
        self.feed.model.set_rows(rows)
        self.header.set_chip("sdr", "SELF-TEST %s" % ("PASS" if msg["all_pass"] else "FAIL"),
                             state="neutral")

    def _tx(self):
        import bench
        s = self._settings()
        # hermetic seam: offscreen/tests never spawn a transmitter; on-device run is the default
        run = (lambda argv: None) if _offscreen() else None
        ok, message = bench.transmit(s, run=run)
        self.card.set_hero("KEYED" if ok else "BLOCKED",
                           "conducted into a load — no antenna, no OTA")
        self.card.set_rows([("TXGUARD", "SAFE — conducted" if ok else "GATED/BLOCKED"),
                            ("RESULT", message[:80])])

    def stop(self):
        if self._stopped:
            return
        try:
            import opsec
            opsec.unsubscribe(self._refresh_gate)
        except Exception:
            pass
        stw = getattr(self, "_stw", None)
        if stw is not None:
            stw.stop()
            stw.quit()
            stw.wait(3000)
        super().stop()
