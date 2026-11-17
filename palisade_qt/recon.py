"""RECON — survey + assess: Wi-Fi / BLE / network (key 6).

Since CL1 the counter-surveillance detectors live on their own page (SWEEP, sweep.py — the
DetectorWorker class stays here and is imported there, unchanged) and ENGAGE is global chrome: the
ENGAGEMENT slot in the top strip opens panels.EngagePanel.

Two tiers, wired to the legacy engines AS-IS:

  * PASSIVE (no gate): wifisurvey, blescan, rffinger, scout — receive-only, ungated by design.
  * ACTIVE (gated): wifipent, blepent, netpent, passaudit — every action goes through the engine's
    `prepare(...)` which calls `engagement.authorize_action(...)`. The gate is enforced by the
    ENGINE, not this UI: with no active engagement (or an out-of-scope target) prepare() returns no
    argv. This UI only reflects gate state and passes the shared evidence chain through — it NEVER
    routes around the gate, and it wires no new TX/attack path.

The ENGAGEMENT panel is the governance keystone: operator identity (opprofile), engagement scope
(engagement.start/end), the authorized-action trail, and the tamper-evident evidence chain.

Honesty: passive tools show real scan results or an honest standby when no adapter is present;
live never fabricates (demo is the only synthetic path, flagged SDR/SCAN-DEMO). Offscreen/offline
seams mean tests never open a real adapter or spawn a scan.
"""
import os
import random
import shutil
import subprocess
import sys
import time

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp, stop_worker
from . import theme, eventbus
from .kit import ControlBar, FeedTable, micro, card
from .worker import Worker
from .timebase import zulu
from .runpane import RunPane

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SUBTABS = ("WIFI", "BLE", "NET", "RF")
SYS_NET = "/sys/class/net"


def _unique(d, stem, ext):
    """RA-RXc N4: a results path no earlier run used — UTC time plus a random suffix, so two runs
    in the same second never share (and overwrite) one evidence file."""
    import uuid
    return os.path.join(d, "%s-%s-%s%s" % (stem, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                                           uuid.uuid4().hex[:6], ext))


def monitor_iface():
    """The first interface already in monitor mode (ARPHRD_IEEE80211_RADIOTAP = 803), or None."""
    try:
        names = sorted(os.listdir(SYS_NET))
    except OSError:
        return None
    for n in names:
        try:
            with open(os.path.join(SYS_NET, n, "type")) as fh:
                if fh.read().strip() == "803":
                    return n
        except OSError:
            continue
    return None

# SCAN-1/2: what each scan path really does (honest labels; nmcli and BlueZ discovery probe)
WIFI_MODE = {
    None: "WIFISURVEY · scan path not known yet · no deauth/inject",          # RA-SCAN N1
    "iw": "WIFISURVEY · passive (iw, beacons only) · no deauth/inject",
    "nmcli": "WIFISURVEY · ACTIVE scan (NetworkManager probes) · no deauth/inject",
    "demo": "WIFISURVEY · demo · no deauth/inject",
}
BLE_MODE = "BLESCAN · active discovery (scan requests) · no connect/pair"


from .kit.seams import offscreen as _offscreen  # noqa: E402  (C5: one copy)


def _run_cmd(argv, timeout=12):
    """Run a passive scan command and return stdout text, or None under offscreen/offline, when
    the tool is absent, or when it FAILED (H3: a failed scan is not "0 AP"). See _run_scan for
    the reason."""
    out, _why = _run_scan(argv, timeout)
    return out


def _kill_group(proc):
    """SIGTERM the scan's process group, SIGKILL after 1 s. Never raises."""
    for sig, wait in ((15, 1.0), (9, 1.0)):
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            pass
        try:
            proc.wait(wait)
        except subprocess.TimeoutExpired:
            pass


def _run_scan(argv, timeout=12, worker=None):
    """-> (stdout, None) on exit 0, else (None, reason). Never spawns under offscreen/offline.
    RA-SCAN N2: the command runs in its own process group; with a worker it is polled
    interruptibly, and stop() (or the timeout) kills the group at once — closing RECON never
    leaves a scan or its thread behind."""
    if _offscreen() or not argv:
        return None, "offline"
    if not shutil.which(argv[0]):
        return None, "%s not installed" % argv[0]
    import tempfile
    try:
        with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
            proc = subprocess.Popen(argv, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                    text=True, start_new_session=True)
            try:
                if worker is not None:
                    rc = worker.poll_process(proc, timeout_ms=int(timeout * 1000), poll_ms=50)
                else:
                    try:
                        rc = proc.wait(timeout)
                    except subprocess.TimeoutExpired:
                        rc = None
            finally:
                if proc.poll() is None:
                    _kill_group(proc)
            if rc is None:
                if worker is not None and worker.stopping:
                    return None, "stopped"
                return None, "timed out after %ds" % timeout
            out.seek(0)
            err.seek(0)
            stdout, stderr = out.read(), err.read()
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    if rc != 0:
        lines = (stderr or stdout or "").strip().splitlines()
        return None, "exit %d%s" % (rc, (" — " + lines[-1][:80]) if lines else "")
    return stdout, None


# ======================= shared engagement gate =======================

def _engagement():
    import engagement
    return engagement


class GatedTool(QtWidgets.QFrame):
    """A card for one ACTIVE tool. It calls the engine's prepare() (which enforces
    engagement.authorize_action); it never bypasses the gate. With no engagement it shows
    'REQUIRES ENGAGEMENT'.

    RX (owner decision 2026-11-17: NET + Wi-Fi execution in v0.1): a card built with a `runner`
    (runpane.RunPane) hands the ticket the gate produced to the executor through that pane, which
    starts the real tool and streams its output. A card without one (BLEPENT, PASSAUDIT — v0.2)
    still only shows the authorized command. `extra()` supplies the engine's further prepare()
    arguments (Wi-Fi interface / channel / client) — the ENGINE still builds and gates the argv.

    DEAUTH (owner decision 2026-11-17: targeted deauth is a gated capability): `runners` maps an
    action to its own pane, so a short deauth can run while a handshake capture keeps running on
    the card's main pane (the capture is what the deauth is for). Each pane runs one process; the
    gate and the executor are the same for both."""

    def __init__(self, title, domain, prepare_fn, actions, app, tok, target_hint="target",
                 parent=None, runner=None, extra=None, fields=None, runners=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self._prepare = prepare_fn
        self._app = app
        self._tok = tok
        self._domain = domain
        self._runner = runner
        self._runners = dict(runners or {})
        self._last_pane = None
        self._extra = extra
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lay.addWidget(micro("%s · gated" % title))
        self.state = QtWidgets.QLabel("")
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        row = QtWidgets.QHBoxLayout()
        self.target = QtWidgets.QLineEdit()
        self.target.setPlaceholderText(target_hint)
        row.addWidget(self.target, 1)
        lay.addLayout(row)
        self._fields = list(fields or ())
        if self._fields:
            frow = QtWidgets.QHBoxLayout()
            for label, w in self._fields:
                frow.addWidget(micro(label))
                frow.addWidget(w, 1)
            lay.addLayout(frow)
        self._btns = []
        self._acts = list(actions)
        brow = QtWidgets.QHBoxLayout()
        for act in actions:
            b = QtWidgets.QPushButton(act.upper())
            b.clicked.connect(lambda _=False, a=act: self._authorize(a))
            brow.addWidget(b)
            self._btns.append(b)
        brow.addStretch(1)
        lay.addLayout(brow)
        self.result = QtWidgets.QLabel("")
        self.result.setProperty("class", "note")
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(self.result)
        from . import chrome
        chrome.gate_signals().changed.connect(self.refresh)      # follows the engine (G12)
        for pane in self._panes():
            pane.finished.connect(lambda h, pane=pane: self._run_finished(pane))
        self.refresh()

    def _runner_for(self, action):
        return self._runners.get(action, self._runner)

    def _panes(self):
        out = []
        for pane in [self._runner] + list(self._runners.values()):
            if pane is not None and pane not in out:
                out.append(pane)
        return out

    def _run_finished(self, pane):
        """The card's last line follows the process: never 'RUNNING' after it has ended."""
        txt = self.result.text()
        if "RUNNING — output below" in txt and self._last_pane is pane:
            self.result.setText(txt.replace("RUNNING — output below",
                                            "ENDED — %s" % pane.state.text()))
        self.refresh()

    def refresh(self):
        eng = _engagement()
        active = eng.is_active()
        for b, act in zip(self._btns, self._acts):
            pane = self._runner_for(act)
            busy = pane is not None and pane.running()
            b.setEnabled(active and not busy)          # one process per pane; STOP is on the pane
        self.target.setEnabled(active)
        for _label, w in self._fields:
            w.setEnabled(active)
        if active:
            info = eng.info()
            self.state.setStyleSheet("color:%s;" % self._tok["warn"])     # amber: armed, not healthy
            self.state.setText("◆ authorized scope: %s" % ", ".join(info["scope"][:4]))
        elif eng.expired():
            self.state.setStyleSheet("color:%s;" % self._tok["alert"])
            self.state.setText("▲ engagement EXPIRED — END it and open a new one (E)")
            self.result.setText("")
        else:
            self.state.setStyleSheet("color:%s;" % self._tok["muted"])
            self.state.setText("○ REQUIRES ENGAGEMENT — open ENGAGEMENT in the top strip (E)")
            self.result.setText("")

    def _authorize(self, action):
        target = self.target.text().strip()
        if not target:
            self.result.setText("enter a %s first" % self._domain)
            return
        runner = self._runner_for(action)
        if runner is not None and runner.running():
            self.result.setText("a tool is already running — STOP it first")
            return
        kw = {}
        if self._extra is not None:
            kw, err = self._extra(action)
            if err:
                self.result.setStyleSheet("color:%s;" % self._tok["muted"])
                self.result.setText("NOT RUN: %s" % err)
                return
        # the ENGINE gates this (engagement.authorize_action); we pass the shared evidence chain
        ok, why, ticket = self._prepare(action, target, evidence_chain=self._app.evidence, **kw)
        if not ok:
            self.result.setStyleSheet("color:%s;" % self._tok["muted"])
            self.result.setText("DENIED: %s" % why)
            return
        self.result.setStyleSheet("color:%s;" % self._tok["warn"])        # AUTHORIZED is amber (D9)
        bind = " · LABEL-ONLY authorization" if ticket.binding == "label-only" else ""
        if runner is None:
            self.result.setText("AUTHORIZED: %s\n$ %s\n(single-use ticket%s — runs only through "
                                "the executor; execution is v0.2)" % (why, ticket.display(), bind))
            self._app.on_authorized(self._domain, action, target, list(ticket.argv or ()))
            return
        self._app.on_authorized(self._domain, action, target, list(ticket.argv or ()))
        self._app.prepare_run(ticket)
        self._last_pane = runner
        started, msg = runner.run(ticket, spawner=self._app._spawner())
        self.result.setText("AUTHORIZED: %s%s\n$ %s\n%s" % (
            why, bind, ticket.display(),
            "RUNNING — output below" if started else "NOT RUN: %s" % msg))
        if not started:
            self.result.setStyleSheet("color:%s;" % self._tok["alert"])
        self.refresh()


# ======================= passive scan workers =======================

class WifiScanWorker(Worker):
    """wifisurvey AP scan. No gate, no TX beyond the scan itself.

    PASSIVE first: `iw dev X scan passive` (listen for beacons, no probe requests). That needs
    CAP_NET_ADMIN, so as the normal desktop user it is refused ("Operation not permitted").
    SCAN-1: then fall back to NetworkManager (`nmcli dev wifi list`), which scans on the user's
    behalf. NM's scan is ACTIVE (probe requests), so the row says path="nmcli" and the page says
    "active" — never "passive". Both failing is SCAN FAILED with both reasons.
    H3: the exit code is checked (a failed scan is SCAN FAILED, never "0 AP"), it runs every
    15 s rather than 4 s, and RECON pauses it while the WIFI sub-tab is not on screen."""
    INTERVAL_MS = 15000
    NMCLI_TIMEOUT_S = 25          # nmcli waits for NM's rescan to finish

    def __init__(self, demo=False, iface="wlan0", parent=None):
        super().__init__(demo=demo, interval_ms=self.INTERVAL_MS, parent=parent)
        self.iface = iface

    def step(self):
        import wifisurvey
        if self.demo:
            self.row.emit({"aps": _demo_aps(), "demo": True, "path": "demo"})
            return
        out, why = _run_scan(wifisurvey.scan_argv(self.iface), worker=self)
        if self._stop:
            return
        if out is not None:
            self.row.emit({"aps": wifisurvey.parse_iw_scan(out), "path": "iw"})
            return
        if why == "offline":
            self.status.emit({"standby": True, "scan_failed": why,
                              "sdr": {"text": "WIFI STANDBY — offline", "ok": False}})
            return
        out2, why2 = _run_scan(wifisurvey.nmcli_scan_argv(self.iface),
                               timeout=self.NMCLI_TIMEOUT_S, worker=self)
        if self._stop:
            return
        if out2 is not None:
            aps = wifisurvey.parse_nmcli(out2)
            if aps or not out2.strip():
                self.row.emit({"aps": aps, "path": "nmcli", "iw_refused": why})
                return
            why2 = "output not understood: %r" % out2.strip().splitlines()[0][:40]   # N5
        if why == "iw not installed" and why2 == "nmcli not installed":
            text = "WIFI STANDBY — no iw or nmcli (sudo apt install iw network-manager)"
        else:
            text = "WIFI SCAN FAILED — iw: %s · nmcli: %s" % (why, why2)
        self.status.emit({"standby": True, "scan_failed": "iw: %s; nmcli: %s" % (why, why2),
                          "wifi_path": None, "sdr": {"text": text, "ok": False}})


def _ble_reason(err):
    """A bleak / BlueZ exception -> a short reason a pentester can act on."""
    s = str(err) or type(err).__name__
    low = s.lower()
    if "no bluetooth adapter" in low or "no default controller" in low or \
            "org.bluez.error.notfound" in low:
        return "no Bluetooth adapter"
    if "notready" in low or "not ready" in low or "powered off" in low:
        return "adapter is powered off (bluetoothctl power on)"
    if "rfkill" in low or "blocked" in low:
        return "adapter is rfkill-blocked (rfkill unblock bluetooth)"
    if "accessdenied" in low or "notauthorized" in low or "not authorized" in low or \
            "permission" in low:
        return "not authorized by BlueZ (D-Bus policy)"
    if "serviceunknown" in low or "bluetoothd is not running" in low:
        return "bluetoothd is not running"
    return s.splitlines()[0][:90] if s else "scan error"


class BleScanWorker(Worker):
    """blescan: live BLE survey (SCAN-2). No gate, no connect, no pair, no GATT.

    Backend: bleak (BlueZ over D-Bus, no root) when importable, else `bluetoothctl scan on`.
    Both run BlueZ's normal discovery, which is an ACTIVE scan (the adapter sends scan requests to
    get scan responses) — the page says so. A general survey cannot use BlueZ's passive mode: that
    is an advertisement monitor that needs a byte pattern per advert (ATLAS uses it for Remote ID).

    The worker scans in WINDOW_S windows and emits the whole table every EMIT_MS, so rows update
    live. A device stays listed for STALE_S after it was last heard. A failure is SCAN FAILED
    with the reason, and the scan retries every RETRY_MS (an adapter may be powered on later).
    RECON pauses it while the BLE sub-tab is not on screen; a pause ends the window at once."""

    WINDOW_S = 30
    EMIT_MS = 1000
    STALE_S = 60
    RETRY_MS = 15000
    MIN_WINDOW_S = 2              # a window shorter than this, unasked, is a failure (N6)
    BLEAK_START_S = 10
    BLEAK_STOP_S = 2
    PREFLIGHT_S = 4

    def __init__(self, demo=False, parent=None):
        super().__init__(demo=demo, interval_ms=500, parent=parent)
        import blescan
        self._devs = blescan.Devices(stale_s=self.STALE_S)
        self._seen = {}               # address -> merged advert (name/uuids/mfr stick)
        self.backend = None

    @staticmethod
    def backend_available():
        """'bleak' | 'bluetoothctl' | None."""
        import importlib.util
        if importlib.util.find_spec("bleak") is not None:
            return "bleak"
        if shutil.which("bluetoothctl"):
            return "bluetoothctl"
        return None

    @staticmethod
    def _no_feed_text():
        return "BLE STANDBY — no bleak and no bluetoothctl (sudo apt install bluez)"

    # ---- merge + emit (both backends) ----
    def _merge(self, addr, name=None, rssi=None, uuids=(), mfr=()):
        addr = (addr or "").upper()
        if not addr:
            return None
        d = self._seen.setdefault(addr, {"address": addr, "name": "", "rssi": None,
                                         "service_uuids": [], "manufacturer_data": {}})
        if name and name.replace("-", ":").upper() != addr:
            d["name"] = name
        if rssi is not None:
            d["rssi"] = rssi
        for u in uuids or ():
            u = str(u).lower()
            if u not in d["service_uuids"]:
                d["service_uuids"].append(u)
        for k in mfr or ():
            d["manufacturer_data"][k] = True
        return addr

    def _emit(self, touched, now=None):
        for addr in touched:
            self._devs.ingest(dict(self._seen[addr]), now=now)
        rows = [_ble_row(d) for d in self._devs.active(now=now)]
        rows.sort(key=lambda r: -(r["rssi"] if isinstance(r["rssi"], int) else -999))
        self.row.emit({"devs": rows, "backend": self.backend, "ts": time.time()})
        return rows

    def _window_over(self, t0):
        return self._stop or self._paused or time.monotonic() - t0 >= self.WINDOW_S

    # ---- bleak backend ----
    def _scan_bleak(self):
        """One scan window via bleak. Returns None, or a failure reason."""
        import asyncio
        try:
            from bleak import BleakScanner
        except Exception as e:                     # broken install: fall through to bluetoothctl
            return "bleak import failed: %s" % str(e)[:60]
        batch = []

        def cb(dev, adv):
            batch.append((dev.address, getattr(adv, "local_name", None) or dev.name,
                          getattr(adv, "rssi", None),
                          list(getattr(adv, "service_uuids", None) or []),
                          list((getattr(adv, "manufacturer_data", None) or {}).keys())))

        async def bounded(coro, limit_s, what):
            """RA-SCAN N3: a BlueZ call that hangs never pins the worker: poll stop()/pause
            every 0.1 s and give up after limit_s."""
            task = asyncio.ensure_future(coro)
            t0 = time.monotonic()
            while not task.done():
                if self._stop or time.monotonic() - t0 > limit_s:
                    task.cancel()
                    try:
                        await task
                    except BaseException:
                        pass
                    if self._stop:
                        return False
                    raise TimeoutError("BlueZ did not answer %s within %ds" % (what, limit_s))
                await asyncio.sleep(0.1)
            task.result()
            return True

        async def run():
            scanner = BleakScanner(detection_callback=cb, scanning_mode="active")
            if not await bounded(scanner.start(), self.BLEAK_START_S, "start"):
                return
            try:
                t0 = time.monotonic()
                while not self._window_over(t0):
                    await asyncio.sleep(self.EMIT_MS / 1000.0)
                    got, batch[:] = list(batch), []
                    touched = {self._merge(a, n, r, u, m) for a, n, r, u, m in got}
                    self._emit({t for t in touched if t})
            finally:
                try:
                    await asyncio.wait_for(scanner.stop(), self.BLEAK_STOP_S)
                except Exception:
                    pass                # the scan ends with the D-Bus connection anyway

        try:
            asyncio.run(run())
        except Exception as e:
            return _ble_reason(e)
        return None

    # ---- bluetoothctl backend ----
    def _scan_bluetoothctl(self):
        """One scan window via `bluetoothctl --timeout N scan on`. Returns None or a reason."""
        import blescan
        import threading
        # RA-SCAN N7: bluetoothctl waits silently for a missing bluetoothd, so ask the
        # controller first (interruptible, bounded) and name the reason.
        show, why = _run_scan(["bluetoothctl", "show"], timeout=self.PREFLIGHT_S, worker=self)
        if self._stop:
            return None
        if show is None:
            return ("bluetoothd is not answering" if why.startswith("timed out")
                    else "bluetoothctl show: %s" % why)
        low = show.lower()
        if "no default controller" in low or "controller" not in low:
            return "no Bluetooth adapter"
        if "powered: no" in low:
            return "adapter is powered off (bluetoothctl power on)"
        out, _why = _run_scan(["bluetoothctl", "devices"], timeout=self.PREFLIGHT_S, worker=self)
        if self._stop:
            return None
        names = blescan.parse_bluetoothctl_devices(out or "")
        try:
            proc = subprocess.Popen(blescan.bluetoothctl_scan_argv(self.WINDOW_S),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, text=True, errors="replace",
                                    start_new_session=True)
        except OSError as e:
            return "bluetoothctl: %s" % e
        lines, lock = [], threading.Lock()

        def reader():
            for ln in proc.stdout:
                with lock:
                    lines.append(ln)
        th = threading.Thread(target=reader, daemon=True)
        th.start()
        started, fail, heard = False, None, 0
        t0 = time.monotonic()

        def drain():
            nonlocal started, fail, heard
            with lock:
                got, lines[:] = list(lines), []
            touched = set()
            for ln in got:
                ev = blescan.parse_bluetoothctl_line(ln)
                if ev is None:
                    continue
                if ev[0] == "+":
                    started = True
                    continue
                if ev[0] == "!":
                    fail = fail or ev[1]
                    continue
                addr, f = ev
                if f.get("new") and not started:
                    if f.get("name"):              # a cached device listed at start-up: a name,
                        names[addr] = f["name"]    # not a sighting
                    continue
                if not (f.get("new") or "rssi" in f or "mfr" in f or "uuid" in f):
                    if f.get("name"):
                        names[addr] = f["name"]
                    continue
                touched.add(self._merge(addr, f.get("name") or names.get(addr), f.get("rssi"),
                                        [f["uuid"]] if "uuid" in f else (),
                                        [f["mfr"]] if "mfr" in f else ()))
            heard += len(touched)
            return touched
        try:
            while proc.poll() is None and not self._window_over(t0):
                self.sleep(self.EMIT_MS)
                self._emit(drain())
                if fail:
                    break
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, 15)
                except OSError:
                    pass
                try:
                    proc.wait(2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, 9)
                    except OSError:
                        pass
                    proc.wait(1)
            th.join(1)
        self._emit(drain())
        if fail:
            return fail
        if proc.returncode not in (0, -15, None) and not started and not heard:
            return "bluetoothctl exit %d" % proc.returncode
        if not (self._stop or self._paused or heard) and \
                time.monotonic() - t0 < self.MIN_WINDOW_S:
            return "bluetoothctl exited at once (exit %s)" % proc.returncode     # N6
        return None

    def step(self):
        import blescan
        if self.demo:
            self.row.emit({"devs": _demo_ble(blescan), "demo": True, "backend": "demo"})
            return
        if _offscreen():
            self.status.emit({"standby": True, "sdr": {"text": "BLE STANDBY — offline",
                                                       "ok": False}})
            self._stop = True            # tests / PALISADE_OFFLINE never open an adapter
            return
        self.backend = self.backend_available()
        if self.backend is None:
            self.status.emit({"standby": True, "sdr": {"text": self._no_feed_text(),
                                                       "ok": False}})
            self.sleep(self.RETRY_MS)
            return
        t_step = time.monotonic()
        why = self._scan_bleak() if self.backend == "bleak" else None
        if why and why.startswith("bleak import failed") and shutil.which("bluetoothctl"):
            self.backend = "bluetoothctl"
            why = None
        if self.backend == "bluetoothctl":
            why = self._scan_bluetoothctl()
        if why and not self._stop:
            self.status.emit({"standby": True, "scan_failed": why,
                              "sdr": {"text": "BLE SCAN FAILED — %s" % why, "ok": False}})
            self.sleep(self.RETRY_MS)
        elif not why and not (self._stop or self._paused) and \
                time.monotonic() - t_step < self.MIN_WINDOW_S:
            self.sleep(self.RETRY_MS)          # N6: a window that ended at once never storms


class DetectorWorker(Worker):
    """COUNTER detectors (bugsweep / jammer / imsicatch / gnss): receive-only. Live needs a feed
    (SDR sweep / modem / gpsd); with none it reports honest standby. Demo synthesises a feed, runs
    the real detector AS-IS, and raises alerts. NO TX / jam / attack path anywhere."""

    LEARN_SAMPLES = 4          # samples a detector takes to learn its baseline (LEARNING)
    # E4/H1: what each detector would need — and the plain fact that the live feed is not wired
    FEEDS = {"bugsweep": "an rtl_power sweep", "jammer": "an rtl_power sweep",
             "imsicatch": "a cellular modem cell feed", "gnss": "gpsd satellite C/N0"}

    def __init__(self, demo=False, kind="jammer", parent=None):
        super().__init__(demo=demo, interval_ms=1500, parent=parent)
        self.kind = kind
        self._det = None
        self._n = 0

    def offline_reason(self):
        return ("NOT IMPLEMENTED — no live feed is wired (needs %s)"
                % self.FEEDS.get(self.kind, "a feed"))

    def step(self):
        # H1: report per detector on the row signal (SWEEP keeps one fixed row each) — never on
        # the shared status chip, which the other workers overwrite.
        if not self.demo:
            self.row.emit({"kind": self.kind, "state": "offline", "n": 0,
                           "reason": self.offline_reason()})
            self._stop = True              # nothing to poll until a feed is wired
            return
        alert = self._demo_detect()
        self._n += 1
        state = "learning" if self._n <= self.LEARN_SAMPLES else "watching"
        self.row.emit({"kind": self.kind, "n": self._n, "alert": alert, "demo": True,
                       "state": state, "ts": time.time()})

    def _demo_sweep(self, emitter):
        """A synthetic rtl_power-style sweep: list of (freq_hz, power_db), as the detectors expect
        (freqs in the 430 MHz UHF band so bugsweep's suspect-band filter can match)."""
        bins = [(430_000_000 + i * 100_000, -100 + 3 * random.gauss(0, 1)) for i in range(64)]
        if emitter:
            c = random.randint(5, 58)
            for j in range(c, c + 3):
                bins[j] = (bins[j][0], bins[j][1] + random.randint(20, 45))
        return bins

    def _demo_detect(self):
        if self.kind in ("bugsweep", "jammer"):
            mod = __import__(self.kind)
            if self._det is None:
                self._det = (mod.Sweeper() if self.kind == "bugsweep"
                             else mod.JammingDetector())
                for _ in range(4):
                    self._det.learn(self._demo_sweep(False))
            if self.kind == "bugsweep":              # sweep() -> suspect list
                sus = mod.find_suspects(self._det.sweep(self._demo_sweep(random.random() < 0.3)))
                return ("bug", "%d suspect emitter(s)" % len(sus)) if sus else None
            # jammer: feed() returns a sustained-interference alert STRING (or None) directly
            alert = self._det.feed(self._demo_sweep(random.random() < 0.5))
            return ("jam", alert) if alert else None
        if self.kind == "imsicatch":
            import imsicatch
            base = {"cid": 123, "lac": 1, "mcc": 310, "mnc": 260, "rxlevel": -70, "arfcn": 128}
            if self._det is None:
                self._det = imsicatch.IMSICatcherDetector()
                self._det.learn(base)
            obs = dict(base)
            if random.random() < 0.3:
                obs.update(cid=66613, rxlevel=-35, lac=999)       # a suspicious new cell
            flags = self._det.observe(obs)                        # -> [(name, text, severity), ...]
            if flags:
                return ("imsi", "; ".join(f[1] for f in flags))
            return None
        if self.kind == "gnss":
            import gnss
            sats = [{"cn0": 38 + random.randint(-3, 3)} for _ in range(8)]
            if random.random() < 0.2:
                sats = [{"cn0": 12} for _ in range(2)]            # degraded -> jamming suspected
            jammed, _score, reason = gnss.jamming_check(sats)
            return ("gnss", reason) if jammed else None
        return None


# ---- demo data (synthetic, flagged) ----
def _demo_aps():
    secs = ["WPA2-PSK", "WPA3-SAE", "open", "WEP", "WPA2-EAP"]
    names = ["Cafe-Guest", "HOME-5G", "xfinitywifi", "Acme-Corp", "Pixel_1234"]
    out = []
    for i, (n, s) in enumerate(zip(names, secs)):
        out.append({"bssid": "aa:bb:cc:%02x:%02x:%02x" % (i, i * 7 % 256, i * 13 % 256),
                    "ssid": n, "channel": random.choice([1, 6, 11, 36, 44]),
                    "signal": -random.randint(38, 86), "security": s})
    return out


def _demo_ble(blescan):
    out = []
    for i, (n, kind) in enumerate([("Fitbit", "wearable"), ("", "beacon"),
                                   ("Keyboard", "hid"), ("Tile", "tracker"), ("", "unknown")]):
        out.append({"address": "11:22:33:%02x:%02x:%02x" % (i, i * 9 % 256, i * 3 % 256),
                    "name": n or "—", "vendor": blescan.oui_vendor("11:22:33:00:00:00") or "unknown",
                    "kind": kind, "rssi": -random.randint(40, 92)})
    return out


def _ble_row(d):
    import blescan
    rssi = d.get("rssi")
    return {"address": d.get("address", ""), "name": d.get("name") or "—",
            "vendor": d.get("vendor") or "unknown",
            "kind": d.get("kind") or blescan.kind_of(d),
            "rssi": rssi if isinstance(rssi, int) else None}


# ======================= the app =======================

class ReconApp(PalisadeApp):
    TITLE = "RECON"
    LEASE = None          # RECON uses wifi/BLE/network adapters, not the SDR dongle

    SUBTABS = SUBTABS

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._subtab = "WIFI"
        self._open_alerted = set()
        self._ble_published = set()                      # BLE decodes go on the bus once each
        self._chips = {}                                 # sub-tab -> (chip text, state)
        self.wifi_path = None
        self._gated = []                                 # cards to refresh on gate change
        self.evidence = None      # CL3: the ONE chain lives with the engagement (engagement.chain_states)
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    def current_subtab(self):
        return self._subtab

    def switch_subtab(self, name):
        self._switch(name)

    def on_gate_changed(self):
        self._refresh_gate()             # the ENGAGEMENT panel (or PANIC) changed the gate

    # ---- layout ----
    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.stack = QtWidgets.QStackedWidget()
        self._pages = {
            "WIFI": self._wifi_page(), "BLE": self._ble_page(), "NET": self._net_page(),
            "RF": self._rf_page()}
        for t in SUBTABS:
            self.stack.addWidget(self._pages[t])
        lay.addWidget(self.stack, 1)
        self._sync_tabs()
        return body

    # a passive scan page: a feed + a worker started on show
    def _scan_page(self, columns, note):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        bar = ControlBar()
        bar.add_stretch()
        bar.lay.addWidget(micro(note))
        pl.addWidget(bar)
        feed = FeedTable(columns)
        pl.addWidget(feed, 1)
        page._feed = feed
        return page

    def _wifi_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        left = QtWidgets.QVBoxLayout()
        self.wifi_mode = micro(WIFI_MODE[None])
        left.addWidget(self.wifi_mode)
        self.wifi_feed = FeedTable([("ssid", "SSID"), ("bssid", "BSSID"),
                                    ("ch", "CH"), ("sig", "SIG"), ("sec", "SEC")])
        left.addWidget(self.wifi_feed, 1)
        split.addLayout(left, 3)
        import wifipent
        # RX: the engine's further inputs. The interface defaults to one already in monitor mode
        # (PALISADE never switches an adapter into monitor mode: that needs root — a system step)
        self.wifi_iface = QtWidgets.QLineEdit(monitor_iface() or "wlan0mon")
        self.wifi_iface.setMaximumWidth(110)
        self.wifi_chan = QtWidgets.QSpinBox()
        self.wifi_chan.setRange(1, 196)
        self.wifi_chan.setValue(1)
        self.wifi_client = QtWidgets.QLineEdit()
        self.wifi_client.setPlaceholderText("deauth only")
        self.wifi_run = RunPane("WIFIPENT", self._tok)
        # DEAUTH: its own pane, so it can fire while the handshake capture keeps running
        self.wifi_deauth_run = RunPane("DEAUTH", self._tok)
        self.wifi_deauth_run.out.setPlaceholderText(
            "deauth output — gated: engagement, AP + client in scope, TX armed")
        self.wifi_gated = GatedTool("WIFIPENT", "BSSID", wifipent.prepare,
                                    ["deauth", "pmkid", "handshake"], self, self._tok,
                                    "target BSSID (aa:bb:cc:dd:ee:ff)", runner=self.wifi_run,
                                    extra=self._wifi_extra,
                                    fields=[("IFACE", self.wifi_iface), ("CH", self.wifi_chan),
                                            ("CLIENT", self.wifi_client)],
                                    runners={"deauth": self.wifi_deauth_run})
        self._gated.append(self.wifi_gated)
        self.wifi_feed.selected.connect(self._wifi_pick)
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self.wifi_gated)
        # honest hardware state: the onboard CM5 radio has no monitor mode, so capture tools need
        # a USB adapter already in monitor mode (set up outside PALISADE: root, a system step).
        # Re-read when the WIFI tab is shown and before each action (RA-RX L2).
        self.wifi_hw = QtWidgets.QLabel("")
        self._sync_monitor_note()
        self.wifi_hw.setProperty("class", "note")
        self.wifi_hw.setWordWrap(True)
        right.addWidget(self.wifi_hw)
        right.addWidget(self.wifi_run, 1)
        right.addWidget(self.wifi_deauth_run, 1)
        split.addLayout(right, 2)
        pl.addLayout(split, 1)
        return page

    def _sync_monitor_note(self):
        mon = monitor_iface()
        self.wifi_hw.setText(
            ("monitor-mode interface: %s" % mon) if mon else
            "NO MONITOR-MODE INTERFACE — capture/deauth need a USB adapter in monitor mode "
            "(the onboard radio has none) and root or capabilities on the capture tools")
        if mon and not self.wifi_iface.text().strip():
            self.wifi_iface.setText(mon)

    def _net_extra(self, action):
        """RX-fix2: every scan writes its results (nmap -oN) under the suite data dir, so they
        survive the pane; the directory is created only once the gate passed (prepare_run)."""
        import suite
        return {"out": _unique(os.path.join(suite.DATA, "captures"), "nmap-%s" % action,
                               ".txt")}, None

    def _wifi_pick(self, row):
        """A survey row fills the target BSSID and channel (the operator still presses the
        action; the engine still checks the BSSID against the engagement scope)."""
        if row.get("bssid"):
            self.wifi_gated.target.setText(row["bssid"])
        try:
            self.wifi_chan.setValue(int(row.get("ch")))
        except (TypeError, ValueError):
            pass

    def _wifi_extra(self, action):
        """-> (kwargs for wifipent.prepare, error). Captures go under the suite data dir."""
        self._sync_monitor_note()
        iface = self.wifi_iface.text().strip()
        if self._spawner() is None and not os.path.isdir(os.path.join(SYS_NET, iface)):
            return None, ("interface %s is not present — put an adapter in monitor mode first "
                          "(outside PALISADE; needs root)" % (iface or "?"))
        kw = {"iface": iface, "channel": self.wifi_chan.value()}
        if action == "deauth":
            kw["client"] = self.wifi_client.text().strip()
        else:
            import suite
            d = os.path.join(suite.DATA, "captures")       # created only once authorized (L4)
            kw["out"] = _unique(d, "wifi-%s" % action, "")
        return kw, None

    def _ble_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        left = QtWidgets.QVBoxLayout()
        self.ble_mode = micro(BLE_MODE)
        left.addWidget(self.ble_mode)
        self.ble_feed = FeedTable([("name", "NAME"), ("address", "ADDRESS"),
                                   ("vendor", "VENDOR"), ("kind", "KIND"), ("rssi", "dBm")])
        left.addWidget(self.ble_feed, 1)
        split.addLayout(left, 3)
        import blepent
        # only the ops that need no per-characteristic handle/value input (read/write need a handle
        # + value the single target field can't supply, so they'd be dead buttons) — device-only
        self.ble_gated = GatedTool("BLEPENT", "address", blepent.prepare,
                                   ["enum", "characteristics"], self, self._tok,
                                   "target BLE address")
        self._gated.append(self.ble_gated)
        split.addWidget(self.ble_gated, 2)
        pl.addLayout(split, 1)
        return page

    def _net_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        import netpent
        import passaudit
        self.net_run = RunPane("NETPENT", self._tok)
        self.net_gated = GatedTool("NETPENT", "target", netpent.prepare,
                                   ["discover", "portscan", "services"], self, self._tok,
                                   "target IP / host / CIDR", runner=self.net_run,
                                   extra=self._net_extra)
        self.pass_gated = GatedTool("PASSAUDIT", "target", passaudit.prepare,
                                    ["convert", "hashcat", "aircrack"], self, self._tok,
                                    "capture / hash target")
        self._gated += [self.net_gated, self.pass_gated]
        # RX: NETPENT runs (nmap through the executor); PASSAUDIT stays authorize-only (v0.2)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.net_gated, 1)
        top.addWidget(self.pass_gated, 1)
        pl.addLayout(top)
        pl.addWidget(self.net_run, 1)
        return page

    def _rf_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        c = card(2)
        cl = QtWidgets.QVBoxLayout(c)
        cl.addWidget(micro("RFFINGER · RF device fingerprinting (passive)"))
        self.rf_note = QtWidgets.QLabel("No capture feed — fingerprinting runs on IQ from PRISM / a "
                                        "capture file. Standby until a feed is wired on-device.")
        self.rf_note.setProperty("class", "note")
        self.rf_note.setWordWrap(True)
        cl.addWidget(self.rf_note)
        pl.addWidget(c)
        c2 = card(2)
        c2l = QtWidgets.QVBoxLayout(c2)
        c2l.addWidget(micro("SCOUT · site survey (passive)"))
        self.scout_note = QtWidgets.QLabel("Network / Wi-Fi site survey (own-subnet probing only). "
                                           "Device-only; standby on the dev host.")
        self.scout_note.setProperty("class", "note")
        self.scout_note.setWordWrap(True)
        c2l.addWidget(self.scout_note)
        pl.addWidget(c2)
        pl.addStretch(1)
        return page

    def _refresh_gate(self):
        for g in self._gated:
            g.refresh()

    def _spawner(self):
        """None = the executor's real spawner. Offscreen (tests / CI) an authorized tool is never
        spawned — same seam as BENCH; tests substitute a harmless process."""
        if _offscreen():
            def refuse(argv, **kw):
                raise OSError("offscreen: tool not spawned")
            return refuse
        return None

    def prepare_run(self, ticket):
        """After the gate passed, before the spawn: the capture directory a Wi-Fi capture writes
        into (RA-RX L4: never created for a refused action)."""
        import suite
        d = os.path.join(suite.DATA, "captures")
        argv = list(ticket.argv or ())
        if any(str(a).startswith(d + os.sep) for a in argv):
            os.makedirs(d, exist_ok=True)

    def run_panes(self):
        return [self.wifi_run, self.wifi_deauth_run, self.net_run]

    def on_authorized(self, domain, action, target, argv):
        """An active tool produced an authorized command. Announce it; the trail is in the
        ENGAGEMENT panel. NET and Wi-Fi then run it through their RunPane (executor); the other
        cards only show it."""
        eventbus.bus.publish(eventbus.alert(
            "RECON", "authorized %s:%s on %s" % (domain, action, target), severity="warn",
            action=action, target=target))
        self.request.emit("gate_changed", None)

    # ---- sub-tab switching ----
    def _switch(self, tab):
        self._subtab = tab
        if tab == "WIFI" and hasattr(self, "wifi_hw"):
            self._sync_monitor_note()
        self.stack.setCurrentWidget(self._pages[tab])
        self._sync_tabs()
        self._sync_scan_pause()
        text, state = self._chips.get(tab, ("", "neutral"))      # RA-SCAN N10: the chip
        self.set_chip("sdr", text, state=state)                  # belongs to the tab on screen

    def _tab_chip(self, tab, text, state):
        self._chips[tab] = (text, state)
        if self._subtab == tab:
            self.set_chip("sdr", text, state=state)

    def _tab_status(self, tab, st):
        """A scan worker's status: its chip is kept per tab; other keys go to on_status."""
        sdr = st.get("sdr") if isinstance(st.get("sdr"), dict) else None
        if sdr is not None:
            self._tab_chip(tab, sdr.get("text"), sdr.get("state") or
                           ("ok" if sdr.get("ok") else "warn"))
        if tab == "WIFI" and "wifi_path" in st:
            self.wifi_path = st["wifi_path"]
            self.wifi_mode.setText(WIFI_MODE[None])
        rest = {k: v for k, v in st.items() if k != "sdr"}
        if rest:
            self.on_status(rest)

    def set_active(self, active):
        super().set_active(active)
        self._sync_scan_pause()

    def _scan_visible(self, worker):
        tab = "WIFI" if isinstance(worker, WifiScanWorker) else \
            "BLE" if isinstance(worker, BleScanWorker) else None
        return bool(getattr(self, "_active", False)) and tab is not None and self._subtab == tab

    def _sync_scan_pause(self):
        """H3: the Wi-Fi scan runs only while RECON › WIFI is on screen; SCAN-2: the BLE scan
        only while RECON › BLE is (a pause ends the BLE scan window at once)."""
        for w in getattr(self, "_workers", []):
            if isinstance(w, (WifiScanWorker, BleScanWorker)):
                w.pause(not self._scan_visible(w))

    def _sync_tabs(self):
        self._sync_rail()

    # ---- lifecycle: passive scan + counter detector workers ----
    def start(self):
        if self._started:
            return
        super().start()        # base starts make_worker() (None here) + lease (none)
        # RECON runs the passive wifi/ble scans (the detectors moved to SWEEP with CL1)
        self._workers = []
        self._workers.append(self._spawn(WifiScanWorker(demo=self.demo), self._on_wifi))
        self._workers.append(self._spawn(BleScanWorker(demo=self.demo), self._on_ble))
        self._sync_scan_pause()
        self._refresh_gate()

    def standby_tables(self):
        return []                  # WIFI and BLE have separate workers: routed in _spawn

    def _spawn(self, worker, on_row):
        worker.row.connect(on_row)
        table = self.wifi_feed if isinstance(worker, WifiScanWorker) else \
            self.ble_feed if isinstance(worker, BleScanWorker) else None
        if table is not None:
            worker.status.connect(lambda st, t=table: self._feed_standby(t, st))
            tab = "WIFI" if table is self.wifi_feed else "BLE"
            worker.status.connect(lambda st, tab=tab: self._tab_status(tab, st))
        else:
            worker.status.connect(self.on_status)
        worker.error.connect(self.on_error)
        if isinstance(worker, (WifiScanWorker, BleScanWorker)):   # RA-CL4 N30: paused BEFORE
            worker.pause(not self._scan_visible(worker))           # it can step
        worker.start()
        return worker

    def stop(self):
        if self._stopped:
            return
        for pane in (getattr(self, "wifi_run", None), getattr(self, "wifi_deauth_run", None),
                     getattr(self, "net_run", None)):
            if pane is not None and pane.running():
                pane.stop("RECON closed")          # recorded kill + exit, like BENCH
        for w in getattr(self, "_workers", []):
            w.stop()                       # all first: every scan is told at once
        for w in getattr(self, "_workers", []):
            stop_worker(w, self.TITLE)     # RA-SCAN N2: joins, or parks + alerts — never drops
        self._workers = []
        super().stop()

    @staticmethod
    def _feed_standby(table, st):
        """D4: an empty WIFI/BLE table says why — the worker's own reason, never a blank."""
        if st.get("standby") and isinstance(st.get("sdr"), dict):
            table.model.set_rows([])
            table.set_empty("offline", st["sdr"].get("text") or "OFFLINE")

    # ---- passive results -> feed + event bus ----
    def _on_wifi(self, msg):
        aps = msg.get("aps", [])
        live = not msg.get("demo")                     # synthetic demo stays local, off the OPS bus
        path = msg.get("path") or ("demo" if not live else "iw")
        self.wifi_path = path
        self.wifi_mode.setText(WIFI_MODE.get(path, WIFI_MODE[None]))
        rows = []
        for ap in aps:
            if ap.get("signal") is not None:
                sig = "%d dBm" % int(ap["signal"])
            elif ap.get("quality") is not None:          # NetworkManager: 0-100 %, not dBm
                sig = "%d%%" % int(ap["quality"])
            else:
                sig = "—"
            rows.append({"ssid": ap.get("ssid") or "<hidden>", "bssid": ap.get("bssid", ""),
                         "ch": str(ap.get("channel") or "—"), "sig": sig,
                         "sec": ap.get("security", "")})
            if live and ap.get("security") == "open" and \
                    ap.get("bssid") not in self._open_alerted:   # once per BSSID, not per scan
                self._open_alerted.add(ap.get("bssid"))
                eventbus.bus.publish(eventbus.alert(
                    "RECON", "open Wi-Fi: %s" % (ap.get("ssid") or ap.get("bssid")),
                    severity="warn"))
        self.wifi_feed.model.set_rows(rows)
        if live:
            for ap in aps:                             # real scan results on the bus (decode)
                eventbus.bus.publish(eventbus.decode("RECON", "WIFI", ap.get("bssid", ""),
                                                     ap.get("ssid") or "<hidden>"))
        if not rows:
            self.wifi_feed.set_empty("watching", "no access points heard",
                                     "last scan %s" % zulu())
        self._tab_chip("WIFI", "%d AP%s" % (len(rows), " · NM ACTIVE" if path == "nmcli"
                                            else ""), "neutral")

    def _on_ble(self, msg):
        devs = msg.get("devs", [])
        self.ble_feed.model.set_rows([{"name": d["name"], "address": d["address"],
                                       "vendor": d["vendor"], "kind": d["kind"],
                                       "rssi": "—" if d.get("rssi") is None else str(d["rssi"])}
                                      for d in devs])
        if msg.get("backend") and not msg.get("demo"):
            self.ble_mode.setText("%s · %s" % (BLE_MODE, msg["backend"]))
        self._tab_chip("BLE", "%d BLE" % len(devs), "neutral")
        if not devs:
            self.ble_feed.set_empty("watching", "no BLE devices heard yet",
                                    "last update %s" % zulu())
        if not msg.get("demo"):                        # real decodes only on the bus, once each
            for d in devs:
                if d["address"] not in self._ble_published:
                    self._ble_published.add(d["address"])
                    eventbus.bus.publish(eventbus.decode("RECON", "BLE", d["address"], d["name"]))
