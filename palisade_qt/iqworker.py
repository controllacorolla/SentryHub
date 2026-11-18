"""IQ workers — the live receive path behind PRISM's tuner and PROWL's fast scanner.

One rtl_tcp (iqsource.RtlTcpSource) holds the dongle; frequency / gain / rate changes go over its
control socket, so tuning never restarts the radio. A worker that needs the radio owns it ONLY
through radio_arbiter, with the same rules as every other radio holder (CL5-fix):

  1. the source opens only once the arbiter says HELD for this worker's name;
  2. give-back is close source (rtl_tcp killed + waited) -> release, on the worker thread;
  3. GUI-thread entry points only set flags / queue settings and poke;
  4. every give-back emits an OFF status.

File playback needs no radio and never touches the arbiter. Demo uses SynthSource (flagged DEMO).
Under offscreen/offline (tests, CI) no real radio is opened: tests inject `source_factory`.
"""
import math
import threading
import time

import numpy as np

import dsp
import iqsource

from . import radio_arbiter
from .worker import Worker
from .kit.seams import offscreen as _offscreen

BLOCK_S = 0.05            # IQ block per read (50 ms)
SPEC_FPS = 12.0           # spectrum frames per second sent to the GUI
STATUS_EVERY_S = 0.5
FAULT_RETRY_S = 5.0
NO_DATA_FAULT_S = 3.0     # live source delivering nothing this long = FAULT


class IqWorker(Worker):
    """Base: source lifecycle + arbiter ownership. Subclasses implement process_block()."""
    NAME = "PRISM"
    LABEL = "SDR"
    PAUSE_WHEN_HIDDEN = False          # keeps stepping while hidden so it can release the dongle

    def __init__(self, demo=False, source="rtl", file_path=None, centre_hz=121_500_000,
                 rate=2048000, gain_db=None, ppm=0, agc=False, source_factory=None, parent=None):
        super().__init__(demo=demo, interval_ms=50, parent=parent)
        self.source_kind = "demo" if demo else source
        self.file_path = file_path
        self.centre_hz = int(centre_hz)
        self.rate = int(rate)
        self.gain_db = gain_db
        self.ppm = int(ppm)
        self.rtl_agc = bool(agc)
        self._factory = source_factory
        self._src = None
        self._lock = threading.Lock()
        self._pending = {}
        self._active = True
        self._held_off = False
        self._why = "page hidden"
        self._has_radio = False
        self._fault = None
        self._last_data = None
        self._last_status = 0.0
        radio_arbiter.arbiter.revoked.connect(self._on_revoked)

    # ---------------- GUI-thread entry points: flags + poke only
    def needs_radio(self):
        return self.source_kind == "rtl"

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
        if name == self.NAME:
            self.hold_off("radio given back")

    def hold_off(self, reason):
        self._held_off = True
        self._active = False
        self._why = reason
        self.poke()

    @property
    def held_off(self):
        return self._held_off

    def queue(self, **kw):
        """Queue setting changes (applied on the worker thread at the next block)."""
        with self._lock:
            self._pending.update(kw)
        self.poke()

    # ---------------- worker thread
    def _take_pending(self):
        with self._lock:
            p, self._pending = self._pending, {}
        return p

    def _make_source(self):
        if self._factory is not None:
            return self._factory(self)
        k = self.source_kind
        if k == "demo":
            return iqsource.SynthSource(self.centre_hz, self.rate)
        if k == "file":
            if not self.file_path:
                raise iqsource.SourceError("no IQ file chosen")
            return iqsource.FileSource(self.file_path)
        if _offscreen():
            return None                                  # tests / CI never open a real radio
        return iqsource.RtlTcpSource(self.centre_hz, self.rate, self.gain_db, self.ppm,
                                     self.rtl_agc)

    def _status(self, text, state, **extra):
        d = {"busy": None, "sdr": {"text": text, "state": state}}
        d.update(extra)
        self.status.emit(d)

    def _close_source(self):
        src, self._src = self._src, None
        if src is not None:
            try:
                src.close()                              # rtl_tcp: terminate + wait (no zombie)
            except Exception:
                pass
        self.on_source_closed()

    def _release(self, why=None):
        self._close_source()
        if self._has_radio:
            radio_arbiter.arbiter.release(self.NAME)
            self._has_radio = False
        if why:
            self._status("%s OFF — %s" % (self.LABEL, why), "warn", live=False, off=True)

    def _ensure_radio(self):
        """True while we may run: radio HELD by us (rtl) or no radio needed (file / demo)."""
        if not self.needs_radio():
            if not self._active and self._src is not None and self.source_kind == "file":
                pass                                       # playback keeps running while hidden
            return True
        if not self._active:
            if self._has_radio or self._src is not None:
                self._release(self._why)
            return False
        arb = radio_arbiter.arbiter
        if not self._has_radio:
            if arb.request(self.NAME):
                self._has_radio = True
            else:
                self._status(radio_arbiter.busy_text(self.NAME).replace("RADIO BUSY", "SDR BUSY"),
                             "warn", busy=radio_arbiter.owner_label(), live=False)
                return False
        st, owner = arb.state()
        if owner != self.NAME:                           # freed under us (forced free / PANIC)
            self._has_radio = False
            self._close_source()
            self._held_off = True
            self._active = False
            self._status("%s OFF — %s" % (self.LABEL, radio_arbiter.lost_reason(self.NAME)),
                         "warn", live=False, off=True)
            return False
        if st != "HELD":
            self._status("%s ACQUIRING" % self.LABEL, "warn", live=False, acquiring=True)
            return False
        return True

    def _open(self):
        if self._fault is not None and time.monotonic() - self._fault[1] < FAULT_RETRY_S:
            self._status(("%s FAULT — %s" % (self.LABEL, self._fault[0]))[:90], "alert",
                         fault=self._fault[0], live=False)
            return False
        try:
            src = self._make_source()
            if src is None:
                self._status("%s STANDBY — offline (no capture)" % self.LABEL, "warn",
                             standby=True, live=False)
                return False
            if getattr(src, "kind", None) == "rtl":
                # RA-RADIO N5: a revoke / PANIC / stop during rtl_tcp start-up aborts it now
                src.open(abort=lambda: self._stop or not self._active or (
                    self.needs_radio() and not radio_arbiter.arbiter.held_by(self.NAME)))
            else:
                src.open()
        except iqsource.SourceError as e:
            if self._stop or not self._active:
                return False                             # cancelled, not a fault
            self._fault = (str(e)[:120], time.monotonic())
            self.fault.emit("FAULT: %s %s" % (self.LABEL, e))
            self._status(("%s FAULT — %s" % (self.LABEL, e))[:90], "alert", fault=str(e),
                         live=False)
            if self.needs_radio():
                self._release()                          # radio back while faulted
            return False
        if self.needs_radio() and (self._stop or not self._active
                                   or not radio_arbiter.arbiter.held_by(self.NAME)):
            src.close()                                  # revoke / PANIC while opening
            return False
        self._fault = None
        self.fault.emit("")
        self._src = src
        self.centre_hz = int(getattr(src, "centre_hz", self.centre_hz))
        self.rate = int(getattr(src, "rate", self.rate))
        self._last_data = time.monotonic()
        self.on_source_opened(src)
        return True

    def run(self):
        try:
            while not self._stop:
                if not self._ensure_radio():
                    self.sleep(200)
                    continue
                if self._src is None and not self._open():
                    self.sleep(300)
                    continue
                try:
                    self._apply(self._take_pending())
                    raw, iq = self._src.read(BLOCK_S)
                except (iqsource.SourceError, OSError) as e:
                    self._block_fault(e)
                    continue
                now = time.monotonic()
                if iq.size == 0:
                    if self._src is not None and not self._src.alive():
                        self._fault = ("source ended" if self.source_kind == "file"
                                       else "radio stream stopped", now)
                        self._close_source()
                    elif now - (self._last_data or now) > NO_DATA_FAULT_S:
                        self._fault = ("no samples for %ds" % int(now - self._last_data), now)
                        self._close_source()
                    continue
                self._last_data = now
                try:
                    self.process_block(raw, iq)
                except (iqsource.SourceError, OSError) as e:
                    self._block_fault(e)
                except Exception as e:                   # RA-RADIO N2: a bug must not kill the
                    self._block_fault("internal error %s: %s" % (type(e).__name__, e))  # thread
        except BaseException as e:
            self._status(("%s OFF — stopped: %s" % (self.LABEL, e))[:90], "alert", live=False,
                         off=True, fault=str(e))
            raise
        finally:
            self._release()
            self.on_finish()
            try:
                radio_arbiter.arbiter.revoked.disconnect(self._on_revoked)
            except (RuntimeError, TypeError):
                pass

    def _block_fault(self, e):
        """Any failure while running: FAULT status (buttons go red), source closed, radio given
        back, retried after FAULT_RETRY_S by _open()."""
        msg = str(e)[:120]
        self._fault = (msg, time.monotonic())
        self.fault.emit("FAULT: %s %s" % (self.LABEL, msg))
        self._status(("%s FAULT — %s" % (self.LABEL, msg))[:90], "alert", fault=msg, live=False)
        self._close_source()
        if self.needs_radio():
            self._release()

    # ---------------- subclass hooks
    def on_source_opened(self, src):
        pass

    def on_source_closed(self):
        pass

    def on_finish(self):
        pass

    def _apply(self, p):
        """Apply queued settings to the source (worker thread)."""
        src = self._src
        if not p or src is None:
            return
        if "gain_db" in p:
            self.gain_db = p["gain_db"]
            src.set_gain(self.gain_db)
        if "ppm" in p:
            self.ppm = int(p["ppm"])
            src.set_ppm(self.ppm)
        if "rtl_agc" in p:
            self.rtl_agc = bool(p["rtl_agc"])
            src.set_agc(self.rtl_agc)
        if "rate" in p and int(p["rate"]) != self.rate and self.source_kind != "file":
            self.rate = int(p["rate"])
            src.set_rate(self.rate)
            src.flush(0.05)
            self.on_rate_changed()
        if "centre_hz" in p and self.source_kind != "file":
            self.tune_centre(int(p["centre_hz"]))

    def tune_centre(self, hz):
        src = self._src
        self.centre_hz = int(hz)
        if src is not None:
            src.set_freq(self.centre_hz)

    def on_rate_changed(self):
        pass

    def process_block(self, raw, iq):
        raise NotImplementedError


class TunerWorker(IqWorker):
    """PRISM's receiver: spectrum frames to the GUI + one VFO demodulated to audio, with optional
    audio and baseband recording. rows: {"kind": "spec", ...} at SPEC_FPS."""
    NAME = "PRISM"
    LABEL = "SDR"

    def __init__(self, mode="AM", bw=None, vfo_hz=None, squelch_db=None, audio_agc=None,
                 nfft=8192, audio=True, deemph_us=75, audio_factory=None, **kw):
        super().__init__(**kw)
        self.mode = mode
        self.bw = bw
        self.vfo_hz = int(vfo_hz if vfo_hz is not None else self.centre_hz)
        self.squelch_db = squelch_db
        self.audio_agc = audio_agc
        self.nfft = int(nfft)
        self.audio_on = bool(audio)
        self.deemph_us = deemph_us
        self._audio_factory = audio_factory
        self._spec = None
        self._demod = None
        self._audio = None
        self._rec_iq = None
        self._rec_audio = None
        self._acc = None
        self._acc_n = 0
        self._last_spec = 0.0
        self._level = -200.0
        self._open_sq = False
        self._dc = 0j
        self.rec_msgs = []

    # ---- worker-thread helpers
    def _build_chain(self):
        self._spec = dsp.Spectrum(self.nfft)
        self._demod = dsp.Demodulator(self.rate, self.mode, self.bw,
                                      offset_hz=self.vfo_hz - self.centre_hz,
                                      squelch_db=self.squelch_db, agc=self.audio_agc,
                                      deemph_us=self.deemph_us)
        self.bw = self._demod.bw
        self._open_audio()

    def _open_audio(self):
        if self._audio is not None:
            self._audio.close()
            self._audio = None
        if not self.audio_on or self._demod is None:
            return
        if self._audio_factory is not None:
            self._audio = self._audio_factory(self._demod.audio_rate)
        elif not _offscreen():
            self._audio = iqsource.AudioOut(self._demod.audio_rate)

    def on_source_opened(self, src):
        self._build_chain()

    def on_source_closed(self):
        self._stop_rec("iq", "source closed")
        self._stop_rec("audio", "source closed")
        if self._audio is not None:
            self._audio.close()
            self._audio = None

    def on_finish(self):
        self.on_source_closed()

    def on_rate_changed(self):
        self._stop_rec("iq", "sample rate changed")
        self._build_chain()

    def _stop_rec(self, which, why=""):
        attr = "_rec_iq" if which == "iq" else "_rec_audio"
        r = getattr(self, attr)
        if r is not None:
            r.close()
            setattr(self, attr, None)
            self.row.emit({"kind": "rec", "which": which, "on": False, "path": r.path,
                           "why": r.stopped_reason or why})

    def _keep_vfo_in_band(self):
        half = 0.45 * self.rate
        off = self.vfo_hz - self.centre_hz
        if abs(off) > half:
            if self.source_kind == "file":               # a recording cannot retune: clamp
                self.vfo_hz = int(self.centre_hz + (half if off > 0 else -half))
            else:
                self.tune_centre(self.vfo_hz)            # recentre on the VFO (SDR++ behaviour)
                self._src.flush(0.03)

    def _apply(self, p):
        super()._apply(p)
        if not p or self._demod is None:
            return
        rebuild = False
        if "nfft" in p:
            self.nfft = int(p["nfft"])
            self._spec = dsp.Spectrum(self.nfft)
            self._acc, self._acc_n = None, 0
        if "mode" in p or "bw" in p or "audio_agc" in p or "deemph_us" in p:
            old_rate = self._demod.audio_rate
            self.mode = p.get("mode", self.mode)
            if "mode" in p and "bw" not in p:
                self.bw = None
            else:
                self.bw = p.get("bw", self.bw)
            self.audio_agc = p.get("audio_agc", self.audio_agc)
            self.deemph_us = p.get("deemph_us", self.deemph_us)
            self._demod = dsp.Demodulator(self.rate, self.mode, self.bw,
                                          offset_hz=self.vfo_hz - self.centre_hz,
                                          squelch_db=self.squelch_db, agc=self.audio_agc,
                                          deemph_us=self.deemph_us)
            self.bw = self._demod.bw
            if self._demod.audio_rate != old_rate:
                rebuild = True
                self._stop_rec("audio", "audio rate changed")
        if "vfo_hz" in p:
            self.vfo_hz = int(p["vfo_hz"])
        if "squelch_db" in p:
            self.squelch_db = p["squelch_db"]
            self._demod.squelch_db = self.squelch_db
        if "audio" in p:
            self.audio_on = bool(p["audio"])
            rebuild = True
        if rebuild:
            self._open_audio()
        if "rec_iq" in p:
            if p["rec_iq"] and self._rec_iq is None:
                try:
                    self._rec_iq = iqsource.IqRecorder(self.centre_hz, self.rate,
                                                       directory=p.get("rec_dir"))
                    self.row.emit({"kind": "rec", "which": "iq", "on": True,
                                   "path": self._rec_iq.path})
                except OSError as e:
                    self.error.emit("IQ recording failed: %s" % e)
            elif not p["rec_iq"]:
                self._stop_rec("iq", "stopped")
        if "rec_audio" in p:
            if p["rec_audio"] and self._rec_audio is None:
                try:
                    self._rec_audio = iqsource.AudioRecorder(self.vfo_hz, self.mode,
                                                             self._demod.audio_rate,
                                                             directory=p.get("rec_dir"))
                    self.row.emit({"kind": "rec", "which": "audio", "on": True,
                                   "path": self._rec_audio.path})
                except OSError as e:
                    self.error.emit("audio recording failed: %s" % e)
            elif not p["rec_audio"]:
                self._stop_rec("audio", "stopped")
        if self._rec_iq is not None and "centre_hz" in p:
            self._stop_rec("iq", "retuned (a baseband file has one centre frequency)")
        self._keep_vfo_in_band()
        self._demod.set_offset(self.vfo_hz - self.centre_hz)

    def process_block(self, raw, iq):
        if self._demod is None:
            self._build_chain()
        if self._rec_iq is not None:
            self._rec_iq.write(raw)
            if self._rec_iq.stopped_reason:
                self._stop_rec("iq")
        # RTL DC offset: a slow DC blocker so a VFO parked on the centre is not a carrier
        m = complex(np.mean(iq))
        self._dc = 0.95 * self._dc + 0.05 * m
        iq = iq - np.complex64(self._dc)
        spec = self._spec.process(iq)
        if spec is not None:
            if self._acc is None:
                self._acc, self._acc_n = spec.astype(np.float64), 1
            else:
                self._acc = np.logaddexp(self._acc * 0.2302585, spec * 0.2302585) / 0.2302585
                self._acc_n += 1
        pcm, self._level, self._open_sq = self._demod.process(iq)
        if self._audio is not None:
            self._audio.write(pcm)
        if self._rec_audio is not None:
            self._rec_audio.write(pcm)
            if self._rec_audio.stopped_reason:
                self._stop_rec("audio")
        now = time.monotonic()
        if self._acc is not None and now - self._last_spec >= 1.0 / SPEC_FPS:
            db = (self._acc - 10 * np.log10(self._acc_n)).astype(np.float32)
            self._acc, self._acc_n = None, 0
            self._last_spec = now
            self.row.emit({"kind": "spec", "db": db, "centre_hz": self.centre_hz,
                           "rate": self.rate, "vfo_hz": self.vfo_hz, "level": self._level,
                           "open": self._open_sq, "bw": self.bw, "mode": self.mode,
                           "source": self.source_kind,
                           "rec_iq_s": self._rec_iq.seconds(self.rate) if self._rec_iq else None,
                           "rec_audio_s": (self._rec_audio.frames / self._rec_audio.rate
                                           if self._rec_audio else None)})
        if now - self._last_status >= STATUS_EVERY_S:
            self._last_status = now
            kind = self.source_kind
            if kind == "demo":
                self._status("SDR DEMO", "neutral", live=False)
            elif kind == "file":
                self._status("SDR FILE — playback", "neutral", live=False)
            else:
                text = "SDR PRISM %.4f %s" % (self.vfo_hz / 1e6, self.mode)
                self._status(text, "live", live=True, stale=False)
            if self._audio is not None and self._audio.error:
                self.error.emit(self._audio.error)


# =============================================================================== fast scanner

SETTLE_S = 0.06           # samples dropped after a retune (PLL settle + buffered old samples)


def plan_windows(channels_hz, rate, guard_hz=8000):
    """Group sorted channel frequencies into capture windows that fit in 0.84 x rate, each with a
    centre chosen so no channel sits on the DC spike. -> [(centre_hz, [channel indices])]."""
    half = 0.42 * rate
    order = sorted(range(len(channels_hz)), key=lambda i: channels_hz[i])
    out = []
    i = 0
    while i < len(order):
        lo = channels_hz[order[i]]
        grp = []
        while i < len(order) and channels_hz[order[i]] - lo <= 2 * half - 2 * guard_hz:
            grp.append(order[i])
            i += 1
        fs = [channels_hz[k] for k in grp]
        base = (fs[0] + fs[-1]) / 2.0
        centre = base
        for d in (0, 1, -1, 2, -2, 3, -3, 4, -4):
            c = base + d * guard_hz * 1.25
            if all(abs(f - c) >= guard_hz for f in fs) and all(abs(f - c) <= half for f in fs):
                centre = c
                break
        out.append((int(round(centre)), grp))
    return out


class FastScanWorker(IqWorker):
    """PROWL's scanner on the IQ stream (SDR++ scanner style): each retune captures up to
    ~1.7 MHz, so every channel in that window is judged from ONE spectrum — a full 118-137 MHz
    airband pass is ~12 retunes, not 760 rtl_fm starts. Stops on the strongest channel above the
    squelch (dB over the measured noise floor), demodulates it to audio, holds while it is active,
    resumes after the resume delay, leaves after the max hold, re-checks the priority channel on
    a timer, honours lockouts and a manual HOLD. rows: {"kind": "scan", ...} ~3 Hz."""
    NAME = "PROWL-SCAN"
    LABEL = "SCAN"

    def __init__(self, channels=(), squelch_db=10.0, dwell_s=0.15, resume_s=2.0, max_hold_s=30.0,
                 priority=None, priority_every_s=2.0, lockouts=(), audio=True, audio_factory=None,
                 nfft=8192, **kw):
        kw.setdefault("centre_hz", int(channels[0][0] * 1e6) if channels else 121_500_000)
        super().__init__(**kw)
        self.channels = [tuple(c) for c in channels]     # (MHz, label, mode, bw_hz)
        self.squelch_db = float(squelch_db)
        self.dwell_s = float(dwell_s)
        self.resume_s = float(resume_s)
        self.max_hold_s = float(max_hold_s)
        self.priority = tuple(priority) if priority else None
        self.priority_every_s = float(priority_every_s)
        self.lockouts = set(round(float(f), 4) for f in lockouts)
        self.audio_on = bool(audio)
        self._audio_factory = audio_factory
        self.nfft = int(nfft)
        self.hold = False
        self._reset_plan()
        self._audio = None
        self._demod = None
        self._state = "SEARCH"
        self._listen = None          # channel index being listened to (or "P" for priority)
        self._levels = {}            # channel idx -> last SNR dB
        self._last_heard = {}        # channel idx -> epoch
        self._hits = {}              # channel idx -> count
        self._floor = None
        self._last_emit = 0.0
        self._last_pri = 0.0
        self._clock = 0.0
        self._pass_t0 = 0.0
        self.pass_s = None
        self._skip_until = {}        # channel MHz -> stream time its max-hold cooldown ends

    # ---------------- GUI entry points (flags / queue only)
    def set_hold(self, on):
        self.queue(hold=bool(on))

    def skip_current(self):
        """Lock out the channel being listened to (the scan moves on). Returns its MHz or None."""
        i = self._listen
        if i is None or i == "P" or i >= len(self.channels):
            return None
        f = round(self.channels[i][0], 4)
        self.queue(lockout_add=f)
        return f

    def clear_skips(self):
        self.queue(lockouts=set())

    # ---------------- plan
    def _reset_plan(self):
        self._hz = [int(round(c[0] * 1e6)) for c in self.channels]
        self._windows = plan_windows(self._hz, self.rate) if self._hz else []
        self._win = 0
        self._spec = None
        self._acc = None
        self._acc_n = 0
        self._settle = 0
        self._t_win = 0.0
        self._detour = None          # RA-RADIO N3: positions saved for a priority check refer
        self._return_win = None      # to the OLD plan; a new plan forgets them

    def _apply(self, p):
        super()._apply({k: v for k, v in p.items() if k in ("gain_db", "ppm", "rtl_agc")})
        for k in ("squelch_db", "dwell_s", "resume_s", "max_hold_s", "priority_every_s"):
            if k in p:
                setattr(self, k, float(p[k]))
        if "priority" in p:
            self.priority = tuple(p["priority"]) if p["priority"] else None
        if "hold" in p:
            self.hold = bool(p["hold"])
        if "lockouts" in p:
            self.lockouts = set(round(float(f), 4) for f in p["lockouts"])
        if "lockout_add" in p:
            f = round(float(p["lockout_add"]), 4)
            self.lockouts.add(f)
            i = self._listen                     # RA-RADIO N11: end the listen only if it is
            if i not in (None, "P") and i < len(self.channels) and \
                    round(self.channels[i][0], 4) == f:     # still the channel locked out
                self._end_listen()
        if "audio" in p:
            self.audio_on = bool(p["audio"])
            if not self.audio_on and self._audio is not None:
                self._audio.close()
                self._audio = None
        if "channels" in p:
            self.channels = [tuple(c) for c in p["channels"]]
            self._end_listen()
            self._levels, self._last_heard, self._hits = {}, {}, {}
            self._reset_plan()
            self._goto_window(0)

    def on_source_opened(self, src):
        self._spec = dsp.Spectrum(self.nfft)
        self._goto_window(0)

    def on_source_closed(self):
        if self._audio is not None:
            self._audio.close()
            self._audio = None
        self._listen = None
        self._state = "SEARCH"

    def on_finish(self):
        self.on_source_closed()

    # ---------------- tuning
    def _goto_window(self, w):
        if not self._windows:
            return
        self._win = w % len(self._windows)
        if self._win == 0:
            now = self._clock
            self.pass_s = now - self._pass_t0
            self._pass_t0 = now
        centre = self._windows[self._win][0]
        if self._src is not None and centre != self.centre_hz:
            self.tune_centre(centre)
        self.centre_hz = centre
        if self._spec is not None:
            self._spec.reset()
        self._acc, self._acc_n = None, 0
        self._settle = int(math.ceil(SETTLE_S / BLOCK_S))
        self._t_win = 0.0

    def _goto_freq(self, hz):
        """Retune so hz is inside the capture (priority check / listen across windows)."""
        for w, (c, grp) in enumerate(self._windows):
            if any(self._hz[k] == hz for k in grp):
                if w != self._win:
                    self._goto_window_keep(w)
                return

    def _goto_window_keep(self, w):
        self._win = w
        self.tune_centre(self._windows[w][0])
        if self._spec is not None:
            self._spec.reset()
        self._acc, self._acc_n = None, 0
        self._settle = int(math.ceil(SETTLE_S / BLOCK_S))
        self._t_win = 0.0

    # ---------------- listen
    def _chan_cfg(self, i):
        if i == "P":
            f, mode, bw = self.priority[0], self.priority[1], self.priority[2]
            return int(round(f * 1e6)), mode, bw
        c = self.channels[i]
        return self._hz[i], c[2], c[3]

    def _start_listen(self, i, now):
        hz, mode, bw = self._chan_cfg(i)
        self._listen = i
        self._state = "LISTEN" if i != "P" else "PRIORITY"
        self._t_listen = now
        self._t_active = now
        self._demod = dsp.Demodulator(self.rate, mode, bw, offset_hz=hz - self.centre_hz)
        if self.audio_on:
            rate = self._demod.audio_rate
            if self._audio is None or self._audio.rate != rate:
                if self._audio is not None:
                    self._audio.close()
                self._audio = (self._audio_factory(rate) if self._audio_factory is not None
                               else (None if _offscreen() else iqsource.AudioOut(rate)))
        key = i
        self._hits[key] = self._hits.get(key, 0) + 1
        self._last_heard[key] = time.time()
        label = (self.channels[i][1] if i != "P" else "priority") or ""
        self.row.emit({"kind": "hit", "mhz": hz / 1e6, "label": label, "mode": mode})

    def _resume_listen(self, i, win, t_listen, now):
        """Return from a quiet priority check to the channel we were listening to."""
        if not (0 <= win < len(self._windows)) or not (i == "P" or 0 <= i < len(self.channels)):
            self._goto_window(0)                         # plan changed under the detour (N3)
            return
        self._goto_window_keep(win)
        hz, mode, bw = self._chan_cfg(i)
        self._listen = i
        self._state = "LISTEN"
        self._t_listen = t_listen
        self._t_active = now
        self._demod = dsp.Demodulator(self.rate, mode, bw, offset_hz=hz - self.centre_hz)

    def _end_listen(self):
        self._listen = None
        self._demod = None
        self._state = "SEARCH"

    # ---------------- per block
    def _snr(self, spec, idxs, centre):
        floor = dsp.noise_floor_db(spec)
        self._floor = floor
        out = {}
        if not idxs:
            return out
        fr = [self._hz[k] for k in idxs]
        bws = [self.channels[k][3] for k in idxs]
        for k, f, bw in zip(idxs, fr, bws):
            lv = dsp.channel_levels(spec, self.rate, centre, [f], bw)[0]
            if lv is not None:
                out[k] = lv - floor
        return out

    def _eligible(self, k):
        f = round(self.channels[k][0], 4)
        return f not in self.lockouts and self._clock >= self._skip_until.get(f, -1.0)

    def process_block(self, raw, iq):
        if self._spec is None:
            self._spec = dsp.Spectrum(self.nfft)
        # scan timing runs on STREAM time (samples received), not the wall clock: dwell, resume
        # delay, max hold and the priority timer mean the same thing live, in playback and tests
        self._clock += iq.size / float(self.rate)
        now = self._clock
        if not self._windows:
            self._emit(now, force=False)
            return
        if self._settle > 0:
            self._settle -= 1
            return
        m = complex(np.mean(iq))
        iq = iq - np.complex64(m)
        spec = self._spec.process(iq)
        if spec is not None:
            p = spec.astype(np.float64) * 0.2302585
            self._acc = p if self._acc is None else np.logaddexp(self._acc, p)
            self._acc_n += 1
        self._t_win += iq.size / self.rate
        centre, grp = self._windows[self._win]

        if self._listen is not None:
            self._listen_block(iq, spec, now)
        elif self._t_win >= self.dwell_s and self._acc is not None:
            avg = (self._acc / 0.2302585 - 10 * np.log10(self._acc_n)).astype(np.float32)
            snr = self._snr(avg, grp, centre)
            self._levels.update(snr)
            for k in grp:
                if k not in snr:
                    self._levels.pop(k, None)
            pri = self._priority_index()
            detour, self._detour = getattr(self, "_detour", None), None
            if pri is not None and pri in snr and snr[pri] >= self.squelch_db \
                    and self._eligible(pri):
                self._start_listen(pri, now)
            elif detour is not None:                    # priority quiet: back to the channel
                self._resume_listen(*detour, now=now)
            else:
                best = max((k for k in grp if snr.get(k, -999) >= self.squelch_db
                            and self._eligible(k)), key=lambda k: snr[k], default=None)
                if best is not None:
                    self._start_listen(best, now)
                elif not self.hold:
                    self._advance(pri, grp, now)
                else:
                    self._acc, self._acc_n, self._t_win = None, 0, 0.0
        self._emit(now)

    def _advance(self, pri, grp, now):
        """Next window. A due priority check detours to the priority channel's window first
        (unless it was just judged in this one) and then returns to where the pass was."""
        ret, self._return_win = getattr(self, "_return_win", None), None
        target = ret if ret is not None else self._win + 1
        if pri is not None and pri in grp:
            self._last_pri = now                       # judged just now with this window
        elif pri is not None and now - self._last_pri >= self.priority_every_s:
            self._last_pri = now
            pw = next((w for w, (_c, g) in enumerate(self._windows) if pri in g), None)
            if pw is not None and pw != target % len(self._windows):
                self._return_win = target
                self._goto_window_keep(pw)
                return
        self._goto_window(target)

    def _priority_index(self):
        """Index of the priority channel in the channel list (added there if missing)."""
        if not self.priority:
            return None
        hz = int(round(self.priority[0] * 1e6))
        for k, f in enumerate(self._hz):
            if abs(f - hz) < 500:
                return k
        return None

    def _listen_block(self, iq, spec, now):
        i = self._listen
        hz, _mode, bw = self._chan_cfg(i)
        if spec is not None:
            lv = dsp.channel_levels(spec, self.rate, self.centre_hz, [hz], bw)[0]
            floor = dsp.noise_floor_db(spec)
            self._floor = floor
            snr = (lv - floor) if lv is not None else -99.0
            self._levels[i] = snr
            # hysteresis: once open, stay open down to 3 dB under the squelch
            if snr >= self.squelch_db - 3.0:
                self._t_active = now
                self._last_heard[i] = time.time()
        active = now - self._t_active < 0.25
        pcm, _lvl, _open = self._demod.process(iq)
        if self._audio is not None:
            self._audio.write(pcm if active else np.zeros_like(pcm))
        if self.hold:
            self._state = "HOLD"
            return
        self._state = "LISTEN"
        if now - self._t_active > self.resume_s:          # quiet for the resume delay: move on
            self._end_listen()
            self._goto_window(self._win + 1)
            return
        if self.max_hold_s > 0 and now - self._t_listen > self.max_hold_s:
            # RA-RADIO N4: max hold benches the channel for as long as it just held the scanner
            # (at least 5 s), so a continuous carrier (ATIS, NOAA) cannot hide the other
            # channels of its capture; then it is eligible again
            if i != "P":
                self._skip_until[round(self.channels[i][0], 4)] = now + max(5.0, self.max_hold_s)
            self._end_listen()
            self._goto_window(self._win + 1)
            return
        pri = self._priority_index()
        if pri is not None and i != pri and now - self._last_pri >= self.priority_every_s:
            self._last_pri = now
            pw = next((w for w, (_c, g) in enumerate(self._windows) if pri in g), None)
            if pw == self._win and spec is not None:
                ps = self._snr(spec, [pri], self.centre_hz).get(pri, -99)
                if ps >= self.squelch_db and self._eligible(pri):
                    self._end_listen()
                    self._start_listen(pri, now)
            elif pw is not None:
                # priority lives in another capture: a short look there (dwell + settle, the
                # audio gap a hardware scanner's priority check also has), then come back
                self._detour = (i, self._win, self._t_listen)
                self._listen = None
                self._demod = None
                self._state = "PRIORITY CHECK"
                self._goto_window_keep(pw)

    def _emit(self, now, force=False):
        if not force and now - self._last_emit < 0.33:
            return
        self._last_emit = now
        rows = []
        cur = self._listen
        for k, c in enumerate(self.channels):
            snr = self._levels.get(k)
            t = self._last_heard.get(k)
            locked = round(c[0], 4) in self.lockouts
            rows.append({"_id": c[0], "freq": "%.4f" % c[0], "label": c[1] + (" ⊘" if locked
                                                                              else ""),
                         "mode": c[2], "sig": "" if snr is None else "%+.0f dB" % snr,
                         "_level": snr, "last": _zulu(t) if t else "",
                         "_hot": k == cur, "_skip": locked, "hits": self._hits.get(k, 0)})
        active = None
        if cur is not None:
            hz, mode, _bw = self._chan_cfg(cur)
            label = self.channels[cur][1] if cur != "P" else "priority"
            active = ("%.4f" % (hz / 1e6), label, self._levels.get(cur))
        win = self._windows[self._win] if self._windows else None
        self.row.emit({"kind": "scan", "rows": rows, "active": active,
                       "state": "HOLD" if self.hold else self._state,
                       "floor": self._floor, "pass_s": self.pass_s,
                       "window": ((win[0] - 0.42 * self.rate) / 1e6,
                                  (win[0] + 0.42 * self.rate) / 1e6) if win else None,
                       "windows": len(self._windows)})
        wall = time.monotonic()
        if wall - self._last_status >= STATUS_EVERY_S:
            self._last_status = wall
            if self.source_kind == "demo":
                self._status("SCAN DEMO", "neutral", live=False)
            elif self.source_kind == "file":
                self._status("SCAN FILE — playback", "neutral", live=False)
            else:
                self._status("SCAN %s %d CH" % (self._state, len(self.channels)), "live",
                             live=True)


def _zulu(t):
    from .timebase import zulu
    return zulu(t)
