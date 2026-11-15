"""BENCH — conducted TX self-test.

The whole point of this callsign: TX only into a cable (dummy load / attenuator / a receiver's
antenna port), never an antenna, every key-up gated by txguard. Two parts, both reused AS-IS:

  * loopback.software_selftests() — pure in-software encode→decode round-trips (CW / RTTY / AIS /
    OpenDroneID). No radio, always runnable, hermetic — the honest "does the DSP chain work" check.
  * bench.preflight()/bench.transmit() — the conducted key-up, gated by txguard's bench policy
    (needs TX enabled AND an explicit per-session conducted-only acknowledgment). The gate state is
    shown live: TX PERMITTED when a conducted burst is permitted, TX GATED (with the reason) when not.

No OTA ever leaves BENCH. `run` is a hermetic seam so tests never spawn a transmitter.
"""
import os
import sys

from PySide6 import QtWidgets

from .app import PalisadeApp
from . import theme, chrome
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

    def primary_action(self):
        self._run_selftest()      # Enter runs the harmless action; keying TX is never the default
        return True

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
        self.bar.add_stretch()
        lay.addWidget(self.bar)
        # the acknowledgment and the gate state get their own row: on one line with the selectors
        # they forced the window wider than the screen (D1)
        ackrow = QtWidgets.QHBoxLayout()
        ackrow.setSpacing(12)
        self.ack = QtWidgets.QCheckBox("conducted-only (into a load, not an antenna)")
        self.ack.toggled.connect(self._refresh_gate)
        ackrow.addWidget(self.ack)
        ackrow.addStretch(1)
        ackrow.addWidget(micro("Gate"))
        self.gate = QtWidgets.QLabel("")
        self.gate.setProperty("class", "value")
        ackrow.addWidget(self.gate)
        lay.addLayout(ackrow)

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

    def _refresh_gate(self):
        import bench
        ok, why = bench.preflight(self._settings(), self._band_freq())
        self.tx_btn.setEnabled(ok)
        # "TX SAFE" is retired: it meant "not transmitting" in the strip and "transmit permitted"
        # here. A passing gate is a hazard state, so it is amber PERMITTED, never green (D4/D9).
        if ok:
            self.gate.setText("▲ TX PERMITTED · conducted")
            self.gate.setStyleSheet("color:%s;" % self._tok["warn"])
        else:
            self.gate.setText("○ TX GATED")
            self.gate.setStyleSheet("color:%s;" % self._tok["muted"])
        chrome.report_tx_permit("BENCH", ok)         # the shell's TX slot shows PERMITTED
        self.card.set_rows([("TXGUARD", "PERMITTED — conducted" if ok else "GATED"),
                            ("REASON", why), ("RESULT", "—")])

    def on_gate_changed(self):
        """The shell says a gate changed (PANIC, engagement): re-read bench's own gate so the TX
        slot shows its real answer, not what it was before."""
        if not self._stopped:
            self._refresh_gate()

    def on_panic(self):
        """PANIC revokes the conducted-only acknowledgement. In this app the ack IS this checkbox
        (bench.preflight reads it from the settings this page builds), so unchecking it is a pure
        UI action; the gate then refuses on its own logic (owner decision, CL1-fix2)."""
        if self._stopped or not self.ack.isChecked():
            return []
        self.ack.setChecked(False)          # toggled -> _refresh_gate -> re-reads bench.preflight
        return ["BENCH ack revoked"]

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
        self.card.set_rows([("TXGUARD", "PERMITTED — conducted" if ok else "GATED/BLOCKED"),
                            ("RESULT", message)])

    def stop(self):
        if self._stopped:
            return
        chrome.report_tx_permit("BENCH", False)
        stw = getattr(self, "_stw", None)
        if stw is not None:
            stw.stop()
            stw.quit()
            stw.wait(3000)
        super().stop()
