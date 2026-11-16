"""PROWL — scanner / tuner, wired to the real scanner / fm / nwr engines.

Three sub-modes, each leasing the one built-in SDR through the shared radio_arbiter (only one
holds the dongle at a time; switching releases the old and acquires the new; the page releases
on background/close):

  * SCAN — scanner.listen_channel() across a preset bank (lease "PROWL-SCAN").
  * FM   — fm.pipeline()/fm.Pipe broadcast + weather tuner with audio + RDS (lease "PROWL-FM").
  * NWR  — nwr.pipeline()/nwr.parse_same() NOAA Weather Radio SAME/EAS alerts (lease "PROWL-NWR").

Legacy decode/radio paths are reused AS-IS — this module only wires them to Qt and the arbiter.
Honesty: live mode publishes only real decodes; with no rtl_fm it shows STANDBY (never synth).
Demo is the only synthetic path (SDR-DEMO chip). offscreen/offline never opens a real radio.
"""
import os
import shutil
import sys
import random
import threading
import time
from collections import deque

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp
from . import theme, radio_arbiter, eventbus
from .kit import ControlBar, FeedTable, DetailCard, micro, card
from .worker import Worker
from .kit.components import StatusLine

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

DEMO_CHANNELS = [
    ("162.400", "NOAA WX1"), ("154.265", "Fire Disp"), ("155.340", "EMS"),
    ("121.500", "Aircraft Guard"), ("146.520", "2m Call"), ("462.5625", "FRS 1"),
    ("453.212", "City PD"), ("159.480", "Rail"),
]

# NOAA Weather Radio 7-channel plan (162.400–162.550 MHz). nwr.py only hardcodes 162.400, so the
# PROWL NWR sub-mode owns the channel list and calls nwr.pipeline() per channel (reused AS-IS).
NWR_CHANNELS = [
    ("162.400M", "WX2"), ("162.425M", "WX4"), ("162.450M", "WX5"), ("162.475M", "WX3"),
    ("162.500M", "WX6"), ("162.525M", "WX7"), ("162.550M", "WX1"),
]

FM_DEFAULTS = {"freq": 97.3, "mode": "wbfm", "gain": 40, "squelch": 0, "rds": True}
# B1: tuning steps — broadcast 200 kHz, NBFM 25 / 12.5 / 5 kHz (weather radio, marine, business)
FM_STEPS = (("200 kHz", 0.2), ("100 kHz", 0.1), ("25 kHz", 0.025), ("12.5 kHz", 0.0125),
            ("5 kHz", 0.005))
FM_STEP_DEFAULT = 0


def _offscreen():
    """True under tests/CI/offline — the radio seams return None so no real device is opened."""
    return bool(os.environ.get("PALISADE_OFFLINE") or
                os.environ.get("QT_QPA_PLATFORM") == "offscreen")


def _open_fm_pipe(rtl, mid, sink, on_rds):
    """Spawn fm.Pipe (rtl_fm[/redsea]/audio), or None under offscreen/offline. Reuses fm.Pipe."""
    if _offscreen():
        return None
    import fm
    return fm.Pipe(rtl, sink, mid, on_rds=on_rds)


def _open_nwr_pipe(stages):
    """Spawn the nwr rtl_fm | multimon-ng pipeline from argv lists in one session (audit A4), or
    None under offscreen/offline."""
    if _offscreen():
        return None
    from .kit.procs import Pipeline
    return Pipeline(stages)


class _RadioWorker(Worker):
    """Mixin for a PROWL sub-mode that leases the single SDR via the arbiter and honours the
    page's front/back state (release the dongle when backgrounded — the ATLAS/PRISM pattern).

    CL5-fix rules, enforced here for every sub-mode:
      1. the decoder starts only once the arbiter says HELD for us (never during ACQUIRING);
      2. give-back is always kill -> wait for exit -> release, on the WORKER thread;
      6. GUI-thread entry points (set_active, a revoke, PANIC, stop) only set flags and poke;
      7. every give-back emits an OFF status, so no page keeps a live claim on a radio it gave up.
    """
    NAME = None
    LABEL = "SDR"

    PAUSE_WHEN_HIDDEN = False          # a radio holder must keep stepping to release when hidden

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._active = True
        self._has_radio = False
        self._revoked = False
        self._off_reason = "page hidden"
        radio_arbiter.arbiter.revoked.connect(self._on_revoked)

    def set_active(self, on):
        on = bool(on)
        if on == self._active and not (on and self._revoked):
            return                     # no change: never wake (and re-emit) on a repeat call
        self._active = on
        if on:
            self._revoked = False
        else:
            self._off_reason = "page hidden"
            self._interrupt()
        if not self.demo:              # demo holds no radio: nothing to wake for
            self.poke()

    def _on_revoked(self, name):
        """A1: the operator wants the radio back. Flags only (this runs on the GUI thread): the
        next step() stops the pipeline, waits for it, and releases (the acknowledgement); we stay
        off until the page is fronted again or the operator resumes."""
        if name == self.NAME:
            self.hold_off("radio given back")

    def hold_off(self, reason):
        """Stay off the radio until resumed (a revoke, PANIC). GUI-safe: flags + poke."""
        self._revoked = True
        self._active = False
        self._off_reason = reason
        self._interrupt()
        self.poke()

    @property
    def held_off(self):
        return self._revoked

    def _interrupt(self):
        """Break whatever blocking listen is in progress (SCAN overrides). Flags only."""

    def _kill(self):
        """Stop this sub-mode's pipeline and WAIT for it to exit. Worker thread only."""

    def _ensure_lease(self):
        """True only while we HOLD the single SDR (arbiter state HELD for our name). Requests it
        if active+free; gives it back (kill, wait, release) if backgrounded; emits RADIO BUSY
        (publish nothing) if another layer holds it, ACQUIRING while readsb is being paused."""
        if not self._active:
            self._give_back(self._off_reason)
            return False
        arb = radio_arbiter.arbiter
        if not self._has_radio:
            if not arb.request(self.NAME):
                self.status.emit({"src": self.LABEL, "busy": radio_arbiter.owner_label(), "live": False,
                                  "sdr": {"text": "RADIO BUSY", "ok": False}})
                return False
            self._has_radio = True
        st, owner = arb.state()
        if owner != self.NAME:                       # freed under us (forced free / PANIC)
            self._has_radio = False
            self._give_back("radio taken back")
            return False
        if st != "HELD":
            self.status.emit({"src": self.LABEL, "busy": None, "live": False, "acquiring": True,
                              "sdr": {"text": "%s ACQUIRING radio" % self.LABEL,
                                      "state": "warn", "ok": False}})
            return False
        return True

    def _give_back(self, why):
        """Kill, wait, THEN release (N4), and say so (CL5-fix 7)."""
        self._kill()
        if self._has_radio:
            radio_arbiter.arbiter.release(self.NAME)   # readsb / the autopilot resume
            self._has_radio = False
        self.status.emit({"src": self.LABEL, "busy": None, "live": False, "off": True,
                          "sdr": {"text": "%s OFF — %s" % (self.LABEL, why),
                                  "state": "warn", "ok": False}})

    # kept for callers of the old name; same ordering as _give_back
    def _release_radio(self):
        self._give_back(self._off_reason)

    def _finish(self):
        """End of run(): give the radio back from the worker thread, stop listening for revokes."""
        try:
            self._give_back("stopped")
        finally:
            try:
                radio_arbiter.arbiter.revoked.disconnect(self._on_revoked)
            except (RuntimeError, TypeError):
                pass

    def stop(self):
        """GUI-safe: flags only. run() ends and _finish() kills, waits and releases there."""
        self._active = False
        self._off_reason = "stopped"
        self._interrupt()
        super().stop()


# ============================ SCAN ============================

class ScanWorker(_RadioWorker):
    NAME = "PROWL-SCAN"
    LABEL = "SCAN"

    def __init__(self, demo=True, bank="NOAA Wx", squelch=-70, parent=None):
        super().__init__(demo=demo, interval_ms=350, parent=parent)
        self.squelch = squelch
        self.hold = False
        self._bank = bank
        self._scan = None          # live scan state dict; kept on self so stop() can break the
        self._fatal = False        # blocking listen_channel (scan["on"]=False) — else it hangs
        self._skip = set()         # E2: locked-out channels (MHz)
        self._nfm_sq = None        # B2: live NFM squelch (rtl_fm -l units) set from the page
        self._settings = None

    def set_bank(self, bank):
        self._bank = bank
        self._skip.clear()

    def skip_current(self):
        """E2: lock out the channel the scanner is on right now (SCAN resumes elsewhere)."""
        scan = self._scan
        chans = getattr(self, "_channels", None)
        if scan is None or not chans:
            return None
        freq = chans[scan["idx"] % len(chans)][0]
        self._skip.add(freq)
        scan["pause"] = True        # break the current listen; the loop clears pause itself
        return freq

    def clear_skips(self):
        self._skip.clear()

    def set_nfm_squelch(self, level):
        """B2: the live squelch is the engine's rtl_fm -l level; a change retunes the current
        channel at the new level (the engine's own 'retune' path)."""
        self._nfm_sq = int(level)
        if self._settings is not None:
            self._settings["nfm_squelch"] = int(level)
        if self._scan is not None:
            self._scan["retune"] = True

    def run(self):
        try:
            if self.demo:
                self._run_demo()
            elif _offscreen() or not shutil.which("rtl_fm"):
                self._run_standby()    # live + no rtl_fm (or offscreen): honest standby, no spawn
            else:
                self._run_live()
        finally:
            self._finish()             # listen_channel has returned (its rtl_fm reaped): release

    def _interrupt(self):
        scan = self._scan
        if scan is not None:
            scan["pause"] = True       # breaks the in-progress listen_channel within one select

    def _run_standby(self):
        """Live mode without rtl_fm: list the bank's channels all-quiet and publish NO fake hits."""
        import scanner as engine
        s, _ = _load_scanner_settings(engine)
        channels = (engine.bank_channels(self._bank, s.get("custom", []))
                    or engine.bank_channels(engine.DEFAULTS["bank"], []))
        self._channels = channels
        scan = {"on": False, "pause": False, "idx": 0, "rms": 0.0}
        while not self._stop:
            self._emit_state(channels, {}, scan)   # channels listed, all quiet, no fabricated hits
            self.status.emit({"sdr": {"text": "SCAN STANDBY — no rtl_fm", "ok": False},
                              "standby": True})
            self.sleep(1000)

    def _run_demo(self):
        while not self._stop:
            rows = []
            active = None
            for freq, label in DEMO_CHANNELS:
                hot = random.random() < 0.12
                sig = random.randint(-55, -35) if hot else random.randint(-115, -95)
                if hot and sig > self.squelch:
                    active = (freq, label, sig)
                rows.append({"_id": freq, "freq": freq, "label": label, "sig": "%d" % sig,
                             "last": time.strftime("%H:%M:%S") if hot else "", "_hot": hot})
            self.row.emit({"rows": rows, "active": active})
            if not active:
                self.status.emit({"sdr": {"text": "SCAN DEMO", "state": "neutral"}})
            self.sleep(self.interval_ms)

    def _run_live(self):
        import scanner as engine
        s, _ = _load_scanner_settings(engine)
        if self._nfm_sq is not None:
            s["nfm_squelch"] = self._nfm_sq
        self._settings = s
        channels = (engine.bank_channels(self._bank, s.get("custom", []))
                    or engine.bank_channels(engine.DEFAULTS["bank"], []))
        self._channels = channels
        self._scan = {"on": True, "pause": False, "idx": 0, "rms": 0.0}
        scan = self._scan
        hits = {}
        sink_fn = (lambda: None) if _offscreen() else engine.sink_cmd
        try:
            while not self._stop and scan["on"]:
                if not self._ensure_lease():        # backgrounded or radio busy
                    self.sleep(300)
                    continue
                if not channels:
                    self.sleep(500)
                    continue
                if self.hold:
                    self._emit_state(channels, hits, scan, held=True)
                    self.sleep(300)
                    continue
                if scan.get("pause") and self._active:
                    scan["pause"] = False       # a skip broke the listen; carry on scanning
                idx = scan["idx"] % len(channels)
                if channels[idx][0] in self._skip and len(self._skip) < len(channels):
                    scan["idx"] = (idx + 1) % len(channels)
                    continue
                freq, label, mode = channels[idx]
                scan["rms"] = 0.0
                result = engine.listen_channel(freq, mode, s, scan,
                                               self._make_post(freq, label, hits),
                                               sink_fn=sink_fn, clock=time.time)
                if self._stop or not scan["on"]:
                    break
                if self._fatal:                     # rtl_fm fault (surfaced by post): back off
                    self._fatal = False
                    self.sleep(2000)
                    continue
                if result == "retune":              # B2 / CL5-fix 11: a squelch change is NOT a
                    continue                        # hit — re-listen the same channel at the new level
                if result is True:
                    hits[freq] = time.time()           # B3: epoch, never HH:MM:SS re-parsed
                self._emit_state(channels, hits, scan)
                nxt = (idx + 1) % len(channels)
                tries = 0
                while channels[nxt][0] in self._skip and tries < len(channels):   # E2: skip/lockout
                    nxt = (nxt + 1) % len(channels)
                    tries += 1
                scan["idx"] = nxt
        finally:
            self._scan = None

    def _make_post(self, freq, label, hits):
        def post(msg):
            kind = msg[0] if isinstance(msg, tuple) else msg
            if kind == "hit":
                hits[freq] = time.time()                   # B3: epoch
                # a real squelch-break -> the one typed decode event (no geo, so not a contact)
                eventbus.bus.publish(eventbus.decode(
                    "PROWL", "SCAN", "%.4f" % freq, "%s active @ %.4f MHz" % (label, freq),
                    severity="live", freq_mhz=freq, label=label))
            elif kind == "fatal":                   # rtl_fm vanished mid-scan: surface, don't swallow
                self._fatal = True
                self.error.emit(msg[1] if isinstance(msg, tuple) and len(msg) > 1
                                else "scanner fault")
        return post

    def _emit_state(self, channels, hits, scan, held=False):
        rows = []
        active = None
        now = time.time()
        for freq, label, mode in channels:
            t_hit = hits.get(freq)
            hot = t_hit is not None and (now - t_hit) < 30          # B3: epoch arithmetic
            rms = scan.get("rms", 0)
            sig = int(-40 - (1.0 - min(1.0, rms / 8000.0)) * 80) if hot else -100
            last = time.strftime("%H:%M:%S", time.localtime(t_hit)) if t_hit else ""
            if hot and not held:
                active = (str(freq), label, sig)
            rows.append({"_id": freq,          # the cursor follows the channel across refreshes
                         "freq": "%.4f" % freq, "label": label + (" ⊘" if freq in self._skip else ""),
                         "sig": "%d" % sig, "last": last, "_hot": hot, "_skip": freq in self._skip})
        self.row.emit({"rows": rows, "active": active})

    def stop(self):
        scan = self._scan
        if scan is not None:
            scan["on"] = False           # break the blocking listen_channel within one select cycle
        super().stop()                   # flags only; run()'s _finish releases after rtl_fm exits


# ============================ FM ============================

class FmWorker(_RadioWorker):
    NAME = "PROWL-FM"
    LABEL = "FM"

    def __init__(self, demo=True, freq=97.3, mode="wbfm", gain=40, squelch=0, rds=True, parent=None):
        super().__init__(demo=demo, interval_ms=500, parent=parent)
        self.freq, self.mode, self.gain, self.squelch, self.rds = freq, mode, gain, squelch, rds
        self._pipe = None
        self._retune = False
        self._rds = {}
        self._lock = threading.Lock()
        self._demo_i = 0

    def set_tune(self, freq, mode, rds=None):
        self.freq, self.mode = float(freq), mode
        if rds is not None:
            self.rds = bool(rds)
        with self._lock:
            self._rds = {}
        self._retune = True

    def step(self):
        if self._stop:
            return
        if self.demo:
            self._demo_step()
            return
        if not shutil.which("rtl_fm"):
            self._give_back("no rtl_fm")
            self.status.emit({"sdr": {"text": "FM STANDBY — no rtl_fm", "ok": False},
                              "standby": True, "live": False})
            return
        if not self._ensure_lease():          # gives the radio back (kill, wait, release) if off
            return
        if self._retune:
            self._retune = False
            self._respawn()
        elif self._pipe is None:
            self._spawn()
        elif self._pipe.poll() is not None:         # pipeline died (device yanked / preempted)
            self._respawn()
        with self._lock:
            rds = dict(self._rds)
        audio = self._pipe is not None
        self.row.emit({"kind": "fm", "freq": self.freq, "mode": self.mode,
                       "rds": rds, "audio": audio})
        self.status.emit({"busy": None, "live": audio,
                          "sdr": {"text": ("FM %.1f ♪" % self.freq) if audio
                                          else ("FM %.1f" % self.freq), "ok": True}})

    def _spawn(self):
        import fm
        rtl, mid, sink = fm.pipeline(self.freq, self.mode, self.gain, self.squelch, self.rds)
        pipe = _open_fm_pipe(rtl, mid, sink, self._on_rds)
        orphan = None
        with self._lock:                 # guard against a concurrent stop / revoke / PANIC
            if self._stop or not self._active or not radio_arbiter.arbiter.held_by(self.NAME):
                orphan = pipe            # never run a decoder on a radio we no longer hold
            else:
                self._pipe = pipe
        if orphan is not None:
            try:
                orphan.stop()
            except Exception:
                pass

    def _respawn(self):
        self._kill()
        self._spawn()

    def _on_rds(self, d):
        """redsea JSON group (fires on redsea's reader thread) -> latest station fields."""
        if not isinstance(d, dict):
            return
        with self._lock:
            for k in ("ps", "radiotext", "prog_type", "callsign", "pi"):
                v = d.get(k)
                if v:
                    self._rds[k] = v

    def _demo_step(self):
        self._demo_i += 1
        stations = [("KEXP", "90.3", "Alternative"), ("KUOW", "94.9", "News/Talk"),
                    ("KISW", "99.9", "Rock"), ("KPLU", "88.5", "Jazz")]
        ps, f, pty = stations[self._demo_i % len(stations)]
        self.row.emit({"kind": "fm", "freq": self.freq, "mode": self.mode, "audio": True,
                       "rds": {"ps": ps, "prog_type": pty, "pi": "%04X" % (0x1000 + self._demo_i),
                               "radiotext": "demo stream — now playing"}})
        self.status.emit({"sdr": {"text": "FM DEMO", "state": "neutral"}})

    def _kill(self):
        with self._lock:
            pipe, self._pipe = self._pipe, None
        if pipe is not None:
            try:
                pipe.stop()
            except Exception:
                pass

    def run(self):
        try:
            super().run()
        finally:
            self._finish()   # kill, wait, release — on this thread, never the GUI's


# ============================ NWR ============================

class NwrWorker(_RadioWorker):
    NAME = "PROWL-NWR"
    LABEL = "NWR"

    def __init__(self, demo=True, channel="162.400M", label="WX2", gain=0, parent=None):
        super().__init__(demo=demo, interval_ms=400, parent=parent)
        self.channel, self.label, self.gain = channel, label, gain
        self._proc = None
        self._thread = None
        self._q = deque()
        self._lock = threading.Lock()
        self._retune = False
        self._demo_src = None
        self._down = 0
        self._last_line = 0.0
        self._exits = deque()          # recent decoder exits (flap detection, RA-CL5b N-d)
        self._io_pid = None            # decoder (multimon-ng) pid whose read counter we watch
        self._io_bytes = None          # its last /proc/<pid>/io wchar
        self._audio_ts = 0.0           # when the decoder last read new audio

    # CL5-fix2/3 (RA-CL5b N-d, RA-CL5c N-l): "LIVE" needs AUDIO, not just a process. rtl_fm
    # sends ~44 kB/s of samples; multimon-ng's READ counter (/proc/<pid>/io rchar) grows only
    # while samples reach it — not on rtl_fm stderr chatter, not when the decoder is stuck. No growth for AUDIO_STALL_S -> not live;
    # for AUDIO_RESPAWN_S -> kill and respawn (counts as an exit). An unreadable counter is
    # treated as no audio: the page must never claim a weather watch it cannot verify.
    AUDIO_STALL_S = 3.0
    AUDIO_SETTLE_S = 2.0           # a new decoder must have read audio this long before LIVE
    AUDIO_GAP_S = 1.0              # … with no gap longer than this (rtl_fm sends ~44 kB/s)
    AUDIO_RESPAWN_S = 10.0
    FLAP_WINDOW_S = 60.0           # this many seconds …
    FLAP_EXITS = 3                 # … with this many exits = a flapping decoder (fault + backoff)

    @staticmethod
    def _rchar(pid):
        try:
            with open("/proc/%d/io" % pid) as f:
                for ln in f:
                    if ln.startswith("rchar:"):
                        return int(ln.split()[1])
        except (OSError, ValueError):
            return None
        return None

    def _audio_flowing(self):
        """True while the DECODER (multimon-ng, the last stage) read new audio within
        AUDIO_STALL_S (worker thread). RA-CL5c N-l: rtl_fm's own write counter also grew on
        stderr chatter and on bytes that only filled the pipe; what matters is audio consumed."""
        proc = self._proc
        procs = getattr(proc, "procs", None) or []
        if not procs:
            return False
        pid = procs[-1].pid
        n = self._rchar(pid)
        now = time.time()
        if pid != self._io_pid:                  # a new decoder: start a fresh baseline
            self._io_pid, self._io_bytes, self._audio_ts = pid, n, 0.0
            self._flow_since = 0.0
            self._spawn_ts = now
            return False
        if n is None:
            return False
        if self._io_bytes is not None and n > self._io_bytes:
            if not getattr(self, "_flow_since", 0.0) or now - self._audio_ts > self.AUDIO_GAP_S:
                self._flow_since = now           # (re)start of a continuous run of reads
            self._audio_ts = now
        self._io_bytes = n
        # LIVE = reading NOW (no gap > AUDIO_GAP_S) and continuously for AUDIO_SETTLE_S: a one-off
        # burst (the decoder's own start-up reads, a pipe-buffer flush) is not a receiver
        return bool(self._audio_ts) and now - self._audio_ts <= self.AUDIO_GAP_S \
            and bool(self._flow_since) and now - self._flow_since >= self.AUDIO_SETTLE_S

    FLAP_HOLD_S = (10, 30, 60)     # hold-down after the 1st / 2nd / later flap detections

    def _note_exit(self, why):
        """Record one decoder exit / forced respawn. A decoder that keeps dying is not a weather
        watch: on FLAP_EXITS within FLAP_WINDOW_S raise ONE visible FAULT and hold the respawn
        down (the page reads NOT MONITORING throughout)."""
        now = time.time()
        self._exits.append(now)
        while self._exits and now - self._exits[0] > self.FLAP_WINDOW_S:
            self._exits.popleft()
        self._down = len(self._exits)
        if self._down >= self.FLAP_EXITS:
            self._flaps = getattr(self, "_flaps", 0) + 1
            hold = self.FLAP_HOLD_S[min(self._flaps, len(self.FLAP_HOLD_S)) - 1]
            self._flap_until = now + hold
            self._exits.clear()
            msg = "NWR decoder keeps failing (%s, ×%d in %ds) — retry in %ds" % (
                why, self._down, int(self.FLAP_WINDOW_S), hold)
            self._flap_msg = msg
            self.error.emit(msg)
            self.fault.emit("FAULT: " + msg)

    def _flap_hold(self):
        """True while a flapping decoder is held down (status says so)."""
        until = getattr(self, "_flap_until", 0.0)
        if not until:
            return False
        if time.time() < until:
            self.status.emit({"src": "NWR", "busy": None, "down": True, "live": False,
                              "sdr": {"text": "NWR FAULT — %s" % self._flap_msg[:60],
                                      "state": "alert", "ok": False}})
            return True
        self._flap_until = 0.0
        return False

    def set_channel(self, channel, label):
        self.channel, self.label = channel, label
        self._retune = True

    def step(self):
        if self._stop:
            return
        if self.demo:
            self._demo_step()
            return
        if not (shutil.which("rtl_fm") and shutil.which("multimon-ng")):
            self._give_back("no rtl_fm")
            self.status.emit({"src": "NWR", "sdr": {"text": "NWR STANDBY — no rtl_fm", "ok": False},
                              "standby": True, "live": False})
            return
        if not self._ensure_lease():          # gives the radio back (kill, wait, release) if off
            return
        if self._proc is None and self._flap_hold():
            return
        if self._retune:
            self._retune = False
            self._respawn()
        elif self._proc is None:
            self._spawn()
        if self._proc is not None and self._proc.poll() is not None:   # R3: dead ≠ healthy
            rc = self._proc.poll()
            self._kill()
            self.status.emit({"src": "NWR", "busy": None, "down": True, "live": False,
                              "sdr": {"text": "NWR DOWN — decoder exited (%s) ×%d" % (
                                  rc, len(self._exits) + 1), "state": "alert", "ok": False}})
            self._note_exit("exit %s" % rc)          # FAULT + hold-down when flapping
            return
        self._drain()
        age = (time.time() - self._last_line) if self._last_line else None
        if self._proc is None:                    # offscreen seam opens nothing: not live
            self.status.emit({"src": "NWR", "busy": None, "down": False, "live": False,
                              "sdr": {"text": "NWR — no capture (offline)", "ok": False}})
            return
        if not self._audio_flowing():
            since = time.time() - (self._audio_ts or getattr(self, "_spawn_ts", time.time()))
            if since >= self.AUDIO_RESPAWN_S:     # wedged: reap it and start again
                self._kill()
                self.status.emit({"src": "NWR", "busy": None, "down": True, "live": False,
                                  "sdr": {"text": "NWR STALLED — no audio for %ds, restarting"
                                          % int(since), "state": "alert", "ok": False}})
                self._note_exit("no audio")
                return
            self.status.emit({"src": "NWR", "busy": None, "down": False, "live": False,
                              "sdr": {"text": ("NWR — audio arriving, confirming"
                                               if since <= self.AUDIO_GAP_S else
                                               "NWR — no audio reaching the decoder (%ds)"
                                               % int(since))
                                      if self._audio_ts else "NWR — waiting for audio",
                                      "state": "warn", "ok": False}})
            return
        if getattr(self, "_flaps", 0) and not self._exits and \
                time.time() - self._audio_ts < 1.0 and self._spawn_ts < time.time() - 30:
            self._flaps = 0                       # stable for 30 s: clear the FAULT
            self.fault.emit("")
        self.status.emit({"src": "NWR", "busy": None, "down": False, "last_heard_s": age, "live": True,
                          "sdr": {"text": "NWR %s %s%s" % (
                              self.label, self.channel,
                              "" if age is None else " · heard %ds ago" % int(age)),
                          "ok": True}})

    def _spawn(self):
        import nwr
        proc = _open_nwr_pipe(nwr.pipeline_argv(self.channel, self.gain))
        orphan = None
        with self._lock:                 # guard against a concurrent stop / revoke / PANIC
            if self._stop or not self._active or not radio_arbiter.arbiter.held_by(self.NAME):
                orphan = proc            # never run a decoder on a radio we no longer hold
            else:
                self._proc = proc
        if orphan is not None:
            self._terminate(orphan)
        elif proc is not None:
            self._thread = threading.Thread(target=self._read, args=(proc,), daemon=True)
            self._thread.start()

    def _respawn(self):
        self._kill()
        self._spawn()

    def _read(self, proc):
        try:
            for line in proc.stdout:
                if self._stop or proc is not self._proc:
                    break
                self._last_line = time.time()            # any decoder output = receiver alive
                self._handle_line(line)
        except Exception:
            pass

    def _handle_line(self, line):
        import nwr
        a = nwr.parse_same(line)
        if not a:                     # multimon-ng chatter / non-SAME -> skip, never fabricate
            return
        with self._lock:
            self._q.append(a)

    def _drain(self):
        with self._lock:
            items = list(self._q)
            self._q.clear()
        for a in items:
            self._emit_alert(a)

    def _emit_alert(self, a, demo=False):
        import nwr
        mins = nwr.purge_minutes(a.get("purge"))
        row = {"kind": "nwr", "time": time.strftime("%H:%M:%S"),
               "event": a["event_name"], "code": a["event"],
               "areas": ", ".join(a.get("areas", [])), "org": a.get("org_name", ""),
               "station": a.get("station", ""), "urgent": a.get("urgent", False),
               "valid": ("%d min" % mins) if mins is not None else "", "_demo": demo}
        self.row.emit(row)
        if not demo:                  # only real SAME headers reach the OPS alert strip
            eventbus.bus.publish(eventbus.alert(
                "PROWL", "%s — %s" % (a["event_name"], ", ".join(a.get("areas", [])) or "local"),
                severity="alert" if a.get("urgent") else "warn",
                event=a["event"], areas=a.get("areas", []), station=a.get("station", "")))

    def _demo_step(self):
        import nwr
        if self._demo_src is None:
            self._demo_src = nwr.Demo()        # persistent so demo cycles TOR/SVR/RWT/FFW
        for line in self._demo_src.lines():
            a = nwr.parse_same(line)
            if a:
                self._emit_alert(a, demo=True)
        self.status.emit({"src": "NWR", "sdr": {"text": "NWR DEMO", "state": "neutral"}})

    @staticmethod
    def _terminate(proc):
        """R4: SIGTERM the group, WAIT for exit (then SIGKILL) before anything respawns, so the
        dongle is really free when the next rtl_fm opens it."""
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass

    def _kill(self):
        with self._lock:
            proc, self._proc = self._proc, None
        self._terminate(proc)
        self._drain()        # RA-CL5c N-q: SAME headers parsed before the stop still get emitted

    def run(self):
        try:
            super().run()
        finally:
            self._finish()   # kill, wait, release — on this thread, never the GUI's


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



def _describe_mhz(freq_mhz_str):
    """freqdb.describe for an 'MHz' string, reused as-is. '—' if unknown/unparseable."""
    try:
        import freqdb
        return freqdb.describe(int(float(freq_mhz_str) * 1e6))
    except Exception:
        return "—"


# ============================ the app ============================

class ProwlApp(PalisadeApp):
    TITLE = "PROWL"
    LEASE = None          # each sub-mode leases the SDR per-run via radio_arbiter, not the base

    SUBMODES = ("SCAN", "FM", "NWR")
    SUBTABS = SUBMODES

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._submode = "SCAN"
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    def current_subtab(self):
        return self._submode

    def switch_subtab(self, name):
        self._switch_submode(name)

    # ---- keyboard (D8): Space holds the scan; [ ] step the band / tuner / channel ----
    def handle_key(self, text):
        if self._submode == "SCAN":
            if text == " ":
                self._toggle_hold()
                return True
            if text in "sS":                       # E2: skip / lock out the current channel
                self._skip_current()
                return True
            if text in "[]":
                n = self.bank_combo.count()
                if n:
                    step = 1 if text == "]" else -1
                    self.bank_combo.setCurrentIndex((self.bank_combo.currentIndex() + step) % n)
                return True
        elif self._submode == "FM" and text in "[]":
            st = self.fm_step.currentData() if hasattr(self, "fm_step") else 0.2
            self._fm_step(st if text == "]" else -st)
            return True
        elif self._submode == "NWR" and text in "[]":
            n = self.nwr_combo.count()
            if n:
                step = 1 if text == "]" else -1
                self.nwr_combo.setCurrentIndex((self.nwr_combo.currentIndex() + step) % n)
            return True
        return False

    def primary_action(self):
        if self._resume_radio():
            return True
        if self._submode == "SCAN":
            self._toggle_hold()
            return True
        if self._submode == "FM":
            self._fm_retune()
            return True
        return False

    def tune_fm(self, mhz):
        """Shell 'send to tuner' (D10): open the FM sub-tab on this frequency."""
        self._switch_submode("FM")
        self.fm_freq.setValue(float(mhz))
        self._fm_retune()

    # ---- layout ----
    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.busy = StatusLine("")                 # RADIO BUSY / STANDBY line for the sub-mode
        self.busy.setStyleSheet("color:%s;" % self._tok["warn"])
        lay.addWidget(self.busy)

        self.stack = QtWidgets.QStackedWidget()
        self._pages = {"SCAN": self._build_scan_page(),
                       "FM": self._build_fm_page(),
                       "NWR": self._build_nwr_page()}
        for m in self.SUBMODES:
            self.stack.addWidget(self._pages[m])
        lay.addWidget(self.stack, 1)
        self._sync_mode_buttons()
        return body

    def _build_scan_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.bar = ControlBar()
        self.squelch = QtWidgets.QSpinBox()
        if self.demo:
            self.squelch.setRange(-120, -20)
            self.squelch.setValue(-70)
            self.squelch.setSuffix(" dBm")
            self.squelch.setToolTip("Demo squelch (synthetic levels)")
        else:
            # B2: the live control IS the engine's rtl_fm power squelch (-l), in its own units
            self.squelch.setRange(0, 1000)
            try:
                import scanner as _eng
                self.squelch.setValue(int(_load_scanner_settings(_eng)[0].get("nfm_squelch", 50)))
            except Exception:
                self.squelch.setValue(50)
            self.squelch.setSuffix(" -l")
            self.squelch.setToolTip("NFM squelch: rtl_fm -l level (0 = open). Raise it if the "
                                    "scanner stops on empty channels, lower it if it misses traffic. "
                                    "Applies to the live scan at once.")
        self.squelch.valueChanged.connect(self._sq)
        self.bar.add_field("squelch", self.squelch, "Squelch")

        self.bank_combo = QtWidgets.QComboBox()
        try:
            import scanner as engine
            banks = engine.BANK_ORDER
        except ImportError:
            banks = ["NOAA Wx", "CB", "GMRS/FRS", "Marine VHF", "Airband"]
        self.bank_combo.addItems(banks)
        try:
            import scanner as _eng2
            self.bank_combo.setCurrentText(_eng2.DEFAULTS["bank"])   # E2: an intermittent bank
        except ImportError:
            self.bank_combo.setCurrentText("GMRS/FRS")
        self.bank_combo.currentTextChanged.connect(self._set_bank)
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
        self.sig_bar.setFixedHeight(14)
        self.sig_bar.setStyleSheet(
            "QProgressBar { background: %s; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: %s; border-radius: 3px; }"
            % (self._tok["well"], self._tok["accent"]))
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
        self.fdb_results.setProperty("class", "note")
        self.fdb_results.setWordWrap(True)
        self.fdb_results.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        fl.addWidget(self.fdb_results)
        right.addWidget(fdb, 2)

        split.addLayout(right, 1)
        lay.addLayout(split, 1)
        return page

    def _build_fm_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        bar = ControlBar()
        self.fm_freq = QtWidgets.QDoubleSpinBox()
        self.fm_freq.setRange(24.0, 1766.0)
        self.fm_freq.setDecimals(3)                 # B1: 162.550 stays 162.550, not 162.6
        self.fm_freq.setSingleStep(0.1)
        self.fm_freq.setValue(FM_DEFAULTS["freq"])
        self.fm_freq.setSuffix(" MHz")
        self.fm_freq.editingFinished.connect(self._fm_retune)
        bar.add_field("freq", self.fm_freq, "Tune")
        self.fm_step = QtWidgets.QComboBox()        # B1: a step menu for narrow channels
        for label, step in FM_STEPS:
            self.fm_step.addItem(label, step)
        self.fm_step.setCurrentIndex(FM_STEP_DEFAULT)
        self.fm_step.currentIndexChanged.connect(
            lambda _i: self.fm_freq.setSingleStep(self.fm_step.currentData()))
        bar.add_field("step", self.fm_step, "Step")
        bar.add_button("−", lambda: self._fm_step(-self.fm_step.currentData()))
        bar.add_button("+", lambda: self._fm_step(self.fm_step.currentData()))
        self.fm_mode = QtWidgets.QComboBox()
        self.fm_mode.addItems(["wbfm", "nbfm"])
        self.fm_mode.currentTextChanged.connect(lambda _=None: self._fm_retune())
        bar.add_field("mode", self.fm_mode, "Mode")
        self.fm_gain = QtWidgets.QSpinBox()
        self.fm_gain.setRange(0, 49)
        self.fm_gain.setValue(FM_DEFAULTS["gain"])
        self.fm_gain.setSuffix(" dB")
        self.fm_gain.valueChanged.connect(self._fm_retune)
        bar.add_field("gain", self.fm_gain, "Gain")
        self.fm_rds = QtWidgets.QCheckBox("RDS")
        self.fm_rds.setChecked(FM_DEFAULTS["rds"])
        self.fm_rds.toggled.connect(lambda _=None: self._fm_retune())
        bar.lay.addWidget(self.fm_rds)
        bar.add_stretch()
        self.fm_audio = QtWidgets.QLabel("—")
        self.fm_audio.setProperty("class", "value")
        bar.lay.addWidget(micro("Audio"))
        bar.lay.addWidget(self.fm_audio)
        lay.addWidget(bar)

        self.fm_station = DetailCard("STATION")
        self.fm_station.set_hero("—", "tune a frequency")
        lay.addWidget(self.fm_station, 1)
        return page

    def _build_nwr_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        bar = ControlBar()
        self.nwr_combo = QtWidgets.QComboBox()
        for freq, label in NWR_CHANNELS:
            self.nwr_combo.addItem("%s  %s" % (label, freq.rstrip("M")), (freq, label))
        self.nwr_combo.currentIndexChanged.connect(self._nwr_retune)
        bar.add_field("channel", self.nwr_combo, "NWR channel")
        bar.add_stretch()
        bar.lay.addWidget(micro("Receiver"))
        # CL5-fix 7 / N2: this says LIVE only while the arbiter says PROWL-NWR HOLDS the radio
        # AND the worker reported a running decoder in the last few seconds; anything else is
        # NOT MONITORING, in the alert colour. A dead weather receiver must never look healthy.
        self.nwr_state = QtWidgets.QLabel("DEMO — synthetic alerts" if self.demo
                                          else "NOT MONITORING — starting")
        self.nwr_state.setProperty("class", "value")
        bar.lay.addWidget(self.nwr_state)
        self._live_ts = 0.0
        self._live_why = "starting"
        self._nwr_timer = QtCore.QTimer(page)
        self._nwr_timer.timeout.connect(self._sync_nwr_state)
        self._nwr_timer.start(1000)
        lay.addWidget(bar)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        self.nwr_feed = FeedTable([("time", "TIME"), ("event", "EVENT"),
                                   ("areas", "AREAS"), ("station", "STATION")])
        self.nwr_feed.selected.connect(self._nwr_show)
        split.addWidget(self.nwr_feed, 3)
        self.nwr_detail = DetailCard("SAME ALERT")
        self.nwr_detail.set_hero("—", "no alerts" if self.demo else "NOT MONITORING")
        split.addWidget(self.nwr_detail, 2)
        lay.addLayout(split, 1)
        return page

    # ---- sub-mode switching (only one worker/lease live at a time) ----
    def _switch_submode(self, mode):
        if mode == self._submode:
            self._sync_mode_buttons()
            return
        self._submode = mode
        self.stack.setCurrentWidget(self._pages[mode])
        self._sync_mode_buttons()
        self.busy.setText("")
        # CL5-fix2 (N-c): never wait on the GUI thread. The old sub-mode stops on its own thread
        # (kill -> wait -> release); the new one starts when it has finished.
        self.swap_worker()
        if self.swapping():
            self.busy.setText("%s: waiting for the previous mode to give the radio back" % mode)
        self._sync_nwr_state()

    def on_swapped(self):
        self.busy.setText("" if self._worker is not None
                          else "%s: radio off — press Enter to start" % self._submode)
        self._sync_nwr_state()

    def _sync_mode_buttons(self):
        self._sync_rail()

    def make_worker(self):
        if self._submode == "FM":
            w = FmWorker(demo=self.demo, freq=self.fm_freq.value(),
                         mode=self.fm_mode.currentText(), gain=self.fm_gain.value(),
                         rds=self.fm_rds.isChecked())
        elif self._submode == "NWR":
            freq, label = self.nwr_combo.currentData() or NWR_CHANNELS[0]
            w = NwrWorker(demo=self.demo, channel=freq, label=label)
        else:
            w = ScanWorker(demo=self.demo, bank=self.bank_combo.currentText(),
                           squelch=self.squelch.value())
        w.set_active(self._active)       # inherit the page's front/back state at start
        return w

    def set_active(self, active):
        super().set_active(active)
        if self._worker is not None and hasattr(self._worker, "set_active"):
            self._worker.set_active(active)   # release the dongle while PROWL is backgrounded
        self._sync_nwr_state()

    def on_panic(self):
        """PANIC (CL5-fix 5): the sub-mode drops the radio and stays off — it must not respawn
        its decoder after the shell kills it. Flags only; the shell then frees the arbiter and
        reports what the arbiter says. Enter (or re-opening the page) resumes."""
        w = self._worker
        if w is not None and hasattr(w, "hold_off") and not self.demo:
            w.hold_off("PANIC")
        if not self.demo:
            self.cancel_swap()           # a switch in flight must not start a decoder after PANIC
        return []

    def _resume_radio(self):
        """After a revoke / PANIC the sub-mode stays off until the operator asks again."""
        w = self._worker
        if w is None and self._started and not self._stopped and self._active \
                and not self.swapping():
            self.swap_worker()           # PANIC cancelled a switch: start the shown sub-mode now
            return True
        if w is not None and getattr(w, "held_off", False) and self._active:
            w.set_active(True)
            self.busy.setText("")
            return True
        return False

    # ---- SCAN handlers ----
    def _set_bank(self, bank):
        if isinstance(self._worker, ScanWorker):
            self._worker.set_bank(bank)

    def _toggle_hold(self):
        if isinstance(self._worker, ScanWorker):
            self._worker.hold = not self._worker.hold
            self.hold_btn.setText("HOLD" if self._worker.hold else "SCAN")

    def _sq(self, v):
        if isinstance(self._worker, ScanWorker):
            if self.demo:
                self._worker.squelch = v
            else:
                self._worker.set_nfm_squelch(v)      # B2: wired to the engine's live setting

    def _skip_current(self):
        if isinstance(self._worker, ScanWorker):
            f = self._worker.skip_current()
            if f is not None:
                self.set_chip("scan", "locked out %.4f" % f, state="warn")

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

    def _hot_color(self):
        # green means a real, healthy signal: synthetic demo rows never get it (D9 / RA-CL1)
        return self._tok["accent"] if self.demo else self._tok["live"]

    def _sig_color(self, sig, hot):
        if hot:
            return self._hot_color()
        if sig > -60:
            return self._tok["warn"]
        return self._tok["muted"]

    def _on_scan_row(self, msg):
        rows = msg["rows"]
        for r in rows:
            sig = int(r["sig"])
            r["_colors"] = {"sig": self._sig_color(sig, r.get("_hot", False))}
            if r.get("_hot"):
                r["_colors"]["label"] = self._hot_color()
                r["_colors"]["freq"] = self._hot_color()
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
            ("ALLOCATION", _describe_mhz(row.get("freq", ""))),
        ])

    # ---- FM handlers ----
    def _fm_step(self, delta):
        self.fm_freq.setValue(round(self.fm_freq.value() + delta, 4))   # B1: keep kHz precision
        self._fm_retune()

    def _fm_retune(self):
        freq = self.fm_freq.value()
        # auto narrowband in the NOAA weather band, like the Tk fm app
        if 162.3 < freq < 162.6 and self.fm_mode.currentText() != "nbfm":
            self.fm_mode.blockSignals(True)
            self.fm_mode.setCurrentText("nbfm")
            self.fm_mode.blockSignals(False)
        if isinstance(self._worker, FmWorker):
            self._worker.gain = self.fm_gain.value()
            self._worker.set_tune(freq, self.fm_mode.currentText(), self.fm_rds.isChecked())

    def _on_fm_row(self, msg):
        rds = msg.get("rds") or {}
        ps = rds.get("ps") or ("DEMO" if self.demo else "—")
        self.fm_station.set_hero(ps, "%.1f MHz · %s" % (msg["freq"], msg.get("mode", "")))
        rows = [("FREQUENCY", "%.1f MHz" % msg["freq"]), ("MODE", msg.get("mode", ""))]
        if rds.get("pi"):
            rows.append(("PI", rds["pi"]))
        if rds.get("prog_type"):
            rows.append(("PTY", rds["prog_type"]))
        if rds.get("callsign"):
            rows.append(("CALL", rds["callsign"]))
        if rds.get("radiotext"):
            rows.append(("TEXT", rds["radiotext"]))
        rows.append(("ALLOCATION", _describe_mhz("%.3f" % msg["freq"])))
        self.fm_station.set_rows(rows)
        self.fm_audio.setText("LIVE ♪" if msg.get("audio") else "—")

    # ---- NWR handlers ----
    def _nwr_retune(self):
        data = self.nwr_combo.currentData()
        if data and isinstance(self._worker, NwrWorker):
            self._worker.set_channel(data[0], data[1])

    def _on_nwr_row(self, row):
        row = dict(row)
        if row.get("urgent"):
            row["_colors"] = {"event": self._tok.get("alert", self._tok["warn"])}
        self.nwr_feed.model.prepend(row, cap=200)
        if self.nwr_feed.model.rowCount() == 1:
            self._nwr_show(row)

    def _nwr_show(self, row):
        self.nwr_detail.set_hero(row.get("event", "—"),
                                 ("URGENT" if row.get("urgent") else "advisory"))
        self.nwr_detail.set_rows([
            ("TIME", row.get("time", "")),
            ("CODE", row.get("code", "")),
            ("AREAS", row.get("areas", "") or "—"),
            ("ORIGIN", row.get("org", "") or "—"),
            ("STATION", row.get("station", "") or "—"),
            ("VALID", row.get("valid", "") or "—"),
        ])

    # ---- shared row/status routing ----
    def on_row(self, msg):
        kind = msg.get("kind") if isinstance(msg, dict) else None
        if kind == "fm":
            self._on_fm_row(msg)
        elif kind == "nwr":
            self._on_nwr_row(msg)
        else:
            self._on_scan_row(msg)

    NWR_STALE_S = 3.0          # no healthy NWR status for this long -> NOT MONITORING

    def nwr_monitoring(self):
        """True only if the NWR receiver is really running on a radio the arbiter says we hold."""
        if self.demo or self._submode != "NWR" or not isinstance(self._worker, NwrWorker):
            return False
        return bool(self._live_ts) and (time.time() - self._live_ts) < self.NWR_STALE_S \
            and radio_arbiter.arbiter.held_by(NwrWorker.NAME)

    def _sync_nwr_state(self):
        if not hasattr(self, "nwr_state"):
            return
        if self.demo:
            text, color, live = "DEMO — synthetic alerts", None, True
        elif self.nwr_monitoring():
            text, color, live = "LIVE · %s" % (self._worker.label + " " +
                                               self._worker.channel.rstrip("M")), \
                self._tok["live"], True
        else:
            why = self._live_why if self._submode == "NWR" else "NWR not selected"
            if self._live_ts and (time.time() - self._live_ts) >= self.NWR_STALE_S:
                why = "receiver silent (no status for %ds)" % int(time.time() - self._live_ts)
            text, color, live = "NOT MONITORING — %s" % why, \
                self._tok.get("alert", self._tok["warn"]), False
        if self.nwr_state.text() != text:
            self.nwr_state.setText(text)
            self.nwr_state.setStyleSheet("" if color is None else "color:%s;" % color)
        if self.nwr_feed.model.rowCount() == 0:
            self.nwr_detail.set_hero("—", "no alerts" if live else "NOT MONITORING")

    def on_status(self, status):
        super().on_status(status)
        if "live" in status and status.get("src") == "NWR":
            if status["live"]:
                self._live_ts = time.time()
            else:
                self._live_ts = 0.0
                self._live_why = (status.get("sdr") or {}).get("text") or "receiver off"
                if status.get("busy"):
                    self._live_why = "RADIO BUSY — held by %s" % status["busy"]
            self._sync_nwr_state()
        if status.get("off") or status.get("acquiring"):
            text = (status.get("sdr") or {}).get("text", "")
            w = self._worker
            if status.get("off") and getattr(w, "held_off", False):
                text += "  ·  press Enter to resume"
            self.busy.setText(text)
        elif status.get("standby"):
            self.busy.setText(status.get("sdr", {}).get("text", "STANDBY"))
            if self._submode == "SCAN":
                self.active.setText("standby — no device")
        elif "busy" in status:
            owner = status["busy"]
            self.busy.setText("RADIO BUSY — held by %s" % owner if owner else "")
