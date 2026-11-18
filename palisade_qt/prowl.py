"""PROWL — scanner / tuner, wired to the real scanner / fm / nwr engines.

Three sub-modes, each leasing the one built-in SDR through the shared radio_arbiter (only one
holds the dongle at a time; switching releases the old and acquires the new; the page releases
on background/close):

  * SCAN — scanner.listen_channel() across a preset bank (lease "PROWL-SCAN").
  * FM   — fm.pipeline()/fm.Pipe broadcast + weather tuner with audio + RDS (lease "PROWL-FM").
  * NWR  — nwr.pipeline_argv()/nwr.parse_same() NOAA Weather Radio SAME/EAS alerts (lease "PROWL-NWR").

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
from .timebase import zulu
from .kit import ControlBar, FeedTable, DetailCard, micro
from .worker import Worker
from .kit.components import Section, StatusLine, set_run
from .iqworker import FastScanWorker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import banks  # noqa: E402
import dsp  # noqa: E402

CUSTOM_RANGE = "Custom range"
MY_BOOKMARKS = "My bookmarks"     # the bookmarks saved in PRISM (prism.json)
SCAN_STEPS = (("5 kHz", 5000), ("6.25 kHz", 6250), ("7.5 kHz", 7500), ("8.33 kHz", 8333.33),
              ("10 kHz", 10000), ("12.5 kHz", 12500), ("15 kHz", 15000), ("20 kHz", 20000),
              ("25 kHz", 25000), ("50 kHz", 50000), ("100 kHz", 100000), ("200 kHz", 200000))
SCAN_DEFAULTS = {"engine": "", "bank": "Airband (full)", "bank_squelch": {}, "dwell": 0.15,
                 "resume": 2.0, "max_hold": 30.0, "audio": True, "include_ranges": True,
                 "range_lo": 118.0, "range_hi": 136.975, "range_step": 25000.0,
                 "range_mode": "AM", "priority_on": False, "priority_mhz": 121.5,
                 "priority_mode": "AM", "priority_every": 2.0, "lockouts": []}


def _load_scan_cfg():
    try:
        import suite
        return suite.settings("prowl_scan", SCAN_DEFAULTS)
    except Exception:
        return dict(SCAN_DEFAULTS), None


def prism_bookmarks():
    """PRISM's saved bookmarks as scan channels [(MHz, label, MODE, bw_hz)], read-only (the file
    is not created when PRISM has never run)."""
    try:
        import suite
        cfg = suite.load_json(os.path.join(suite.CFG, "prism.json"), {}) or {}
    except Exception:
        return []
    out = []
    for b in cfg.get("bookmarks") or []:
        try:
            hz = int(b["hz"])
            mode = b.get("mode") if b.get("mode") in dsp.MODES else "NFM"
            bw = float(b.get("bw") or 0) or dsp.DEFAULT_BW[mode]
            out.append((round(hz / 1e6, 6), str(b.get("label", ""))[:40], mode,
                        dsp.clamp_bw(mode, bw)))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def _default_engine(demo):
    """FAST (rtl_tcp IQ) when rtl_tcp is installed; CLASSIC (rtl_fm per channel) otherwise and
    in demo (the demo channel list)."""
    return "fast" if (not demo and shutil.which("rtl_tcp")) else "classic"

DEMO_CHANNELS = [
    ("162.400", "NOAA WX1"), ("154.265", "Fire Disp"), ("155.340", "EMS"),
    ("121.500", "Aircraft Guard"), ("146.520", "2m Call"), ("462.5625", "FRS 1"),
    ("453.212", "City PD"), ("159.480", "Rail"),
]

# NOAA Weather Radio 7-channel plan (162.400–162.550 MHz). nwr.py only hardcodes 162.400, so the
# PROWL NWR sub-mode owns the channel list and calls nwr.pipeline_argv() per channel (reused AS-IS).
NWR_CHANNELS = [
    ("162.400M", "WX2"), ("162.425M", "WX4"), ("162.450M", "WX5"), ("162.475M", "WX3"),
    ("162.500M", "WX6"), ("162.525M", "WX7"), ("162.550M", "WX1"),
]

FM_DEFAULTS = {"freq": 97.3, "mode": "wbfm", "gain": 40, "squelch": 0, "rds": True}
# B1: tuning steps — broadcast 200 kHz, NBFM 25 / 12.5 / 5 kHz (weather radio, marine, business)
FM_STEPS = (("200 kHz", 0.2), ("100 kHz", 0.1), ("25 kHz", 0.025), ("12.5 kHz", 0.0125),
            ("5 kHz", 0.005))
FM_STEP_DEFAULT = 0


from .kit.seams import offscreen as _offscreen  # noqa: E402  (C5: one copy)


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
                                  "sdr": {"text": radio_arbiter.busy_text(self.NAME), "ok": False}})
                return False
            self._has_radio = True
        st, owner = arb.state()
        if owner != self.NAME:                       # freed under us (forced free / PANIC / H4)
            self._has_radio = False
            self._give_back(radio_arbiter.lost_reason(self.NAME))
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

    def _refuse_settings(self, err):
        """L4: a settings value failed its check (frequency, gain). Give the radio back, show a
        FAULT, and do not retry until the operator retunes — never a silent default."""
        self._refused = str(err)[:120]
        self._give_back("settings refused")
        self.fault.emit("FAULT: %s settings refused: %s" % (self.LABEL, self._refused))
        self.status.emit({"src": self.LABEL, "busy": None, "live": False, "off": True,
                          "fault": self._refused,
                          "sdr": {"text": "%s FAULT — SETTINGS REFUSED" % self.LABEL,
                                  "state": "alert", "ok": False}})

    EARLY_EXIT_S = 3.0          # a decoder that dies sooner than this did not really run
    EARLY_EXITS_MAX = 3         # … this many times in a row: stop, say so, give the radio back

    def _stall(self, why):
        """RA-CL8c: the decoder cannot run (exits at once, missing binary). Give the radio back,
        show a FAULT and do not retry until the operator retunes/restarts — never a respawn loop
        on a held radio, never a LIVE claim."""
        self._refused = str(why)[:120]
        self._give_back("decoder fault")
        self.fault.emit("FAULT: %s %s" % (self.LABEL, self._refused))
        self.status.emit({"src": self.LABEL, "busy": None, "live": False, "off": True,
                          "fault": self._refused,
                          "sdr": {"text": "%s FAULT — %s" % (self.LABEL, self._refused),
                                  "state": "alert", "ok": False}})

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

    def __init__(self, demo=False, bank="NOAA Wx", squelch=30, channels=None, timing=None,
                 lockouts=(), parent=None):
        super().__init__(demo=demo, interval_ms=350, parent=parent)
        self.squelch = squelch
        self.hold = False
        self._bank = bank
        # radio cluster: the page's bank / range list and its dwell / resume delay / max hold
        # ({"dwell", "hold", "max_active"} in the engine's own keys) override scanner.json
        self._channels_override = [tuple(c[:3]) for c in channels] if channels else None
        self._timing = dict(timing or {})
        self._scan = None          # live scan state dict; kept on self so stop() can break the
        self._fatal = False        # blocking listen_channel (scan["on"]=False) — else it hangs
        self._skip = set(round(float(f), 4) for f in lockouts)   # E2: locked-out channels (MHz)
        self._nfm_sq = None        # B2: live NFM squelch (rtl_fm -l units) set from the page
        self._settings = None

    def set_bank(self, bank, channels=None, lockouts=()):
        self._bank = bank
        self._channels_override = [tuple(c[:3]) for c in channels] if channels else None
        self._skip = set(round(float(f), 4) for f in lockouts)
        if self._scan is not None:
            self._scan["pause"] = True          # break the current listen; the loop re-reads

    def set_timing(self, **kw):
        """dwell / hold (resume delay) / max_active, in scanner.json units (seconds)."""
        self._timing.update({k: float(v) for k, v in kw.items()})
        if self._settings is not None:
            self._settings.update(self._timing)

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
        channels = self._bank_list(engine, s)
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
                level = random.randint(40, 95) if hot else None     # synthetic (demo) level %
                if hot and level > self.squelch:
                    active = (freq, label, level)
                rows.append({"_id": freq, "freq": freq, "label": label, "sig": _level_text(level),
                             "_level": level, "last": zulu() if hot else "", "_hot": hot})
            self.row.emit({"rows": rows, "active": active})
            if not active:
                self.status.emit({"sdr": {"text": "SCAN DEMO", "state": "neutral"}})
            self.sleep(self.interval_ms)

    def _bank_list(self, engine, s):
        if self._channels_override:
            return [(float(f), str(lb), "am" if str(m).upper() == "AM" else "nfm")
                    for f, lb, m in self._channels_override]
        return (engine.bank_channels(self._bank, s.get("custom", []))
                or engine.bank_channels(engine.DEFAULTS["bank"], []))

    def _check_scanner_settings(self, s):
        """RA-CL8b NEW-D: a malformed scanner.json crashed the worker with only 'SCAN OFF'. Check
        the values listen_channel uses; raise SettingsRefused so the page says why."""
        import argsafe
        argsafe.gain_arg(s.get("gain"))
        for k in ("squelch", "nfm_squelch", "dwell", "hold", "max_active"):
            v = s.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1e6:
                raise argsafe.SettingsRefused("bad %s in scanner settings: %r" % (k, v))
        c = s.get("custom", [])
        if not isinstance(c, list) or not all(isinstance(x, str) for x in c):
            raise argsafe.SettingsRefused("bad custom channel list in scanner settings: %r" % (c,))

    def _run_live(self):
        import scanner as engine
        import argsafe
        s, _ = _load_scanner_settings(engine)
        if self._nfm_sq is not None:
            s["nfm_squelch"] = self._nfm_sq
        try:
            self._check_scanner_settings(s)
        except argsafe.SettingsRefused as e:
            self._refuse_settings(e)
            return
        s.update(self._timing)
        self._settings = s
        channels = self._bank_list(engine, s)
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
                    if self._channels_override is not None or self._bank:
                        nl = self._bank_list(engine, s)
                        if nl != channels:      # the page changed the bank / range
                            channels = nl
                            self._channels = channels
                            hits = {}
                            scan["idx"] = 0
                idx = scan["idx"] % len(channels)
                if channels[idx][0] in self._skip and len(self._skip) < len(channels):
                    scan["idx"] = (idx + 1) % len(channels)
                    continue
                freq, label, mode = channels[idx]
                scan["rms"] = 0.0
                self._early_this = False
                result = engine.listen_channel(freq, mode, s, scan,
                                               self._make_post(freq, label, hits),
                                               sink_fn=sink_fn, clock=time.time)
                if self._stop or not scan["on"]:
                    break
                if self._fatal:                     # rtl_fm missing: it will not come back
                    self._fatal = False
                    self._stall(getattr(self, "_fatal_msg", "scanner fault"))
                    break
                # RA-CL8c NEW-H: rtl_fm quitting at once on every channel is a fault, not a
                # quiet band: stop, say so, give the radio back
                early = self._early_count = (getattr(self, "_early_count", 0) + 1
                                             if self._early_this else 0)
                if early >= self.EARLY_EXITS_MAX:
                    self._early_count = 0
                    self._stall("rtl_fm exits at once (×%d) — is the SDR free?" % early)
                    break
                if self._early_this:
                    continue                        # not a listen: do not mark the channel quiet
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
                self._fatal_msg = (msg[1] if isinstance(msg, tuple) and len(msg) > 1
                                   else "scanner fault")
                self.error.emit(self._fatal_msg)
            elif kind == "status":                  # RA-CL8c NEW-H: rtl_fm exited at once
                self._early_this = True
                self._early_msg = msg[1] if isinstance(msg, tuple) and len(msg) > 1 else ""
        return post

    def _emit_state(self, channels, hits, scan, held=False):
        rows = []
        active = None
        now = time.time()
        # H11: the only thing measured is the AUDIO level of the channel being listened to right
        # now (rtl_fm's output RMS). It is shown as a unitless level on THAT channel only; every
        # other channel is blank — never an invented dBm, never a constant -100.
        cur = channels[scan.get("idx", 0) % len(channels)][0] if channels else None
        rms = float(scan.get("rms", 0) or 0)
        for freq, label, mode in channels:
            t_hit = hits.get(freq)
            hot = t_hit is not None and (now - t_hit) < 30          # B3: epoch arithmetic
            level = None
            if hot and not held and freq == cur and rms > 0:
                level = int(round(min(1.0, rms / 8000.0) * 100))
            last = zulu(t_hit) if t_hit else ""
            if hot and not held:
                active = (str(freq), label, level)
            rows.append({"_id": freq,          # the cursor follows the channel across refreshes
                         "freq": "%.4f" % freq, "label": label + (" ⊘" if freq in self._skip else ""),
                         "sig": _level_text(level), "_level": level, "last": last, "_hot": hot,
                         "_skip": freq in self._skip})
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

    def __init__(self, demo=False, freq=97.3, mode="wbfm", gain=40, squelch=0, rds=True, parent=None):
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
        self._refused = None
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
        if getattr(self, "_refused", None) and not self._retune:
            return                            # L4: refused settings hold until a retune
        self._refused = None
        if not self._ensure_lease():          # gives the radio back (kill, wait, release) if off
            return
        if self._retune:
            self._retune = False
            self._respawn()
        elif self._pipe is None:
            self._spawn()
        elif self._pipe.poll() is not None:         # pipeline died (device yanked / preempted)
            # RA-CL8c NEW-G: count exits that come right after a spawn; a decoder that cannot
            # run is a FAULT with the radio given back, not a respawn every 500 ms under "♪"
            quick = time.time() - getattr(self, "_spawn_ts", 0) < self.EARLY_EXIT_S
            self._early = getattr(self, "_early", 0) + 1 if quick else 0
            if self._early >= self.EARLY_EXITS_MAX:
                self._early = 0
                self._stall("decoder exits at once (×%d) — is the SDR free?" % self.EARLY_EXITS_MAX)
                return
            self._respawn()
        if self._refused:
            return
        with self._lock:
            rds = dict(self._rds)
        pipe = self._pipe
        # ♪ only for a pipeline that is running and has stayed up past the early-exit window start
        audio = pipe is not None and pipe.poll() is None and \
            time.time() - getattr(self, "_spawn_ts", 0) >= 1.0
        self.row.emit({"kind": "fm", "freq": self.freq, "mode": self.mode,
                       "rds": rds, "audio": audio})
        self.status.emit({"busy": None, "live": audio,
                          "sdr": {"text": ("FM %.1f ♪" % self.freq) if audio
                                          else ("FM %.1f" % self.freq), "ok": True}})

    def _spawn(self):
        import fm
        try:
            rtl, mid, sink = fm.pipeline(self.freq, self.mode, self.gain, self.squelch, self.rds)
        except Exception as e:      # RA-CL8: any malformed setting refuses
            self._refuse_settings(e)
            return
        try:
            pipe = _open_fm_pipe(rtl, mid, sink, self._on_rds)
        except OSError as e:          # RA-CL8c NEW-I: no rtl_fm/redsea/aplay: FAULT, radio back
            self._stall("cannot start the decoder: %s" % e)
            return
        self._spawn_ts = time.time()
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

    def __init__(self, demo=False, channel="162.400M", label="WX2", gain=0, parent=None):
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
        self._refused = None
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
        if getattr(self, "_refused", None) and not self._retune:
            return                            # L4: refused settings hold until a retune
        self._refused = None
        if not self._ensure_lease():          # gives the radio back (kill, wait, release) if off
            return
        if self._proc is None and self._flap_hold():
            return
        if self._retune:
            self._retune = False
            self._respawn()
        elif self._proc is None:
            self._spawn()
        if self._refused:
            return
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
        try:
            argv = nwr.pipeline_argv(self.channel, self.gain)
        except Exception as e:      # RA-CL8: any malformed setting refuses
            self._refuse_settings(e)
            return
        proc = _open_nwr_pipe(argv)
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
        row = {"kind": "nwr", "time": zulu(),
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



def _level_text(level):
    """H11: a unitless audio level (0-100 %) or blank — never dBm, which nothing here measures."""
    return "%d%%" % level if level is not None else ""


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
        self._scfg, self._scfg_path = _load_scan_cfg()
        eng = self._scfg.get("engine")
        self._engine = eng if eng in ("fast", "classic") and not demo else _default_engine(demo)
        self._sel_row = None
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
        c = self._scfg
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.bar = ControlBar()
        self.bar.lay.setSpacing(10)
        self.hold_btn = self.bar.add_button("SCAN", self._toggle_hold)
        self.hold_btn.setMinimumWidth(96)
        self.hold_btn.setToolTip("Green = scanning. Press (or Space) to HOLD on the current "
                                 "channel (red); press again to resume.")
        self.engine_combo = QtWidgets.QComboBox()
        self.engine_combo.addItem("FAST (IQ)", "fast")
        self.engine_combo.addItem("CLASSIC (rtl_fm)", "classic")
        self.engine_combo.setToolTip("FAST judges every channel in a ~1.7 MHz capture at once "
                                     "(rtl_tcp). CLASSIC opens rtl_fm per channel.")
        self.engine_combo.setCurrentIndex(0 if self._engine == "fast" else 1)
        self.bar.add_field("engine", self.engine_combo, "Engine")
        self.bank_combo = QtWidgets.QComboBox()
        self.bank_combo.addItems(list(banks.BANK_ORDER) + [MY_BOOKMARKS, CUSTOM_RANGE])
        bank = c["bank"] if c["bank"] in banks.BANK_ORDER + [MY_BOOKMARKS, CUSTOM_RANGE] \
            else banks.BANK_ORDER[0]
        self.bank_combo.setCurrentText(bank)
        self.bar.add_field("bank", self.bank_combo, "Bank")
        # classic engine squelch (rtl_fm -l, or the demo's synthetic %) — B2, unchanged
        self.squelch = QtWidgets.QSpinBox()
        if self.demo:
            self.squelch.setRange(0, 100)
            self.squelch.setValue(30)
            self.squelch.setSuffix(" %")
            self.squelch.setToolTip("Demo squelch on the synthetic audio level (0-100)")
        else:
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
        self._sq_classic_box = self.bar.add_field("squelch", self.squelch, "Squelch")
        # FAST engine squelch: dB above the measured noise floor, remembered per bank
        self.fast_sq = QtWidgets.QSpinBox()
        self.fast_sq.setRange(2, 40)
        self.fast_sq.setSuffix(" dB")
        self.fast_sq.setToolTip("Stop on a channel this many dB above the noise floor. "
                                "Remembered per bank.")
        self.fast_sq.setValue(self._bank_sq(bank))
        self.fast_sq.valueChanged.connect(self._fast_sq_changed)
        self.bar.add_field("fast_squelch", self.fast_sq, "Squelch (per bank)")
        self.step_combo = QtWidgets.QComboBox()
        for label, hz in SCAN_STEPS:
            self.step_combo.addItem(label, hz)
        self.bar.add_field("step", self.step_combo, "Range step")
        self.bar.add_stretch()
        for cb in (self.engine_combo, self.bank_combo, self.step_combo):
            cb.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.engine_combo.setMinimumContentsLength(12)
        self.bank_combo.setMinimumContentsLength(16)
        self.step_combo.setMinimumContentsLength(8)
        lay.addWidget(self.bar)

        info = QtWidgets.QHBoxLayout()
        info.setContentsMargins(4, 0, 4, 0)
        info.setSpacing(12)
        self.active = QtWidgets.QLabel("—  scanning")
        self.active.setProperty("class", "value")
        info.addWidget(self.active)
        self.scan_info = QtWidgets.QLabel("")
        self.scan_info.setProperty("class", "note")
        self.scan_info.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                     QtWidgets.QSizePolicy.Preferred)
        info.addWidget(self.scan_info, 1)
        self.heard_only = QtWidgets.QCheckBox("Named + heard only")
        self.heard_only.setToolTip("Hide range steps that have never broken squelch "
                                   "(a full airband range is 760 rows)")
        self.heard_only.setChecked(True)
        info.addWidget(self.heard_only)
        lay.addLayout(info)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(8)
        self.feed = FeedTable([("freq", "FREQUENCY"), ("label", "CHANNEL"), ("mode", "MODE"),
                               ("sig", "LEVEL"), ("hits", "HITS"), ("last", "LAST (Z)")])
        self.feed.selected.connect(self._show)
        split.addWidget(self.feed, 1)

        right = QtWidgets.QScrollArea()
        right.setWidgetResizable(True)
        right.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        right.setFrameShape(QtWidgets.QFrame.NoFrame)
        right.setFixedWidth(320)
        self.scan_side = right
        inner = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(inner)
        rv.setContentsMargins(0, 0, 6, 0)
        rv.setSpacing(6)
        right.setWidget(inner)

        self.detail = DetailCard("CHANNEL")
        self.detail.set_hero("—", "select a channel")
        rv.addWidget(self.detail)
        self.sig_bar = QtWidgets.QProgressBar()
        self.sig_bar.setRange(0, 100)
        self.sig_bar.setValue(0)
        self.sig_bar.setTextVisible(False)
        self.sig_bar.setFixedHeight(14)
        self.sig_bar.setStyleSheet(
            "QProgressBar { background: %s; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: %s; border-radius: 3px; }"
            % (self._tok["well"], self._tok["accent"]))
        rv.addWidget(self.sig_bar)

        # ---- timing
        t = self.sec_timing = Section("TIMING")
        self.dwell = self._dspin(0.05, 5.0, c["dwell"], 0.05, " s",
                                 "Time spent sampling each step before moving on")
        t.row("Dwell", self.dwell)
        self.resume = self._dspin(0.0, 30.0, c["resume"], 0.5, " s",
                                  "Quiet time after a transmission ends before scanning resumes")
        t.row("Resume delay", self.resume)
        self.max_hold = self._dspin(0.0, 600.0, c["max_hold"], 5.0, " s",
                                    "Longest stay on one active channel (0 = no limit); a "
                                    "continuous carrier must not park the scanner")
        t.row("Max hold", self.max_hold)
        self.audio_chk = QtWidgets.QCheckBox("Audio out")
        self.audio_chk.setChecked(bool(c["audio"]))
        t.row("", self.audio_chk)
        for w in (self.dwell, self.resume, self.max_hold):
            w.valueChanged.connect(self._timing_changed)
        self.audio_chk.toggled.connect(self._audio_changed)
        rv.addWidget(t)

        # ---- range scan
        r = self.sec_range = Section("RANGE SCAN")
        self.include_ranges = QtWidgets.QCheckBox("Also step the bank's ranges")
        self.include_ranges.setChecked(bool(c["include_ranges"]))
        self.include_ranges.setToolTip("e.g. Airband (full) = every 25 kHz channel 118-137 MHz")
        r.row("", self.include_ranges)
        self.range_lo = self._dspin(24.0, 1766.0, c["range_lo"], 0.025, " MHz", None, 4)
        self.range_hi = self._dspin(24.0, 1766.0, c["range_hi"], 0.025, " MHz", None, 4)
        r.row("Start", self.range_lo)
        r.row("Stop", self.range_hi)
        self.range_mode = QtWidgets.QComboBox()
        self.range_mode.addItems(["AM", "NFM", "WFM"])
        self.range_mode.setCurrentText(c["range_mode"] if c["range_mode"] in ("AM", "NFM", "WFM")
                                       else "AM")
        r.row("Mode", self.range_mode)
        self.range_go = QtWidgets.QPushButton("SCAN THIS RANGE")
        self.range_go.clicked.connect(self._scan_range)
        r.row("", self.range_go)
        self.include_ranges.toggled.connect(lambda _on: self._apply_bank())
        rv.addWidget(r)

        # ---- priority
        pr = self.sec_pri = Section("PRIORITY")
        self.pri_on = QtWidgets.QCheckBox("Priority channel")
        self.pri_on.setChecked(bool(c["priority_on"]))
        pr.row("", self.pri_on)
        self.pri_freq = self._dspin(24.0, 1766.0, c["priority_mhz"], 0.0125, " MHz", None, 4)
        pr.row("Frequency", self.pri_freq)
        self.pri_mode = QtWidgets.QComboBox()
        self.pri_mode.addItems(["AM", "NFM", "WFM"])
        self.pri_mode.setCurrentText(c["priority_mode"] if c["priority_mode"] in
                                     ("AM", "NFM", "WFM") else "AM")
        pr.row("Mode", self.pri_mode)
        self.pri_every = self._dspin(0.5, 30.0, c["priority_every"], 0.5, " s",
                                     "How often the priority channel is checked while scanning "
                                     "or listening elsewhere")
        pr.row("Check every", self.pri_every)
        self.pri_set = QtWidgets.QPushButton("SET FROM ACTIVE / SELECTED")
        self.pri_set.clicked.connect(self._pri_from_selected)
        pr.row("", self.pri_set)
        for w in (self.pri_on,):
            w.toggled.connect(lambda _x: self._priority_changed())
        for w in (self.pri_freq, self.pri_every):
            w.valueChanged.connect(lambda _x: self._priority_changed())
        self.pri_mode.currentIndexChanged.connect(lambda _x: self._priority_changed())
        rv.addWidget(pr)

        # ---- lockouts
        lo = self.sec_lock = Section("LOCKOUTS")
        self.lock_list = QtWidgets.QListWidget()
        self.lock_list.setMinimumHeight(90)
        lo.row("", self.lock_list)
        lb = QtWidgets.QWidget()
        ll = QtWidgets.QHBoxLayout(lb)
        ll.setContentsMargins(0, 0, 0, 0)
        self.lock_cur = QtWidgets.QPushButton("LOCK OUT (S)")
        self.lock_cur.clicked.connect(self._skip_current)
        self.lock_del = QtWidgets.QPushButton("REMOVE")
        self.lock_del.clicked.connect(self._lock_remove)
        self.lock_clr = QtWidgets.QPushButton("CLEAR")
        self.lock_clr.clicked.connect(self._lock_clear)
        for b in (self.lock_cur, self.lock_del, self.lock_clr):
            ll.addWidget(b)
        lo.row("", lb)
        rv.addWidget(lo)

        # ---- frequency DB (was a fixed card)
        fd = self.sec_fdb = Section("FREQUENCY DB", open_=False)
        self.fdb_input = QtWidgets.QLineEdit()
        self.fdb_input.setPlaceholderText("MHz, or search a service…")
        self.fdb_input.returnPressed.connect(self._fdb_query)
        self.fdb_input.textChanged.connect(self._fdb_query)
        fd.row("", self.fdb_input)
        self.fdb_results = QtWidgets.QLabel("")
        self.fdb_results.setProperty("class", "note")
        self.fdb_results.setWordWrap(True)
        self.fdb_results.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        fd.row("", self.fdb_results)
        rv.addWidget(fd)
        rv.addStretch(1)

        split.addWidget(right)
        lay.addLayout(split, 1)

        self.engine_combo.currentIndexChanged.connect(self._engine_changed)
        self.bank_combo.currentTextChanged.connect(self._set_bank)
        self.step_combo.currentIndexChanged.connect(lambda _i: self._apply_bank())
        self._sync_step_for_bank(bank)
        self._sync_engine_rows()
        self._refresh_locks()
        set_run(self.hold_btn, True)
        return page

    @staticmethod
    def _dspin(lo, hi, val, step, suffix, tip=None, decimals=2):
        w = QtWidgets.QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setDecimals(decimals)
        w.setSingleStep(step)
        w.setValue(float(val))
        w.setSuffix(suffix)
        w.setKeyboardTracking(False)
        if tip:
            w.setToolTip(tip)
        return w

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
        self.fm_mode.addItems(["wbfm", "nbfm", "am"])   # am: airband direct tune
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
        elif self._engine == "fast":
            try:
                chans = self._scan_channels()
            except ValueError as e:
                self.scan_info.setText("Range refused: %s" % e)
                chans = []
            w = FastScanWorker(demo=self.demo, channels=chans,
                               squelch_db=float(self.fast_sq.value()),
                               dwell_s=self.dwell.value(), resume_s=self.resume.value(),
                               max_hold_s=self.max_hold.value(),
                               priority=self._priority_tuple(),
                               priority_every_s=self.pri_every.value(),
                               lockouts=self._locks(), audio=self.audio_chk.isChecked())
        else:
            chans = None
            if not self.demo:
                try:
                    chans = [(c[0], c[1], c[2]) for c in self._scan_channels()]
                except ValueError:
                    chans = None
            w = ScanWorker(demo=self.demo, bank=self.bank_combo.currentText(),
                           squelch=self.squelch.value(), channels=chans,
                           timing={"dwell": self.dwell.value(), "hold": self.resume.value(),
                                   "max_active": self.max_hold.value()},
                           lockouts=self._locks())
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
        if w is not None and not self.demo and self._active and not self.swapping() \
                and isinstance(w, ScanWorker) and w.isFinished():
            # RA-CL8d NEW-O: SCAN stopped on a fault or refused settings; Enter starts it again
            self.swap_worker()
            return True
        return False

    # ---- SCAN handlers ----
    def _save_scan(self, **kw):
        self._scfg.update(kw)
        if self._scfg_path and not self.demo:
            try:
                import suite
                suite.save_json(self._scfg_path, self._scfg)
            except Exception:
                pass

    def _field_visible(self, widget, on):
        lay = self.bar.lay
        for i in range(lay.count()):
            sub = lay.itemAt(i).layout()
            if sub is not None and sub.indexOf(widget) >= 0:
                for k in range(sub.count()):
                    w = sub.itemAt(k).widget()
                    if w is not None:
                        w.setVisible(on)

    def _sync_engine_rows(self):
        fast = self._engine == "fast"
        self._field_visible(self.squelch, not fast)
        self._field_visible(self.fast_sq, fast)
        for w in (self.sec_pri, self.include_ranges, self.pri_on):
            w.setEnabled(fast)
        self.sec_pri.setToolTip("" if fast else "Priority needs the FAST engine")

    def _engine_changed(self, *_):
        self._engine = self.engine_combo.currentData()
        self._save_scan(engine=self._engine)
        self._sync_engine_rows()
        if self._submode == "SCAN":
            self.swap_worker()

    def _bank_sq(self, bank):
        b = banks.BANKS.get(bank)
        default = b["squelch"] if b else 10
        try:
            return int(self._scfg.get("bank_squelch", {}).get(bank, default))
        except (TypeError, ValueError):
            return default

    def _fast_sq_changed(self, v):
        bsq = dict(self._scfg.get("bank_squelch") or {})
        bsq[self.bank_combo.currentText()] = int(v)
        self._save_scan(bank_squelch=bsq)
        w = self._worker
        if isinstance(w, FastScanWorker):
            w.queue(squelch_db=float(v))

    def _sync_step_for_bank(self, bank):
        b = banks.BANKS.get(bank)
        step = b["step"] if b else float(self._scfg.get("range_step", 25000))
        i = min(range(self.step_combo.count()),
                key=lambda k: abs(self.step_combo.itemData(k) - step))
        self.step_combo.blockSignals(True)
        self.step_combo.setCurrentIndex(i)
        self.step_combo.blockSignals(False)

    def _scan_channels(self):
        """[(MHz, label, MODE, bw_hz)] for the current bank (or custom range) + priority."""
        bank = self.bank_combo.currentText()
        step = float(self.step_combo.currentData() or 25000)
        out = []
        if bank == CUSTOM_RANGE:
            mode = self.range_mode.currentText()
            bw = dsp.DEFAULT_BW[mode] if mode != "AM" else 8330
            for f in banks.range_channels(self.range_lo.value(), self.range_hi.value(), step):
                out.append((f, "", mode, bw))
        elif bank == MY_BOOKMARKS:
            out = prism_bookmarks()
        else:
            b = banks.BANKS[bank]
            named = list(b["channels"])
            out = [(f, lb, b["mode"], b["bw"]) for f, lb in named]
            if self.include_ranges.isChecked() and self._engine == "fast":
                for a, z, _st in b["ranges"]:
                    for f in banks.range_channels(a, z, step):
                        if not any(abs(f - n) * 1e6 < step / 2 for n, _ in named):
                            out.append((f, "", b["mode"], b["bw"]))
            if not out and b["ranges"]:                       # a ranges-only bank
                a, z, _st = b["ranges"][0]
                out = [(f, "", b["mode"], b["bw"]) for f in banks.range_channels(a, z, step)]
            out.sort(key=lambda c: c[0])
        if self._engine == "fast" and self.pri_on.isChecked():
            pf = round(self.pri_freq.value(), 4)
            if not any(abs(c[0] - pf) < 0.0005 for c in out):
                mode = self.pri_mode.currentText()
                out.append((pf, "PRIORITY", mode, dsp.DEFAULT_BW[mode] if mode != "AM" else 8330))
                out.sort(key=lambda c: c[0])
        return out

    def _priority_tuple(self):
        if self._engine != "fast" or not self.pri_on.isChecked():
            return None
        mode = self.pri_mode.currentText()
        return (round(self.pri_freq.value(), 4), mode,
                dsp.DEFAULT_BW[mode] if mode != "AM" else 8330)

    def _apply_bank(self):
        """Push the bank / range / step / priority list to the running scanner."""
        try:
            chans = self._scan_channels()
        except ValueError as e:
            self.scan_info.setText("Range refused: %s" % e)
            return
        self._save_scan(bank=self.bank_combo.currentText(),
                        include_ranges=self.include_ranges.isChecked(),
                        range_step=float(self.step_combo.currentData() or 25000))
        w = self._worker
        if isinstance(w, FastScanWorker):
            w.queue(channels=chans, priority=self._priority_tuple(),
                    squelch_db=float(self.fast_sq.value()))
        elif isinstance(w, ScanWorker):
            if self.demo:
                w.set_bank(self.bank_combo.currentText())
            else:
                w.set_bank(self.bank_combo.currentText(),
                           channels=[(c[0], c[1], c[2]) for c in chans],
                           lockouts=self._locks())
        if self._engine == "classic" and len(chans) > 200:
            self.scan_info.setText("%d channels: the CLASSIC engine opens rtl_fm per channel "
                                   "(~1 s each). Use FAST for ranges." % len(chans))

    def _set_bank(self, bank):
        self.fast_sq.blockSignals(True)
        self.fast_sq.setValue(self._bank_sq(bank))
        self.fast_sq.blockSignals(False)
        self._sync_step_for_bank(bank)
        b = banks.BANKS.get(bank)
        if b and b.get("note"):
            self.scan_info.setText(b["note"])
        elif bank == MY_BOOKMARKS:
            n = len(prism_bookmarks())
            self.scan_info.setText("%d bookmark%s from PRISM." % (n, "" if n == 1 else "s")
                                   if n else "No bookmarks yet: add them in PRISM (BOOKMARKS).")
        elif bank == CUSTOM_RANGE:
            self.scan_info.setText("Custom range: set start / stop / mode in RANGE SCAN.")
        else:
            self.scan_info.setText("")
        self._apply_bank()

    def _scan_range(self):
        if self.bank_combo.currentText() != CUSTOM_RANGE:
            self.bank_combo.setCurrentText(CUSTOM_RANGE)   # -> _set_bank -> _apply_bank
        else:
            self._apply_bank()
        self._save_scan(range_lo=self.range_lo.value(), range_hi=self.range_hi.value(),
                        range_mode=self.range_mode.currentText())

    def _timing_changed(self, *_):
        d, r, m = self.dwell.value(), self.resume.value(), self.max_hold.value()
        self._save_scan(dwell=d, resume=r, max_hold=m)
        w = self._worker
        if isinstance(w, FastScanWorker):
            w.queue(dwell_s=d, resume_s=r, max_hold_s=m)
        elif isinstance(w, ScanWorker):
            w.set_timing(dwell=d, hold=r, max_active=m)

    def _audio_changed(self, on):
        self._save_scan(audio=bool(on))
        w = self._worker
        if isinstance(w, FastScanWorker):
            w.queue(audio=bool(on))

    def _priority_changed(self):
        self._save_scan(priority_on=self.pri_on.isChecked(),
                        priority_mhz=round(self.pri_freq.value(), 4),
                        priority_mode=self.pri_mode.currentText(),
                        priority_every=self.pri_every.value())
        w = self._worker
        if isinstance(w, FastScanWorker):
            w.queue(priority_every_s=self.pri_every.value())
        self._apply_bank()

    def _pri_from_selected(self):
        row = self._sel_row or {}
        try:
            f = float(row.get("freq", ""))
        except (TypeError, ValueError):
            return
        self.pri_freq.blockSignals(True)
        self.pri_freq.setValue(f)
        self.pri_freq.blockSignals(False)
        if row.get("mode") in ("AM", "NFM", "WFM"):
            self.pri_mode.blockSignals(True)
            self.pri_mode.setCurrentText(row["mode"])
            self.pri_mode.blockSignals(False)
        self.pri_on.setChecked(True)
        self._priority_changed()

    def _locks(self):
        out = []
        for f in self._scfg.get("lockouts") or []:
            try:
                out.append(round(float(f), 4))
            except (TypeError, ValueError):
                pass
        return out

    def _refresh_locks(self):
        self.lock_list.clear()
        for f in sorted(self._locks()):
            hit = banks.find(f)
            self.lock_list.addItem("%.4f  %s" % (f, hit[1] if hit else ""))

    def _set_locks(self, locks):
        self._save_scan(lockouts=sorted(set(round(float(f), 4) for f in locks)))
        self._refresh_locks()
        w = self._worker
        if isinstance(w, FastScanWorker):
            w.queue(lockouts=set(self._locks()))
        elif isinstance(w, ScanWorker):
            w._skip = set(self._locks())

    def _lock_remove(self):
        it = self.lock_list.currentItem()
        if it is None:
            return
        f = round(float(it.text().split()[0]), 4)
        self._set_locks([x for x in self._locks() if x != f])

    def _lock_clear(self):
        self._set_locks([])

    def _toggle_hold(self):
        w = self._worker
        if isinstance(w, FastScanWorker):
            w.hold = not w.hold
            w.set_hold(w.hold)
            held = w.hold
        elif isinstance(w, ScanWorker):
            w.hold = not w.hold
            held = w.hold
        else:
            return
        self.hold_btn.setText("HOLD" if held else "SCAN")
        set_run(self.hold_btn, not held)

    def _sq(self, v):
        if isinstance(self._worker, ScanWorker):
            if self.demo:
                self._worker.squelch = v
            else:
                self._worker.set_nfm_squelch(v)      # B2: wired to the engine's live setting

    def _skip_current(self):
        w = self._worker
        if isinstance(w, (ScanWorker, FastScanWorker)):
            f = w.skip_current()
            if f is not None:
                self.set_chip("scan", "locked out %.4f" % f, state="warn")
                self._scfg["lockouts"] = sorted(set(self._locks() + [round(f, 4)]))
                self._save_scan()
                self._refresh_locks()

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

    def _sig_color(self, level, hot):
        if hot:
            return self._hot_color()
        return self._tok["muted"]

    def _on_scan_row(self, msg):
        rows = msg["rows"]
        fast = msg.get("kind") == "scan"
        for r in rows:
            r["_colors"] = {"sig": self._sig_color(r.get("_level"), r.get("_hot", False))}
            if r.get("_hot"):
                r["_colors"]["label"] = self._hot_color()
                r["_colors"]["freq"] = self._hot_color()
            if fast:
                r["hits"] = r.get("hits") or ""
        total = len(rows)
        if fast and self.heard_only.isChecked():
            rows = [r for r in rows if r.get("_hot") or r.get("hits")
                    or (r.get("label") or "").strip()]
        self.feed.model.set_rows(rows)
        self.header.set_chip("sdr", "%d CH" % total, state="neutral")
        act = msg.get("active")
        if fast:
            state = msg.get("state", "SEARCH")
            bits = ["%s" % state]
            if msg.get("window"):
                bits.append("capture %.3f–%.3f MHz" % msg["window"])
            if msg.get("floor") is not None:
                bits.append("floor %.0f dBFS" % msg["floor"])
            bits.append("%d steps" % (msg.get("windows") or 0))
            if msg.get("pass_s"):
                bits.append("full pass %.1f s" % msg["pass_s"])
            self.scan_info.setText("  ·  ".join(bits))
        if act:
            level = act[2]
            if fast:
                lvl_txt = ("%+.0f dB over floor" % level) if level is not None else ""
                bar = int(max(0, min(100, (level or 0) * 2.5)))
            else:
                lvl_txt = ("level %d%%" % level) if level is not None else "level not measured"
                bar = level if level is not None else 0
            self.active.setText("%s  %s  %s" % (act[0], act[1], lvl_txt))
            self.active.setProperty("class", "value live")
            self.sig_bar.setValue(bar)
            self._show({"freq": act[0], "label": act[1],
                        "sig": lvl_txt if fast else _level_text(level),
                        "last": zulu(), "_hot": True}, follow=True)
        else:
            self.active.setText("—  scanning")
            self.active.setProperty("class", "value")
            self.sig_bar.setValue(0)
        self.active.style().unpolish(self.active)
        self.active.style().polish(self.active)

    def _on_fast_hit(self, msg):
        """A FAST-scanner stop: the one typed decode event (no geo, so not a contact)."""
        if self.demo:
            return
        f, label = float(msg["mhz"]), msg.get("label") or ""
        eventbus.bus.publish(eventbus.decode(
            "PROWL", "SCAN", "%.4f" % f, "%s active @ %.4f MHz" % (label or "channel", f),
            severity="live", freq_mhz=f, label=label))

    def _show(self, row, follow=False):
        if not follow:
            self._sel_row = row
        elif self._sel_row is None:
            self._sel_row = row
        self.detail.set_hero(row.get("label") or row.get("freq", "—"),
                             row.get("freq", "") + " MHz")
        rows = [("LEVEL", row.get("sig") or "not measured"),
                ("LAST HEARD", row.get("last") or "—"),
                ("STATUS", "ACTIVE" if row.get("_hot") else "quiet")]
        if row.get("mode"):
            rows.append(("MODE", row["mode"]))
        rows.append(("ALLOCATION", _describe_mhz(row.get("freq", ""))))
        self.detail.set_rows(rows)

    # ---- FM handlers ----
    def _fm_step(self, delta):
        self.fm_freq.setValue(round(self.fm_freq.value() + delta, 4))   # B1: keep kHz precision
        self._fm_retune()

    def _fm_retune(self):
        freq = self.fm_freq.value()
        # auto narrowband in the NOAA weather band, like the Tk fm app
        if 162.3 < freq < 162.6 and self.fm_mode.currentText() == "wbfm":
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
        if kind == "hit":
            self._on_fast_hit(msg)
        elif kind == "fm":
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
        if self._submode == "SCAN" and hasattr(self, "hold_btn"):
            w = self._worker
            held = bool(getattr(w, "hold", False))
            down = any(status.get(k) for k in ("off", "standby", "fault", "acquiring")) \
                or bool(status.get("busy"))
            running = w is not None and not held and not down
            self.hold_btn.setText("HOLD" if held else "SCAN")
            set_run(self.hold_btn, running)
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
