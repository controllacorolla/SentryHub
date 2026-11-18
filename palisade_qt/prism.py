"""PRISM — SDR++-style receiver: spectrum + waterfall + a tunable, demodulating VFO.

Default source: rtl_tcp IQ (palisade_qt.iqworker.TunerWorker + dsp + iqsource): click / drag /
wheel / type to tune, AM NFM WFM USB LSB CW with audio, bandwidth, squelch, gain/AGC, zoom,
bookmarks + preset banks, audio and baseband recording, IQ file playback. The original
rtl_power wide sweep below is kept as the "Wide sweep" source (spans wider than the IQ rate).

Original wide-sweep notes:

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
from PySide6 import QtCore, QtGui, QtWidgets

import banks
import dsp
import iqsource
from .app import PalisadeApp
from . import theme, radio_arbiter
from .kit import ControlBar, micro
from .kit.components import Section, note, set_run
from .kit.tuner import FreqEdit, TunerScope
from .iqworker import TunerWorker
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


SOURCES = (("RTL-SDR (live)", "rtl"), ("IQ file playback", "file"),
           ("Wide sweep (rtl_power)", "sweep"))
STEPS = ((("8.33 kHz", 8333.33), ("12.5 kHz", 12500), ("25 kHz", 25000), ("5 kHz", 5000),
          ("100 kHz", 100000), ("1 kHz", 1000), ("100 Hz", 100), ("10 Hz", 10)))
FFT_SIZES = (2048, 4096, 8192, 16384, 32768)
SMOOTHING = (("off", 0.0), ("light", 0.5), ("medium", 0.75), ("heavy", 0.9))
PRISM_DEFAULTS = {"vfo_hz": 119_100_000, "mode": "AM", "bw": 8330, "step": 25000,
                  "rate": 2048000, "gain_db": 33.8, "auto_gain": False, "rtl_agc": False,
                  "ppm": 0, "squelch_on": False, "squelch_db": -60.0, "audio_agc": True,
                  "audio": True, "deemph_us": 75, "nfft": 8192, "smooth": 0.0, "wf_lo": -85.0, "wf_hi": -25.0,
                  "source": "rtl", "file": "", "bookmarks": []}


def _load_prism_settings():
    try:
        import suite
        s, path = suite.settings("prism", PRISM_DEFAULTS)
        return s, path
    except Exception:
        return dict(PRISM_DEFAULTS), None


class PrismApp(PalisadeApp):
    """PRISM: an SDR++-style receiver. One rtl_tcp IQ stream drives the spectrum/waterfall and a
    VFO you tune by typing, clicking, dragging or the wheel, demodulated (AM/NFM/WFM/USB/LSB/CW)
    to audio with bandwidth, squelch, gain/AGC, zoom, bookmarks + preset banks and recording.
    The old rtl_power wide sweep stays as a source for spans wider than the IQ bandwidth."""
    TITLE = "PRISM"
    LEASE = None                 # the workers take the radio via the arbiter, not the base lease

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._cfg, self._cfg_path = _load_prism_settings()
        c = self._cfg
        self._source = "rtl" if demo else (c["source"] if c["source"] in ("rtl", "file", "sweep")
                                           else "rtl")
        self._vfo_hz = int(c["vfo_hz"])
        self._centre_hz = self._vfo_hz
        self._rate = int(c["rate"]) if int(c["rate"]) in dsp.SAMPLE_RATES else 2048000
        self._lo, self._hi = 430.0, 440.0          # wide-sweep band (MHz)
        self._peak_mhz = None
        self._user_stopped = False
        self._spec_seen = 0
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    # ------------------------------------------------------------------ keys / actions
    def handle_key(self, text):
        if self._source == "sweep":                 # D8: [ ] step the band, + / - span
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
        if text in "[]":                            # VFO one step down / up
            self._step_vfo(1 if text == "]" else -1)
            return True
        if text in "+=":
            self.scope.zoom_in()
            self._sync_zoom()
            return True
        if text in "-_":
            self.scope.zoom_out()
            self._sync_zoom()
            return True
        if text in "mM":                            # cycle demod mode
            i = self.mode_combo.currentIndex()
            self.mode_combo.setCurrentIndex((i + 1) % self.mode_combo.count())
            return True
        return False

    def primary_action(self):
        w = self._worker
        if w is not None and getattr(w, "held_off", False) and self._active:
            self._set_running(True)                 # resume after a revoke / PANIC / STOP
            return True
        return self._send_peak()

    def tune(self, mhz):
        """Palette: tune the VFO (and recentre) on a frequency."""
        if self._source == "sweep":
            self.centre.setValue(float(mhz))
        else:
            self._tune(int(round(float(mhz) * 1e6)), recentre=True)

    def _send_peak(self):
        """'Send to' (D10): hand the current peak to the PROWL FM tuner."""
        if self._peak_mhz is None:
            return False
        self.request.emit("tune_fm", self._peak_mhz)
        return True

    # ------------------------------------------------------------------ layout
    def build_body(self):
        tok = theme.tokens(self.mode)
        c = self._cfg
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # ---- tuning bar
        self.bar = bar = ControlBar()
        bar.lay.setSpacing(8)
        self.run_btn = QtWidgets.QPushButton("STOP")
        self.run_btn.setToolTip("Start / stop the receiver (stopping gives the radio back)")
        self.run_btn.setMinimumWidth(92)
        self.run_btn.clicked.connect(lambda: self._set_running(not self._running()))
        bar.lay.addWidget(self.run_btn)
        self.freq_edit = FreqEdit(iqsource.fmt_freq(self._vfo_hz))
        self.freq_edit.setProperty("class", "freq")
        self.freq_edit.setStyleSheet("font-size:26px; font-weight:600; padding:2px 6px;")
        self.freq_edit.setMinimumWidth(215)
        self.freq_edit.setMaximumWidth(260)
        self.freq_edit.setToolTip("Type a frequency and press Enter: 121.5  ·  446.0M  ·  "
                                  "7030k  ·  162550000\nWheel over a digit steps that digit")
        self.freq_edit.returnPressed.connect(self._typed_freq)
        self.freq_edit.digit_step.connect(self._digit_step)
        bar.add_field("freq", self.freq_edit, "VFO · MHz")
        self.down_btn = bar.add_button("◀", lambda: self._step_vfo(-1))
        self.up_btn = bar.add_button("▶", lambda: self._step_vfo(1))
        for b in (self.down_btn, self.up_btn):
            b.setFixedWidth(40)
            b.setToolTip("VFO down / up one step ([ ])")
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(list(dsp.MODES))
        # RA-RADIO N9: say what RAW is here (SDR++ RAW is stereo I/Q; this audio path is mono)
        self.mode_combo.setItemData(dsp.MODES.index("RAW"),
                                    "RAW: the I channel of the filtered baseband, mono "
                                    "(not stereo I/Q)", QtCore.Qt.ToolTipRole)
        self.mode_combo.setToolTip("Demodulator. RAW is mono (I channel only).")
        self.mode_combo.setCurrentText(c["mode"] if c["mode"] in dsp.MODES else "AM")
        bar.add_field("mode", self.mode_combo, "Mode")
        self.bw_spin = QtWidgets.QDoubleSpinBox()
        self.bw_spin.setDecimals(2)
        self.bw_spin.setSuffix(" kHz")
        self.bw_spin.setKeyboardTracking(False)
        self.bw_spin.setMaximumWidth(132)
        bar.add_field("bw", self.bw_spin, "Bandwidth")
        self.step_combo = QtWidgets.QComboBox()
        for label, hz in STEPS:
            self.step_combo.addItem(label, hz)
        idx = next((i for i, (_, hz) in enumerate(STEPS) if abs(hz - c["step"]) < 1), 2)
        self.step_combo.setCurrentIndex(idx)
        bar.add_field("step", self.step_combo, "Step")
        for cb in (self.mode_combo, self.step_combo):
            cb.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode_combo.setMinimumContentsLength(4)
        self.step_combo.setMinimumContentsLength(6)
        self.zoom_out_btn = bar.add_button("−", self._zoom_out)
        self.zoom_lbl = QtWidgets.QLabel("1×")
        self.zoom_lbl.setProperty("class", "value")
        self.zoom_lbl.setToolTip("Zoom (+ / −)")
        bar.lay.addWidget(self.zoom_lbl)
        self.zoom_in_btn = bar.add_button("+", self._zoom_in)
        for b in (self.zoom_out_btn, self.zoom_in_btn):
            b.setFixedWidth(40)
            b.setToolTip("Zoom the spectrum around the VFO (+ / −)")
        bar.add_stretch()
        self.panel_btn = bar.add_button("PANEL", self._toggle_panel)
        self.panel_btn.setCheckable(False)
        self.panel_btn.setToolTip("Show / hide the settings panel (P)")
        lay.addWidget(bar)

        self.busy = QtWidgets.QLabel("")
        self.busy.setProperty("class", "note")
        self.busy.setWordWrap(True)
        self.busy.setStyleSheet("color:%s;" % tok["warn"])
        self.busy.hide()
        lay.addWidget(self.busy)

        # ---- scope + side panel
        mid = QtWidgets.QHBoxLayout()
        mid.setSpacing(8)
        self.scope = TunerScope(mode=self.mode)
        self.scope.vfo_requested.connect(lambda hz: self._tune(hz))
        self.scope.wheel_step.connect(self._step_vfo)
        self.scope.bw_requested.connect(self._bw_dragged)
        mid.addWidget(self.scope, 1)
        self.side = self._build_side(c)
        mid.addWidget(self.side)
        lay.addLayout(mid, 1)

        # ---- signal bar
        sig = ControlBar()
        sig.lay.setSpacing(10)
        sig.lay.addWidget(micro("Signal"))
        self.meter = QtWidgets.QProgressBar()
        self.meter.setRange(-100, 0)
        self.meter.setValue(-100)
        self.meter.setTextVisible(False)
        self.meter.setFixedSize(180, 14)
        sig.lay.addWidget(self.meter)
        self.level_lbl = QtWidgets.QLabel("— dBFS")
        self.level_lbl.setProperty("class", "value")
        self.level_lbl.setMinimumWidth(120)
        sig.lay.addWidget(self.level_lbl)
        self.sq_lbl = QtWidgets.QLabel("")
        self.sq_lbl.setProperty("class", "note")
        sig.lay.addWidget(self.sq_lbl)
        self.rec_lbl = QtWidgets.QLabel("")
        self.rec_lbl.setProperty("class", "note")
        self.rec_lbl.setStyleSheet("color:%s;" % tok["alert"])
        sig.lay.addWidget(self.rec_lbl)
        sig.add_stretch()
        sig.lay.addWidget(micro("Peak"))
        self.readout = QtWidgets.QLabel("—")
        self.readout.setProperty("class", "value")
        sig.lay.addWidget(self.readout)
        self.send_btn = QtWidgets.QPushButton("PEAK → PROWL FM")
        self.send_btn.setToolTip("Tune the PROWL FM receiver to the current peak (Enter)")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send_peak)
        sig.lay.addWidget(self.send_btn)
        lay.addWidget(sig)

        # wire after everything exists
        self.mode_combo.currentTextChanged.connect(self._mode_changed)
        self.bw_spin.valueChanged.connect(self._bw_changed)
        self.step_combo.currentIndexChanged.connect(self._step_changed)
        self._mode_changed(self.mode_combo.currentText(), bw=c["bw"], initial=True)
        self._step_changed()
        self.scope.set_levels(c["wf_lo"], c["wf_hi"])
        self.scope.set_smoothing(float(c["smooth"]))
        self._sync_source_rows()
        self._refresh_bookmarks()
        self._sync_run_btn()
        sc = QtGui.QShortcut(QtGui.QKeySequence("P"), body)
        sc.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self._toggle_panel)
        self._toggle_panel(force=True)
        return body

    def _build_side(self, c):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(340)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(6)
        scroll.setWidget(inner)

        # SOURCE
        s = self.sec_source = Section("SOURCE")
        self.source_combo = QtWidgets.QComboBox()
        for label, key in SOURCES:
            self.source_combo.addItem(label, key)
        self.source_combo.setCurrentIndex([k for _, k in SOURCES].index(self._source))
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        s.row("Input", self.source_combo)
        fbox = QtWidgets.QWidget()
        fl = QtWidgets.QHBoxLayout(fbox)
        fl.setContentsMargins(0, 0, 0, 0)
        self.file_edit = QtWidgets.QLineEdit(c.get("file", ""))
        self.file_edit.setPlaceholderText("…/recording.cu8 or .wav")
        self.file_edit.returnPressed.connect(self._file_chosen)
        fl.addWidget(self.file_edit, 1)
        self.file_btn = QtWidgets.QPushButton("OPEN")
        self.file_btn.clicked.connect(self._browse_file)
        fl.addWidget(self.file_btn)
        self._file_row = s.row("IQ file", fbox)
        self.rate_combo = QtWidgets.QComboBox()
        for r in dsp.SAMPLE_RATES:
            self.rate_combo.addItem("%.3f MS/s" % (r / 1e6), r)
        self.rate_combo.setCurrentIndex(list(dsp.SAMPLE_RATES).index(self._rate))
        self.rate_combo.currentIndexChanged.connect(self._rate_changed)
        s.row("Sample rate", self.rate_combo)
        self.ppm = QtWidgets.QSpinBox()
        self.ppm.setRange(-200, 200)
        self.ppm.setValue(int(c["ppm"]))
        self.ppm.setSuffix(" ppm")
        self.ppm.valueChanged.connect(lambda v: self._queue(ppm=v, _save={"ppm": v}))
        s.row("Freq. correction", self.ppm)
        # wide sweep (rtl_power) band: kept from the original PRISM
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
        self.centre.valueChanged.connect(self._retune)
        self.span.valueChanged.connect(self._retune)
        self.gain.valueChanged.connect(self._retune)
        self._sweep_rows = [s.row("Sweep centre", self.centre), s.row("Sweep span", self.span),
                            s.row("Sweep gain", self.gain)]
        v.addWidget(s)

        # GAIN
        g = self.sec_gain = Section("GAIN")
        self.auto_gain = QtWidgets.QCheckBox("Tuner auto gain")
        self.auto_gain.setChecked(bool(c["auto_gain"]))
        g.row("", self.auto_gain)
        gbox = QtWidgets.QWidget()
        gl = QtWidgets.QHBoxLayout(gbox)
        gl.setContentsMargins(0, 0, 0, 0)
        self.gain_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.gain_slider.setRange(0, len(dsp.RTL_GAINS) - 1)
        gi = min(range(len(dsp.RTL_GAINS)), key=lambda i: abs(dsp.RTL_GAINS[i] - c["gain_db"]))
        self.gain_slider.setValue(gi)
        gl.addWidget(self.gain_slider, 1)
        self.gain_lbl = QtWidgets.QLabel("")
        self.gain_lbl.setMinimumWidth(70)
        gl.addWidget(self.gain_lbl)
        g.row("RF gain", gbox)
        self.rtl_agc = QtWidgets.QCheckBox("RTL digital AGC")
        self.rtl_agc.setChecked(bool(c["rtl_agc"]))
        g.row("", self.rtl_agc)
        self.auto_gain.toggled.connect(self._gain_changed)
        self.gain_slider.valueChanged.connect(self._gain_changed)
        self.rtl_agc.toggled.connect(lambda on: self._queue(rtl_agc=on, _save={"rtl_agc": on}))
        v.addWidget(g)

        # RADIO
        r = self.sec_radio = Section("RADIO")
        self.sq_on = QtWidgets.QCheckBox("Squelch")
        self.sq_on.setChecked(bool(c["squelch_on"]))
        r.row("", self.sq_on)
        sbox = QtWidgets.QWidget()
        sl = QtWidgets.QHBoxLayout(sbox)
        sl.setContentsMargins(0, 0, 0, 0)
        self.sq_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sq_slider.setRange(-110, 0)
        self.sq_slider.setValue(int(c["squelch_db"]))
        sl.addWidget(self.sq_slider, 1)
        self.sq_val = QtWidgets.QLabel("")
        self.sq_val.setMinimumWidth(70)
        sl.addWidget(self.sq_val)
        r.row("Squelch level", sbox)
        self.audio_agc = QtWidgets.QCheckBox("Audio AGC")
        self.audio_agc.setChecked(bool(c["audio_agc"]))
        r.row("", self.audio_agc)
        self.audio_on = QtWidgets.QCheckBox("Audio out")
        self.audio_on.setChecked(bool(c["audio"]))
        r.row("", self.audio_on)
        self.deemph = QtWidgets.QComboBox()
        for label, us in (("75 µs (US)", 75), ("50 µs (EU)", 50), ("off", 0)):
            self.deemph.addItem(label, us)
        self.deemph.setCurrentIndex({75: 0, 50: 1, 0: 2}.get(int(c["deemph_us"]), 0))
        r.row("WFM de-emphasis", self.deemph)
        self.sq_on.toggled.connect(self._sq_changed)
        self.sq_slider.valueChanged.connect(self._sq_changed)
        self.audio_agc.toggled.connect(
            lambda on: self._queue(audio_agc=on, _save={"audio_agc": on}))
        self.audio_on.toggled.connect(lambda on: self._queue(audio=on, _save={"audio": on}))
        self.deemph.currentIndexChanged.connect(
            lambda _i: self._queue(deemph_us=self.deemph.currentData(),
                                   _save={"deemph_us": self.deemph.currentData()}))
        v.addWidget(r)

        # DISPLAY
        d = self.sec_display = Section("DISPLAY", open_=False)
        self.fft_combo = QtWidgets.QComboBox()
        for n in FFT_SIZES:
            self.fft_combo.addItem(str(n), n)
        self.fft_combo.setCurrentIndex(FFT_SIZES.index(c["nfft"]) if c["nfft"] in FFT_SIZES
                                       else 2)
        self.fft_combo.currentIndexChanged.connect(
            lambda _i: self._queue(nfft=self.fft_combo.currentData(),
                                   _save={"nfft": self.fft_combo.currentData()}))
        d.row("FFT size", self.fft_combo)
        self.smooth_combo = QtWidgets.QComboBox()
        for label, w in SMOOTHING:
            self.smooth_combo.addItem(label, w)
        idx = [w for _l, w in SMOOTHING].index(c["smooth"]) if c["smooth"] in \
            [w for _l, w in SMOOTHING] else 0
        self.smooth_combo.setCurrentIndex(idx)
        self.smooth_combo.currentIndexChanged.connect(self._smooth_changed)
        d.row("FFT smoothing", self.smooth_combo)
        self.wf_lo = QtWidgets.QSpinBox()
        self.wf_lo.setRange(-150, 0)
        self.wf_lo.setValue(int(c["wf_lo"]))
        self.wf_lo.setSuffix(" dB")
        self.wf_hi = QtWidgets.QSpinBox()
        self.wf_hi.setRange(-140, 20)
        self.wf_hi.setValue(int(c["wf_hi"]))
        self.wf_hi.setSuffix(" dB")
        self.wf_lo.valueChanged.connect(self._levels_changed)
        self.wf_hi.valueChanged.connect(self._levels_changed)
        d.row("Floor", self.wf_lo)
        d.row("Top", self.wf_hi)
        self.auto_lv = QtWidgets.QPushButton("AUTO LEVELS")
        self.auto_lv.clicked.connect(self._auto_levels)
        d.row("", self.auto_lv)
        v.addWidget(d)

        # RECORD
        rc = self.sec_rec = Section("RECORD")
        rb = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(rb)
        rl.setContentsMargins(0, 0, 0, 0)
        self.rec_audio_btn = QtWidgets.QPushButton("REC AUDIO")
        self.rec_audio_btn.setCheckable(True)
        self.rec_audio_btn.toggled.connect(lambda on: self._queue(rec_audio=on))
        self.rec_iq_btn = QtWidgets.QPushButton("REC IQ")
        self.rec_iq_btn.setCheckable(True)
        self.rec_iq_btn.toggled.connect(lambda on: self._queue(rec_iq=on))
        rl.addWidget(self.rec_audio_btn)
        rl.addWidget(self.rec_iq_btn)
        rc.row("", rb)
        self.rec_note = note("Audio → .wav, baseband → .cu8 (+ .json) in "
                             "~/.local/share/uconsole-suite/recordings")
        rc.row("", self.rec_note)
        v.addWidget(rc)

        # BOOKMARKS + preset banks
        b = self.sec_bm = Section("BOOKMARKS · BANKS")
        self.bank_combo = QtWidgets.QComboBox()
        self.bank_combo.addItem("My bookmarks")
        self.bank_combo.addItems(banks.BANK_ORDER)
        self.bank_combo.currentIndexChanged.connect(self._refresh_bookmarks)
        b.row("List", self.bank_combo)
        self.bm_list = QtWidgets.QListWidget()
        self.bm_list.setMinimumHeight(170)
        self.bm_list.itemActivated.connect(self._bm_tune)
        self.bm_list.itemClicked.connect(self._bm_tune)
        b.row("", self.bm_list)
        abox = QtWidgets.QWidget()
        al = QtWidgets.QHBoxLayout(abox)
        al.setContentsMargins(0, 0, 0, 0)
        self.bm_name = QtWidgets.QLineEdit()
        self.bm_name.setPlaceholderText("name")
        al.addWidget(self.bm_name, 1)
        self.bm_add = QtWidgets.QPushButton("ADD")
        self.bm_add.setToolTip("Bookmark the VFO frequency, mode and bandwidth")
        self.bm_add.clicked.connect(self._bm_add)
        al.addWidget(self.bm_add)
        self.bm_del = QtWidgets.QPushButton("DEL")
        self.bm_del.clicked.connect(self._bm_delete)
        al.addWidget(self.bm_del)
        b.row("", abox)
        v.addWidget(b)
        v.addStretch(1)
        self._gain_changed(initial=True)
        self._sq_changed(initial=True)
        return scroll

    # ------------------------------------------------------------------ helpers
    def _save(self, **kw):
        self._cfg.update(kw)
        if self._cfg_path and not self.demo:
            try:
                import suite
                suite.save_json(self._cfg_path, self._cfg)
            except Exception:
                pass

    def _queue(self, _save=None, **kw):
        if _save:
            self._save(**_save)
        w = self._worker
        if w is not None and hasattr(w, "queue"):
            w.queue(**kw)

    def _toggle_panel(self, force=False):
        if not force:
            self.side.setVisible(not self.side.isVisible())
        self.panel_btn.setText("PANEL" if not self.side.isHidden() else "PANEL ◂")

    def _sync_zoom(self):
        self.zoom_lbl.setText("%d×" % self.scope.zoom)

    def _zoom_in(self):
        self.scope.zoom_in()
        self._sync_zoom()

    def _zoom_out(self):
        self.scope.zoom_out()
        self._sync_zoom()

    def _levels_changed(self, *_):
        self.scope.set_levels(self.wf_lo.value(), self.wf_hi.value())
        self._save(wf_lo=self.wf_lo.value(), wf_hi=self.wf_hi.value())

    def _auto_levels(self):
        lo, hi = self.scope.auto_levels()
        for w, val in ((self.wf_lo, lo), (self.wf_hi, hi)):
            w.blockSignals(True)
            w.setValue(int(round(val)))
            w.blockSignals(False)
        self._save(wf_lo=int(round(lo)), wf_hi=int(round(hi)))

    def _step_hz(self):
        return float(self.step_combo.currentData() or 25000)

    def _step_changed(self, *_):
        self.scope.set_step(self._step_hz())
        self._save(step=self._step_hz())

    def _step_vfo(self, n):
        if self._source == "sweep":
            return
        step = self._step_hz()
        hz = round((self._vfo_hz + n * step) / step) * step
        self._tune(int(round(hz)))

    def _digit_step(self, delta_hz):
        if self._source == "sweep":
            return
        self._tune(int(self._vfo_hz + delta_hz))

    def _bw_dragged(self, hz):
        if self._source == "sweep":
            return
        mode = self.mode_combo.currentText()
        self.bw_spin.setValue(dsp.clamp_bw(mode, hz) / 1000.0)   # bw_spin handler queues + saves

    def _smooth_changed(self, *_):
        w = float(self.smooth_combo.currentData())
        self.scope.set_smoothing(w)
        self._save(smooth=w)

    def _typed_freq(self):
        try:
            hz = iqsource.parse_freq(self.freq_edit.text())
        except ValueError as e:
            self.freq_edit.setText(iqsource.fmt_freq(self._vfo_hz))
            self.busy.setText("Frequency refused: %s" % e)
            self.busy.show()
            return
        self.busy.hide()
        self._tune(hz, recentre=True)

    def _tune(self, hz, recentre=False, mode=None, bw=None):
        """Move the VFO. Recentres the receiver when asked (typed / bookmark) or when the VFO
        leaves the captured band. A file cannot retune: the VFO is kept inside its band."""
        hz = int(min(max(hz, 24_000_000), 1_766_000_000))
        half = 0.45 * self._rate
        if self._source == "file":
            hz = int(min(max(hz, self._centre_hz - half), self._centre_hz + half))
        elif recentre or abs(hz - self._centre_hz) > half:
            self._centre_hz = hz
        self._vfo_hz = hz
        if mode and mode in dsp.MODES and mode != self.mode_combo.currentText():
            self.mode_combo.setCurrentText(mode)        # rebuilds the demod with its default bw
        if bw:
            self.bw_spin.setValue(float(bw) / 1000.0)
        self.freq_edit.setText(iqsource.fmt_freq(hz))
        self.scope.set_vfo(hz)
        kw = {"vfo_hz": hz}
        if self._source != "file":
            kw["centre_hz"] = self._centre_hz
        self._queue(_save={"vfo_hz": hz}, **kw)

    def _mode_changed(self, mode, bw=None, initial=False):
        lo, hi = dsp.BW_LIMITS[mode]
        bw = dsp.clamp_bw(mode, bw if bw else dsp.DEFAULT_BW[mode])
        self.bw_spin.blockSignals(True)
        self.bw_spin.setRange(lo / 1000.0, hi / 1000.0)
        self.bw_spin.setSingleStep(0.5 if hi <= 5000 else 2.5)
        self.bw_spin.setValue(bw / 1000.0)
        self.bw_spin.blockSignals(False)
        self.scope.set_vfo(self._vfo_hz, bw, mode)
        if not initial:
            step = dsp.DEFAULT_STEP.get(mode)
            i = next((k for k, (_, hz) in enumerate(STEPS) if abs(hz - step) < 1), None)
            if i is not None and mode in ("USB", "LSB", "CW", "WFM"):
                self.step_combo.setCurrentIndex(i)
            self._queue(mode=mode, bw=bw, _save={"mode": mode, "bw": bw})

    def _bw_changed(self, khz):
        bw = float(khz) * 1000.0
        self.scope.set_vfo(self._vfo_hz, bw)
        self._queue(bw=bw, _save={"bw": bw})

    def _gain_changed(self, *_a, initial=False):
        auto = self.auto_gain.isChecked()
        g = dsp.RTL_GAINS[self.gain_slider.value()]
        self.gain_slider.setEnabled(not auto)
        self.gain_lbl.setText("AUTO" if auto else "%.1f dB" % g)
        if not initial:
            self._queue(gain_db=None if auto else g, _save={"auto_gain": auto, "gain_db": g})

    def _gain_db(self):
        return None if self.auto_gain.isChecked() else dsp.RTL_GAINS[self.gain_slider.value()]

    def _sq_changed(self, *_a, initial=False):
        on = self.sq_on.isChecked()
        db = float(self.sq_slider.value())
        self.sq_slider.setEnabled(on)
        self.sq_val.setText("%d dB" % db if on else "off")
        self.scope.set_squelch_line(None)            # channel power is not a per-bin level
        if not initial:
            self._queue(squelch_db=db if on else None, _save={"squelch_on": on, "squelch_db": db})

    def _rate_changed(self, *_):
        self._rate = int(self.rate_combo.currentData())
        self._save(rate=self._rate)
        self._queue(rate=self._rate)
        self.scope.clear()

    # ---- source
    def _sync_source_rows(self):
        sweep = self._source == "sweep"
        for w in self._sweep_rows:
            w.setVisible(sweep)
            lbl = self.sec_source.form.labelForField(w)
            if lbl is not None:
                lbl.setVisible(sweep)
        f = self._source == "file"
        self._file_row.setVisible(f)
        lbl = self.sec_source.form.labelForField(self._file_row)
        if lbl is not None:
            lbl.setVisible(f)
        for w in (self.freq_edit, self.down_btn, self.up_btn, self.mode_combo, self.bw_spin,
                  self.step_combo, self.rate_combo, self.ppm, self.sec_gain, self.sec_radio,
                  self.sec_rec):
            w.setEnabled(not sweep)

    def _source_changed(self, *_):
        key = self.source_combo.currentData()
        if key == self._source:
            return
        self._source = key
        self._save(source=key)
        self._sync_source_rows()
        self.scope.clear()
        for b in (self.rec_audio_btn, self.rec_iq_btn):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        if key == "file":
            self._file_chosen(swap=False)
        self.swap_worker()

    def _browse_file(self):
        start = self.file_edit.text() or iqsource.rec_dir()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open IQ recording", start, "IQ recordings (*.cu8 *.raw *.bin *.wav)")
        if path:
            self.file_edit.setText(path)
            self._file_chosen()

    def _file_chosen(self, swap=True):
        path = self.file_edit.text().strip()
        self._save(file=path)
        if not path:
            return
        try:
            meta = iqsource.file_meta(path)
        except iqsource.SourceError as e:
            self.busy.setText("IQ file refused: %s" % e)
            self.busy.show()
            return
        if meta.get("rate"):
            self._rate = int(meta["rate"])
        if meta.get("centre_hz"):
            self._centre_hz = self._vfo_hz = int(meta["centre_hz"])
            self.freq_edit.setText(iqsource.fmt_freq(self._vfo_hz))
            self.scope.set_vfo(self._vfo_hz)
        if swap and self._source == "file":
            self.swap_worker()

    # ---- run state
    def _running(self):
        w = self._worker
        return (w is not None and not self._user_stopped and not getattr(w, "held_off", False)
                and not getattr(self, "_faulted", False)
                and not (w.isFinished() and not self.swapping()))   # B3: a dead thread is off

    def _set_running(self, on):
        w = self._worker
        self._user_stopped = not on
        if w is not None:
            if on and w.isFinished() and self._active and not self.swapping():
                self._faulted = False            # RA-RADIOb B3: START restarts a dead worker
                self.swap_worker()
                self.busy.hide()
            elif on:
                self._faulted = False
                if getattr(w, "faulted", False):
                    w.retry_now()                # RA-RADIOc C1: START retries at once
                if hasattr(w, "set_active"):
                    w.set_active(self._active)
                self.busy.hide()
            elif hasattr(w, "hold_off"):
                w.hold_off("stopped by operator")
        self._sync_run_btn()

    def _sync_run_btn(self):
        on = self._running()
        self.run_btn.setText("STOP" if on else "START")
        set_run(self.run_btn, on)

    # ---- bookmarks
    def _bookmarks(self):
        out = []
        for b in self._cfg.get("bookmarks") or []:
            try:
                out.append({"hz": int(b["hz"]), "label": str(b.get("label", "")),
                            "mode": b.get("mode") if b.get("mode") in dsp.MODES else "NFM",
                            "bw": float(b.get("bw") or 0) or None})
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def _refresh_bookmarks(self, *_):
        self.bm_list.clear()
        name = self.bank_combo.currentText()
        if name == "My bookmarks":
            items = [(b["hz"], b["label"], b["mode"], b["bw"]) for b in self._bookmarks()]
            self.bm_del.setEnabled(True)
        else:
            bank = banks.BANKS[name]
            items = [(int(round(f * 1e6)), lb, bank["mode"], bank["bw"])
                     for f, lb in bank["channels"]]
            if not items and bank["ranges"]:
                a, z, st = bank["ranges"][0]
                items = [(int(round(a * 1e6)), "range start %.3f–%.3f" % (a, z), bank["mode"],
                          bank["bw"])]
            self.bm_del.setEnabled(False)
        for hz, label, mode, bw in items:
            it = QtWidgets.QListWidgetItem("%.4f  %s  %s" % (hz / 1e6, mode, label))
            it.setData(QtCore.Qt.UserRole, (hz, label, mode, bw))
            it.setToolTip(label)
            self.bm_list.addItem(it)
        self.scope.set_bookmarks([(hz, lb) for hz, lb, _m, _b in items])

    def _bm_tune(self, item):
        hz, label, mode, bw = item.data(QtCore.Qt.UserRole)
        if self._source == "sweep":
            self.centre.setValue(hz / 1e6)
            return
        self._tune(int(hz), recentre=True, mode=mode, bw=bw)

    def _bm_add(self):
        name = self.bm_name.text().strip() or "%.4f" % (self._vfo_hz / 1e6)
        bms = self._cfg.get("bookmarks") or []
        bms.append({"hz": self._vfo_hz, "label": name[:40], "mode": self.mode_combo.currentText(),
                    "bw": self.bw_spin.value() * 1000.0})
        self._save(bookmarks=bms)
        self.bm_name.clear()
        self.bank_combo.setCurrentIndex(0)
        self._refresh_bookmarks()

    def _bm_delete(self):
        it = self.bm_list.currentItem()
        if it is None or self.bank_combo.currentIndex() != 0:
            return
        hz, label, _m, _b = it.data(QtCore.Qt.UserRole)
        bms = [b for b in (self._cfg.get("bookmarks") or [])
               if not (int(b.get("hz", 0)) == hz and b.get("label", "") == label)]
        self._save(bookmarks=bms)
        self._refresh_bookmarks()

    # ------------------------------------------------------------------ sweep (rtl_power)
    def _retune(self):
        c, s = self.centre.value(), self.span.value()
        self._lo, self._hi = c - s / 2, c + s / 2
        w = self._worker
        if isinstance(w, SweepWorker):
            w.gain = self.gain.value()
            w.set_band(self._lo, self._hi)

    # ------------------------------------------------------------------ worker
    def on_panic(self):
        """PANIC (CL5-fix 5): stop and stay off; Enter or the START button resumes."""
        w = self._worker
        if w is not None and hasattr(w, "hold_off") and not self.demo:
            w.hold_off("PANIC")
        self._sync_run_btn()
        return []

    def make_worker(self):
        self._spec_seen = 0
        if self._source == "sweep":
            w = SweepWorker(demo=self.demo, lo=self._lo, hi=self._hi, gain=self.gain.value())
        else:
            src = "demo" if self.demo else self._source
            if src == "file":
                try:
                    meta = iqsource.file_meta(self.file_edit.text().strip()) \
                        if self.file_edit.text().strip() else {}
                except iqsource.SourceError:
                    meta = {}
                if meta.get("centre_hz"):
                    self._centre_hz = int(meta["centre_hz"])
                if meta.get("rate"):
                    self._rate = int(meta["rate"])
            w = TunerWorker(demo=self.demo, source=src, file_path=self.file_edit.text().strip(),
                            centre_hz=self._centre_hz, rate=self._rate, gain_db=self._gain_db(),
                            ppm=self.ppm.value(), agc=self.rtl_agc.isChecked(),
                            mode=self.mode_combo.currentText(), bw=self.bw_spin.value() * 1000.0,
                            vfo_hz=self._vfo_hz,
                            squelch_db=float(self.sq_slider.value()) if self.sq_on.isChecked()
                            else None,
                            audio_agc=self.audio_agc.isChecked(), nfft=self.fft_combo.currentData(),
                            audio=self.audio_on.isChecked(), deemph_us=self.deemph.currentData())
        if not self.demo:
            w.set_active(self._active and not self._user_stopped)
        if self._user_stopped and hasattr(w, "hold_off") and not self.demo:
            w.hold_off("stopped by operator")
        return w

    def set_active(self, active):
        super().set_active(active)
        if not self.demo and self._worker is not None and hasattr(self._worker, "set_active"):
            if not (active and self._user_stopped):
                self._worker.set_active(active)      # hold the radio only while PRISM is in front
        self._sync_run_btn()

    def on_swapped(self):
        self._sync_run_btn()

    def on_status(self, status):
        super().on_status(status)                    # chips (incl. SDR PRISM/BUSY/STANDBY)
        # RA-RADIO N2: a faulted / stopped receiver is never shown green; live data clears it
        if status.get("fault") or status.get("off") or status.get("standby"):
            self._faulted = True
        elif status.get("live") or (status.get("sdr") or {}).get("state") == "neutral":
            self._faulted = False
        if status.get("off") or status.get("acquiring"):
            text = (status.get("sdr") or {}).get("text", "")
            if status.get("off") and getattr(self._worker, "held_off", False):
                text += "  ·  press Enter or START to resume"
            self.busy.setText(text)
            self.busy.show()
        elif status.get("standby"):                    # live + no radio tool: honest, no fake
            self.busy.setText("STANDBY — %s (no synthetic spectrum)" % (
                (status.get("sdr") or {}).get("text", "").split(" — ", 1)[-1] or "no radio"))
            self.busy.show()
        elif status.get("fault") or status.get("stale"):    # H2: frozen data is never green
            self.busy.setText((status.get("sdr") or {}).get("text", ""))
            self.busy.show()
        elif "busy" in status:
            owner = status["busy"]
            if owner:
                self.busy.setText("RADIO BUSY — held by %s" % owner)
                self.busy.show()
            else:
                self.busy.hide()
        self._sync_run_btn()

    def on_row(self, row):
        if isinstance(row, dict):
            kind = row.get("kind")
            if kind == "spec":
                return self._on_spec(row)
            if kind == "rec":
                return self._on_rec(row)
            return None
        freqs, power = row                           # wide sweep (rtl_power)
        self.scope.push(power, float(freqs[0]) * 1e6, float(freqs[-1]) * 1e6)
        self._set_peak(float(np.max(power)), float(freqs[int(np.argmax(power))]))
        return None

    def _set_peak(self, peak_db, peak_mhz, unit="dB rel"):
        # H13: no absolute power units (uncalibrated). rtl_power sweep = uncalibrated "dB rel"; IQ receiver = dBFS
        self.readout.setText("%.0f %s @ %.4f MHz" % (peak_db, unit, peak_mhz))
        self._peak_mhz = peak_mhz
        self.send_btn.setEnabled(True)

    def _on_spec(self, row):
        db, centre, rate = row["db"], row["centre_hz"], row["rate"]
        self._centre_hz = int(centre)
        if row.get("source") == "file" and int(row["rate"]) != self._rate:
            self._rate = int(rate)
        self.scope.push(db, centre - rate / 2.0, centre + rate / 2.0)
        self._spec_seen += 1
        if self._spec_seen == 3 and self._cfg.get("wf_lo") == PRISM_DEFAULTS["wf_lo"] \
                and self._cfg.get("wf_hi") == PRISM_DEFAULTS["wf_hi"]:
            self._auto_levels()                      # first look: fit the colours to the floor
        if int(row["vfo_hz"]) != self._vfo_hz and row.get("source") == "file":
            self._vfo_hz = int(row["vfo_hz"])        # the worker clamped the VFO to the file
            self.freq_edit.setText(iqsource.fmt_freq(self._vfo_hz))
            self.scope.set_vfo(self._vfo_hz)
        k = int(np.argmax(db))
        self._set_peak(float(db[k]), (centre + (k - db.size // 2) * rate / db.size) / 1e6,
                       unit="dBFS")
        lvl = float(row["level"])
        self.meter.setValue(int(max(-100, min(0, lvl))))
        self.level_lbl.setText("%.1f dBFS" % lvl)
        sq = self.sq_on.isChecked()
        self.sq_lbl.setText(("SQ OPEN" if row["open"] else "SQ CLOSED") if sq else "")
        bits = []
        if row.get("rec_audio_s") is not None:
            bits.append("● REC AUDIO %ds" % int(row["rec_audio_s"]))
        if row.get("rec_iq_s") is not None:
            bits.append("● REC IQ %ds" % int(row["rec_iq_s"]))
        self.rec_lbl.setText("  ".join(bits))

    def _on_rec(self, row):
        btn = self.rec_iq_btn if row["which"] == "iq" else self.rec_audio_btn
        btn.blockSignals(True)
        btn.setChecked(bool(row["on"]))
        btn.blockSignals(False)
        set_run(btn, bool(row["on"])) if row["on"] else self._unrun(btn)
        if row["on"]:
            self.rec_note.setText("Recording → %s" % row["path"])
        else:
            self.rec_note.setText("Saved %s%s" % (row["path"],
                                                  (" (%s)" % row["why"]) if row.get("why")
                                                  and row["why"] != "stopped" else ""))

    @staticmethod
    def _unrun(btn):
        btn.setProperty("run", None)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
