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
import time

from PySide6 import QtWidgets

from .app import PalisadeApp
from . import theme
from .kit import ControlBar, FeedTable, DetailCard
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MODES = ["AIS", "ACARS", "POCSAG", "RDS", "CW", "RTTY"]


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


def _can_run(mode):
    """Check if the required binary for a mode is on PATH."""
    needs = {"AIS": "rtl_ais", "ACARS": "acarsdec", "POCSAG": "multimon-ng", "RDS": "redsea"}
    binary = needs.get(mode)
    return binary is None or shutil.which(binary) is not None


# ---- per-mode live decoders (pure functions imported from the real engines) ----

def _run_ais(worker):
    import ais as engine
    s = _load_settings("ais", engine.DEFAULTS)
    cmd = engine.pipeline(gain=s.get("gain", 0))
    asm = engine.AivdmAssembler()
    n = 0
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, text=True, bufsize=1, errors="replace",
                            start_new_session=True)
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
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, bufsize=1, errors="replace",
                                start_new_session=True)
    except FileNotFoundError:
        worker.error.emit("acarsdec not found — install it or use --demo")
        return
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
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, text=True, bufsize=1, errors="replace",
                            start_new_session=True)
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
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, text=True, bufsize=1, errors="replace",
                            start_new_session=True)
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


_LIVE_RUNNERS = {"AIS": _run_ais, "ACARS": _run_acars, "POCSAG": _run_pocsag, "RDS": _run_rds}


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

            if self.demo or mode not in _LIVE_RUNNERS:
                self._run_demo(mode)
            elif not _can_run(mode):
                self.status.emit({"sdr": {"text": "%s DEMO (no binary)" % mode, "ok": False}})
                self._run_demo(mode)
            else:
                try:
                    runner = _LIVE_RUNNERS[mode]
                    runner(self)
                except Exception as e:
                    self.error.emit("%s: %s" % (mode, str(e)[:150]))
                    self.status.emit({"sdr": {"text": "%s ERROR" % mode, "ok": False}})
                    self.msleep(2000)

            if self._stop:
                break
            if not self._mode_changed:
                self.msleep(500)

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


class BabelApp(PalisadeApp):
    TITLE = "BABEL"
    LEASE = "BABEL"

    PROTO_COLORS = {
        "AIS": "#4DA6FF", "ACARS": "#66D9A0", "POCSAG": "#FFB74D",
        "RDS": "#CE93D8", "CW": "#F06292", "RTTY": "#90CAF9",
    }

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.bar = ControlBar()
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(MODES)
        self.mode.currentTextChanged.connect(self._set_mode)
        self.bar.add_field("mode", self.mode, "Decoder")
        self.bar.add_stretch()
        self.count = QtWidgets.QLabel("0 msgs")
        self.count.setProperty("class", "value")
        self.bar.lay.addWidget(self.count)
        outer.addWidget(self.bar)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        self.feed = FeedTable([("time", "TIME"), ("proto", "PROTO"),
                               ("id", "ID"), ("summary", "MESSAGE")])
        self.feed.view.setColumnWidth(0, 90)
        self.feed.view.setColumnWidth(2, 100)
        self.feed.selected.connect(self._show)
        split.addWidget(self.feed, 3)
        self.detail = DetailCard("MESSAGE")
        split.addWidget(self.detail, 1)
        outer.addLayout(split, 1)
        self._count = 0
        return body

    def _set_mode(self, mode):
        self.feed.model.set_rows([])
        self._count = 0
        self.count.setText("0 msgs")
        if self._worker is not None:
            self._worker.set_mode(mode)

    def make_worker(self):
        return DecoderWorker(demo=self.demo, mode=self.mode.currentText())

    def on_row(self, row):
        proto = row.get("proto", "")
        color = self.PROTO_COLORS.get(proto)
        if color:
            row["_colors"] = {"proto": color}
        self.feed.model.prepend(row, cap=400)
        self._count += 1
        self.count.setText("%d msgs" % self._count)
        self.header.set_chip("sdr", "%d MSGS" % self._count, state="neutral")
        if self._count == 1:
            self._show(row)

    def _show(self, row):
        self.detail.set_hero(row.get("id", "—"), row.get("proto", ""))
        self.detail.set_rows([("TIME", row.get("time", ""))] + row.get("detail", []))
