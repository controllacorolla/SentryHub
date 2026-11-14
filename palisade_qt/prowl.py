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
import subprocess
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


def _open_nwr_pipe(cmd):
    """Spawn the nwr rtl_fm|multimon-ng shell pipeline, or None under offscreen/offline.
    cmd is nwr.pipeline()'s shell STRING (a pipe), so shell=True is required — reused AS-IS."""
    if _offscreen():
        return None
    return subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, text=True, bufsize=1, errors="replace",
                            start_new_session=True)


class _RadioWorker(Worker):
    """Mixin for a PROWL sub-mode that leases the single SDR via the arbiter and honours the
    page's front/back state (release the dongle when backgrounded — the ATLAS/PRISM pattern)."""
    NAME = None

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._active = True
        self._has_radio = False

    def set_active(self, on):
        self._active = bool(on)

    def _ensure_lease(self):
        """True if we hold the single SDR. Acquire if active+free; release if backgrounded; emit
        RADIO BUSY (publish nothing) if another layer holds it."""
        if not self._active:
            self._release_radio()
            return False
        if self._has_radio:
            return True
        if radio_arbiter.arbiter.request(self.NAME):
            self._has_radio = True
            self.status.emit({"busy": None})
            return True
        self.status.emit({"busy": radio_arbiter.owner_label(),
                          "sdr": {"text": "RADIO BUSY", "ok": False}})
        return False

    def _release_radio(self):
        if self._has_radio:
            radio_arbiter.arbiter.release(self.NAME)   # readsb / the autopilot resume
            self._has_radio = False


# ============================ SCAN ============================

class ScanWorker(_RadioWorker):
    NAME = "PROWL-SCAN"

    def __init__(self, demo=True, bank="NOAA Wx", squelch=-70, parent=None):
        super().__init__(demo=demo, interval_ms=350, parent=parent)
        self.squelch = squelch
        self.hold = False
        self._bank = bank
        self._scan = None          # live scan state dict; kept on self so stop() can break the
        self._fatal = False        # blocking listen_channel (scan["on"]=False) — else it hangs

    def set_bank(self, bank):
        self._bank = bank

    def run(self):
        if self.demo:
            self._run_demo()
        elif _offscreen() or not shutil.which("rtl_fm"):
            self._run_standby()        # live + no rtl_fm (or offscreen): honest standby, no spawn
        else:
            self._run_live()

    def set_active(self, on):
        super().set_active(on)
        if self._scan is not None:
            self._scan["pause"] = not on   # break the in-progress listen_channel when backgrounded

    def _run_standby(self):
        """Live mode without rtl_fm: list the bank's channels all-quiet and publish NO fake hits."""
        import scanner as engine
        s, _ = _load_scanner_settings(engine)
        channels = (engine.bank_channels(self._bank, s.get("custom", []))
                    or engine.bank_channels("NOAA Wx", []))
        scan = {"on": False, "pause": False, "idx": 0, "rms": 0.0}
        while not self._stop:
            self._emit_state(channels, {}, scan)   # channels listed, all quiet, no fabricated hits
            self.status.emit({"sdr": {"text": "SCAN STANDBY — no rtl_fm", "ok": False},
                              "standby": True})
            waited = 0
            while waited < 1000 and not self._stop:
                self.msleep(20)
                waited += 20

    def _run_demo(self):
        while not self._stop:
            rows = []
            active = None
            for freq, label in DEMO_CHANNELS:
                hot = random.random() < 0.12
                sig = random.randint(-55, -35) if hot else random.randint(-115, -95)
                if hot and sig > self.squelch:
                    active = (freq, label, sig)
                rows.append({"freq": freq, "label": label, "sig": "%d" % sig,
                             "last": time.strftime("%H:%M:%S") if hot else "", "_hot": hot})
            self.row.emit({"rows": rows, "active": active})
            if not active:
                self.status.emit({"sdr": {"text": "SCAN DEMO", "ok": True}})
            waited = 0
            while waited < self.interval_ms and not self._stop:
                self.msleep(10)
                waited += 10

    def _run_live(self):
        import scanner as engine
        s, _ = _load_scanner_settings(engine)
        channels = (engine.bank_channels(self._bank, s.get("custom", []))
                    or engine.bank_channels("NOAA Wx", []))
        self._scan = {"on": True, "pause": False, "idx": 0, "rms": 0.0}
        scan = self._scan
        hits = {}
        sink_fn = (lambda: None) if _offscreen() else engine.sink_cmd
        try:
            while not self._stop and scan["on"]:
                if not self._ensure_lease():        # backgrounded or radio busy
                    self.msleep(300)
                    continue
                if not channels:
                    self.msleep(500)
                    continue
                if self.hold:
                    self._emit_state(channels, hits, scan, held=True)
                    self.msleep(300)
                    continue
                idx = scan["idx"] % len(channels)
                freq, label, mode = channels[idx]
                scan["rms"] = 0.0
                result = engine.listen_channel(freq, mode, s, scan,
                                               self._make_post(freq, label, hits),
                                               sink_fn=sink_fn, clock=time.time)
                if self._stop or not scan["on"]:
                    break
                if self._fatal:                     # rtl_fm fault (surfaced by post): back off
                    self._fatal = False
                    self.msleep(2000)
                    continue
                if result:
                    hits[freq] = time.strftime("%H:%M:%S")
                self._emit_state(channels, hits, scan)
                scan["idx"] = (idx + 1) % len(channels)
        finally:
            self._release_radio()
            self._scan = None

    def _make_post(self, freq, label, hits):
        def post(msg):
            kind = msg[0] if isinstance(msg, tuple) else msg
            if kind == "hit":
                hits[freq] = time.strftime("%H:%M:%S")
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
        for freq, label, mode in channels:
            hot = freq in hits and (time.time() - _parse_time(hits.get(freq, "")) < 30)
            rms = scan.get("rms", 0)
            sig = int(-40 - (1.0 - min(1.0, rms / 8000.0)) * 80) if hot else -100
            last = hits.get(freq, "")
            if hot and not held:
                active = (str(freq), label, sig)
            rows.append({"freq": "%.4f" % freq, "label": label, "sig": "%d" % sig,
                         "last": last, "_hot": hot})
        self.row.emit({"rows": rows, "active": active})

    def stop(self):
        super().stop()
        if self._scan is not None:
            self._scan["on"] = False     # break the blocking listen_channel within one select cycle
        self._release_radio()


# ============================ FM ============================

class FmWorker(_RadioWorker):
    NAME = "PROWL-FM"

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
            self._release_radio()
            self._kill()
            self.status.emit({"sdr": {"text": "FM STANDBY — no rtl_fm", "ok": False},
                              "standby": True})
            return
        if not self._ensure_lease():
            self._kill()
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
        self.status.emit({"busy": None,
                          "sdr": {"text": ("FM %.1f ♪" % self.freq) if audio
                                          else ("FM %.1f" % self.freq), "ok": True}})

    def _spawn(self):
        import fm
        rtl, mid, sink = fm.pipeline(self.freq, self.mode, self.gain, self.squelch, self.rds)
        pipe = _open_fm_pipe(rtl, mid, sink, self._on_rds)
        orphan = None
        with self._lock:                 # guard against a concurrent stop()/_kill on the GUI thread
            if self._stop:
                orphan = pipe            # stop() won the race -> never hold a radio past stop()
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
        self.status.emit({"sdr": {"text": "FM DEMO", "ok": True}})

    def _kill(self):
        with self._lock:
            pipe, self._pipe = self._pipe, None
        if pipe is not None:
            try:
                pipe.stop()
            except Exception:
                pass

    def stop(self):
        super().stop()       # sets _stop first, so an in-flight _spawn sees it and drops the pipe
        self._kill()
        self._release_radio()


# ============================ NWR ============================

class NwrWorker(_RadioWorker):
    NAME = "PROWL-NWR"

    def __init__(self, demo=True, channel="162.400M", label="WX2", gain=0, parent=None):
        super().__init__(demo=demo, interval_ms=400, parent=parent)
        self.channel, self.label, self.gain = channel, label, gain
        self._proc = None
        self._thread = None
        self._q = deque()
        self._lock = threading.Lock()
        self._retune = False
        self._demo_src = None

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
            self._release_radio()
            self._kill()
            self.status.emit({"sdr": {"text": "NWR STANDBY — no rtl_fm", "ok": False},
                              "standby": True})
            return
        if not self._ensure_lease():
            self._kill()
            return
        if self._retune:
            self._retune = False
            self._respawn()
        elif self._proc is None:
            self._spawn()
        self._drain()
        self.status.emit({"busy": None,
                          "sdr": {"text": "NWR %s %s" % (self.label, self.channel), "ok": True}})

    def _spawn(self):
        import nwr
        proc = _open_nwr_pipe(nwr.pipeline(self.channel, self.gain))
        orphan = None
        with self._lock:                 # guard against a concurrent stop()/_kill on the GUI thread
            if self._stop:
                orphan = proc            # stop() won the race -> never hold a radio past stop()
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
        self.status.emit({"sdr": {"text": "NWR DEMO", "ok": True}})

    @staticmethod
    def _terminate(proc):
        if proc is not None and proc.poll() is None:
            import signal as _sig
            try:
                os.killpg(proc.pid, _sig.SIGTERM)
            except (ProcessLookupError, PermissionError, AttributeError):
                pass

    def _kill(self):
        with self._lock:
            proc, self._proc = self._proc, None
        self._terminate(proc)

    def stop(self):
        super().stop()       # sets _stop first, so an in-flight _spawn sees it and drops the proc
        self._kill()
        self._release_radio()


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


def _parse_time(s):
    """Parse HH:MM:SS into a rough timestamp for today (for recency check)."""
    try:
        parts = s.split(":")
        return time.mktime(time.localtime()[:3] + (int(parts[0]), int(parts[1]), int(parts[2]), 0, 0, -1))
    except (ValueError, IndexError):
        return 0


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

    def __init__(self, demo=False, mode="dark", parent=None):
        self._submode = "SCAN"
        super().__init__(demo=demo, mode=mode, parent=parent)

    # ---- layout ----
    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)
        self._mode_btns = {}
        for m in self.SUBMODES:
            b = QtWidgets.QPushButton(m)
            b.setCheckable(True)
            b.setFixedWidth(92)
            b.clicked.connect(lambda _=False, mm=m: self._switch_submode(mm))
            self._mode_btns[m] = b
            top.addWidget(b)
        top.addStretch(1)
        self.busy = QtWidgets.QLabel("")
        self.busy.setStyleSheet("color:%s;" % self._tok["warn"])
        top.addWidget(self.busy)
        lay.addLayout(top)

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
        self.squelch.setRange(-120, -20)
        self.squelch.setValue(-70)
        self.squelch.setSuffix(" dBm")
        self.squelch.valueChanged.connect(self._sq)
        self.squelch.setEnabled(self.demo)        # live squelch comes from the scanner engine
        if not self.demo:                         # settings (scanner.json), not this preview knob
            self.squelch.setToolTip("Live squelch is set by the scanner engine (scanner.json)")
        self.bar.add_field("squelch", self.squelch, "Squelch")

        self.bank_combo = QtWidgets.QComboBox()
        try:
            import scanner as engine
            banks = engine.BANK_ORDER
        except ImportError:
            banks = ["NOAA Wx", "CB", "GMRS/FRS", "Marine VHF", "Airband"]
        self.bank_combo.addItems(banks)
        self.bank_combo.setCurrentText("NOAA Wx")
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
        self.sig_bar.setFixedHeight(8)
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
        self.fdb_results.setProperty("class", "micro")
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
        self.fm_freq.setDecimals(1)
        self.fm_freq.setSingleStep(0.1)
        self.fm_freq.setValue(FM_DEFAULTS["freq"])
        self.fm_freq.setSuffix(" MHz")
        self.fm_freq.editingFinished.connect(self._fm_retune)
        bar.add_field("freq", self.fm_freq, "Tune")
        bar.add_button("−", lambda: self._fm_step(-0.2))     # seek down (step tune)
        bar.add_button("+", lambda: self._fm_step(0.2))           # seek up
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
        bar.lay.addWidget(micro("Monitoring"))
        self.nwr_state = QtWidgets.QLabel("—")
        self.nwr_state.setProperty("class", "value")
        bar.lay.addWidget(self.nwr_state)
        lay.addWidget(bar)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        self.nwr_feed = FeedTable([("time", "TIME"), ("event", "EVENT"),
                                   ("areas", "AREAS"), ("station", "STATION")])
        self.nwr_feed.selected.connect(self._nwr_show)
        split.addWidget(self.nwr_feed, 3)
        self.nwr_detail = DetailCard("SAME ALERT")
        self.nwr_detail.set_hero("—", "no alerts")
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
        if self._started and not self._stopped:
            if self._worker is not None:
                self._worker.stop()
                self._worker.quit()
                self._worker.wait(3000)      # release the old lease before acquiring the new
                self._worker = None
            self._worker = self.make_worker()
            if self._worker is not None:
                self._worker.row.connect(self.on_row)
                self._worker.status.connect(self.on_status)
                self._worker.error.connect(self.on_error)
                self._worker.start()

    def _sync_mode_buttons(self):
        for m, b in self._mode_btns.items():
            b.setChecked(m == self._submode)

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
            self._worker.squelch = v

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

    def _sig_color(self, sig, hot):
        if hot:
            return self._tok["live"]
        if sig > -60:
            return self._tok["warn"]
        return self._tok["muted"]

    def _on_scan_row(self, msg):
        rows = msg["rows"]
        for r in rows:
            sig = int(r["sig"])
            r["_colors"] = {"sig": self._sig_color(sig, r.get("_hot", False))}
            if r.get("_hot"):
                r["_colors"]["label"] = self._tok["live"]
                r["_colors"]["freq"] = self._tok["live"]
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
        self.fm_freq.setValue(round(self.fm_freq.value() + delta, 1))
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

    def on_status(self, status):
        super().on_status(status)
        if status.get("standby"):
            self.busy.setText(status.get("sdr", {}).get("text", "STANDBY"))
            if self._submode == "SCAN":
                self.active.setText("standby — no device")
        elif "busy" in status:
            owner = status["busy"]
            self.busy.setText("RADIO BUSY — held by %s" % owner if owner else "")
