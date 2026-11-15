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


def _open_pipe(cmd, shell=True, stderr=subprocess.DEVNULL):
    """Spawn a decoder capture pipeline — or None under offscreen/offline so tests and CI never
    open a real radio. The caller has already confirmed the binary is present via _can_run()."""
    if os.environ.get("PALISADE_OFFLINE") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return None
    return subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE, stderr=stderr,
                            stdin=subprocess.DEVNULL, text=True, bufsize=1, errors="replace",
                            start_new_session=True)


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
    worker._proc = proc
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
    worker._proc = proc
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
    worker._proc = proc
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
    worker._proc = proc
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
    worker._proc = proc
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
    """Graceful shutdown: SIGINT, then SIGTERM, then SIGKILL."""
    if not proc or proc.poll() is not None:
        return
    import signal
    for sig, wait in ((signal.SIGINT, 2.0), (signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


class DecoderWorker(Worker):
    def __init__(self, demo=True, mode="AIS", parent=None):
        super().__init__(demo=demo, interval_ms=600, parent=parent)
        self.mode = mode
        self._n = 0
        self._proc = None
        self._mode_changed = False

    def set_mode(self, mode):
        self.mode = mode
        self._mode_changed = True
        if self._proc and self._proc.poll() is None:
            _stop_proc(self._proc)
            self._proc = None

    def run(self):
        while not self._stop:
            mode = self.mode
            self._mode_changed = False

            if self.demo:
                self._run_demo(mode)
            elif mode not in _LIVE_RUNNERS:
                self._run_practice(mode)      # live + no RX backend (CW/RTTY): honest, never synth
            elif not _can_run(mode):
                self._run_standby(mode)       # live + no decoder binary: honest standby, no synth
            else:
                self._run_live(mode)

            if self._stop:
                break
            if not self._mode_changed:
                self.msleep(500)

    def _run_live(self, mode):
        """Acquire the single SDR via the shared arbiter, run the real decoder, then release. If
        another callsign holds the radio, show RADIO BUSY and (being live) synthesise nothing."""
        if not radio_arbiter.arbiter.request(LEASE_NAME):
            owner = radio_arbiter.owner_label() or radio_arbiter.arbiter.owner() or "?"
            self.status.emit({"sdr": {"text": "RADIO BUSY — %s" % owner, "ok": False},
                              "busy": owner})
            waited = 0                       # idle and retry while the radio is held elsewhere
            while waited < 1500 and not self._stop and not self._mode_changed:
                self.msleep(50)
                waited += 50
            return
        self.status.emit({"busy": None})     # we hold the radio — clear any BUSY banner
        try:
            _LIVE_RUNNERS[mode](self)
        except Exception as e:
            self.error.emit("%s: %s" % (mode, str(e)[:150]))
            self.status.emit({"sdr": {"text": "%s ERROR" % mode, "ok": False}})
            self.msleep(2000)
        finally:
            radio_arbiter.arbiter.release(LEASE_NAME)

    def _run_standby(self, mode):
        """Live mode with the decoder binary absent: show an honest STANDBY and publish nothing.
        Live never synthesises — demo mode (the SDR-DEMO chip) is the only synthetic path."""
        binary = _MODE_BINARY.get(mode, "decoder")
        self.status.emit({"sdr": {"text": "%s STANDBY — no %s" % (mode, binary), "ok": False}})
        while not self._stop and not self._mode_changed:
            self.msleep(50)

    def _run_practice(self, mode):
        """Live mode for a mode with NO live RX backend (CW/RTTY are txguard TX/practice tools
        with no demodulator; digimodes has no decoder). Say so honestly and publish nothing — live
        never synthesises. The decoded text is available in demo mode (SDR-DEMO) only."""
        self.status.emit({"sdr": {"text": "%s — practice only (no live decode)" % mode, "ok": False},
                          "practice": True})
        while not self._stop and not self._mode_changed:
            self.msleep(50)

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
                self.msleep(10)
                waited += 10

    def stop(self):
        super().stop()
        if self._proc and self._proc.poll() is None:
            _stop_proc(self._proc)
        radio_arbiter.arbiter.release(LEASE_NAME)   # belt-and-suspenders if wait() ever times out


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

    def __init__(self, demo=True, freq=SSTV_DEFAULT_FREQ, gain=40, parent=None):
        super().__init__(demo=demo, interval_ms=1000, parent=parent)
        self.freq, self.gain = freq, gain
        self._has_radio = False
        self._rec = None
        self._wav = None
        self._last_decode = 0.0
        self._demo_sent = False
        self._decoding = False
        self._lock = threading.Lock()     # serialises _rec / _has_radio across step() and stop()

    # seams so tests/CI never open a real radio or require a WAV
    def _make_recorder(self, path):
        if os.environ.get("PALISADE_OFFLINE") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return None
        import sstv
        return sstv.Recorder(path, self.freq, self.gain, monitor=False)

    def _decode(self, path):
        import sstvdec
        return sstvdec.decode_wav(path)

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
                              "standby": True})
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
                import tempfile
                self._wav = os.path.join(tempfile.gettempdir(),
                                         "palisade_sstv_%d.wav" % os.getpid())
                rec = self._rec = self._make_recorder(self._wav)
        if rec is None:                              # offscreen seam: hold lease, no capture
            self.status.emit({"sdr": {"text": "SSTV — capturing", "ok": True}, "busy": None})
            return
        if rec.err:                                  # rtl_fm died: reap + restart on the next step
            self._stop_rec()
            self.status.emit({"sdr": {"text": "SSTV — %s (retrying)" % rec.err[:34], "ok": False}})
            return
        secs = rec.seconds()
        self.status.emit({"sdr": {"text": "SSTV — capturing %ds (lvl %.0f)" % (secs, rec.level),
                                  "ok": True}, "busy": None})
        now = time.time()
        # run the CPU-bound decode on a DISPOSABLE daemon thread so step() stays responsive to
        # _stop (the worker QThread must join within wait(); decode_wav can't be interrupted)
        if secs > 20 and not self._decoding and (now - self._last_decode) > 12:
            self._last_decode = now
            self._decoding = True
            threading.Thread(target=self._decode_job, args=(self._wav,), daemon=True).start()

    def _decode_job(self, path):
        try:
            r = self._decode(path)
        except ValueError as e:                      # no header yet / truncated: keep listening
            if not self._stop:
                self.status.emit({"sdr": {"text": "SSTV — listening (%s)" % str(e)[:26],
                                          "ok": False}})
            return
        except Exception as e:
            if not self._stop:
                self.error.emit("SSTV decode: %s" % str(e)[:120])
            return
        finally:
            self._decoding = False
        if self._stop:
            return                                   # torn down mid-decode: drop the abandoned frame
        self.row.emit({"kind": "sstv", "image": r["image"], "mode": r.get("mode", "?"),
                       "lines": r.get("lines", 0), "slant": r.get("slant_ppm", 0)})
        eventbus.bus.publish(eventbus.decode(
            "BABEL-SSTV", "SSTV", r.get("mode", "?"),
            "%s frame · %d lines" % (r.get("mode", "?"), r.get("lines", 0)), severity="info"))

    def _ensure_lease(self):
        if self._stop:
            return False
        if self._has_radio:
            return True
        if radio_arbiter.arbiter.request(self.NAME):
            if self._stop:                           # stop() won the race -> release immediately
                radio_arbiter.arbiter.release(self.NAME)
                return False
            self._has_radio = True
            self.status.emit({"busy": None})
            return True
        self.status.emit({"busy": radio_arbiter.owner_label(),
                          "sdr": {"text": "RADIO BUSY", "ok": False}})
        return False

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
        if wav:
            try:
                os.remove(wav)
            except OSError:
                pass

    def stop(self):
        super().stop()          # sets _stop first, so _ensure_lease/_start can't re-acquire/respawn
        self._stop_rec()
        self._release()


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
            self._worker.stop()
            self._worker.quit()
            self._worker.wait(3000)         # release the old lease before the new worker starts
            self._worker = None
        self._worker = self.make_worker()
        if self._worker is not None:
            self._worker.row.connect(self.on_row)
            self._worker.status.connect(self.on_status)
            self._worker.error.connect(self.on_error)
            self._worker.start()

    def make_worker(self):
        if self.mode_combo.currentText() == "SSTV":
            return SstvWorker(demo=self.demo)
        return DecoderWorker(demo=self.demo, mode=self.mode_combo.currentText())

    def on_status(self, status):
        super().on_status(status)
        if status.get("practice") or status.get("standby"):   # no backend / no device: say so
            self.busy.setText(status.get("sdr", {}).get("text", ""))
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
        # re-decoding a growing WAV refines the SAME frame — only count a genuinely new one
        if self._sstv_mode is None or row.get("mode") != self._sstv_mode:
            self._count += 1
        self._sstv_mode = row.get("mode")
        self.count.setText("%d frame%s" % (self._count, "" if self._count == 1 else "s"))
        self.header.set_chip("sdr", "SSTV %d" % self._count, state="neutral")

    def _show(self, row):
        self.detail.set_hero(row.get("id", "—"), row.get("proto", ""))
        self.detail.set_rows([("TIME", row.get("time", ""))] + row.get("detail", []))
