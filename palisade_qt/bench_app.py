"""BENCH — conducted TX self-test.

The whole point of this callsign: TX only into a cable (dummy load / attenuator / a receiver's
antenna port), never an antenna, every key-up gated by txguard. Two parts, both reused AS-IS:

  * loopback.software_selftests() — pure in-software encode→decode round-trips (CW / RTTY / AIS /
    OpenDroneID). No radio, always runnable, hermetic — the honest "does the DSP chain work" check.
  * bench.preflight()/bench.start_transmit() — the conducted key-up, through the ONE txguard chain
    (audit G1/G8): kill switch armed + session unlocked + the SAVED bench tx_enabled setting (default
    off; this page never overrides it) + the conducted-only acknowledgment + the band (protected
    bands stay denied even conducted — txguard.CONDUCTED_PROTECTED_ALLOWED). The gate state follows
    the engine (chrome.gate_signals): TX PERMITTED when a conducted burst is permitted, TX GATED
    (with the reason) when not.
  * The key-up runs through the executor as a registered process group: the button becomes STOP
    while it runs, disarm / PANIC kill it, and the card shows the transmitter's real exit code.

No OTA ever leaves BENCH. Offscreen (tests) the key-up is never spawned.
"""
import os
import time
import sys

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp
from . import theme, chrome
from .kit import ControlBar, FeedTable, DetailCard, micro
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# conducted bench targets. Protected bands are denied even conducted (owner decision, strict
# default), so no protected preset is offered (the 121.5 MHz preset is removed — audit G1).
BANDS = [("20 m CW (ham)", 14_060_000), ("2 m (ham)", 144_390_000),
         ("70 cm (ham)", 433_920_000), ("915 MHz ISM", 915_000_000)]
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


KEYED_AFTER_S = 1.0       # H8: the runner must stay up this long before the page says KEYED


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
        self._handle = None
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._check_handle)
        self.power.valueChanged.connect(lambda _v: self._refresh_gate())
        chrome.gate_signals().changed.connect(self._refresh_gate)      # follows the engine (G12)
        self._refresh_gate()
        return body

    def _wrap(self, lay):
        w = QtWidgets.QWidget()
        w.setLayout(lay)
        return w

    def _band_freq(self):
        return BANDS[self.band.currentIndex()][1]

    def _saved(self):
        """The saved bench settings — the ONLY source of tx_enabled (default off)."""
        import bench
        try:
            return bench.saved_settings()
        except Exception:
            return {"tx_enabled": False}

    def _settings(self):
        import bench
        saved = self._saved() or {}
        s = dict(bench.DEFAULTS)
        s.update({k: v for k, v in saved.items() if k in bench.DEFAULTS})
        s["tx_enabled"] = saved.get("tx_enabled") is True        # never forced on here (G1)
        s["bench_conducted_ack"] = self.ack.isChecked()
        s["freq_hz"] = self._band_freq()
        s["power_dbm"] = self.power.value()
        s["tx_gain"] = None                    # derived from the authorized power by txguard (G9)
        return s

    def _refresh_gate(self, *_a):
        import bench
        if not hasattr(self, "tx_btn"):
            return
        if self._handle is not None and self._handle.running():
            return                              # STOP stays available while keyed
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

    def _spawner(self):
        """None = the executor's real spawner. Offscreen (tests / CI) a key-up is never spawned."""
        if _offscreen():
            def refuse(argv, **kw):
                raise OSError("offscreen: transmitter not spawned")
            return refuse
        return None

    def _tx(self):
        import bench
        if self._handle is not None and self._handle.running():
            self._handle.stop("operator STOP")
            self._check_handle()
            return
        s = self._settings()
        ok, message, h = bench.start_transmit(
            s, spawner=self._spawner(),
            opt_in=lambda: (self._saved() or {}).get("tx_enabled") is True)   # live (CL2-fix N8)
        if not ok:
            self.card.set_hero("BLOCKED", "conducted into a load — no antenna, no OTA")
            self.card.set_rows([("TXGUARD", "GATED/BLOCKED"), ("RESULT", message)])
            return
        self._handle = h
        self.tx_btn.setText("STOP CONDUCTED TX")
        self.tx_btn.setEnabled(True)
        # H8: a spawned process is not a keyed transmitter. STARTING until the runner has stayed
        # up for KEYED_AFTER_S; if it exits first, _check_handle shows FAILED with its exit code.
        self._keyed_at = time.monotonic() + KEYED_AFTER_S
        self._keyed = False
        self.card.set_hero("STARTING", "conducted into a load — no antenna, no OTA")
        self.card.set_rows([("TXGUARD", "PERMITTED — conducted"), ("RUNNING", message)])
        self._poll.start()

    def _check_handle(self):
        h = self._handle
        if h is None:
            return
        if h.running():
            if not getattr(self, "_keyed", True) and time.monotonic() >= self._keyed_at:
                self._keyed = True
                self.card.set_hero("KEYED", "conducted into a load — no antenna, no OTA")
            return
        self._poll.stop()
        self._handle = None
        self.tx_btn.setText("KEY CONDUCTED TX (confirm)")
        code = h.exit_code
        if h.stopped:
            result = "stopped (%s) · exit %s" % (h.stopped, code)
        else:
            result = "exit %s%s" % (code, "" if code == 0 else " — FAILED")
        hero = ("ENDED" if h.stopped else "DONE" if code == 0 else
                "FAILED" if getattr(self, "_keyed", True) else "FAILED TO KEY")
        self.card.set_hero(hero, "conducted into a load — no antenna, no OTA")
        self.card.set_rows([("RESULT", result), ("OUTPUT", (h.lines[-1] if h.lines else "—"))])
        self._refresh_gate()

    def stop(self):
        if self._stopped:
            return
        chrome.report_tx_permit("BENCH", False)
        if getattr(self, "_handle", None) is not None:
            self._handle.stop("BENCH closed")
            self._handle = None
        if hasattr(self, "_poll"):
            self._poll.stop()
        try:
            chrome.gate_signals().changed.disconnect(self._refresh_gate)
        except (TypeError, RuntimeError):
            pass
        stw = getattr(self, "_stw", None)
        if stw is not None:
            stw.stop()
            stw.quit()
            stw.wait(3000)
        super().stop()
