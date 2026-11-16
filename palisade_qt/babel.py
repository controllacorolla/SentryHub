"""BABEL — universal decoder feed wired to the real engines.

Each mode (AIS, ACARS, POCSAG, RDS) launches the same subprocess pipeline the original Tk app
uses, parses stdout with the same pure decode functions, and emits rows to the Qt GUI thread.
CW and RTTY are encode/practice tools (no passive pipeline) so they stay demo-only for now.
When the required binary is missing, the mode auto-degrades to demo with a status chip notice.
"""
import os
import random
import shutil
import subprocess
import sys
import threading
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .app import PalisadeApp
from . import theme, radio_arbiter, eventbus
from .kit import ControlBar, FeedTable, DetailCard
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MODES = ["AIS", "ACARS", "POCSAG", "RDS", "TPMS", "SSTV", "CW", "RTTY"]

SSTV_LEASE = "BABEL-SSTV"       # SSTV captures off-air (ISS 145.800) -> needs the single SDR
SSTV_DEFAULT_FREQ = 145.800

# BABEL's radio modes (AIS/ACARS/POCSAG/RDS) all want the one built-in dongle, so they go through
# the shared radio_arbiter under this single lease name — exactly like ATLAS's lease layers. Only
# one owner at a time; if another callsign holds the radio, BABEL shows RADIO BUSY and (being live)
# synthesises nothing. CW/RTTY are practice tools with no capture pipe, so they never lease.
LEASE_NAME = "BABEL"


def _open_pipe(cmd, shell=None, stderr=None):
    """Spawn a decoder capture pipeline — or None under offscreen/offline so tests and CI never
    open a real radio. The caller has already confirmed the binary is present via _can_run().
    `cmd` may be a legacy `a | b` shell STRING (split into argv stages — never run through a
    shell) or a list of argv lists. Every stage shares one session so PANIC / the arbiter kill
    the whole pipeline (audit A4). stderr goes to a temp file so an early exit can show WHY (R2)."""
    if os.environ.get("PALISADE_OFFLINE") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return None
    import tempfile
    from .kit.procs import Pipeline, split_shell_pipeline
    stages = split_shell_pipeline(cmd) if isinstance(cmd, str) else [list(x) for x in cmd]
    err = tempfile.TemporaryFile(mode="w+", errors="replace")
    pipe = Pipeline(stages, stderr_last=err)
    pipe.errfile = err
    return pipe


def _stderr_tail(proc, n=3):
    """The last n stderr lines of a Pipeline opened by _open_pipe (for the fault banner)."""
    f = getattr(proc, "errfile", None)
    if f is None:
        return ""
    try:
        f.seek(0)
        lines = [ln.rstrip() for ln in f.read().splitlines() if ln.strip()]
        return " | ".join(lines[-n:])[:200]
    except Exception:
        return ""


def _synth(mode):
    """Demo-only synthetic messages (unchanged from the original scaffold)."""
    now = time.strftime("%H:%M:%S")
    if mode == "AIS":
        mmsi = random.randint(200000000, 775000000)
        return {"time": now, "proto": "AIS", "id": str(mmsi), "summary": "pos report",
                "detail": [("MMSI", mmsi), ("LAT", "%.4f" % random.uniform(47, 48)),
                           ("LON", "%.4f" % random.uniform(-123, -122)),
                           ("SOG", "%.1f kn" % random.uniform(0, 22)),
                           ("COG", "%d°" % random.randint(0, 359))]}
    if mode == "ACARS":
        fl = random.choice(["UAL", "DAL", "ASA", "FDX"]) + str(random.randint(100, 2999))
        lbl = random.choice(["H1", "Q0", "5Z", "80"])
        return {"time": now, "proto": "ACARS", "id": fl, "summary": "label %s" % lbl,
                "detail": [("FLIGHT", fl), ("LABEL", lbl), ("MODE", "2"),
                           ("TEXT", "POS N47.5 W122.3 FL%d" % random.randint(300, 400))]}
    if mode == "POCSAG":
        cap = random.randint(100000, 2000000)
        return {"time": now, "proto": "POCSAG", "id": str(cap), "summary": "alpha msg",
                "detail": [("CAPCODE", cap), ("BAUD", random.choice([512, 1200, 2400])),
                           ("TEXT", random.choice(["CALL CONTROL", "UNIT 7 RESPOND", "TEST PAGE"]))]}
    if mode == "RDS":
        pi = "%04X" % random.randint(0x1000, 0xFFFF)
        ps = random.choice(["KEXP", "KUOW", "KISW", "JACK-FM"])
        return {"time": now, "proto": "RDS", "id": pi, "summary": ps,
                "detail": [("PI", pi), ("PS", ps), ("PTY", random.randint(0, 31)),
                           ("RT", "Now playing — demo stream")]}
    if mode == "TPMS":
        sid = "%08X" % random.randint(0, 0xFFFFFFFF)
        return {"time": now, "proto": "TPMS", "id": sid, "summary": "%d kPa · %d°C" % (
                    random.randint(210, 260), random.randint(8, 34)),
                "detail": [("ID", sid), ("MODEL", random.choice(["Toyota", "Schrader", "Pacific"])),
                           ("PRESSURE", "%d kPa" % random.randint(210, 260)),
                           ("TEMP", "%d °C" % random.randint(8, 34)), ("BATT", "ok")]}
    if mode == "CW":
        return {"time": now, "proto": "CW", "id": "%d WPM" % random.randint(12, 28),
                "summary": random.choice(["CQ CQ DE", "599 TU", "QRZ?"]),
                "detail": [("WPM", random.randint(12, 28)), ("TONE", "700 Hz")]}
    rt = "RYRY " + "".join(random.choice("0123456789") for _ in range(4))
    return {"time": now, "proto": "RTTY", "id": "45 baud", "summary": rt,
            "detail": [("BAUD", 45.45), ("SHIFT", "170 Hz"), ("TEXT", rt)]}


def _load_settings(name, defaults):
    """Load per-decoder settings without importing suite's Tk deps."""
    import json
    cfg = os.path.join(os.path.expanduser("~"), ".config", "uconsole-suite")
    path = os.path.join(cfg, name + ".json")
    try:
        with open(path) as f:
            s = json.load(f)
        if isinstance(s, dict):
            for k, v in defaults.items():
                s.setdefault(k, v)
            return s
    except (OSError, ValueError):
        pass
    return dict(defaults)


# the capture binary each live radio mode needs on PATH
_MODE_BINARY = {"AIS": "rtl_ais", "ACARS": "acarsdec", "POCSAG": "multimon-ng", "RDS": "redsea",
                "TPMS": "rtl_433"}


def _can_run(mode):
    """Check if the required binary for a mode is on PATH."""
    binary = _MODE_BINARY.get(mode)
    return binary is None or shutil.which(binary) is not None


# ---- per-mode live decoders (pure functions imported from the real engines) ----

def _run_ais(worker):
    import ais as engine
    s = _load_settings("ais", engine.DEFAULTS)
    cmd = engine.pipeline(gain=s.get("gain", 0))
    asm = engine.AivdmAssembler()
    n = 0
    proc = _open_pipe(cmd)
    if proc is None:
        return                       # offscreen/offline seam: never open a real radio in tests
    if not worker._adopt(proc):      # RUN off / hidden / revoked / PANIC while spawning
        _stop_proc(proc)
        return
    worker.status.emit({"sdr": {"text": "AIS LIVE", "ok": True}})
    try:
        for line in proc.stdout:
            if worker.stopping:
                break
            msg = asm.feed(line.rstrip("\n"))
            if not msg or not msg.get("mmsi"):
                continue
            now = time.strftime("%H:%M:%S")
            n += 1
            row = {"time": now, "proto": "AIS", "id": str(msg["mmsi"]),
                   "summary": msg.get("status_name", "type %d" % msg.get("type", 0)),
                   "detail": [("MMSI", msg["mmsi"]), ("TYPE", msg.get("type"))]}
            if msg.get("lat") is not None:
                row["detail"].extend([("LAT", "%.5f" % msg["lat"]),
                                      ("LON", "%.5f" % msg["lon"])])
            if msg.get("sog_kt") is not None:
                row["detail"].append(("SOG", "%.1f kn" % msg["sog_kt"]))
            if msg.get("cog_deg") is not None:
                row["detail"].append(("COG", "%d°" % int(msg["cog_deg"])))
            if msg.get("name"):
                row["detail"].append(("NAME", msg["name"]))
                row["summary"] = msg["name"]
            worker.row.emit(row)
            if n % 5 == 0:
                worker.status.emit({"sdr": {"text": "AIS %d" % n, "ok": True}})
    finally:
        _stop_proc(proc)


def _run_acars(worker):
    import signals as engine
    s = _load_settings("signals", engine.DEFAULTS)
    engine.migrate(s)
    argv = engine.build_argv(s)
    parser = engine.parse_acars if s.get("source") != "vdl2" else engine.parse_vdl2
    n = 0
    try:
        proc = _open_pipe(argv, shell=False, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        worker.error.emit("acarsdec not found — install it or use --demo")
        return
    if proc is None:
        return                       # offscreen/offline seam: never open a real radio in tests
    if not worker._adopt(proc):      # RUN off / hidden / revoked / PANIC while spawning
        _stop_proc(proc)
        return
    worker.status.emit({"sdr": {"text": "ACARS LIVE", "ok": True}})
    try:
        for line in proc.stdout:
            if worker.stopping:
                break
            msg = parser(line.rstrip("\n"))
            if not msg:
                continue
            now = time.strftime("%H:%M:%S")
            n += 1
            flight = msg.get("flight") or msg.get("reg") or "—"
            row = {"time": now, "proto": "ACARS", "id": flight,
                   "summary": "label %s" % msg.get("label", "?"),
                   "detail": [("FLIGHT", flight),
                              ("REG", msg.get("reg", "")),
                              ("LABEL", msg.get("label", "")),
                              ("TEXT", msg.get("text", ""))]}
            worker.row.emit(row)
            if n % 3 == 0:
                worker.status.emit({"sdr": {"text": "ACARS %d" % n, "ok": True}})
    finally:
        _stop_proc(proc)


def _run_pocsag(worker):
    import pager as engine
    s = _load_settings("pager", engine.DEFAULTS)
    cmd = engine.pipeline(freq=s.get("freq", engine.FREQ_DEFAULT), gain=s.get("gain", 0))
    n = 0
    proc = _open_pipe(cmd)
    if proc is None:
        return                       # offscreen/offline seam: never open a real radio in tests
    if not worker._adopt(proc):      # RUN off / hidden / revoked / PANIC while spawning
        _stop_proc(proc)
        return
    worker.status.emit({"sdr": {"text": "POCSAG LIVE", "ok": True}})
    try:
        for line in proc.stdout:
            if worker.stopping:
                break
            page = engine.parse_line(line.rstrip("\n"))
            if not page:
                continue
            now = time.strftime("%H:%M:%S")
            n += 1
            row = {"time": now, "proto": page.get("proto", "POCSAG"),
                   "id": str(page["address"]),
                   "summary": (page.get("text") or page.get("kind") or "page")[:60],
                   "detail": [("ADDRESS", page["address"]),
                              ("BAUD", page.get("baud")),
                              ("KIND", page.get("kind", "")),
                              ("TEXT", page.get("text", ""))]}
            worker.row.emit(row)
            if n % 3 == 0:
                worker.status.emit({"sdr": {"text": "POCSAG %d" % n, "ok": True}})
    finally:
        _stop_proc(proc)


def _run_rds(worker):
    import rds as engine
    s = _load_settings("rds", engine.DEFAULTS)
    cmd = engine.pipeline(freq=s.get("freq", engine.FREQ_DEFAULT), gain=s.get("gain", 0))
    stations = engine.Stations()
    n = 0
    proc = _open_pipe(cmd)
    if proc is None:
        return                       # offscreen/offline seam: never open a real radio in tests
    if not worker._adopt(proc):      # RUN off / hidden / revoked / PANIC while spawning
        _stop_proc(proc)
        return
    worker.status.emit({"sdr": {"text": "RDS LIVE", "ok": True}})
    try:
        for line in proc.stdout:
            if worker.stopping:
                break
            r = engine.parse_rds(line.rstrip("\n"))
            if not r:
                continue
            st = stations.add(r)
            if not st:
                continue
            now = time.strftime("%H:%M:%S")
            n += 1
            row = {"time": now, "proto": "RDS", "id": st["pi"],
                   "summary": st.get("ps") or st.get("callsign") or "—",
                   "detail": [("PI", st["pi"]),
                              ("PS", st.get("ps", "")),
                              ("CALLSIGN", st.get("callsign", "")),
                              ("PTY", st.get("pty")),
                              ("RT", st.get("rt", ""))]}
            worker.row.emit(row)
            if n % 5 == 0:
                worker.status.emit({"sdr": {"text": "RDS %d stn" % len(stations.by_pi), "ok": True}})
    finally:
        _stop_proc(proc)


def _run_tpms(worker):
    """TPMS tire-pressure sensors via rtl_433 JSON (315/433.92 MHz). tpms.parse_tpms reused AS-IS;
    rtl_433 is the capture binary and SDR owner (tpms.py has no pipeline of its own)."""
    import tpms as engine
    s = _load_settings("tpms", {"freqs": ["315M", "433.92M"], "gain": 0})
    argv = ["rtl_433", "-F", "json", "-M", "level"]
    for f in s.get("freqs", ["315M", "433.92M"]):
        argv += ["-f", f]
    if int(s.get("gain") or 0):
        argv += ["-g", str(int(s["gain"]))]
    proc = _open_pipe(argv, shell=False)
    if proc is None:
        return                       # offscreen/offline seam: never open a real radio in tests
    if not worker._adopt(proc):      # RUN off / hidden / revoked / PANIC while spawning
        _stop_proc(proc)
        return
    worker.status.emit({"sdr": {"text": "TPMS LIVE", "ok": True}})
    veh = engine.Vehicles()
    n = 0
    try:
        for line in proc.stdout:
            if worker.stopping:
                break
            r = engine.parse_tpms(line.rstrip("\n"))
            if not r or not r.get("id"):     # rtl_433 decodes many devices; keep only real TPMS
                continue
            veh.add(r)
            n += 1
            now = time.strftime("%H:%M:%S")
            dist = engine.rssi_to_distance_m(r.get("rssi"))
            detail = [("ID", r["id"]), ("MODEL", r.get("model") or "—")]
            if r.get("pressure_kpa") is not None:
                detail.append(("PRESSURE", "%.0f kPa" % r["pressure_kpa"]))
            if r.get("temp_c") is not None:
                detail.append(("TEMP", "%.0f °C" % r["temp_c"]))
            if dist is not None:
                detail.append(("RANGE", "~%.0f m" % dist))
            detail.append(("BATT", "ok" if r.get("battery_ok") else "low/unknown"))
            parts = []
            if r.get("pressure_kpa") is not None:
                parts.append("%.0f kPa" % r["pressure_kpa"])
            if r.get("temp_c") is not None:
                parts.append("%.0f°C" % r["temp_c"])
            summary = " · ".join(parts) or "sensor"
            worker.row.emit({"time": now, "proto": "TPMS", "id": str(r["id"]),
                             "summary": summary, "detail": detail})
            eventbus.bus.publish(eventbus.decode(            # real decode only -> OPS decode card
                "BABEL-TPMS", "TPMS", str(r["id"]), summary, severity="info",
                pressure_kpa=r.get("pressure_kpa"), temp_c=r.get("temp_c")))
            if n % 5 == 0:
                worker.status.emit({"sdr": {"text": "TPMS %d" % n, "ok": True}})
    finally:
        _stop_proc(proc)


_LIVE_RUNNERS = {"AIS": _run_ais, "ACARS": _run_acars, "POCSAG": _run_pocsag, "RDS": _run_rds,
                 "TPMS": _run_tpms}


def _stop_proc(proc):
    """Stop a decoder pipeline: group SIGTERM, wait, SIGKILL, wait — every member, no zombie (A4).
    Always terminate(): a Pipeline whose first stage exited can still have live stages (poll()
    reports the first exit), and terminate() is idempotent. Blocks: worker thread only."""
    if not proc:
        return
    try:
        proc.terminate()
    except Exception:
        pass
    f = getattr(proc, "errfile", None)
    if f is not None:
        try:
            f.close()
        except Exception:
            pass


EARLY_EXIT_S = 5.0            # a decoder that dies this soon after spawn is a FAULT, not a retry
FAULT_BACKOFF_S = (2, 4, 8, 16, 30, 60)


class DecoderWorker(Worker):
    """One live decoder at a time. The radio is taken only while the operator has pressed RUN
    AND the page is in front (R1: release when hidden, never start a decoder until RUN). An early
    decoder exit is a FAULT with its stderr shown, retried with backoff while KEEPING the lease
    (R2: no release/re-acquire churn, so readsb is not restarted ten times)."""
    PAUSE_WHEN_HIDDEN = False          # it must keep stepping to release the dongle when hidden

    def __init__(self, demo=True, mode="AIS", parent=None):
        super().__init__(demo=demo, interval_ms=600, parent=parent)
        self.mode = mode
        self._n = 0
        self._proc = None
        self._mode_changed = False
        self._running = False          # RUN pressed
        self._active = True            # page in front
        self._faults = 0
        radio_arbiter.arbiter.revoked.connect(self._on_revoked)

    # GUI-thread entry points: flags + a NON-blocking kill only (CL5-fix 6). The worker thread
    # then reaps the pipeline (terminate waits for every stage) BEFORE it releases the radio.
    def set_running(self, on):
        self._running = bool(on)
        self._mode_changed = True      # re-evaluate at once (take the radio / give it back)
        if not on:
            self._kill_async()
        self.poke()

    def set_active(self, on):
        if bool(on) == self._active:
            return                     # no change: don't restart the loop on a repeat call
        self._active = bool(on)
        self._mode_changed = True
        if not on:
            self._kill_async()
        self.poke()

    def _on_revoked(self, name):
        if name == LEASE_NAME:
            self.hold_off("radio given back")

    def hold_off(self, reason):
        """A revoke or PANIC: stop the decoder and do not start it again until the operator
        presses RUN. The page unticks RUN when it sees `run_off`."""
        self._running = False
        self._mode_changed = True
        self._kill_async()
        self.status.emit({"run_off": True, "busy": None, "live": False,
                          "sdr": {"text": "%s OFF — %s" % (self.mode, reason), "state": "warn",
                                  "ok": False}, "idle": True})
        self.poke()

    def _adopt(self, proc):
        """A runner just spawned `proc`. Keep it only if we still want and HOLD the radio; a
        GUI-thread kill that ran before this assignment saw no proc, so check here (the PANIC
        race: no decoder may outlive the flag that said stop)."""
        self._proc = proc
        if self._stop or self._mode_changed or not self.wants_radio() \
                or not radio_arbiter.arbiter.held_by(LEASE_NAME):
            self._proc = None
            return False
        return True

    def _kill_async(self):
        from .kit.procs import terminate_async
        terminate_async(self._proc)

    def wants_radio(self):
        return self._running and self._active and not self.demo

    def _nap(self, ms):
        """Sleep up to ms, waking early on stop() OR on a RUN / hidden / mode change."""
        deadline = time.time() + ms / 1000.0
        while not self._stop and not self._mode_changed and time.time() < deadline:
            self.sleep(min(50, max(1, int((deadline - time.time()) * 1000))))
        return self._stop or self._mode_changed

    def _kill_proc(self):
        """Worker thread only: blocks until every stage is gone."""
        proc, self._proc = self._proc, None
        if proc is not None:
            _stop_proc(proc)

    def set_mode(self, mode):
        self.mode = mode
        self._mode_changed = True
        self._faults = 0
        self._kill_async()
        self.poke()

    def run(self):
        try:
            self._loop()
        finally:
            self._kill_proc()
            radio_arbiter.arbiter.release(LEASE_NAME)   # after the pipeline is reaped
            try:
                radio_arbiter.arbiter.revoked.disconnect(self._on_revoked)
            except (RuntimeError, TypeError):
                pass

    def _loop(self):
        while not self._stop:
            mode = self.mode
            self._mode_changed = False

            if self.demo:
                self._run_demo(mode)
            elif mode not in _LIVE_RUNNERS:
                self._run_practice(mode)      # live + no RX backend (CW/RTTY): honest, never synth
            elif not _can_run(mode):
                self._run_standby(mode)       # live + no decoder binary: honest standby, no synth
            elif not self.wants_radio():
                self._run_idle(mode)          # R1: no RUN, or page hidden -> no radio taken
            else:
                self._run_live(mode)

            if self._stop:
                break
            if not self._mode_changed:
                self._nap(500)

    def _run_idle(self, mode):
        self.status.emit({"sdr": {"text": "%s IDLE — press RUN" % mode if self._active
                                  else "%s paused (page hidden)" % mode, "state": "neutral"},
                          "busy": None, "idle": True})
        while not self._stop and not self._mode_changed and not self.wants_radio():
            self.sleep(50)

    def _run_live(self, mode):
        """Acquire the single SDR via the shared arbiter, run the real decoder, then release. If
        another callsign holds the radio, show RADIO BUSY and (being live) synthesise nothing."""
        if not radio_arbiter.arbiter.request(LEASE_NAME):
            owner = radio_arbiter.owner_label() or radio_arbiter.arbiter.owner() or "?"
            self.status.emit({"sdr": {"text": "RADIO BUSY — %s" % owner, "ok": False},
                              "busy": owner})
            waited = 0                       # idle and retry while the radio is held elsewhere
            while waited < 1500 and not self._stop and not self._mode_changed and self.wants_radio():
                self.sleep(50)
                waited += 50
            return
        try:
            # CL5-fix 1 / N1: the decoder starts only once the arbiter says HELD. Until then the
            # page says ACQUIRING (readsb is still being stopped and may hold the dongle).
            arb = radio_arbiter.arbiter
            while not arb.held_by(LEASE_NAME):
                if self._stop or self._mode_changed or not self.wants_radio() \
                        or arb.owner() != LEASE_NAME:
                    return                   # finally: release (nothing was started)
                self.status.emit({"busy": None, "live": False, "acquiring": True,
                                  "sdr": {"text": "%s ACQUIRING radio" % mode, "state": "warn",
                                          "ok": False}})
                self._nap(100)
            self.status.emit({"busy": None})     # we hold the radio — clear any BUSY banner
            # R2: run the decoder; an exit within EARLY_EXIT_S is a fault. Retry with backoff
            # while HOLDING the lease, so readsb is not paused/resumed on every attempt.
            while not self._stop and not self._mode_changed and self.wants_radio():
                t0 = time.time()
                self._proc = None
                try:
                    _LIVE_RUNNERS[mode](self)
                except Exception as e:
                    self.error.emit("%s: %s" % (mode, str(e)[:150]))
                if self._stop or self._mode_changed or not self.wants_radio():
                    break
                if not radio_arbiter.arbiter.held_by(LEASE_NAME):    # freed under us
                    self._running = False
                    self.status.emit({"run_off": True, "busy": None, "live": False, "idle": True,
                                      "sdr": {"text": "%s OFF — radio taken back" % mode,
                                              "state": "warn", "ok": False}})
                    break
                if self._proc is None:
                    # the capture seam opened nothing (offscreen / offline): hold the lease and say
                    # so — not a decoder fault, and no release/re-acquire churn
                    self.status.emit({"sdr": {"text": "%s — no capture (offline)" % mode,
                                              "ok": False}, "standby": True})
                    self._nap(1000)
                    continue
                ran = time.time() - t0
                tail = _stderr_tail(self._proc)
                if ran < EARLY_EXIT_S:
                    self._faults += 1
                    wait = FAULT_BACKOFF_S[min(self._faults, len(FAULT_BACKOFF_S)) - 1]
                    msg = "%s decoder exited after %.1fs (×%d)%s — retry in %ds" % (
                        mode, ran, self._faults, (": " + tail) if tail else "", wait)
                    self.fault.emit("FAULT: " + msg)
                    self.status.emit({"sdr": {"text": "%s FAULT" % mode, "state": "alert",
                                              "ok": False}, "fault": msg})
                    self._nap(wait * 1000)        # keep the lease while backing off
                else:
                    self._faults = 0            # a long run that ended: plain restart
                    if self._faulted:
                        self._faulted = False
                        self.fault.emit("")
        finally:
            self._kill_proc()                    # reaped (every stage gone) …
            radio_arbiter.arbiter.release(LEASE_NAME)   # … THEN released

    def _run_standby(self, mode):
        """Live mode with the decoder binary absent: show an honest STANDBY and publish nothing.
        Live never synthesises — demo mode (the SDR-DEMO chip) is the only synthetic path."""
        binary = _MODE_BINARY.get(mode, "decoder")
        self.status.emit({"sdr": {"text": "%s STANDBY — no %s" % (mode, binary), "ok": False}})
        while not self._stop and not self._mode_changed:
            self.sleep(100)

    def _run_practice(self, mode):
        """Live mode for a mode with NO live RX backend (CW/RTTY are txguard TX/practice tools
        with no demodulator; digimodes has no decoder). Say so honestly and publish nothing — live
        never synthesises. The decoded text is available in demo mode (SDR-DEMO) only."""
        self.status.emit({"sdr": {"text": "%s — practice only (no live decode)" % mode, "ok": False},
                          "practice": True})
        while not self._stop and not self._mode_changed:
            self.sleep(100)

    def _run_demo(self, mode):
        while not self._stop and not self._mode_changed:
            self._n += 1
            try:
                self.row.emit(_synth(mode))
            except Exception:
                pass
            if self._n % 3 == 0:
                self.status.emit({"sdr": {"text": "SDR DEMO", "ok": True}})
            waited = 0
            while waited < self.interval_ms and not self._stop and not self._mode_changed:
                self.sleep(20)
                waited += 20

    def stop(self):
        """GUI-safe: flags + a non-blocking kill. run()'s finally reaps, then releases."""
        super().stop()
        self._mode_changed = True
        self._kill_async()


def _sstv_demo_image():
    """A synthetic SSTV-style colour-bar test pattern (demo only, flagged SDR-DEMO). Never shown
    in live mode — live only displays a real decoded frame."""
    import numpy as np
    h, w = 256, 320
    bars = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
            (255, 0, 255), (255, 0, 0), (0, 0, 255), (20, 20, 20)]
    img = np.zeros((h, w, 3), dtype=np.uint8)
    bw = w // len(bars)
    for i, c in enumerate(bars):
        img[: h * 3 // 4, i * bw:(i + 1) * bw] = c
    grad = np.linspace(0, 255, w, dtype=np.uint8)
    img[h * 3 // 4:, :] = np.repeat(grad[None, :, None], h - h * 3 // 4, axis=0)
    return img


class SstvImagePanel(QtWidgets.QFrame):
    """Shows the decoded SSTV frame (a numpy RGB ndarray) as a scaled pixmap + a caption. The
    numpy buffer is kept alive for the QImage's lifetime."""

    def __init__(self, mode="dark", parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
        tok = theme.tokens(mode)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        self.caption = QtWidgets.QLabel("SSTV — no frame yet")     # reports state -> not a caption
        self.caption.setProperty("class", "note")
        self.caption.setWordWrap(True)
        lay.addWidget(self.caption)
        self.view = QtWidgets.QLabel("listening…")
        self.view.setAlignment(QtCore.Qt.AlignCenter)
        self.view.setStyleSheet("color:%s;" % tok["muted"])
        self.view.setMinimumHeight(80)              # sized from the space it is given
        lay.addWidget(self.view, 1)
        self._buf = None

    def show_image(self, arr, caption):
        import numpy as np
        self._buf = np.ascontiguousarray(arr, dtype=np.uint8)   # keep the buffer alive
        h, w = self._buf.shape[:2]
        img = QtGui.QImage(self._buf.data, w, h, 3 * w, QtGui.QImage.Format_RGB888)
        pix = QtGui.QPixmap.fromImage(img).scaled(
            self.view.width() or 560, self.view.height() or 360,
            QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.view.setPixmap(pix)
        self.caption.setText(caption)

    def set_note(self, text):
        self.caption.setText(text)

    def clear(self):
        self.view.setPixmap(QtGui.QPixmap())
        self.view.setText("listening…")
        self.caption.setText("SSTV — no frame yet")
        self._buf = None


def _sstv_ready():
    """numpy + rtl_fm both present (numpy is a hard dependency of the sstvdec decoder)."""
    import importlib.util
    if importlib.util.find_spec("numpy") is None:
        return False, "numpy"
    if not shutil.which("rtl_fm"):
        return False, "rtl_fm"
    return True, None


class SstvWorker(Worker):
    """Captures the ISS SSTV downlink (rtl_fm -> WAV via sstv.Recorder) under the BABEL-SSTV lease
    and re-runs sstvdec.decode_wav on the growing WAV until a frame decodes. Reused AS-IS: the
    capture is sstv.Recorder, the decode is sstvdec.decode_wav; this only wires them to Qt. Live
    shows a frame ONLY on a real decode — ISS SSTV is rare, so STANDBY/listening is the norm."""
    NAME = SSTV_LEASE
    PAUSE_WHEN_HIDDEN = False          # R1: it must keep stepping to give the radio back when hidden

    def __init__(self, demo=True, freq=SSTV_DEFAULT_FREQ, gain=40, parent=None):
        super().__init__(demo=demo, interval_ms=1000, parent=parent)
        self.freq, self.gain = freq, gain
        self._running = False          # R1 / CL5-fix 3: the radio is taken only on RUN …
        self._active = True            # … while the page is in front
        self._why = "press RUN"
        self._has_radio = False
        self._rec = None
        self._wav = None
        self._scan_from = 0            # CL5-fix 12: absolute sample the next decode starts at
        self._decoded_upto = 0         # absolute sample the last decode reached
        self._frame = None             # the frame being received {"id", "start", "lines"}
        self._frames = 0
        self._demo_sent = False
        self._decoding = False
        self._lock = threading.Lock()     # serialises _rec / _has_radio across step() and stop()
        radio_arbiter.arbiter.revoked.connect(self._on_revoked)

    # ---- GUI-thread entry points: flags + poke only (CL5-fix 3 / 6) ----
    def set_running(self, on):
        self._running = bool(on)
        if not on:
            self._why = "press RUN"
        self.poke()

    def set_active(self, on):
        if bool(on) == self._active:
            return
        self._active = bool(on)
        if not on:
            self._why = "page hidden"
        self.poke()

    def _on_revoked(self, name):
        if name == self.NAME:
            self.hold_off("radio given back")

    def hold_off(self, reason):
        """A revoke or PANIC: stop capturing and stay off until the operator presses RUN."""
        self._running = False
        self._why = reason
        self.status.emit({"run_off": True})
        self.poke()

    def wants_radio(self):
        return self._running and self._active and not self.demo

    # seams so tests/CI never open a real radio or require a WAV
    def _make_recorder(self, path):
        if os.environ.get("PALISADE_OFFLINE") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return None
        import sstv
        return sstv.Recorder(path, self.freq, self.gain, monitor=False)   # rolling window (R5)

    def _decode(self, x, fs):
        """Seam: decode audio already in memory (sstvdec.decode_samples — decode_wav's body)."""
        import sstvdec
        return sstvdec.decode_samples(x, fs)

    DECODE_EVERY_S = 12        # decode once this much NEW audio has arrived
    OVERLAP_S = 2.0            # re-read this much before the new audio: a VIS header is ~0.9 s
    FRAME_LEAD_S = 1.0         # a frame's VIS leader sits just before its image start

    def step(self):
        if self._stop:
            return
        if self.demo:
            if not self._demo_sent:
                self._demo_sent = True
                self.row.emit({"kind": "sstv", "image": _sstv_demo_image(), "mode": "PD120",
                               "lines": 496, "slant": 0, "demo": True})
                self.status.emit({"sdr": {"text": "SSTV DEMO", "ok": True}})
            return
        ok, missing = _sstv_ready()
        if not ok:
            self._stop_rec()
            self._release()
            self.status.emit({"sdr": {"text": "SSTV STANDBY — no %s" % missing, "ok": False},
                              "standby": True, "live": False})
            return
        if not self.wants_radio():
            self._give_back(self._why)
            return
        if not self._ensure_lease():
            self._stop_rec()
            return
        # acquire/snapshot the recorder under the lock so a concurrent stop() can't race us into
        # creating a Recorder after teardown (which would leak a 2nd rtl_fm on the one dongle)
        with self._lock:
            if self._stop:
                return
            rec = self._rec
            if rec is None:
                import suite
                os.makedirs(suite.CACHE, exist_ok=True)          # R5: under the cache dir, not /tmp
                self._wav = os.path.join(suite.CACHE, "palisade_sstv_%d.wav" % os.getpid())
                rec = self._rec = self._make_recorder(self._wav)
        if rec is not None and (not self.wants_radio()
                                or not radio_arbiter.arbiter.held_by(self.NAME)):
            self._stop_rec()                         # RUN off / revoke / PANIC while starting
            return
        if rec is None:                              # offscreen seam: hold lease, no capture
            self.status.emit({"sdr": {"text": "SSTV — no capture (offline)", "ok": False},
                              "busy": None, "live": False})
            return
        if rec.err:                                  # rtl_fm died: reap + restart on the next step
            self._stop_rec()
            self.status.emit({"sdr": {"text": "SSTV — %s (retrying)" % rec.err[:34], "ok": False}})
            return
        secs = rec.seconds()
        self.status.emit({"sdr": {"text": "SSTV — capturing %ds (lvl %.0f)" % (secs, rec.level),
                                  "ok": True}, "busy": None, "live": True})
        # run the CPU-bound decode on a DISPOSABLE daemon thread so step() stays responsive to
        # _stop (the worker QThread must join within wait(); a decode can't be interrupted).
        # CL5-fix 12: only when DECODE_EVERY_S of NEW audio arrived, and only over the new audio
        # (plus the frame being received, if one is) — never the whole window every 12 s.
        import sstv
        total = rec.total_samples()
        if not self._decoding and total - self._decoded_upto >= self.DECODE_EVERY_S * sstv.RATE:
            self._decoding = True
            threading.Thread(target=self._decode_job, args=(rec, sstv.RATE), daemon=True).start()

    def _decode_job(self, rec, fs):
        import numpy as np
        try:
            raw, base = rec.samples_since(self._scan_from)
            upto = base + len(raw) // 2
            x = np.frombuffer(raw, dtype="<i2").astype(np.float32)
            try:
                r = self._decode(x, fs)
            except ValueError as e:              # no header yet / truncated: keep listening
                self._decoded_upto = upto
                if self._frame is None and "no SSTV header" in str(e):
                    # nothing here: next time look only at audio after this (minus the overlap)
                    self._scan_from = max(base, upto - int(self.OVERLAP_S * fs))
                if not self._stop:
                    self.status.emit({"sdr": {"text": "SSTV — listening (%s)" % str(e)[:26],
                                              "ok": False}})
                return
            except Exception as e:
                self._decoded_upto = upto
                if not self._stop:
                    self.error.emit("SSTV decode: %s" % str(e)[:120])
                return
            self._decoded_upto = upto
            if self._stop:
                return                           # torn down mid-decode: drop the abandoned frame
            self._fold_frame(r, base, upto, fs)
        finally:
            self._decoding = False

    def _fold_frame(self, r, base, upto, fs):
        """One decode result -> a NEW frame (row + one decode event), a refinement of the frame
        being received (row only, never a duplicate event), or the end of that frame."""
        start = r.get("start")
        start_abs = base + int(start if start is not None else r.get("t0", 0))
        lines = int(r.get("lines", 0))
        period = float(r.get("period") or 0) or fs
        end_abs = base + int(r.get("t0", start or 0) + (lines // 2) * period)
        f = self._frame
        same = f is not None and abs(start_abs - f["start"]) < int(0.5 * fs)
        if same and lines <= f["lines"]:         # no growth with new audio: the frame is over
            self._frame = None
            self._scan_from = max(self._scan_from, end_abs)
            return
        if not same:
            self._frames += 1
            f = self._frame = {"id": self._frames, "start": start_abs, "lines": 0}
            eventbus.bus.publish(eventbus.decode(
                "BABEL-SSTV", "SSTV", r.get("mode", "?"),
                "%s frame · %d lines" % (r.get("mode", "?"), lines), severity="info"))
        f["lines"] = lines
        self.row.emit({"kind": "sstv", "image": r["image"], "mode": r.get("mode", "?"),
                       "lines": lines, "slant": r.get("slant_ppm", 0), "frame": f["id"]})
        try:
            import sstvdec
            full = sstvdec.PD_MODES[r.get("mode")][3]
        except Exception:
            full = None
        if full is not None and lines >= full:   # complete: look for the next one after it
            self._frame = None
            self._scan_from = max(self._scan_from, end_abs)
        else:                                    # still arriving: keep its header in view
            self._scan_from = max(base, start_abs - int(self.FRAME_LEAD_S * fs))

    def _ensure_lease(self):
        """True only while we HOLD the radio (HELD, not ACQUIRING — CL5-fix 1)."""
        if self._stop:
            return False
        arb = radio_arbiter.arbiter
        if not self._has_radio:
            if not arb.request(self.NAME):
                self.status.emit({"busy": radio_arbiter.owner_label(), "live": False,
                                  "sdr": {"text": "RADIO BUSY", "ok": False}})
                return False
            with self._lock:
                self._has_radio = True
        st, owner = arb.state()
        if owner != self.NAME:                       # freed under us (forced free / PANIC)
            with self._lock:
                self._has_radio = False
            self._running = False
            self._give_back("radio taken back")
            self.status.emit({"run_off": True})
            return False
        if st != "HELD":
            self.status.emit({"busy": None, "live": False, "acquiring": True,
                              "sdr": {"text": "SSTV ACQUIRING radio", "state": "warn",
                                      "ok": False}})
            return False
        return True

    def _give_back(self, why):
        """Stop the recorder (rtl_fm reaped) THEN release, and say so (CL5-fix 7)."""
        self._stop_rec()
        self._release()
        idle = why == "press RUN"
        self.status.emit({"busy": None, "live": False, "idle": True,
                          "sdr": {"text": "SSTV IDLE — press RUN" if idle else "SSTV OFF — %s" % why,
                                  "state": "neutral" if idle else "warn", "ok": False}})

    def _release(self):
        with self._lock:
            had, self._has_radio = self._has_radio, False
        if had:
            radio_arbiter.arbiter.release(self.NAME)

    def _stop_rec(self):
        with self._lock:
            rec, self._rec = self._rec, None
            wav, self._wav = self._wav, None
        if rec is not None:
            try:
                rec.stop()
            except Exception:
                pass
        self._scan_from = self._decoded_upto = 0     # a new recorder restarts the sample clock
        self._frame = None
        if wav:
            for f in (wav, wav[:-4] + ".prev.wav"):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def run(self):
        try:
            super().run()
        finally:
            self._stop_rec()                         # rtl_fm reaped on this thread …
            self._release()                          # … then the radio is released
            try:
                radio_arbiter.arbiter.revoked.disconnect(self._on_revoked)
            except (RuntimeError, TypeError):
                pass

    def stop(self):
        """GUI-safe: flags only (CL5-fix 6). run() stops the recorder and releases."""
        super().stop()          # sets _stop first, so _ensure_lease/_start can't re-acquire/respawn


class BabelApp(PalisadeApp):
    TITLE = "BABEL"
    LEASE = None          # the radio is leased per-mode via radio_arbiter, not by the base class

    # protocol tints per theme (D9 / RA-CL1): the dark set was unreadable on LIGHT's pale table and
    # meaningless in SUN. LIGHT keeps >= 4.5:1 on its table, SUN is black (>= 7:1) — the protocol
    # is a word in its own column, so the tint never carries meaning on its own.
    PROTO_COLORS = {
        "AIS": "#4DA6FF", "ACARS": "#66D9A0", "POCSAG": "#FFB74D",
        "RDS": "#CE93D8", "TPMS": "#80DEEA", "CW": "#F06292", "RTTY": "#90CAF9",
    }
    PROTO_COLORS_LIGHT = {
        "AIS": "#0B4F8A", "ACARS": "#0B5E3C", "POCSAG": "#7A4A00",
        "RDS": "#6A2C80", "TPMS": "#0B5F6B", "CW": "#9C1E50", "RTTY": "#2B4A8C",
    }

    def proto_colors(self):
        if self.mode == "sun":
            return {k: "#000000" for k in self.PROTO_COLORS}
        if self.mode == "light":
            return self.PROTO_COLORS_LIGHT
        return self.PROTO_COLORS

    def build_body(self):
        self._tok = theme.tokens(self.mode)      # self.mode stays the theme string (not the combo)
        self._cur_mode = MODES[0]
        self._sstv_mode = None
        body = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.bar = ControlBar()
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(MODES)
        self.mode_combo.currentTextChanged.connect(self._set_mode)
        self.bar.add_field("mode", self.mode_combo, "Decoder")
        self.run_btn = QtWidgets.QPushButton("RUN")      # R1: the radio is taken only on RUN
        self.run_btn.setCheckable(True)
        self.run_btn.setToolTip("Take the SDR and start this decoder. STOP releases it. The page "
                                "releases it on its own when you leave it.")
        self.run_btn.toggled.connect(self._toggle_run)
        self.bar.lay.addWidget(self.run_btn)
        self.busy = QtWidgets.QLabel("")        # "RADIO BUSY — held by X" when another layer owns it
        self.busy.setProperty("class", "note")
        self.busy.setWordWrap(True)
        self.busy.setStyleSheet("color: %s;" % self._tok["warn"])
        self.bar.lay.addWidget(self.busy, 1)
        self.count = QtWidgets.QLabel("0 msgs")
        self.count.setProperty("class", "value")
        self.bar.lay.addWidget(self.count)
        outer.addWidget(self.bar)

        self.stack = QtWidgets.QStackedWidget()
        text_page = QtWidgets.QWidget()
        split = QtWidgets.QHBoxLayout(text_page)
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(10)
        self.feed = FeedTable([("time", "TIME"), ("proto", "PROTO"),
                               ("id", "ID"), ("summary", "MESSAGE")])
        self.feed.view.setColumnWidth(0, 90)
        self.feed.view.setColumnWidth(2, 100)
        self.feed.selected.connect(self._show)
        split.addWidget(self.feed, 3)
        self.detail = DetailCard("MESSAGE")
        split.addWidget(self.detail, 1)
        self.image_panel = SstvImagePanel(mode=self.mode)
        self.stack.addWidget(text_page)          # index 0: text decoders
        self.stack.addWidget(self.image_panel)   # index 1: SSTV image
        outer.addWidget(self.stack, 1)
        self._count = 0
        return body

    def _toggle_run(self, on):
        self.run_btn.setText("STOP" if on else "RUN")
        w = self._worker
        if w is not None and hasattr(w, "set_running"):
            w.set_running(on)

    def set_active(self, active):
        super().set_active(active)
        w = self._worker
        if w is not None and hasattr(w, "set_active"):
            w.set_active(active)          # R1: a hidden page gives the radio back

    def primary_action(self):
        self.run_btn.toggle()
        return True

    def _set_mode(self, mode):
        prev_img, now_img = (self._cur_mode == "SSTV"), (mode == "SSTV")
        self._cur_mode = mode
        self.stack.setCurrentIndex(1 if now_img else 0)
        self.feed.model.set_rows([])
        self.image_panel.clear()            # don't present the old pass's frame as the new mode's
        self._sstv_mode = None
        self._count = 0
        self.count.setText("0 msgs")
        self.busy.setText("")               # the new mode re-derives BUSY from the arbiter
        if prev_img != now_img:             # worker TYPE changes (text decoder <-> SSTV image)
            self._rebuild_worker()
        elif self._worker is not None and hasattr(self._worker, "set_mode"):
            self._worker.set_mode(mode)

    def _rebuild_worker(self):
        if not self._started or self._stopped:
            return
        if self._worker is not None:
            from .app import stop_worker
            stop_worker(self._worker, self.TITLE)   # release the old lease first; never abort (A2)
            self._worker = None
        self._worker = self.make_worker()
        if self._worker is not None:
            self._worker.row.connect(self.on_row)
            self._worker.status.connect(self.on_status)
            self._worker.error.connect(self.on_error)
            if hasattr(self._worker, "fault"):
                self._worker.fault.connect(self.on_fault)
            self._worker.start()

    def make_worker(self):
        if self.mode_combo.currentText() == "SSTV":
            w = SstvWorker(demo=self.demo)
        else:
            w = DecoderWorker(demo=self.demo, mode=self.mode_combo.currentText())
        if hasattr(w, "set_running"):
            w.set_running(self.run_btn.isChecked())
            w.set_active(self._active)
        return w

    def on_panic(self):
        """PANIC (CL5-fix 5): RUN off and the decoder held off, so nothing respawns after the
        shell kills the process tree. Non-blocking (the worker reaps and releases)."""
        w = self._worker
        if w is not None and hasattr(w, "hold_off") and not self.demo:
            w.hold_off("PANIC")
        self._untick_run()
        return []

    def _untick_run(self):
        if self.run_btn.isChecked():
            self.run_btn.blockSignals(True)
            self.run_btn.setChecked(False)
            self.run_btn.setText("RUN")
            self.run_btn.blockSignals(False)

    def on_status(self, status):
        if status.get("run_off"):                # the worker gave the radio back (revoke / PANIC)
            self._untick_run()
        super().on_status(status)
        if status.get("practice") or status.get("standby") or status.get("idle") \
                or status.get("fault") or status.get("acquiring"):                        # no backend / idle / fault: say so
            self.busy.setText(status.get("fault") or status.get("sdr", {}).get("text", ""))
        elif "busy" in status:                   # the single-SDR banner, driven by the arbiter
            owner = status["busy"]
            self.busy.setText("RADIO BUSY — held by %s" % owner if owner else "")

    def on_row(self, row):
        is_sstv = row.get("kind") == "sstv"
        if is_sstv != (self._cur_mode == "SSTV"):
            return                               # stale row from the old worker during a mode swap
        if is_sstv:                              # an SSTV image frame -> the image panel
            self._on_sstv(row)
            return
        proto = row.get("proto", "")
        color = self.proto_colors().get(proto)
        if color:
            row["_colors"] = {"proto": color}
        self.feed.model.prepend(row, cap=400)
        self._count += 1
        self.count.setText("%d msgs" % self._count)
        self.header.set_chip("sdr", "%d MSGS" % self._count, state="neutral")
        if self._count == 1:
            self._show(row)

    def _on_sstv(self, row):
        tag = "DEMO · " if row.get("demo") else ""
        cap = "SSTV · %s%s · %d lines · slant %d ppm" % (
            tag, row.get("mode", "?"), row.get("lines", 0), row.get("slant", 0))
        self.image_panel.show_image(row["image"], cap)   # always refresh the latest frame
        # a refinement of the frame being received carries the same id — count new frames only
        key = row.get("frame", row.get("mode"))
        if self._sstv_mode is None or key != self._sstv_mode:
            self._count += 1
        self._sstv_mode = key
        self.count.setText("%d frame%s" % (self._count, "" if self._count == 1 else "s"))
        self.header.set_chip("sdr", "SSTV %d" % self._count, state="neutral")

    def _show(self, row):
        self.detail.set_hero(row.get("id", "—"), row.get("proto", ""))
        self.detail.set_rows([("TIME", row.get("time", ""))] + row.get("detail", []))
