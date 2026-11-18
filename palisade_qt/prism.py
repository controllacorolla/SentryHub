"""PRISM — real-time spectrum analyzer + waterfall (PyQtGraph).

Hero: a linked spectrum line (amplitude vs frequency) over a scrolling waterfall (time x freq x
amplitude as colour) — ScopePanel. Live mode drives the suite's existing rtl_power engine
(waterfall.rtl_power_sweep_argv + noisefloor.parse_rtl_power_row, reused AS-IS) and renders each
assembled sweep. Demo synthesises sweeps (SDR-DEMO flagged).

Single radio: PRISM takes the dongle through the shared radio_arbiter ("PRISM"), the same arbiter
ATLAS's APRS/AIS layers use — so only ONE owner at a time. PRISM holds it only while its page is
active (acquire on show/active, release on page-leave and close); if the radio is held elsewhere
PRISM shows RADIO BUSY. No decode/radio behaviour is changed here. offscreen/offline never opens a
real radio.
"""
import math
import shutil
import threading
import time

import numpy as np
from PySide6 import QtWidgets

from .app import PalisadeApp
from . import theme, radio_arbiter
from .kit import ControlBar, ScopePanel, micro
from .worker import Worker
from .kit.seams import offscreen as _seam_offscreen

BINS = 512
NAME = "PRISM"
STALE_AFTER_S = 5.0          # H2: no assembled sweep for this long -> STALE, never a green chip
FAULT_RETRY_S = 5.0          # rtl_power died: wait this long before respawning it


class _SweepAssembler:
    """Collect rtl_power CSV rows (each a frequency segment of a pass) into a full sweep. Emits
    (freqs_MHz, power_dbm) when a new pass begins (a segment whose f_low repeats). Parser reused."""

    def __init__(self):
        import noisefloor
        self._nf = noisefloor
        self._acc = {}

    def feed(self, line):
        r = self._nf.parse_rtl_power_row(line)
        if not r:
            return None
        flow = r["f_low"]
        done = None
        if flow in self._acc and len(self._acc) > 1:   # wrap: this segment starts a new pass
            done = self._emit()
            self._acc = {}
        self._acc[flow] = r["bins"]
        return done

    def _emit(self):
        allbins = []
        for flow in sorted(self._acc):
            allbins += self._acc[flow]
        allbins.sort()
        if not allbins:
            return None
        freqs = np.array([f / 1e6 for f, _ in allbins])
        power = np.array([db for _, db in allbins], dtype=np.float32)
        return freqs, power


def _offline():
    return bool(_seam_offscreen())


def _open_rtl_power(lo_mhz, hi_mhz, gain):
    """Stream rtl_power over the band to stdout (argv list, no shell). None under tests/offline or
    without rtl_power, so CI never opens a real radio. Reuses waterfall's argv builder. stderr is a
    pipe, so an rtl_power that dies can say why (H2)."""
    if _seam_offscreen():
        return None
    if not shutil.which("rtl_power"):
        return None
    import waterfall
    bin_hz = max(1, int((hi_mhz - lo_mhz) * 1e6 / BINS))
    argv = waterfall.rtl_power_sweep_argv(int(lo_mhz * 1e6), int(hi_mhz * 1e6), bin_hz, "-",
                                          gain, "1")
    import subprocess
    from .kit.procs import Pipeline
    return Pipeline([argv], stderr_last=subprocess.PIPE)   # own session; killed + waited (A4)


class SweepWorker(Worker):
    """Demo -> synthetic sweeps. Live -> rtl_power through the arbiter, but only while `active`."""

    def __init__(self, demo=False, lo=430.0, hi=440.0, gain=0, parent=None):
        super().__init__(demo=demo, interval_ms=80, parent=parent)
        self.lo, self.hi, self.gain = lo, hi, gain
        self._t0 = time.time()
        self._active = False
        self._has_radio = False
        self._proc = None
        self._asm = None
        self._latest = None
        self._lock = threading.Lock()
        self._band_dirty = False
        self._held_off = False
        self._why = "page hidden"
        # H2: the chip is LIVE only while assembled sweeps really arrive
        self._spawned_at = None          # monotonic time rtl_power was started
        self._last_sweep = None          # monotonic time of the last assembled sweep
        self._err_tail = []              # last stderr lines of the current rtl_power
        self._fault = None               # (why, monotonic) when rtl_power exited on its own
        radio_arbiter.arbiter.revoked.connect(self._on_revoked)

    PAUSE_WHEN_HIDDEN = False          # keeps stepping while hidden so it can release the dongle

    def set_active(self, on):
        on = bool(on)
        if on == self._active and not (on and self._held_off):
            return
        self._active = on
        if on:
            self._held_off = False
        else:
            self._why = "page hidden"
        self.poke()

    def _on_revoked(self, name):
        """A1: operator asked for the radio back — stop sweeping, wait, release on the next step.
        Flags only (GUI thread); stays off until the page is fronted again or resumed."""
        if name == NAME:
            self.hold_off("radio given back")

    def hold_off(self, reason):
        self._held_off = True
        self._active = False
        self._why = reason
        self.poke()

    @property
    def held_off(self):
        return self._held_off

    def set_band(self, lo, hi):
        with self._lock:
            self.lo, self.hi, self._band_dirty = lo, hi, True

    # ---- demo
    def _demo_row(self):
        freqs = np.linspace(self.lo, self.hi, BINS)
        t = time.time() - self._t0
        p = -108 + 4 * np.random.randn(BINS)
        for base, drift, pwr, w in ((0.21, 0.4, 48, 1.4), (0.65, -0.2, 32, 0.8)):
            cf = self.lo + (self.hi - self.lo) * base + drift * math.sin(t * 0.3)
            p += pwr * np.exp(-((freqs - cf) ** 2) / (2 * ((w * (self.hi - self.lo) / 100) ** 2)))
        return freqs, p

    # ---- live radio (through the one arbiter)
    def _start_rtl(self):
        self._asm = _SweepAssembler()
        with self._lock:
            lo, hi, self._band_dirty = self.lo, self.hi, False
        self._proc = _open_rtl_power(lo, hi, self.gain)
        if self._proc is not None and (self._stop or not self._active
                                       or not radio_arbiter.arbiter.held_by(NAME)):
            self._kill_rtl()                         # revoke / PANIC while spawning: never keep it
            return
        if self._proc is not None:
            self._spawned_at, self._last_sweep, self._err_tail = time.monotonic(), None, []
            threading.Thread(target=self._read, args=(self._proc,), daemon=True).start()
            err = getattr(self._proc, "stderr", None)
            if err is not None:
                threading.Thread(target=self._read_err, args=(self._proc, err), daemon=True).start()

    def _read(self, proc):
        try:
            for line in proc.stdout:
                if proc is not self._proc:
                    break
                done = self._asm.feed(line) if self._asm else None
                if done is not None:
                    with self._lock:
                        self._latest = done
                        self._last_sweep = time.monotonic()
        except Exception:
            pass

    def _read_err(self, proc, err):
        try:
            for line in err:
                line = line.strip() if isinstance(line, str) else \
                    line.decode("utf-8", "replace").strip()
                if line and proc is self._proc:
                    self._err_tail = (self._err_tail + [line])[-4:]
        except Exception:
            pass

    def _live_status(self, now=None):
        """(text, state) for the SDR chip while rtl_power should be sweeping (H2): LIVE only if a
        sweep arrived within STALE_AFTER_S; STARTING before the first one; STALE after."""
        now = time.monotonic() if now is None else now
        with self._lock:
            last = self._last_sweep
        if last is not None and now - last <= STALE_AFTER_S:
            return "SDR PRISM", "live"
        if last is None:
            age = now - (self._spawned_at or now)
            if age <= STALE_AFTER_S:
                return "SDR PRISM — starting", "warn"
            return "SDR STALE — no sweep in %ds" % int(age), "alert"
        return "SDR STALE — last sweep %ds ago" % int(now - last), "alert"

    def _kill_rtl(self):
        self._asm = None
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()                 # Pipeline: SIGTERM → wait → SIGKILL → wait: no zombie
            except Exception:
                pass

    def _release(self, why=None):
        self._kill_rtl()                             # rtl_power reaped (terminate waits) …
        if self._has_radio:
            radio_arbiter.arbiter.release(NAME)      # … then the dongle goes back (ATLAS/readsb)
            self._has_radio = False
            if why:                                  # CL5-fix 7: never keep "SDR PRISM" after this
                self.status.emit({"busy": None, "live": False, "off": True,
                                  "sdr": {"text": "SDR OFF — %s" % why, "state": "warn"}})

    def step(self):
        if self.demo:
            self.row.emit(self._demo_row())
            return
        if not self._active:                         # page left -> give the radio back
            if self._has_radio:
                self._release(self._why)
            return
        arb = radio_arbiter.arbiter
        if not self._has_radio:
            if arb.request(NAME):
                self._has_radio = True
            else:
                self.status.emit({"busy": radio_arbiter.owner_label(),
                                  "sdr": {"text": radio_arbiter.busy_text(NAME).replace(
                                      "RADIO BUSY", "SDR BUSY"), "state": "warn"}})
                return
        st, owner = arb.state()
        if owner != NAME:                            # freed under us (forced free / PANIC)
            self._has_radio = False
            self._kill_rtl()
            self._held_off = True
            self._active = False
            self.status.emit({"busy": None, "live": False, "off": True,
                              "sdr": {"text": "SDR OFF — %s" % radio_arbiter.lost_reason(NAME),
                                      "state": "warn"}})
            return
        if st != "HELD":                             # CL5-fix 1: no rtl_power until HELD
            self.status.emit({"busy": None, "live": False, "acquiring": True,
                              "sdr": {"text": "SDR ACQUIRING", "state": "warn"}})
            return
        proc = self._proc
        if proc is not None and proc.poll() is not None:     # H2: it died on its own -> FAULT
            rc = proc.poll()
            tail = " · ".join(self._err_tail[-2:])
            self._kill_rtl()
            self._fault = ("rtl_power exited (%s)%s" % (rc, (": " + tail) if tail else ""),
                           time.monotonic())
        if self._fault is not None:
            why, t = self._fault
            if time.monotonic() - t < FAULT_RETRY_S and not self._band_dirty:
                self.status.emit({"busy": None, "fault": why,
                                  "sdr": {"text": ("SDR FAULT — " + why)[:80], "state": "alert"}})
                return
            self._fault = None                       # retry (or the operator retuned)
        if self._asm is None:                        # not sweeping yet (or given back): start
            self._start_rtl()
        if self._band_dirty:                         # retune -> respawn rtl_power on the new band
            self._kill_rtl()                         # (terminate() waits until it has exited)
            self._start_rtl()
        with self._lock:
            row, self._latest = self._latest, None
        if self._proc is not None:
            text, state = self._live_status()
            self.status.emit({"busy": None, "sdr": {"text": text, "state": state},
                              "stale": state != "live"})
        elif shutil.which("rtl_power") and not _offline():
            self.status.emit({"busy": None, "sdr": {"text": "SDR FAULT — rtl_power did not start",
                                                    "state": "alert"}})
        elif shutil.which("rtl_power"):
            self.status.emit({"busy": None, "standby": True,
                              "sdr": {"text": "SDR STANDBY — offline (no capture)",
                                      "state": "warn"}})
        else:
            # we hold the radio but there's no rtl_power to sweep: say STANDBY, never synthesise.
            # (The scope already stays empty — a row is only emitted from a real assembled sweep.)
            self.status.emit({"busy": None, "standby": True,
                              "sdr": {"text": "SDR STANDBY — no rtl_power", "state": "warn"}})
        if row is not None:
            self.row.emit(row)

    def run(self):
        try:
            super().run()
        finally:
            self._release()                          # RELEASE on close (after rtl_power exits)
            try:
                radio_arbiter.arbiter.revoked.disconnect(self._on_revoked)
            except (RuntimeError, TypeError):
                pass


class PrismApp(PalisadeApp):
    TITLE = "PRISM"
    LEASE = None                 # the SweepWorker takes the radio via the arbiter, not the base lease

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._lo, self._hi = 430.0, 440.0
        self._peak_mhz = None
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    # ---- keyboard (D8): [ ] step the band by one span, + / - narrow / widen the span ----
    def handle_key(self, text):
        if text in "[]":
            step = self.span.value() * (1 if text == "]" else -1)
            self.centre.setValue(self.centre.value() + step)
            return True
        if text in "+=":
            self.span.setValue(max(self.span.minimum(), self.span.value() / 2.0))
            return True
        if text in "-_":
            self.span.setValue(min(self.span.maximum(), self.span.value() * 2.0))
            return True
        return False

    def primary_action(self):
        w = self._worker
        if w is not None and getattr(w, "held_off", False) and self._active:
            w.set_active(True)                       # resume after a revoke / PANIC
            self.busy.hide()
            return True
        return self._send_peak()

    def tune(self, mhz):
        """Palette: centre the analyzer on a frequency."""
        self.centre.setValue(float(mhz))

    def _send_peak(self):
        """'Send to' (D10): hand the current peak to the PROWL FM tuner."""
        if self._peak_mhz is None:
            return False
        self.request.emit("tune_fm", self._peak_mhz)
        return True

    def build_body(self):
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.bar = ControlBar()
        self.centre = QtWidgets.QDoubleSpinBox()
        self.centre.setRange(24, 1766)
        self.centre.setValue((self._lo + self._hi) / 2)
        self.centre.setSuffix(" MHz")
        self.centre.setDecimals(2)
        self.span = QtWidgets.QDoubleSpinBox()
        self.span.setRange(0.5, 40)
        self.span.setValue(self._hi - self._lo)
        self.span.setSuffix(" MHz")
        self.gain = QtWidgets.QSpinBox()
        self.gain.setRange(0, 49)
        self.gain.setValue(30)
        self.gain.setSuffix(" dB")
        self.bar.add_field("centre", self.centre, "Centre")
        self.bar.add_field("span", self.span, "Span")
        self.bar.add_field("gain", self.gain, "Gain")
        self.bar.add_stretch()
        self.readout = QtWidgets.QLabel("—")
        self.readout.setProperty("class", "value")
        # H13: rtl_power is uncalibrated; the value itself reads "dB rel". The caption was shortened
        # from "PEAK · dB (relative)" so PRISM fits beside the left page rail (2026-11-17).
        self.bar.lay.addWidget(micro("PEAK"))
        self.bar.lay.addWidget(self.readout)
        self.send_btn = QtWidgets.QPushButton("PEAK → PROWL FM")
        self.send_btn.setToolTip("Tune the PROWL FM receiver to the current peak (Enter)")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send_peak)
        self.bar.lay.addWidget(self.send_btn)
        self.centre.valueChanged.connect(self._retune)
        self.span.valueChanged.connect(self._retune)
        self.gain.valueChanged.connect(self._retune)
        lay.addWidget(self.bar)

        self.busy = QtWidgets.QLabel("")
        self.busy.setProperty("class", "note")
        self.busy.setWordWrap(True)
        self.busy.setStyleSheet("color:%s;" % theme.tokens(self.mode)["warn"])
        self.busy.hide()
        lay.addWidget(self.busy)

        self.scope = ScopePanel(bins=BINS, history=120, lo_mhz=self._lo, hi_mhz=self._hi,
                                mode=self.mode)
        lay.addWidget(self.scope, 1)
        return body

    def _retune(self):
        c, s = self.centre.value(), self.span.value()
        self._lo, self._hi = c - s / 2, c + s / 2
        if self._worker is not None:
            self._worker.gain = self.gain.value()
            self._worker.set_band(self._lo, self._hi)

    def on_panic(self):
        """PANIC (CL5-fix 5): stop sweeping and stay off; Enter or re-opening PRISM resumes."""
        w = self._worker
        if w is not None and hasattr(w, "hold_off") and not self.demo:
            w.hold_off("PANIC")
        return []

    def make_worker(self):
        w = SweepWorker(demo=self.demo, lo=self._lo, hi=self._hi, gain=self.gain.value())
        if not self.demo:
            w.set_active(self._active)      # inherit the page's current front/back state at start
        return w

    def set_active(self, active):
        super().set_active(active)
        if not self.demo and self._worker is not None and hasattr(self._worker, "set_active"):
            self._worker.set_active(active)          # hold the radio only while PRISM is in front

    def on_status(self, status):
        super().on_status(status)                    # chips (incl. SDR PRISM/BUSY/STANDBY)
        if status.get("off") or status.get("acquiring"):
            text = (status.get("sdr") or {}).get("text", "")
            if status.get("off") and getattr(self._worker, "held_off", False):
                text += "  ·  press Enter to resume"
            self.busy.setText(text)
            self.busy.show()
        elif status.get("standby"):                    # live + no rtl_power: honest, no fake sweep
            self.busy.setText("STANDBY — %s (no synthetic sweep)" % (
                (status.get("sdr") or {}).get("text", "").replace("SDR STANDBY — ", "")
                or "no rtl_power"))
            self.busy.show()
        elif status.get("fault") or status.get("stale"):    # H2: frozen sweep is never green
            self.busy.setText((status.get("sdr") or {}).get("text", ""))
            self.busy.show()
        elif "busy" in status:
            owner = status["busy"]
            if owner:
                self.busy.setText("RADIO BUSY — held by %s" % owner)
                self.busy.show()
            else:
                self.busy.hide()

    def on_row(self, row):
        freqs, power = row
        self.scope.push(freqs, power)
        peak = float(np.max(power))
        pf = float(freqs[int(np.argmax(power))])
        self.readout.setText("%.0f dB rel @ %.2f MHz" % (peak, pf))   # H13: uncalibrated
        self._peak_mhz = pf
        self.send_btn.setEnabled(True)
