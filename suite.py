"""
Shared pieces for the uConsole suite: theme, widgets, RTL-SDR lease, small helpers.
Process utilities come from sky_app (same folder) so every app frees and restores
the dongle the same way.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sky_app as core  # noqa: E402

HOME = os.path.expanduser("~")
CFG = os.path.join(HOME, ".config", "uconsole-suite")
CACHE = os.path.join(HOME, ".cache", "uconsole-suite")
DATA = os.path.join(HOME, ".local", "share", "uconsole-suite")
for _d in (CFG, CACHE, DATA):
    os.makedirs(_d, exist_ok=True)

load_json, save_json, run = core.load_json, core.save_json, core.run

# ------------------------------------------------------------------ theme
import theme as T  # noqa: E402
from theme import (BG, PANEL, ROW, ROW_OFF, ROW_HOT, LINE, LINE_HI, MAPBG, GRID, TXT, MUTED,  # noqa: F401
                   DIM, GREEN, RED, AMBER, AMBER_DIM, BLUE, PURPLE, TRACK)
make_root, btn, set_btn, top_bar, panel, section, entry, brackets = (
    T.make_root, T.btn, T.set_btn, T.top_bar, T.panel, T.section, T.entry, T.brackets)


def typed_value(default, val):
    """A stored value survives only if it has the default's broad type; hand-edited or
    corrupt settings fall back to the default instead of crashing a consumer later."""
    cp = lambda x: json.loads(json.dumps(x))  # noqa: E731
    if isinstance(default, bool):
        return val if isinstance(val, bool) else default
    if isinstance(default, (int, float)):
        return val if isinstance(val, (int, float)) and not isinstance(val, bool) \
            else default
    if isinstance(default, str):
        return val if isinstance(val, str) else default
    if isinstance(default, list):
        return val if isinstance(val, list) else cp(default)
    if isinstance(default, dict):
        if not isinstance(val, dict):
            return cp(default)
        out = dict(val)
        for kk, vv in default.items():
            out[kk] = typed_value(vv, val[kk]) if kk in val else cp(vv)
        return out
    return val


def settings(name, defaults):
    """Per-app settings file in ~/.config/uconsole-suite/<name>.json, merged with
    defaults; values of the wrong type fall back to the default."""
    path = os.path.join(CFG, name + ".json")
    s = load_json(path, None)
    if not isinstance(s, dict):
        s = json.loads(json.dumps(defaults))
        try:
            save_json(path, s)
        except OSError:
            pass   # read-only filesystem: run on defaults, don't refuse to start
    for k, v in defaults.items():
        s[k] = typed_value(v, s[k]) if k in s else json.loads(json.dumps(v))
    return s, path


def pill(parent, F, text="", bg=DIM):
    return T.Tag(parent, F, text, bg)


def bind_wheel(widget, target=None, step=3):
    """Mouse-wheel scrolling for one widget (Linux Button-4/5 and MouseWheel). Scoped to the
    widget, so it never leaks into the shell. target defaults to the widget itself."""
    t = target or widget

    def scroll(d):
        try:
            t.yview_scroll(d, "units")
        except Exception:
            pass
        return "break"
    widget.bind("<Button-4>", lambda e: scroll(-step))
    widget.bind("<Button-5>", lambda e: scroll(step))
    widget.bind("<MouseWheel>", lambda e: scroll(-step if e.delta > 0 else step))


def bind_wheel_tree(widget, target, step=3):
    """Same, but for a canvas whose content is child widgets: bind the whole subtree so the
    wheel works wherever the pointer sits. Call again after rebuilding the content."""
    bind_wheel(widget, target, step)
    for ch in widget.winfo_children():
        bind_wheel_tree(ch, target, step)


def dropdown(parent, F, var, values, width=12, command=None, font="map"):
    """A consistently styled OptionMenu: flat, bordered, dark menu with an accent highlight.
    Returns the widget; callers that rebuild items work on widget['menu'] as usual."""
    import tkinter as tk
    om = (tk.OptionMenu(parent, var, *values, command=command) if command
          else tk.OptionMenu(parent, var, *values))
    om.config(bg=T.SURFACE_2, fg=T.TXT, font=F[font], width=width, bd=0, highlightthickness=1,
              highlightbackground=T.LINE, highlightcolor=T.ACCENT, activebackground=T.HOVER,
              activeforeground=T.TXT, relief="flat", anchor="w", cursor="hand2",
              takefocus=0)
    om["menu"].config(bg=T.SURFACE_2, fg=T.TXT, font=F[font], bd=0, relief="flat",
                      activebackground=T.ACCENT, activeforeground="#ffffff", tearoff=0)
    return om


def header_quit(top, root, F, on_close):
    """A consistent exit in the title bar, visible from every tab. 'Quit' standalone, 'Close'
    inside the Hub (where it closes just this workspace). Pack it before the others on the
    right so it sits just left of the clock."""
    emb = getattr(root, "embedded", False)
    b = btn(top, ("Close" if emb else "Quit"), on_close, F, font="map", padx=10, pady=2,
            kind="quiet")
    b.pack(side="right", padx=(0, 8))
    return b


def bind_quit(root, on_close):
    import tkinter as tk
    if getattr(root, "embedded", False):
        # inside the workstation: Quit closes this workspace; Esc just goes Home and
        # leaves it running (still listening, still logging)
        root.on_close = on_close

        def back(e):
            if isinstance(root.focus_get(), tk.Entry):
                root.focus_set()
                return "break"
            root.go_home()
        root.bind("<Escape>", back)
        return
    root.protocol("WM_DELETE_WINDOW", on_close)

    def esc(e):
        if isinstance(root.focus_get(), tk.Entry):
            root.focus_set()
            return "break"
        on_close()
    root.bind("<Escape>", esc)
    signal.signal(signal.SIGTERM, lambda *a: root.after(0, on_close))
    signal.signal(signal.SIGINT, lambda *a: root.after(0, on_close))

    def tick():
        root.after(250, tick)
    tick()


def errfile(path):
    """Open a stderr capture file, or fall back to /dev/null on a read-only fs."""
    try:
        return open(path, "w")
    except OSError:
        return open(os.devnull, "w")


def run_bg(root, fn, done, poll_ms=60):
    """Run fn() on a worker thread and call done(ok, result_or_exception) back on the Tk
    thread. The worker never touches Tk: the result crosses over through a queue that the
    Tk thread polls. For blocking radio handoffs (stopping readsb can take ~45 s)."""
    import queue as _q
    out = _q.Queue(maxsize=1)

    def work():
        try:
            out.put((True, fn()))
        except Exception as e:      # noqa: BLE001 - handed to the caller
            out.put((False, e))
    threading.Thread(target=work, daemon=True).start()

    def check():
        try:
            ok, val = out.get_nowait()
        except _q.Empty:
            try:
                root.after(poll_ms, check)
            except Exception:
                pass                # window already gone
            return
        done(ok, val)
    root.after(poll_ms, check)


def _lease_lock(lease):
    lk = getattr(lease, "_bg_lock", None)
    if lk is None:
        lk = lease._bg_lock = threading.Lock()
    return lk


# ---- radio manager: one dongle, one holder. When another workspace in this program asks
# for the radio, the current holder is asked to stop first (its own Stop, on the UI
# thread) instead of having its decoder killed underneath it.
_HOLDER = [None]
_RADIO_WATCH = []
AUTOPILOT = {"on": False, "mode": "off", "until": None, "sched": []}    # set by Overwatch, read by the Hub
RADIO_CODE = {"APRS": "APRS", "Sensors": "433", "Balloons": "SNDE", "FM": "FM", "Scanner": "SCAN",
              "Sky airband": "ATC", "RF Explorer": "SPEC", "SDR++": "SDR+", "Signals": "SIG",
              "SSTV": "SSTV", "Weather sat": "WX", "Scout spectrum": "SPEC"}


def radio_code():
    """Four letters for what the one radio is doing right now (AIR = the plane map)."""
    who = radio_holder()
    return RADIO_CODE.get(who, str(who)[:4].upper()) if who else "AIR"


def radio_holder():
    """Name of the app in this program that holds the radio, or None."""
    h = _HOLDER[0]
    return h.who if h is not None and h.held else None


def on_radio_change(fn):
    _RADIO_WATCH.append(fn)


def _radio_changed():
    for fn in list(_RADIO_WATCH):
        try:
            fn(radio_holder())
        except Exception:
            pass


def _yield_radio(to):
    """Ask the current in-process holder to let go. Returns its name if it was asked."""
    prev = _HOLDER[0]
    if prev is None or prev is to or not prev.held:
        return None
    cb = getattr(prev, "on_preempt", None)
    if cb is None:
        return None
    _HOLDER[0] = prev             # (kept so the caller can watch it let go)
    prev.handover = True          # its release must not restart the plane map under `to`
    try:
        cb()
    except Exception as e:
        print("radio handoff from %s: %r" % (prev.who, e), file=sys.stderr)
    return prev.who


def acquire_bg(root, lease, done):
    """lease.acquire() without freezing the window. Handoffs on one lease are serialized,
    so a Stop pressed mid-acquire releases AFTER the acquire lands. On failure the lease
    is released (acquire may already have paused readsb)."""
    prev = _HOLDER[0] if _yield_radio(lease) else None

    def fn():
        # a holder that stops asynchronously (Sky's scanner) needs a moment to exit
        t0 = time.time()
        while prev is not None and prev.held and time.time() - t0 < 10:
            time.sleep(0.1)
        with _lease_lock(lease):
            try:
                return lease.acquire()
            except Exception:
                try:
                    lease.release()
                except Exception:
                    pass
                raise
    def finished(ok, val):
        _radio_changed()
        done(ok, val)
    run_bg(root, fn, finished)


def release_bg(root, lease, done=None):
    """lease.release() without freezing the window. Don't use it while quitting: a daemon
    thread dies with the app and could leave readsb stopped - release synchronously then."""
    def fn():
        with _lease_lock(lease):
            try:
                lease.release()
            except Exception:
                pass

    def finished(ok, val):
        _radio_changed()
        (done or (lambda a, b: None))(ok, val)
    run_bg(root, fn, finished)


def release_now(lease):
    """Synchronous release for quit paths; waits for any in-flight background handoff."""
    with _lease_lock(lease):
        try:
            lease.release()
        except Exception:
            pass


def in_thread(fn, *a):
    threading.Thread(target=fn, args=a, daemon=True).start()


def notify(title, body):
    if shutil.which("notify-send"):
        fire_and_forget(["notify-send", "-a", "uConsole", title, body])


_LOCKS = []


def single_instance(name):
    """Hold an exclusive lock for the life of the process (the handle is kept alive here).
    On a read-only filesystem (SD/NVMe fault, post-brownout) the lock is skipped rather
    than refusing to start: exactly then the field tools must still open."""
    import fcntl
    if T.EMBED is not None and name != "Radio Hub":
        return None                 # a workspace inside the workstation: the shell holds the lock
    try:
        f = open(os.path.join(CACHE, name + ".lock"), "w")
    except OSError as e:
        print("%s: no instance lock (%s) - continuing without it" % (name, e))
        return None
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("%s is already open." % name)
        if shutil.which("wmctrl"):
            subprocess.call(["wmctrl", "-a", name], stderr=subprocess.DEVNULL)
        sys.exit(0)
    _LOCKS.append(f)
    return f


_CHILDREN = []


def reap():
    """Collect finished one-shot children (notify-send, editors, viewers) so they don't linger."""
    for p in list(_CHILDREN):
        if p.poll() is not None:
            _CHILDREN.remove(p)


def fire_and_forget(cmd):
    try:
        p = subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _CHILDREN.append(p)
        return p
    except OSError:
        return None


# ------------------------------------------------------------------ process groups

def spawn(cmd, shell=False, **kw):
    """Start a process in its own group so the whole pipeline can be stopped."""
    return subprocess.Popen(cmd, shell=shell, start_new_session=True,
                            stdin=subprocess.DEVNULL, **kw)


def stop_group(proc, grace=3.0):
    if not proc or proc.poll() is not None:
        return
    for sig, wait in ((signal.SIGINT, grace), (signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


# ------------------------------------------------------------------ RTL-SDR lease

RTL_USERS = ["rtl_fm", "rtl_tcp", "rtl_433", "rtl_power", "rtl_sdr", "sdrpp", "gqrx",
             "satdump", "acarsdec", "dump1090", "dump1090-fa"]
RTL_SERVICES = ["readsb", "dump1090-fa"]
LEASE_STATE = os.path.join(CACHE, "rtl-lease.json")
SKY_CONF = os.path.join(HOME, ".config", "sky-app", "rtl_airband.conf")


def sky_uses_rtl():
    try:
        return 'type = "rtlsdr"' in open(SKY_CONF).read()
    except OSError:
        return False


def rtl_owner():
    """Human-readable owner of the built-in SDR, by looking at what is running."""
    if core.pids_named("rtl_airband") and sky_uses_rtl():
        return "Airband"
    for name, label in (("rtl_fm", "FM radio"), ("satdump", "Weather sat"),
                        ("sdrpp", "SDR++"), ("gqrx", "Gqrx"), ("rtl_tcp", "rtl_tcp"),
                        ("rtl_433", "Signals"), ("acarsdec", "Signals")):
        if core.pids_named(name):
            return label
    if adsb_device() != "hackrf":
        for svc in RTL_SERVICES:
            if core.service_state(svc) == "active":
                return "ADS-B map"
    return "free"


def _lease_state():
    st = load_json(LEASE_STATE, {})
    return st if isinstance(st, dict) else {}


def lease_holder():
    """(owner, pid) of the app that currently holds the built-in SDR, or (None, None)."""
    st = _lease_state()
    pid = st.get("pid")
    if st.get("owner") and pid and core.alive(pid):
        return st["owner"], pid
    return None, None


READSB_DEFAULT = "/etc/default/readsb"


def adsb_device():
    """Which radio readsb is configured to use: 'hackrf' or 'rtlsdr' (from /etc/default/readsb)."""
    if not core.H4M_ENABLED:
        return "rtlsdr"
    try:
        with open(READSB_DEFAULT) as f:
            for line in f:
                line = line.strip()
                if line.startswith("RECEIVER_OPTIONS") and "hackrf" in line.lower():
                    return "hackrf"
    except OSError:
        pass
    return "rtlsdr"


class RtlLease:
    """Take the built-in SDR: pause readsb, close other users. release() puts readsb back.

    One lease file is shared by every app, so whoever paused the plane map hands that
    debt to the next holder; release() only restores readsb if nobody else has taken
    the dongle since. Safe to call acquire()/release() repeatedly."""

    def __init__(self, who, log=print):
        self.who, self.log = who, log
        self.held = False

    @property
    def paused(self):
        return list(_lease_state().get("paused", []))

    def _write(self, **kw):
        st = _lease_state()
        st.update(kw)
        save_json(LEASE_STATE, st)

    def acquire(self, keep=()):
        owner, pid = lease_holder()
        if owner and pid != os.getpid():
            self.log("Taking the built-in SDR from %s" % owner)
        self._write(owner=self.who, pid=os.getpid(), t=time.time())
        self.held = True
        self.handover = False
        _HOLDER[0] = self
        if core.pids_named("rtl_airband") and sky_uses_rtl():
            self.log("Stopping Sky airband (it was using the built-in SDR)")
            core.kill_pids(core.pids_named("rtl_airband"))
        victims = []
        for n in RTL_USERS:
            if n not in keep and n not in RTL_SERVICES:
                victims += [p for p in core.pids_named(n) if p != os.getpid()]
        if victims:
            self.log("Closing other SDR programs: %s" % victims)
            core.kill_pids(victims, grace=2.0)
        if adsb_device() == "hackrf":
            return   # readsb runs on the H4M; the built-in dongle is free, nothing to pause
        # stop the plane-map services; run twice so a service someone just restarted
        # (e.g. Sky noticing its scanner died) is caught as well
        for attempt in range(2):
            for svc in RTL_SERVICES:
                if core.service_state(svc) in ("active", "activating", "reloading",
                                               "deactivating"):
                    self._stop_service(svc)
            if attempt == 0:
                time.sleep(1.2)

    # readsb is Type=simple: `systemctl start` returns while it is still opening the
    # tuner. Stopping it inside that window wedges its USB reader thread, which holds
    # the dongle ~30 s and then aborts - the next app gets usb_claim_interface -6.
    SETTLE_S = 4.0
    STOP_TIMEOUT_S = 45
    EXIT_WAIT_S = 40

    def _uptime(self, svc):
        """Seconds since svc entered 'active', or None if unknown."""
        rc, out = core.run(["systemctl", "show", "-p", "ActiveEnterTimestampMonotonic",
                            "--value", svc], timeout=5)
        try:
            us = int((out or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return None
        if us <= 0:
            return None
        return time.monotonic() - us / 1e6

    def _stop_service(self, svc):
        state = core.service_state(svc)
        if state == "active":
            up = self._uptime(svc)
            if up is not None and up < self.SETTLE_S:
                self.log("Waiting for %s to finish starting" % svc)
                time.sleep(self.SETTLE_S - up)
        # record the debt first: release() must restore it even if the stop fails
        paused = self.paused
        if svc not in paused:
            paused.append(svc)
            self._write(paused=paused)
        if state != "deactivating":
            self.log("Pausing %s (plane map)" % svc)
            rc, out = core.sudo_systemctl("stop", svc, timeout=self.STOP_TIMEOUT_S)
            if rc != 0 and "timed out" not in (out or "").lower() \
                    and "timeout" not in (out or "").lower():
                raise RuntimeError("Couldn't stop %s (%s). Re-run the suite installer." %
                                   (svc, out or "sudo refused"))
        end = time.time() + self.EXIT_WAIT_S
        while time.time() < end and core.service_state(svc) in ("active", "deactivating",
                                                                 "activating", "reloading"):
            time.sleep(0.25)
        if core.service_state(svc) in ("active", "deactivating", "activating", "reloading"):
            raise RuntimeError("%s is still holding the SDR after %ds; try again in a minute"
                               % (svc, self.EXIT_WAIT_S))

    def release(self):
        """Restore the plane map unless another live app now holds the dongle."""
        if getattr(self, "handover", False):
            # we were asked to yield to another workspace: it inherits the paused plane map
            self.handover = False
            self.held = False
            if _HOLDER[0] is self:
                _HOLDER[0] = None
            return
        if _HOLDER[0] is self:
            _HOLDER[0] = None
        owner, pid = lease_holder()
        if owner and (pid != os.getpid() or owner != self.who):
            # someone else has it now - another program, or another workspace in this one
            self.held = False
            return
        for svc in self.paused:
            self.log("Restoring %s (plane map)" % svc)
            rc, out = core.sudo_systemctl("start", svc)
            if rc == 0:
                paused = self.paused
                if svc in paused:
                    paused.remove(svc)
                self._write(paused=paused)
            else:
                self.log("Couldn't restart %s: %s" % (svc, out))
        self._write(owner=None, pid=None)
        self.held = False


# ------------------------------------------------------------------ system readings

def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def battery():
    """(percent, status, volts, watts) from the first battery in /sys/class/power_supply."""
    import glob
    for d in sorted(glob.glob("/sys/class/power_supply/*")):
        if read(os.path.join(d, "type")) != "Battery":
            continue
        cap = read(os.path.join(d, "capacity"))
        st = read(os.path.join(d, "status"), "")
        uv = read(os.path.join(d, "voltage_now"))
        ua = read(os.path.join(d, "current_now"))
        uw = read(os.path.join(d, "power_now"))
        v = int(uv) / 1e6 if uv and uv.lstrip("-").isdigit() else None
        w = None
        if uw and uw.lstrip("-").isdigit():
            w = int(uw) / 1e6
        elif v and ua and ua.lstrip("-").isdigit():
            w = v * int(ua) / 1e6
        return (int(cap) if cap and cap.isdigit() else None), st, v, w
    return None, "", None, None


def cpu_temp():
    t = read("/sys/class/thermal/thermal_zone0/temp")
    return int(t) / 1000 if t and t.lstrip("-").isdigit() else None


# battery percent at/under which, while discharging, we trip low-power mode
LOW_BATT = 15
_THROTTLE_BITS = {0: "under-voltage", 1: "arm frequency capped", 2: "currently throttled",
                  3: "soft temperature limit", 16: "under-voltage has occurred",
                  17: "arm frequency capping has occurred", 18: "throttling has occurred",
                  19: "soft temperature limit has occurred"}


def throttle_flags():
    """Pi throttle/under-voltage state from vcgencmd, or None if unavailable.
    Returns a dict with the raw word, human flags, and the bits that matter most."""
    if not shutil.which("vcgencmd"):
        return None
    rc, out = run(["vcgencmd", "get_throttled"], timeout=3)
    if rc != 0 or "=" not in out:
        return None
    try:
        v = int(out.split("=")[1].strip(), 16)
    except ValueError:
        return None
    return {"raw": v,
            "flags": [txt for bit, txt in _THROTTLE_BITS.items() if v & (1 << bit)],
            "undervolt_now": bool(v & 1),
            "undervolt_seen": bool(v & (1 << 16)),
            "throttled_now": bool(v & (1 << 2)),
            "capped_now": bool(v & (1 << 1))}


def power_status():
    """One dict describing power health: battery, temperature, and Pi throttling.
    Safe on any machine - missing sources read as None."""
    pct, st, v, w = battery()
    th = throttle_flags()
    charging = st in ("Charging", "Full")
    return {"pct": pct, "status": st, "charging": charging, "volts": v, "watts": w,
            "temp": cpu_temp(), "throttle": th,
            "undervolt_now": bool(th and th["undervolt_now"]),
            "undervolt_seen": bool(th and th["undervolt_seen"]),
            "low_batt": pct is not None and pct <= LOW_BATT and not charging}


# ---- device health: the CM5 in a sealed handheld runs hot and the cells sag under load.
# One background poller per program; the UI only ever reads its last snapshot.
HOT_C, COOL_C, WARM_C = 80.0, 72.0, 70.0     # Pi 5 / CM5 starts throttling at 80 degC
CRIT_BATT = 5
HOT_FILE = os.path.join(CACHE, "hot")


def thermal_level(temp, was_hot=False):
    """'ok' | 'warm' | 'hot' | 'unknown'. Hot latches until the CPU is back under COOL_C,
    so work that was paused for heat doesn't flap on and off around the limit."""
    if temp is None:
        return "unknown"
    if temp >= HOT_C or (was_hot and temp > COOL_C):
        return "hot"
    return "warm" if temp >= WARM_C else "ok"


def is_hot(max_age=90):
    """True while the health monitor says the CPU is over the limit. The marker is only
    believed while fresh, so one left behind by a crash can't throttle the apps forever."""
    try:
        return time.time() - os.path.getmtime(HOT_FILE) < max_age
    except OSError:
        return False


def health_events(prev, cur):
    """What changed between two snapshots that the operator should be told about:
    a list of (kind, text). Pure, so it can be tested without hardware."""
    ev = []
    prev = prev or {}
    if cur.get("level") == "hot" and prev.get("level") != "hot":
        ev.append(("hot", "CPU %.0f °C - too hot. Transcription is paused until it cools."
                   % cur["temp"]))
    elif prev.get("level") == "hot" and cur.get("level") in ("ok", "warm"):
        ev.append(("cool", "CPU back to %.0f °C - normal work resumed." % cur["temp"]))
    if cur.get("undervolt_now") and not prev.get("undervolt_now"):
        ev.append(("undervolt", "Under-voltage: the cells or supply can't keep up with the load."))
    pct = cur.get("pct")
    if pct is not None and not cur.get("charging"):
        was = prev.get("pct")
        if pct <= CRIT_BATT and (was is None or was > CRIT_BATT or prev.get("charging")):
            ev.append(("battery", "Battery %d%% - shut down soon or plug in." % pct))
        elif pct <= LOW_BATT and (was is None or was > LOW_BATT or prev.get("charging")):
            ev.append(("battery", "Battery %d%% - low-power mode on." % pct))
    return ev


_HEALTH = {"snap": {}, "thread": None, "watch": [], "lock": threading.Lock()}


def health():
    """Last health snapshot (power_status() plus 'level'); {} until the first poll. Never blocks."""
    return _HEALTH["snap"]


def on_health(fn):
    """fn(kind, text) on each health event. Called on the monitor thread: hand off to the UI."""
    _HEALTH["watch"].append(fn)


def health_poll():
    """One poll: read the sensors, keep the low-power and hot markers in step, fire events."""
    prev = _HEALTH["snap"]
    cur = power_status()
    cur["level"] = thermal_level(cur.get("temp"), prev.get("level") == "hot")
    cur["t"] = time.time()
    try:
        os.makedirs(CACHE, exist_ok=True)
        lp = os.path.join(CACHE, "low_power")
        if cur.get("low_batt"):
            open(lp, "w").close()
        elif os.path.exists(lp) and not os.environ.get("UCS_LOW_POWER"):
            os.remove(lp)
        if cur["level"] == "hot":
            open(HOT_FILE, "w").close()          # touched every poll while hot
        elif os.path.exists(HOT_FILE):
            os.remove(HOT_FILE)
    except OSError:
        pass
    _HEALTH["snap"] = cur
    for kind, text in health_events(prev, cur):
        for fn in list(_HEALTH["watch"]):
            try:
                fn(kind, text)
            except Exception:
                pass
    return cur


def start_health(interval=10.0):
    """Start the one health poller for this program (safe to call from every app)."""
    with _HEALTH["lock"]:
        if _HEALTH["thread"] is not None:
            return
        def loop():
            while True:
                try:
                    health_poll()
                except Exception:
                    pass
                time.sleep(interval)
        _HEALTH["thread"] = threading.Thread(target=loop, daemon=True, name="health")
        _HEALTH["thread"].start()


def low_power():
    """True when apps should cut back (fewer tile workers, slower redraw, pause heavy work).
    Manual override via the UCS_LOW_POWER env or a sentinel file; otherwise auto on low battery
    or while the CPU is over its heat limit."""
    if os.environ.get("UCS_LOW_POWER"):
        return os.environ["UCS_LOW_POWER"] not in ("0", "", "off", "no")
    if os.path.exists(os.path.join(CACHE, "low_power")) or is_hot():
        return True
    snap = health()
    if snap:
        return bool(snap.get("low_batt"))
    try:
        return power_status()["low_batt"]
    except Exception:
        return False


class SessionLog:
    """Append-only, day-stamped event log the whole suite can write to. One JSONL file per
    day under ~/.local/share/uconsole-suite/sessions/. Thread-safe, best-effort: a logging
    failure never interrupts the app. Deduplicates repeats within a short window so a loitering
    contact doesn't spam the log."""
    DIR = os.path.join(HOME, ".local", "share", "uconsole-suite", "sessions")

    def __init__(self, app, dedup_window=300):
        self.app = app
        self.dedup_window = dedup_window
        self._last = {}
        self._lock = threading.Lock()

    def _path(self):
        return os.path.join(self.DIR, time.strftime("%Y-%m-%d") + ".jsonl")

    def event(self, kind, text, **fields):
        """Record one event: kind (e.g. 'contact','alert','acars','sensor'), a human line, extra fields."""
        key = (kind, fields.get("id") or text)
        now = time.time()
        with self._lock:
            if key in self._last and now - self._last[key] < self.dedup_window:
                return
            self._last[key] = now
            # prune the dedup table so it can't grow unbounded
            if len(self._last) > 500:
                cut = now - self.dedup_window
                self._last = {k: t for k, t in self._last.items() if t >= cut}
        rec = {"t": round(now, 1), "ts": time.strftime("%H:%M:%S"), "app": self.app,
               "kind": kind, "text": text}
        rec.update(fields)
        try:
            os.makedirs(self.DIR, exist_ok=True)
            with open(self._path(), "a") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    @classmethod
    def recent(cls, n=300, day=None):
        """Last n events from a given day (default today), oldest first."""
        path = os.path.join(cls.DIR, (day or time.strftime("%Y-%m-%d")) + ".jsonl")
        rows = []
        try:
            with open(path) as f:
                for ln in f:
                    try:
                        rows.append(json.loads(ln))
                    except ValueError:
                        continue
        except OSError:
            return []
        return rows[-n:]

    @classmethod
    def days(cls):
        import glob
        return sorted(os.path.basename(p)[:-6]
                      for p in glob.glob(os.path.join(cls.DIR, "*.jsonl")))


def backup_configs(dest=None):
    """Tar all user settings + accumulated data (records, bingo) to a dated archive.
    Returns the archive path. Re-derivable things (tile cache, recordings) are left out."""
    import tarfile
    import glob
    paths = []
    if os.path.isdir(CFG):
        paths.append(CFG)
    # accumulated data worth keeping, re-derivable caches are not
    for p in (os.path.join(HOME, ".local", "share", "uconsole-suite", "sky_records.json"),
              os.path.join(CACHE, "bingo.json")):
        if os.path.exists(p):
            paths.append(p)
    if dest is None:
        dest = os.path.join(HOME, "uconsole-suite-backup-%s.tar.gz" % time.strftime("%Y%m%d-%H%M"))
    with tarfile.open(dest, "w:gz") as tf:
        for p in paths:
            # store relative to HOME so restore lands in the right place on any user
            tf.add(p, arcname=os.path.relpath(p, HOME))
    n = sum(len(glob.glob(os.path.join(p, "**"), recursive=True)) if os.path.isdir(p) else 1
            for p in paths)
    return dest, n


def restore_configs(archive):
    """Restore a backup_configs archive into HOME. Overwrites existing settings.
    Returns the list of restored member names."""
    import tarfile
    if not os.path.exists(archive):
        raise FileNotFoundError(archive)
    names = []
    with tarfile.open(archive, "r:gz") as tf:
        for m in tf.getmembers():
            # defensive: never let an archive write outside HOME
            target = os.path.normpath(os.path.join(HOME, m.name))
            if not target.startswith(os.path.normpath(HOME) + os.sep):
                continue
            try:
                tf.extract(m, HOME, filter="data")   # 3.12+: blocks traversal/absolute/device files
            except TypeError:
                tf.extract(m, HOME)                   # older Python: our manual check above still guards
            names.append(m.name)
    return names


def power_banner(root, F, interval=4000):
    """A thin strip that shows ONLY when something is wrong with power or heat: under-voltage,
    CPU over its limit, or a nearly empty battery. Reads the health monitor's last snapshot,
    so it never runs a subprocess on the UI thread. Inside the workstation only the shell
    shows it. Returns the frame."""
    import tkinter as tk
    bar = tk.Frame(root, bg=T.BG)          # invisible until a real power/heat condition
    if getattr(root, "embedded", False):
        return bar
    lbl = tk.Label(bar, bg="#4a1f1c", fg="#e8d6d2", font=F["smb"], anchor="w", padx=12, pady=3)
    shown = {"v": None}
    start_health()

    def tick():
        p = health()
        if p.get("undervolt_now"):
            text = ("⚡  UNDER-VOLTAGE - the Pi isn't getting enough power. Use a 5V/5A supply "
                    "and a good cable; check the cell contacts.")
        elif p.get("level") == "hot":
            text = ("▲  CPU %.0f °C - running hot. Transcription is paused; open the case to "
                    "air or stop a heavy app." % p["temp"])
        elif p.get("pct") is not None and p["pct"] <= CRIT_BATT and not p.get("charging"):
            text = "▼  BATTERY %d%% - plug in or shut down cleanly now." % p["pct"]
        else:
            text = None
        if text != shown["v"]:
            shown["v"] = text
            if text:
                lbl.config(text=text)
                lbl.pack(fill="x")
            else:
                lbl.pack_forget()
        try:
            root.after(interval, tick)
        except tk.TclError:
            pass
    tick()
    return bar


def gps_fix(timeout=1.5):
    """One-shot gpsd TPV: dict or None."""
    import socket
    try:
        # 'with' closes the socket on every path, including a recv() timeout/reset
        with socket.create_connection(("127.0.0.1", 2947), timeout=timeout) as s:
            s.sendall(b'?WATCH={"enable":true,"json":true}\n')
            s.settimeout(timeout)
            buf, end = b"", time.time() + timeout
            while time.time() < end:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                for line in buf.split(b"\n"):
                    try:
                        m = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(m, dict):
                        continue
                    mode = m.get("mode", 0)
                    if m.get("class") == "TPV" and isinstance(mode, int) and mode >= 2:
                        return m
    except OSError:
        return None
    return None


def network_status():
    """Wi-Fi SSID + signal, the primary IPv4, and Tailscale (if installed). Cheap: reads /proc and
    one iw/ip call; returns a dict with 'ssid', 'signal' (dBm or None), 'ip', 'tailscale'."""
    import subprocess
    out = {"ssid": None, "signal": None, "ip": None, "tailscale": None, "iface": None}
    try:
        with open("/proc/net/wireless") as f:
            for line in f.read().splitlines()[2:]:
                parts = line.split()
                if len(parts) >= 4:
                    out["iface"] = parts[0].rstrip(":")
                    out["signal"] = int(float(parts[3].rstrip(".")))
                    break
    except (OSError, ValueError):
        pass
    if out["iface"]:
        try:
            r = subprocess.run(["iw", "dev", out["iface"], "link"], capture_output=True, text=True,
                               timeout=2)
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("SSID:"):
                    out["ssid"] = line[5:].strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        r = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True,
                           text=True, timeout=2)
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            if parts[1].startswith("tailscale"):
                out["tailscale"] = out["tailscale"] or parts[3].split("/")[0]
            elif not parts[1].startswith(("docker", "veth", "br-")) and out["ip"] is None:
                out["ip"] = parts[3].split("/")[0]
    except (OSError, subprocess.TimeoutExpired):
        pass
    if out["ip"] is None:   # fallback without iproute2: the address a default route would use
        import socket
        try:
            sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sk.connect(("10.255.255.255", 1))
            out["ip"] = sk.getsockname()[0]
            sk.close()
        except OSError:
            pass
    return out
