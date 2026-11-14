#!/usr/bin/env python3
"""Radio Hub - one launcher for the uConsole suite, and the owner of the built-in SDR."""

import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import suite as S  # noqa: E402

PY = sys.executable or "python3"

TILES = [
    # key, title, subtitle, colour, command
    ("ops", "Ops", "Everything on one map", S.BLUE, [PY, os.path.join(HERE, "ops.py")]),
    ("ow", "Overwatch", "Sky dome + radio autopilot", S.BLUE, [PY, os.path.join(HERE, "overwatch.py")]),
    ("sky", "Sky", "Aircraft + balloons + ATC voice", S.AMBER, [PY, os.path.join(HERE, "sky.py")]),
    ("fm", "FM Radio", "Broadcast + NOAA weather", S.GREEN, [PY, os.path.join(HERE, "fm.py")]),
    ("scanner", "Scanner", "Preset banks + squelch", S.GREEN, [PY, os.path.join(HERE, "scanner.py")]),
    ("rfx", "RF Explorer", "Spectrum + waterfall", S.GREEN, [PY, os.path.join(HERE, "rf_explorer.py")]),
    ("sdrpp", "SDR++", "Free tuning, any band", S.GREEN, None),
    ("wx", "Weather Sats", "Meteor passes + images", S.AMBER, [PY, os.path.join(HERE, "wxsat.py")]),
    ("sensors", "Sensors", "433 MHz neighborhood", S.BLUE, [PY, os.path.join(HERE, "sensors.py")]),
    ("sstv", "SSTV", "Pictures from the ISS", S.BLUE, [PY, os.path.join(HERE, "sstv.py")]),
    ("sonde", "Balloons", "NWS weather balloons", S.BLUE, [PY, os.path.join(HERE, "balloons.py")]),
    ("aprs", "APRS", "Ham position network", S.GREEN, [PY, os.path.join(HERE, "aprs.py")]),
    ("mesh", "Mesh", "Meshtastic messages + map", S.BLUE, [PY, os.path.join(HERE, "mesh_dash.py")]),
    ("field", "Field Status", "GPS, battery, thermals", S.BLUE, [PY, os.path.join(HERE, "field_status.py")]),
    ("ai", "Assistant", "Push-to-talk local AI", S.PURPLE, [PY, os.path.join(HERE, "assistant.py")]),
    ("tx", "Transcripts", "What ATC said, as text", S.PURPLE, [PY, os.path.join(HERE, "transcriber.py"), "--view"]),
    ("signals", "Signals", "ACARS + VDL2 from the air", S.GREEN, [PY, os.path.join(HERE, "signals.py")]),
    ("pager", "Pagers", "POCSAG + FLEX messages", S.GREEN, [PY, os.path.join(HERE, "pager.py")]),
    ("nwr", "Weather Radio", "NOAA SAME / EAS alerts", S.BLUE, [PY, os.path.join(HERE, "nwr.py")]),
    ("ais", "AIS", "Ships on 162 MHz", S.BLUE, [PY, os.path.join(HERE, "ais.py")]),
    ("rds", "RDS", "FM station ID + RadioText", S.GREEN, [PY, os.path.join(HERE, "rds.py")]),
    ("cw", "CW Keyer", "Morse encode/decode + gated TX", S.PURPLE, [PY, os.path.join(HERE, "cw.py")]),
    ("rtty", "RTTY", "Baudot teletype + gated TX", S.PURPLE, [PY, os.path.join(HERE, "rtty.py")]),
    ("freqdb", "Frequency DB", "Who is allocated where", S.DIM, [PY, os.path.join(HERE, "freqdb.py")]),
    ("digi", "Digital Modes", "FT8/WSPR/PSK31 gated launch", S.PURPLE, [PY, os.path.join(HERE, "digimodes.py")]),
    ("iq", "IQ Recorder", "Raw captures + metadata", S.DIM, [PY, os.path.join(HERE, "iqtool.py")]),
    ("class", "Classifier", "Modulation triage", S.DIM, [PY, os.path.join(HERE, "classify.py")]),
    ("roll", "Rolling Code", "Keyfob analysis (no TX)", S.RED, [PY, os.path.join(HERE, "rollcode.py")]),
    ("gnss", "GNSS Monitor", "GPS jamming/spoof watch", S.RED, [PY, os.path.join(HERE, "gnss.py")]),
    ("nf", "Noise Floor", "Band survey + new emitters", S.DIM, [PY, os.path.join(HERE, "noisefloor.py")]),
    ("pass", "Pass Scheduler", "Satellite passes + capture", S.BLUE, [PY, os.path.join(HERE, "passsched.py")]),
    ("wifi", "Wi-Fi Survey", "Passive 802.11 scan", S.RED, [PY, os.path.join(HERE, "wifisurvey.py")]),
    ("jam", "Jamming Detector", "Sustained interference", S.RED, [PY, os.path.join(HERE, "jammer.py")]),
    ("fp", "RF Fingerprint", "Device signatures", S.RED, [PY, os.path.join(HERE, "rffinger.py")]),
    ("imsi", "IMSI-Catcher", "Fake BTS detection", S.RED, [PY, os.path.join(HERE, "imsicatch.py")]),
    ("dx", "DX Cluster", "Propagation spots", S.GREEN, [PY, os.path.join(HERE, "dxcluster.py")]),
    ("remote", "Remote Mode", "Web dashboard + API", S.DIM, [PY, os.path.join(HERE, "headless.py")]),
    ("tpms", "TPMS", "Tire sensors / vehicle ID", S.GREEN, [PY, os.path.join(HERE, "tpms.py")]),
    ("replay", "Replay", "IQ replay (gated)", S.RED, [PY, os.path.join(HERE, "replay.py")]),
    ("ble", "BLE Scanner", "Passive BLE enumerate", S.RED, [PY, os.path.join(HERE, "blescan.py")]),
    ("mlat", "MLAT Feed", "ADS-B multilateration", S.GREEN, [PY, os.path.join(HERE, "mlat.py")]),
    ("pwr", "Power Governor", "Brownout-aware throttling", S.BLUE, [PY, os.path.join(HERE, "powergov.py")]),
    ("tac", "Tactical Map", "All-source fused map", S.AMBER, [PY, os.path.join(HERE, "tacmap.py")]),
    ("df", "Direction Finding", "KrakenSDR DF + geoloc", S.RED, [PY, os.path.join(HERE, "kraken.py")]),
    ("op", "Operator", "Callsign / profile", S.DIM, [PY, os.path.join(HERE, "opprofile.py")]),
    ("test", "Self-Test", "Loopback decoder check", S.DIM, [PY, os.path.join(HERE, "loopback.py")]),
    ("eng", "Engagement", "Scoped assessment authz", S.RED, [PY, os.path.join(HERE, "engagement.py")]),
    ("pm3", "Proxmark3", "RFID/NFC (gated)", S.RED, [PY, os.path.join(HERE, "proxmark.py")]),
    ("wifix", "Wi-Fi Assess", "Handshake/PMKID (gated)", S.RED, [PY, os.path.join(HERE, "wifipent.py")]),
    ("blex", "BLE Assess", "GATT enum/rw (gated)", S.RED, [PY, os.path.join(HERE, "blepent.py")]),
    ("zb", "Zigbee", "802.15.4 (gated)", S.RED, [PY, os.path.join(HERE, "zigbee.py")]),
    ("zw", "Z-Wave", "S0/S2 assess (gated)", S.RED, [PY, os.path.join(HERE, "zwave.py")]),
    ("sweep", "Bug Sweep", "TSCM counter-surveillance", S.AMBER, [PY, os.path.join(HERE, "bugsweep.py")]),
    ("net", "Network Assess", "Host/port/service (gated)", S.RED, [PY, os.path.join(HERE, "netpent.py")]),
    ("pwaudit", "Password Audit", "Crack own handshake (gated)", S.RED, [PY, os.path.join(HERE, "passaudit.py")]),
    ("hid", "USB-HID", "Keystroke inject (gated)", S.RED, [PY, os.path.join(HERE, "usbhid.py")]),
    ("wf", "Waterfall", "Wideband spectrum", S.AMBER, [PY, os.path.join(HERE, "waterfall.py")]),
    ("rfai", "RF Copilot", "Offline AI analyst (qwen)", S.PURPLE, [PY, os.path.join(HERE, "copilot.py")]),
    ("scout", "Scout", "Network + RF site survey", S.RED, [PY, os.path.join(HERE, "scout.py")]),
    ("hw", "Hardware", "Serial · I2C · GPIO bench", S.PURPLE, [PY, os.path.join(HERE, "hwlab.py")]),
    ("dev", "Dev terminal", "BLE · MQTT · SSH", S.PURPLE, [PY, os.path.join(HERE, "devterm.py")]),
    ("fc", "Field computer", "Map · track · almanac", S.BLUE, [PY, os.path.join(HERE, "fieldcomp.py")]),
    ("can", "CAN Bus", "Automotive · sniff/decode (gated TX)", S.RED, [PY, os.path.join(HERE, "canbus.py")]),
    ("bus", "Bus Lab", "UART · JTAG · SPI-flash (gated)", S.RED, [PY, os.path.join(HERE, "buslab.py")]),
    ("flip", "Flipper", "Flipper bridge + NFC relay", S.RED, [PY, os.path.join(HERE, "flipper.py")]),
    ("spec", "Spectrum", "Analyzer · max-hold · markers", S.AMBER, [PY, os.path.join(HERE, "specan.py")]),
]


class Shell:
    """The workstation: one window, every app a workspace inside it.

    Apps are imported and run in this process; their "root" is a Workspace frame
    (theme.workspace_class). The shell owns the event loop, swaps the status bar and the
    body when you change workspace, and sends keyboard shortcuts only to the one in
    front. Workspaces keep running when hidden, so a scan or a decode carries on."""

    MODS = {  # key -> (module, entry function)
        "ops": ("ops", "main"), "sky": ("sky", "main"), "fm": ("fm", "main"),
        "scanner": ("scanner", "main"), "rfx": ("rf_explorer", "main"), "wx": ("wxsat", "main"),
        "sensors": ("sensors", "main"), "sstv": ("sstv", "main"), "sonde": ("balloons", "main"),
        "aprs": ("aprs", "main"), "mesh": ("mesh_dash", "main"),
        "field": ("field_status", "main"), "ai": ("assistant", "main"),
        "tx": ("transcriber", "viewer"), "signals": ("signals", "main"), "pager": ("pager", "main"), "nwr": ("nwr", "main"), "ais": ("ais", "main"), "rds": ("rds", "main"), "cw": ("cw", "main"), "rtty": ("rtty", "main"), "freqdb": ("freqdb", "main"), "digi": ("digimodes", "main"), "iq": ("iqtool", "main"), "class": ("classify", "main"), "roll": ("rollcode", "main"), "gnss": ("gnss", "main"), "nf": ("noisefloor", "main"), "pass": ("passsched", "main"), "wifi": ("wifisurvey", "main"), "jam": ("jammer", "main"), "fp": ("rffinger", "main"), "imsi": ("imsicatch", "main"), "dx": ("dxcluster", "main"), "remote": ("headless", "main"), "tpms": ("tpms", "main"), "replay": ("replay", "main"), "ble": ("blescan", "main"), "mlat": ("mlat", "main"), "pwr": ("powergov", "main"), "tac": ("tacmap", "main"), "df": ("kraken", "main"), "op": ("opprofile", "main"), "test": ("loopback", "main"), "eng": ("engagement", "main"), "pm3": ("proxmark", "main"), "wifix": ("wifipent", "main"), "blex": ("blepent", "main"), "zb": ("zigbee", "main"), "zw": ("zwave", "main"), "sweep": ("bugsweep", "main"), "net": ("netpent", "main"), "pwaudit": ("passaudit", "main"), "hid": ("usbhid", "main"), "wf": ("waterfall", "main"), "rfai": ("copilot", "main"), "can": ("canbus", "main"), "bus": ("buslab", "main"), "flip": ("flipper", "main"), "spec": ("specan", "main"),
        "scout": ("scout", "main"), "ow": ("overwatch", "main"),
        "hw": ("hwlab", "main"), "dev": ("devterm", "main"), "fc": ("fieldcomp", "main"),
    }
    PASS = ("--demo",)            # shell flags every workspace inherits

    def __init__(self, root, F, barhost, host):
        self.root, self.F, self.barhost, self.host = root, F, barhost, host
        self.ws = {}
        self.order = []           # most recently shown last
        self.active = None
        self.routed = set()
        self.pending = None
        self.modal = False        # command palette open: shortcuts off
        self.closing = False      # window going away: no more layout work
        self.on_change = lambda: None
        self.on_notify = lambda text, src: None

    # ---- shortcuts
    def route(self, seq):
        if seq not in self.routed:
            self.routed.add(seq)
            self.root.bind(seq, lambda e, q=seq: self.dispatch(q, e))

    def dispatch(self, seq, e):
        if self.modal:
            return None
        w = self.ws.get(self.active)
        fn = w.keys.get(seq) if w else None
        if fn is None:
            return None
        if len(seq) == 1 or seq == "<space>":
            import tkinter as tk
            if isinstance(self.root.focus_get(), (tk.Entry, tk.Text)) and \
                    str(self.root.focus_get().cget("state")) == "normal":
                return None       # typing in a field: plain-letter shortcuts stay quiet
        return fn(e)

    # ---- workspaces
    def new_workspace(self, title, key=None):
        key = key or self.pending or title
        w = S.T.workspace_class()(self, self.host, key, title)
        self.ws[key] = w
        return w

    def show(self, key):
        w = self.ws.get(key)
        if w is None or not w.alive:
            return False
        cur = self.ws.get(self.active)
        if cur is not None and cur is not w:
            cur.pack_forget()
            if cur.bar is not None:
                cur.bar.pack_forget()
        if w.bar is not None:
            w.bar.pack(fill="x")
        w.pack(fill="both", expand=True)
        self.active = key
        if key in self.order:
            self.order.remove(key)
        self.order.append(key)
        w.focus_set()
        self.on_change()
        return True

    def open(self, key, args=(), show=True):
        """Open (or bring forward) a workspace. Returns an error string, or None."""
        if key in self.ws:
            if show:
                self.show(key)
            return None
        mod, entry = self.MODS[key]
        import importlib
        import traceback
        old = sys.argv
        sys.argv = [mod + ".py"] + list(args) + [a for a in old[1:] if a in self.PASS]
        self.pending = key
        err = None
        try:
            getattr(importlib.import_module(mod), entry)()
        except SystemExit:
            pass
        except Exception as e:          # one app failing must not take the window down
            err = "%s failed to open: %s" % (key, str(e)[:80])
            try:
                with S.errfile(os.path.join(S.CACHE, key + ".err")) as fh:
                    traceback.print_exc(file=fh)
            except Exception:
                traceback.print_exc()
            w = self.ws.get(key)
            if w is not None:
                w.destroy()
        finally:
            sys.argv = old
            self.pending = None
        if err is None and key not in self.ws:
            err = "%s did not open" % key
        if err is None and show:
            self.show(key)
        self.on_change()
        return err

    def closed(self, w):
        """A workspace destroyed itself (its Quit button, or close())."""
        if self.closing:
            return
        if self.ws.get(w.key) is w:
            del self.ws[w.key]
        if w.key in self.order:
            self.order.remove(w.key)
        if self.active == w.key:
            self.active = None
            self.show(self.order[-1] if self.order and self.order[-1] in self.ws else "home")
        self.on_change()

    def close(self, key):
        w = self.ws.get(key)
        if w is None or key == "home":
            return
        try:
            (w.on_close or w.destroy)()   # the app's own shutdown: stop radio, save, destroy
        except Exception as e:
            print("close %s: %r" % (key, e), file=sys.stderr)
        if w.alive:
            w.destroy()

    def close_all(self, wait_s=45):
        """Close every workspace, then wait for the radio to be given back. Sky stops its
        scanner on a worker thread; exiting before that finishes would leave the plane map
        (readsb) stopped."""
        for key in [k for k in list(self.ws) if k != "home"]:
            self.close(key)
        t0 = time.time()
        while S.radio_holder() and time.time() - t0 < wait_s:
            time.sleep(0.1)
        return S.radio_holder() is None

    def cycle(self):
        keys = ["home"] + [k for k in self.ws if k != "home"]
        if len(keys) > 1:
            self.show(keys[(keys.index(self.active) + 1) % len(keys)] if self.active in keys
                      else "home")

    def notify(self, text, src="ops"):
        self.on_notify(text, src)


def read_jsonl(path, n, max_bytes=400_000):
    """Last n records, reading only the tail of the file."""
    import json
    out = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            chunk = f.read().decode("utf-8", "replace")
        lines = chunk.split("\n")
        if size > max_bytes:
            lines = lines[1:]  # first line may be partial
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def main():
    # Auto-load any drop-in plugins (Phase 3e) before the UI is built, so they appear like any
    # other module. Guarded: a bad plugin can never stop the hub from starting.
    try:
        import plugins as _plugins
        _found = _plugins.discover(os.path.join(HERE, "plugins"))
        if _found:
            added, _ = _plugins.register_into(Shell.MODS, _found)
            if added:
                print("plugins loaded: " + ", ".join(added), file=sys.stderr)
    except Exception as _e:        # never let plugin loading break startup
        print("plugin load skipped: %r" % _e, file=sys.stderr)

    S.single_instance("Sentry")
    root, F = S.make_root("Sentry")
    import tkinter as tk

    T = S.T
    S.power_banner(root, F).pack(side="top", fill="x")
    barhost = tk.Frame(root, bg=T.BG)        # one status bar; each workspace supplies its own
    barhost.pack(side="top", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="top", fill="x")

    # ---- layout: nav rail (every app, grouped) | dashboard (what's happening now)
    foot = tk.Frame(root, bg=T.BG)
    foot.pack(side="bottom", fill="x")
    footsep = tk.Frame(root, bg=S.LINE, height=1)
    footsep.pack(side="bottom", fill="x")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    host = tk.Frame(body, bg=S.BG)           # workspaces live here
    shell = Shell(root, F, barhost, host)
    T.EMBED = shell
    home = shell.new_workspace("Sentry", key="home")
    top = S.top_bar(home, F, "Sentry")
    # RX status: receive-only, right of the wordmark (green dot + RX), clock stays far right
    rx = tk.Frame(top, bg=top["bg"])
    rx.pack(side="left", padx=(T.px(10), 0))
    tk.Canvas(rx, width=T.px(7), height=T.px(7), bg=top["bg"], highlightthickness=0).pack(
        side="left", pady=T.px(3))
    _rxdot = rx.winfo_children()[0]
    _rxdot.create_oval(1, 1, T.px(7) - 1, T.px(7) - 1, fill=S.GREEN, outline="")
    tk.Label(rx, text="RX", font=F["lbl"], fg=T.TXT_2, bg=top["bg"]).pack(side="left",
                                                                          padx=(T.px(4), 0))
    sdr_pill = S.pill(top, F, "SDR")
    h4m_pill = S.pill(top, F, "H4M")
    if not S.core.H4M_ENABLED:
        h4m_pill.f.pack_forget()
    # who has the radio, the moment it changes hands
    def radio_changed(who):                  # may be called from a worker: hand to the UI
        ui_q.put(lambda: (sdr_pill.config(text="SDR " + (who or "idle"),
                                          bg=S.GREEN if who else S.DIM), mark_running()))
    S.on_radio_change(radio_changed)
    gps_pill = S.pill(top, F, "GPS")
    mesh_pill = S.pill(top, F, "Mesh")
    mini = tk.Frame(body, bg=T.SURFACE, width=T.px(34))     # icon rail, shown in a workspace
    mini.pack_propagate(False)
    railw = tk.Frame(body, bg=T.SURFACE, width=T.px(205))   # full rail, shown at Home
    railw.pack(side="left", fill="y")
    railw.pack_propagate(False)
    railsep = tk.Frame(body, bg=S.LINE, width=1)
    railsep.pack(side="left", fill="y")
    gwrap = tk.Canvas(railw, bg=T.SURFACE, highlightthickness=0)
    gwrap.pack(fill="both", expand=True)
    grid = tk.Frame(gwrap, bg=T.SURFACE)   # the rail's contents; scrolls when taller
    gwin = gwrap.create_window(0, 0, window=grid, anchor="nw")

    def _gsync(e=None):
        gwrap.config(scrollregion=(0, 0, 0, grid.winfo_reqheight()))
    grid.bind("<Configure>", _gsync)
    gwrap.bind("<Configure>", lambda e: (gwrap.itemconfig(gwin, width=e.width), _gsync()))

    def _gscroll(d):
        if grid.winfo_reqheight() > gwrap.winfo_height():
            gwrap.yview_scroll(d, "units")
    home.bind("<Button-4>", lambda e: _gscroll(-3))
    home.bind("<Button-5>", lambda e: _gscroll(3))
    home.bind("<MouseWheel>", lambda e: _gscroll(-3 if e.delta > 0 else 3))
    home.bind("<Down>", lambda e: _gscroll(3))
    home.bind("<Up>", lambda e: _gscroll(-3))
    home.bind("<Next>", lambda e: _gscroll(12))
    home.bind("<Prior>", lambda e: _gscroll(-12))

    host.pack(side="left", fill="both", expand=True)
    dash = tk.Frame(home, bg=S.BG)
    dash.pack(fill="both", expand=True, padx=T.px(12), pady=T.px(10))

    def card(parent, title, right=""):
        f = tk.Frame(parent, bg=T.SURFACE, highlightthickness=1, highlightbackground=S.LINE)
        h = tk.Frame(f, bg=T.SURFACE)
        h.pack(fill="x", padx=T.px(10), pady=(T.px(7), T.px(3)))
        tk.Label(h, text=T.spaced(title), font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE).pack(
            side="left")
        r = tk.Label(h, text=right, font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
        r.pack(side="right")
        f.right = r
        inner = tk.Frame(f, bg=T.SURFACE)
        inner.pack(fill="both", expand=True, padx=T.px(10), pady=(0, T.px(8)))
        f.inner = inner
        return f

    # KPI strip
    kpis = tk.Frame(dash, bg=S.BG)
    kpis.pack(fill="x")
    kpi = {}
    for i, (key, title, target) in enumerate((("air", "Aircraft", "ops"),
                                              ("aprs", "APRS · 24 h", "aprs"),
                                              ("sensors", "Sensors", "sensors"),
                                              ("sonde", "Balloons", "sonde"),
                                              ("mesh", "Mesh nodes", "mesh"))):
        kpis.columnconfigure(i, weight=1, uniform="k")
        c = card(kpis, title)
        c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else T.px(8), 0))
        v = tk.Label(c.inner, text="—", font=F["data"], fg=T.TXT, bg=T.SURFACE, anchor="w")
        v.pack(fill="x")
        sub = tk.Label(c.inner, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w")
        sub.pack(fill="x")
        kpi[key] = (v, sub)
        for wdg in (c, c.inner, v, sub):
            wdg.config(cursor="hand2")
            wdg.bind("<Button-1>", lambda e, t=target: do_action(("launch", t)))
            wdg.bind("<Enter>", lambda e, cc=c: cc.config(highlightbackground=T.ACCENT))
            wdg.bind("<Leave>", lambda e, cc=c: cc.config(highlightbackground=S.LINE))
    # the one radio: who has it now and, with Autopilot on, where it goes next
    radio_cv = tk.Canvas(dash, bg=T.SURFACE, height=T.px(30), highlightthickness=1,
                         highlightbackground=S.LINE, cursor="hand2")
    radio_cv.pack(fill="x", pady=(T.px(8), 0))
    radio_cv.bind("<Button-1>", lambda e: do_action(("launch", "ow")))
    radio_cv.bind("<Enter>", lambda e: radio_cv.config(highlightbackground=T.ACCENT))
    radio_cv.bind("<Leave>", lambda e: radio_cv.config(highlightbackground=S.LINE))

    def draw_radio():
        c = radio_cv
        c.delete("all")
        w, h = max(c.winfo_width(), 200), c.winfo_height()
        mid = h / 2
        c.create_text(T.px(10), mid, anchor="w", font=F["lbl"], fill=T.TXT_3, text=T.spaced("Radio"))
        who = S.radio_holder()
        c.create_text(T.px(72), mid, anchor="w", font=F["smb"], fill=T.TXT if who else T.TXT_2,
                      text=who or "Plane map")
        ap = S.AUTOPILOT
        x0 = T.px(215)
        if not ap["on"]:
            c.create_text(x0, mid, anchor="w", font=F["map"], fill=T.TXT_3,
                          text="Autopilot off  ·  Overwatch can share it between the apps for you")
            return
        c.create_text(x0, mid, anchor="w", font=F["lbl"], fill=T.ACCENT, text=T.spaced("Autopilot"))
        sched = ap.get("sched") or []
        x0 += T.px(100)
        if not sched:
            c.create_text(x0, mid, anchor="w", font=F["map"], fill=T.TXT_2,
                          text={"rest": "standing down (heat or battery)",
                                "yield": "yours for now - resumes when the radio is free"}.get(
                                    ap["mode"], ""))
            return
        now = time.time()
        span, x1 = 30 * 60.0, w - T.px(48)
        shade = {"air": T.LINE, "aprs": T.FILL, "sensors": T.LINE_HI, "sonde": T.NOTE}
        short = {"air": "AIR", "aprs": "APRS", "sensors": "433", "sonde": "SONDE"}
        for mode, a, b in sched:
            xa = x0 + max(0.0, a - now) / span * (x1 - x0)
            xb = x0 + min(span, b - now) / span * (x1 - x0)
            if xb <= xa + 1:
                continue
            c.create_rectangle(xa, T.px(7), xb - 1, h - T.px(7), fill=shade.get(mode, T.LINE),
                               outline="")
            if xb - xa > T.px(30):
                c.create_text(xa + 4, mid, anchor="w", font=F["lbl"], text=short.get(mode, ""),
                              fill=T.BG if mode == "sonde" else T.TXT)
        c.create_text(w - T.px(8), mid, anchor="e", font=F["lbl"], fill=T.TXT_3, text="+30m")
    radio_cv.bind("<Configure>", lambda e: draw_radio())

    lower = tk.Frame(dash, bg=S.BG)
    lower.pack(fill="both", expand=True, pady=(T.px(8), 0))
    lower.columnconfigure(0, weight=3, uniform="l")
    lower.columnconfigure(1, weight=2, uniform="l")
    lower.rowconfigure(0, weight=1)
    act = card(lower, "Activity", "today")
    act.grid(row=0, column=0, sticky="nsew")
    act_txt = tk.Text(act.inner, bg=T.SURFACE, fg=T.TXT_2, font=F["map"], bd=0,
                      highlightthickness=0, wrap="word", state="disabled", cursor="arrow")
    act_txt.tag_config("t", foreground=T.TXT_3)
    act_txt.tag_config("app", foreground=T.ACCENT)
    act_txt.tag_config("alert", foreground=T.ALERT)
    act_txt.pack(fill="both", expand=True)
    sysc = card(lower, "System")
    sysc.grid(row=0, column=1, sticky="nsew", padx=(T.px(8), 0))
    sysrows = {}
    for r_, key in enumerate(("Radio", "Position", "Network", "Battery", "Power",
                              "CPU", "Meshtastic", "Assistant", "Next balloon")):
        tk.Label(sysc.inner, text=key, font=F["map"], fg=T.TXT_3, bg=T.SURFACE,
                 anchor="w").grid(row=r_, column=0, sticky="w", pady=1)
        v = tk.Label(sysc.inner, text="—", font=F["map"], fg=T.TXT_2, bg=T.SURFACE, anchor="w")
        v.grid(row=r_, column=1, sticky="w", padx=(T.px(10), 0))
        sysrows[key] = v

    def set_scale(d):
        ui = T.load_ui()
        ui["scale"] = round(max(0.8, min(2.5, ui["scale"] + d)), 2)
        T.save_ui(ui)
        # restart the Hub so the new size applies; other apps pick it up next time they open
        handoff_sdrpp()
        shell.close_all()
        shell.closing = True
        root.destroy()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    for txt, d in (("A+", 0.1), ("A−", -0.1)):
        S.btn(foot, txt, lambda d=d: set_scale(d), F, font="map", padx=8, pady=1,
              kind="quiet").pack(side="right")

    def toggle_night():
        ui = T.load_ui()
        ui["night"] = not ui.get("night")
        T.save_ui(ui)
        handoff_sdrpp()
        shell.close_all()
        shell.closing = True
        root.destroy()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    nb = S.btn(foot, "Night", toggle_night, F, font="map", padx=8, pady=1, kind="quiet")
    nb.config(fg=T.ACCENT if T.NIGHT else T.TXT_3)
    nb.pack(side="right", padx=(0, 10))

    def field_mode():
        """One tap when heading out: Sky listening with radar on, Field Status recording a track."""
        opened = []
        for key, args in (("field", ["--track"]), ("sky", ["--listen", "--radar"])):
            if key in shell.ws:
                continue
            if shell.open(key, args, show=False) is None:
                opened.append(key)
        shell.show("sky")
        hr = time.localtime().tm_hour
        night_hint = "  Tap Night for the red palette." if (hr >= 19 or hr < 6) and not T.NIGHT else ""
        msg.config(text=("Field mode: Sky listening + radar, Field Status recording a track." if opened
                         else "Field mode apps are already open.") + night_hint)

    def overwatch():
        """The sky dome. Autopilot stays off until you turn it on there (A): nothing takes
        the radio without being asked."""
        msg.config(text=shell.open("ow") or HINT)

    S.btn(top, "Overwatch", overwatch, F, font="map", padx=10, pady=2, kind="primary").pack(
        side="right", padx=(0, 14))
    fb = S.btn(top, "Field mode", field_mode, F, font="map", padx=10, pady=2, kind="ghost")
    fb.pack(side="right", padx=(0, 6))

    sitrep_busy = [False]

    def sitrep():
        if sitrep_busy[0]:
            return
        sitrep_busy[0] = True
        msg.config(text="Compiling situation report…")

        def work():
            try:
                import sitrep as _sr
                txt, src = _sr.brief(use_llm=True)
                _sr.speak(txt)
                ui_q.put(lambda: msg.config(text=("Sitrep (%s): " % src) + txt[:90] + ("…" if len(txt) > 90 else "")))
            except Exception as ex:
                err = str(ex)[:60]
                ui_q.put(lambda: msg.config(text="Sitrep failed: " + err))
            finally:
                sitrep_busy[0] = False
        S.in_thread(work)

    S.btn(top, "Sitrep", sitrep, F, font="map", padx=10, pady=2, kind="ghost").pack(
        side="right", padx=(0, 6))
    # a visible way out (Ctrl+Q also works, from anywhere): one confirm so it isn't fat-fingered
    quit_armed = [None]

    def disarm_quit():
        quit_armed[0] = None
        T.set_btn(quit_btn, "⏻ Quit", "quiet")

    def quit_clicked():
        if quit_armed[0] is not None:          # second press within the window: go
            on_close()
            return
        T.set_btn(quit_btn, "Quit — sure?", "danger")
        msg.config(text="Press Quit again to shut down Sentry. Any app using the radio is "
                        "stopped and the plane map is restored.")
        quit_armed[0] = root.after(2500, disarm_quit)
    quit_btn = S.btn(top, "⏻ Quit", quit_clicked, F, font="map", padx=10, pady=2, kind="quiet")
    quit_btn.pack(side="right", padx=(0, 6))

    def open_log(_=None):
        win = tk.Toplevel(root, bg=T.SURFACE)
        win.title("Session log")
        win.transient(root)
        win.geometry("%dx%d+%d+%d" % (min(T.px(760), root.winfo_width() - 80),
                                      min(T.px(520), root.winfo_height() - 100),
                                      root.winfo_rootx() + 40, root.winfo_rooty() + 40))
        pad = tk.Frame(win, bg=T.SURFACE, padx=T.px(18), pady=T.px(12))
        pad.pack(fill="both", expand=True)
        txt = tk.Text(pad, bg=T.SURFACE, fg=T.TXT, font=F["map"], bd=0, highlightthickness=0,
                      wrap="word", spacing1=1, state="disabled")
        txt.tag_config("ts", foreground=T.TXT_3)
        txt.tag_config("app", foreground=T.ACCENT, font=F["smb"])
        txt.tag_config("alert", foreground=T.ALERT, font=F["smb"])
        txt.pack(fill="both", expand=True)
        bar = tk.Frame(win, bg=T.SURFACE, padx=T.px(18), pady=T.px(10))
        bar.pack(side="bottom", fill="x")
        info = tk.Label(bar, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE)
        info.pack(side="left")

        def refresh():
            rows = S.SessionLog.recent(400)
            txt.config(state="normal")
            txt.delete("1.0", "end")
            if not rows:
                txt.insert("end", "No events logged today yet.\nSky logs alerts/emergencies; "
                           "Signals logs ACARS and sensors.\n", "ts")
            for r in rows:
                emerg = r.get("kind") in ("hijack", "radio failure", "emergency")
                txt.insert("end", r.get("ts", "") + "  ", "ts")
                txt.insert("end", "%-8s " % r.get("app", ""), "app")
                txt.insert("end", r.get("text", "") + "\n", "alert" if emerg else None)
            txt.config(state="disabled")
            txt.see("end")
            info.config(text="%d events today" % len(rows))
        refresh()
        S.btn(bar, "Refresh", refresh, F, padx=12, pady=4, kind="ghost").pack(side="right", padx=(0, 8))
        S.btn(bar, "Close", win.destroy, F, padx=12, pady=4, kind="quiet").pack(side="right")

    # External SDR/RF apps that ship with DragonOS etc. - launched, not reimplemented.
    # (label, candidate executables). First one found on PATH wins.
    EXTERNAL_TOOLS = [
        ("Gqrx", ["gqrx"]),
        ("SDR++", ["sdrpp", "sdrpp_brown", "sdrpp-brown"]),
        ("SDRangel", ["sdrangel"]),
        ("CubicSDR", ["CubicSDR", "cubicsdr"]),
        ("SatDump (GUI)", ["satdump-ui", "satdump"]),
        ("SDRTrunk", ["sdr-trunk", "sdrtrunk"]),
        ("Kismet", ["kismet"]),
        ("GNU Radio Companion", ["gnuradio-companion"]),
    ]

    def detected_external():
        import shutil
        found = []
        for label, cands in EXTERNAL_TOOLS:
            for exe in cands:
                p = shutil.which(exe)
                if p:
                    found.append((label, p))
                    break
        return found

    def open_external():
        found = detected_external()
        win = tk.Toplevel(root, bg=T.SURFACE)
        win.title("External SDR apps")
        win.transient(root)
        win.geometry("+%d+%d" % (root.winfo_rootx() + 60, root.winfo_rooty() + 60))
        pad = tk.Frame(win, bg=T.SURFACE, padx=T.px(18), pady=T.px(14))
        pad.pack(fill="both", expand=True)
        if not found:
            tk.Label(pad, text="No external SDR apps found on PATH.\n"
                     "(gqrx, SDR++, SDRangel, SatDump, SDRTrunk, Kismet…)",
                     font=F["map"], fg=T.TXT_3, bg=T.SURFACE, justify="left").pack(anchor="w")
        else:
            tk.Label(pad, text="Launches on this screen and uses the SDR directly — "
                     "stop suite radios first to avoid a clash.", font=F["map"], fg=T.TXT_3,
                     bg=T.SURFACE, wraplength=T.px(340), justify="left").pack(anchor="w", pady=(0, 8))
            for label, path in found:
                def launch(p=path, lb=label):
                    win.destroy()
                    try:
                        S.spawn([p])
                        S.notify("Launched", lb)
                    except Exception as e:
                        S.notify("Couldn't launch " + lb, str(e))
                S.btn(pad, label, launch, F, padx=10, pady=5, kind="ghost").pack(fill="x", pady=2)
        S.btn(pad, "Close", win.destroy, F, padx=10, pady=5, kind="quiet").pack(fill="x", pady=(8, 0))

    def open_doctor(security=False):
        import doctor
        import queue as _q
        win = tk.Toplevel(root, bg=T.SURFACE)
        win.title("Security" if security else "Doctor")
        win.transient(root)
        win.geometry("%dx%d+%d+%d" % (min(T.px(760), root.winfo_width() - 80), min(T.px(500), root.winfo_height() - 100),
                                      root.winfo_rootx() + 40, root.winfo_rooty() + 40))
        pad = tk.Frame(win, bg=T.SURFACE, padx=T.px(18), pady=T.px(12))
        pad.pack(fill="both", expand=True)
        txt = tk.Text(pad, bg=T.SURFACE, fg=T.TXT, font=F["sm"], bd=0, highlightthickness=0, wrap="word",
                      spacing1=2, state="disabled")
        txt.tag_config("sec", foreground=T.TXT_3, font=F["lbl"], spacing1=T.px(10))
        txt.tag_config("ok", foreground=T.OK)
        txt.tag_config("fail", foreground=T.ALERT)
        txt.tag_config("info", foreground=T.TXT_3)
        txt.tag_config("name", foreground=T.TXT, font=F["smb"])
        txt.tag_config("fix", foreground=T.ACCENT, font=F["map"], lmargin1=T.px(40), lmargin2=T.px(40))
        txt.tag_config("det", foreground=T.TXT_2, font=F["map"], lmargin1=T.px(40), lmargin2=T.px(40))
        txt.pack(fill="both", expand=True)
        bar = tk.Frame(win, bg=T.SURFACE, padx=T.px(18), pady=T.px(10))
        bar.pack(side="bottom", fill="x")
        summary = tk.Label(bar, text="Running checks…", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE)
        summary.pack(side="left")
        S.btn(bar, "Close", win.destroy, F, padx=12, pady=4, kind="quiet").pack(side="right")
        rq = _q.Queue()
        seen = {"sec": None, "fail": 0, "n": 0}
        runner = doctor.run_security if security else doctor.run_all
        intro = ("Read-only security review of THIS device only - nothing is transmitted or scanned "
                 "off-box.") if security else None
        if intro:
            txt.config(state="normal")
            txt.insert("end", intro + "\n", "info")
            txt.config(state="disabled")

        def worker():
            for item in runner():
                rq.put(item)
            rq.put(None)

        def pump():
            if not win.winfo_exists():
                return
            done = False
            while not rq.empty():
                item = rq.get()
                if item is None:
                    done = True
                    break
                section, name, ok, detail, fix = item
                txt.config(state="normal")
                if section != seen["sec"]:
                    seen["sec"] = section
                    txt.insert("end", T.spaced(section) + "\n", "sec")
                mark, tag = ("●  ", "ok") if ok else (("○  ", "info") if ok is None else ("✕  ", "fail"))
                txt.insert("end", mark, tag)
                txt.insert("end", name + "\n", "name")
                txt.insert("end", detail + "\n", "det")
                if ok is False and fix:
                    txt.insert("end", "fix: " + fix + "\n", "fix")
                    seen["fail"] += 1
                seen["n"] += 1
                txt.config(state="disabled")
                txt.see("end")
            if done:
                summary.config(text="%d checks, %d problem%s" % (seen["n"], seen["fail"],
                                                                  "" if seen["fail"] == 1 else "s"),
                               fg=T.ALERT if seen["fail"] else T.OK)
            else:
                root.after(150, pump)

        S.in_thread(worker)
        pump()

    def do_backup():
        def work():
            try:
                path, n = S.backup_configs()
                S.notify("Backup saved", "%d files -> %s" % (n, os.path.basename(path)))
                out = "Backed up %d files to %s" % (n, path)
            except Exception as e:
                out = "Backup failed: %s" % e
                S.notify("Backup", out)
            # Tk only from the main thread: hand the label update to poll()
            ui_q.put(lambda: msg.config(text=out[:90]))
            print(out)
        S.in_thread(work)

    def open_hub_settings():
        import settings_ui
        ui = T.load_ui()
        schema = [("Appearance", [
            {"key": "scale", "label": "Text size", "type": "float", "min": 0.8, "max": 2.5, "step": 0.1,
             "help": "1.0 = small, 1.4 = default"},
            {"key": "style", "label": "Look", "type": "choice",
             "choices": [("maven", "Workstation (graphite + blue)"), ("classic", "Classic (amber)")]},
            {"key": "night", "label": "Night mode (red palette)", "type": "bool"},
            {"key": "sans", "label": "UI font", "type": "str"},
            {"key": "mono", "label": "Monospace font", "type": "str"},
        ])]

        def on_save(new):
            T.save_ui(new)
            msg.config(text="Appearance saved - restarting the Hub to apply.")
            root.after(600, lambda: (handoff_sdrpp(), shell.close_all(), setattr(shell, "closing", True),
                                     root.destroy(),
                                     os.execv(sys.executable, [sys.executable] + sys.argv)))
        settings_ui.open_settings(root, F, "Hub settings", schema, ui, on_save, width=600, path=T.UI_PATH)
    tk.Label(foot, text="Text %d%%" % round(T.SCALE * 100), font=F["map"], fg=T.TXT_3,
             bg=T.BG).pack(side="right", padx=(0, 6))
    msg = tk.Label(foot, text="", font=F["map"], fg=T.TXT_2, bg=T.BG)
    msg.pack(side="left", padx=12, pady=5)
    procs = {}
    running_lbl = {}
    sdr_lease = [None]
    ui_q = __import__("queue").Queue()
    status_busy = [False]

    def launch(key, cmd):
        if key in Shell.MODS:                 # a workspace inside this window
            if key not in shell.ws:
                msg.config(text="Opening %s…" % dict((t[0], t[1]) for t in TILES)[key])
                root.update_idletasks()
            err = shell.open(key)
            msg.config(text=err or HINT)
            return
        p = procs.get(key)
        if p and p.poll() is None:
            if shutil.which("wmctrl"):
                subprocess.call(["wmctrl", "-a", dict((t[0], t[1]) for t in TILES)[key]],
                                stderr=subprocess.DEVNULL)
            msg.config(text="%s is already open." % dict((t[0], t[1]) for t in TILES)[key])
            return
        if key == "sdrpp":
            return launch_sdrpp()
        if not os.path.exists(cmd[1]):
            msg.config(text="Missing %s - re-run the suite installer." % cmd[1])
            return
        with S.errfile(os.path.join(S.CACHE, key + ".err")) as err:
            procs[key] = subprocess.Popen(cmd, start_new_session=True,
                                          stdout=subprocess.DEVNULL, stderr=err)
        msg.config(text="Opening %s…" % dict((t[0], t[1]) for t in TILES)[key])

    def launch_sdrpp():
        exe = shutil.which("sdrpp")
        if not exe:
            msg.config(text="SDR++ isn't installed (sdrpp not on PATH).")
            return

        def say(m):
            ui_q.put(lambda: msg.config(text=m))

        if sdr_lease[0] is not None:
            # acquire() can take a while (stopping readsb): a second tap must not start a
            # second SDR++ with a second lease
            msg.config(text="SDR++ is already starting…")
            return
        lease = S.RtlLease("SDR++", log=say)
        sdr_lease[0] = lease
        procs.pop("sdrpp", None)    # an exited earlier SDR++; on_close keys off "not yet set"

        def work():
            try:
                lease.acquire()
                p = subprocess.Popen([exe], start_new_session=True, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                procs["sdrpp"] = p
                say("SDR++ open. The plane map returns when you close it.")
                p.wait()
            except Exception as e:
                say("SDR++: %s" % e)
            finally:
                lease.release()
                sdr_lease[0] = None
                say("SDR++ closed. Plane map restored.")
        S.in_thread(work)

    # app launch commands, keyed, from TILES
    CMD = {t[0]: t[4] for t in TILES}

    # grouped layout: (section, colour, [(key, title, subtitle, action)])
    # action is ("launch", key) for an app, or ("call", fn) for a tool
    GROUPS = [
        ("Overview", S.AMBER, [
            ("ops", "Ops", "Everything on one map", ("launch", "ops")),
            ("ow", "Overwatch", "Sky dome + autopilot", ("launch", "ow")),
        ]),
        ("Aircraft", S.AMBER, [
            ("sky", "Sky", "Radar + ATC audio", ("launch", "sky")),
            ("tx", "Transcripts", "ATC as text", ("launch", "tx")),
            ("signals", "Signals", "ACARS + VDL2", ("launch", "signals")),
            ("pager", "Pagers", "POCSAG + FLEX", ("launch", "pager")),
            ("nwr", "Weather Radio", "SAME / EAS alerts", ("launch", "nwr")),
            ("ais", "AIS", "Ships on 162 MHz", ("launch", "ais")),
            ("rds", "RDS", "FM station data", ("launch", "rds")),
            ("cw", "CW Keyer", "Morse + gated TX", ("launch", "cw")),
            ("rtty", "RTTY", "Baudot + gated TX", ("launch", "rtty")),
            ("freqdb", "Frequency DB", "Allocations lookup", ("launch", "freqdb")),
            ("digi", "Digital Modes", "FT8/WSPR/PSK31", ("launch", "digi")),
            ("iq", "IQ Recorder", "Raw IQ + metadata", ("launch", "iq")),
            ("class", "Classifier", "Modulation triage", ("launch", "class")),
            ("roll", "Rolling Code", "Keyfob analysis", ("launch", "roll")),
            ("gnss", "GNSS Monitor", "GPS jam/spoof", ("launch", "gnss")),
            ("nf", "Noise Floor", "Band survey", ("launch", "nf")),
            ("pass", "Pass Scheduler", "Satellite passes", ("launch", "pass")),
            ("wifi", "Wi-Fi Survey", "802.11 scan", ("launch", "wifi")),
            ("jam", "Jamming Detector", "Interference", ("launch", "jam")),
            ("fp", "RF Fingerprint", "Device signatures", ("launch", "fp")),
            ("imsi", "IMSI-Catcher", "Fake BTS", ("launch", "imsi")),
            ("dx", "DX Cluster", "Propagation", ("launch", "dx")),
            ("remote", "Remote Mode", "Web dashboard", ("launch", "remote")),
            ("tpms", "TPMS", "Tire sensors", ("launch", "tpms")),
            ("replay", "Replay", "IQ replay (gated)", ("launch", "replay")),
            ("ble", "BLE Scanner", "BLE enumerate", ("launch", "ble")),
            ("mlat", "MLAT Feed", "Multilateration", ("launch", "mlat")),
            ("pwr", "Power Governor", "Power/thermal", ("launch", "pwr")),
            ("tac", "Tactical Map", "All-source map", ("launch", "tac")),
            ("df", "Direction Finding", "KrakenSDR DF", ("launch", "df")),
            ("op", "Operator", "Callsign / profile", ("launch", "op")),
            ("test", "Self-Test", "Loopback check", ("launch", "test")),
            ("eng", "Engagement", "Assessment authz", ("launch", "eng")),
            ("pm3", "Proxmark3", "RFID/NFC", ("launch", "pm3")),
            ("wifix", "Wi-Fi Assess", "Handshake/PMKID", ("launch", "wifix")),
            ("blex", "BLE Assess", "GATT enum/rw", ("launch", "blex")),
            ("zb", "Zigbee", "802.15.4", ("launch", "zb")),
            ("zw", "Z-Wave", "S0/S2 assess", ("launch", "zw")),
            ("sweep", "Bug Sweep", "TSCM", ("launch", "sweep")),
            ("net", "Network Assess", "Host/port/svc", ("launch", "net")),
            ("pwaudit", "Password Audit", "Handshake audit", ("launch", "pwaudit")),
            ("hid", "USB-HID", "Keystroke inject", ("launch", "hid")),
            ("wf", "Waterfall", "Spectrum", ("launch", "wf")),
            ("rfai", "RF Copilot", "AI analyst", ("launch", "rfai")),
        ]),
        ("Listen", S.GREEN, [
            ("fm", "FM Radio", "Broadcast + NOAA", ("launch", "fm")),
            ("scanner", "Scanner", "Preset banks + squelch", ("launch", "scanner")),
            ("rfx", "RF Explorer", "Spectrum + waterfall", ("launch", "rfx")),
            ("sdrpp", "SDR++", "Free tuning, any band", ("launch", "sdrpp")),
            ("spec", "Spectrum", "Analyzer + markers", ("launch", "spec")),
        ]),
        ("Weather & space", S.BLUE, [
            ("wx", "Weather Sats", "Meteor passes + images", ("launch", "wx")),
            ("sensors", "Sensors", "433 / 315 / 915 MHz", ("launch", "sensors")),
            ("sstv", "SSTV", "Pictures from the ISS", ("launch", "sstv")),
            ("sonde", "Balloons", "Weather balloons", ("launch", "sonde")),
        ]),
        ("Network & field", S.RED, [
            ("hw", "Hardware", "Serial · I2C · GPIO", ("launch", "hw")),
            ("dev", "Dev terminal", "BLE · MQTT · SSH", ("launch", "dev")),
            ("fc", "Field computer", "Map · track · almanac", ("launch", "fc")),
            ("mesh", "Mesh", "Meshtastic messages", ("launch", "mesh")),
            ("scout", "Scout", "Network + RF survey", ("launch", "scout")),
            ("can", "CAN Bus", "Automotive bus", ("launch", "can")),
            ("bus", "Bus Lab", "UART/JTAG/SPI", ("launch", "bus")),
            ("flip", "Flipper", "Bridge + NFC relay", ("launch", "flip")),
            ("field", "Field Status", "GPS, battery, thermals", ("launch", "field")),
            ("aprs", "APRS", "Ham position network", ("launch", "aprs")),
        ]),
        ("Tools", S.DIM, [
            ("doctor", "Doctor", "Full system check", ("call", lambda: open_doctor(False))),
            ("security", "Security", "Exposure + firewall", ("call", lambda: open_doctor(True))),
            ("log", "Session Log", "Today's contacts", ("call", open_log)),
            ("backup", "Backup", "Save a restore file", ("call", do_backup)),
            ("settings", "Settings", "Size, night, fonts", ("call", open_hub_settings)),
            ("external", "External SDR", "gqrx, SatDump…", ("call", open_external)),
            ("ai", "Assistant", "Push-to-talk local AI", ("launch", "ai")),
        ]),
    ]

    hotkeys = []  # (digit, action) for number-key launch, first 10 tiles

    def do_action(action):
        kind, val = action
        if kind == "launch":
            launch(val, CMD.get(val))
        else:
            val()

    HINT = "Ctrl+K jump to anything  ·  Esc back here  ·  Ctrl+W close a workspace  ·  Ctrl+Q quit"
    msg.config(text=HINT)
    ICON = {"ops": "◈", "ow": "◉", "hw": "⎓", "dev": "⌨", "fc": "⊕", "sky": "✈", "tx": "≡", "signals": "⌁", "pager": "✉", "nwr": "⚠", "ais": "⚓", "rds": "♫", "cw": "•−", "rtty": "⇅", "freqdb": "▦", "digi": "◧", "iq": "⎙", "class": "◫", "roll": "⟲", "gnss": "✛", "nf": "▂", "pass": "☄", "wifi": "≋", "jam": "⚡", "fp": "⊚", "imsi": "📶", "dx": "⇌", "remote": "⌂", "tpms": "◉", "replay": "⟳", "ble": "ᛒ", "mlat": "△", "pwr": "⚡", "tac": "⊕", "df": "➤", "op": "☰", "test": "✓", "eng": "⊗", "pm3": "▥", "wifix": "⚔", "blex": "ᛒ", "zb": "⬡", "zw": "〜", "sweep": "⌕", "net": "⇄", "pwaudit": "⚿", "hid": "⌨", "wf": "▒", "rfai": "✦", "fm": "♪", "scanner": "⇆",
            "rfx": "∿", "sdrpp": "⊕", "wx": "◐", "sensors": "◎", "sstv": "▣", "sonde": "○",
            "mesh": "⬡", "scout": "⌖", "field": "⊙", "aprs": "◇", "doctor": "✚",
            "security": "⛨", "log": "☰", "backup": "⇩", "settings": "⚙", "external": "⇱",
            "ai": "✦", "can": "⊞", "bus": "⌗", "flip": "◪", "spec": "⋀"}

    def tile(parent, key, title, sub, col, action, hk):
        f = tk.Frame(parent, bg=T.SURFACE, cursor="hand2")
        bar = tk.Frame(f, bg=T.SURFACE, width=2)
        bar.pack(side="left", fill="y")
        ic = tk.Label(f, text=ICON.get(key, "·"), font=F["map"], fg=T.TXT_3, bg=T.SURFACE,
                      width=2)
        ic.pack(side="left", padx=(T.px(8), T.px(4)), pady=T.px(3))
        t = tk.Label(f, text=title, font=F["sm"], fg=T.TXT, bg=T.SURFACE, anchor="w")
        t.pack(side="left", fill="x", expand=True)
        rl = tk.Label(f, text=hk, font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
        rl.pack(side="right", padx=(0, T.px(8)))
        if key in CMD:        # only app rows get a running indicator
            running_lbl[key] = (rl, hk)
        ws = (f, ic, t, rl)

        def hover(on):
            bgc = T.HOVER if on else T.SURFACE
            for w_ in ws:
                w_.config(bg=bgc)
            bar.config(bg=T.ACCENT if on else T.SURFACE)
            msg.config(text=("%s - %s" % (title, sub)) if on else HINT)
        for w in ws:
            w.bind("<Button-1>", lambda e, a=action: do_action(a))
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
        return f

    for _name, _col, _tiles in GROUPS:
        hdr = tk.Label(grid, text=T.spaced(_name), font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE,
                       anchor="w")
        hdr.pack(fill="x", padx=T.px(10), pady=(T.px(9), T.px(2)))
        for key, title, sub, action in _tiles:
            hk = str((len(hotkeys) + 1) % 10) if len(hotkeys) < 10 else ""
            tile(grid, key, title, sub, _col, action, hk).pack(fill="x")
            if len(hotkeys) < 10:
                hotkeys.append((hk, action))

    for _digit, _action in hotkeys:
        home.bind(_digit, lambda e, a=_action: do_action(a))

    # ---- icon rail (in a workspace): Home + every app, lit when open, accent when in front
    mini_rows = {}

    def mini_item(key, glyph, title, cmd):
        f = tk.Frame(mini, bg=T.SURFACE, cursor="hand2")
        f.pack(fill="x")
        bar_ = tk.Frame(f, bg=T.SURFACE, width=2)
        bar_.pack(side="left", fill="y")
        lb = tk.Label(f, text=glyph, font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
        lb.pack(fill="x", pady=T.px(3))
        for w_ in (f, lb):
            w_.bind("<Button-1>", lambda e: cmd())
            w_.bind("<Enter>", lambda e: (f.config(bg=T.HOVER), lb.config(bg=T.HOVER),
                                          tip.config(text=" %s " % title),
                                          tip.place(x=T.px(38), y=f.winfo_rooty() -
                                                    root.winfo_rooty()), tip.lift()))
            w_.bind("<Leave>", lambda e: (f.config(bg=T.SURFACE), lb.config(bg=T.SURFACE),
                                          tip.place_forget()))
        mini_rows[key] = (bar_, lb)

    tip = tk.Label(root, text="", font=F["map"], fg=T.TXT, bg=T.SURFACE_2, highlightthickness=1,
                   highlightbackground=T.LINE_HI)
    mini_item("home", "⌂", "Home", lambda: shell.show("home"))
    tk.Frame(mini, bg=T.LINE, height=1).pack(fill="x", pady=T.px(3))
    for _name, _col, _tiles in GROUPS:
        for key, title, sub, action in _tiles:
            if key in Shell.MODS:
                mini_item(key, ICON.get(key, "·"), title, lambda a=action: do_action(a))

    # what the one radio is doing, visible from every workspace
    radio_tag = tk.Label(mini, text="AIR", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE, cursor="hand2")
    radio_tag.pack(side="bottom", pady=(0, T.px(6)))
    radio_auto = tk.Label(mini, text="", font=F["lbl"], fg=T.ACCENT, bg=T.SURFACE, cursor="hand2")
    radio_auto.pack(side="bottom")
    tk.Frame(mini, bg=T.LINE, height=1).pack(side="bottom", fill="x", pady=T.px(3))
    for w_ in (radio_tag, radio_auto):
        w_.bind("<Button-1>", lambda e: shell.open("ow"))
        w_.bind("<Enter>", lambda e: (tip.config(text=" Radio: %s%s " % (
            S.radio_holder() or "plane map", " · Autopilot on" if S.AUTOPILOT["on"] else "")),
            tip.place(x=T.px(38), y=radio_auto.winfo_rooty() - root.winfo_rooty()), tip.lift()))
        w_.bind("<Leave>", lambda e: tip.place_forget())

    # master TX kill switch — default OFF/safe, hardware-red when armed. Visible everywhere.
    # Arming only ENABLES the possibility of TX; a transmission still needs a per-session unlock
    # plus band/power/callsign to pass txguard.authorize().
    import txguard as _TXG
    _TXG.reset_session()                         # always boot disarmed/locked
    tx_tag = tk.Label(mini, text="TX", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE, cursor="hand2")
    tx_tag.pack(side="bottom", pady=(0, T.px(4)))

    def _tx_paint():
        armed = _TXG.is_armed()
        tx_tag.config(text="TX●" if armed else "TX", fg="#ff3b30" if armed else T.TXT_3)

    def _tx_toggle(_=None):
        _TXG.arm(not _TXG.is_armed())
        _tx_paint()
    tx_tag.bind("<Button-1>", _tx_toggle)
    tx_tag.bind("<Enter>", lambda e: (tip.config(text=" TX %s — click to %s " % (
        "ARMED" if _TXG.is_armed() else "safe", "disarm" if _TXG.is_armed() else "arm")),
        tip.place(x=T.px(38), y=tx_tag.winfo_rooty() - root.winfo_rooty()), tip.lift()))
    tx_tag.bind("<Leave>", lambda e: tip.place_forget())
    _tx_paint()

    def mark_running():
        draw_radio()
        code = S.radio_code()
        radio_tag.config(text=code, fg=T.TXT if code != "AIR" else T.TXT_3)
        radio_auto.config(text="AUTO" if S.AUTOPILOT["on"] else "")
        for k, (lbl, hk) in running_lbl.items():
            p = procs.get(k)
            on = bool(p and p.poll() is None) or k in shell.ws
            lbl.config(text="●" if on else hk, fg=T.OK if on else T.TXT_3)
        for k, (bar_, lb) in mini_rows.items():
            front = shell.active == k
            lb.config(fg=T.ACCENT if front else (T.TXT if k in shell.ws else T.TXT_3))
            bar_.config(bg=T.ACCENT if front else T.SURFACE)

    def layout_for_workspace():
        """Home: full rail + footer. In a workspace: icon rail only, every pixel to the app."""
        at_home = shell.active in (None, "home")
        if at_home:
            mini.pack_forget()
            if not railw.winfo_manager():
                railw.pack(side="left", fill="y", before=railsep)
            if not foot.winfo_manager():
                foot.pack(side="bottom", fill="x", before=footsep)
        else:
            railw.pack_forget()
            foot.pack_forget()
            if not mini.winfo_manager():
                mini.pack(side="left", fill="y", before=railsep)
        tip.place_forget()
        mark_running()
    shell.on_change = layout_for_workspace

    # ---- alert banner over any workspace
    toast = tk.Label(root, text="", font=F["smb"], fg=T.TXT, bg="#a5282d", padx=14, pady=6,
                     cursor="hand2")
    toast_id = [None]
    toast_src = ["ops"]

    def notify(text, src):
        if shell.active == src:
            return                          # already looking at it
        toast_src[0] = src
        toast.config(text="⚠  " + text[:90])
        toast.place(relx=0.5, y=T.px(30), anchor="n")
        toast.lift()
        if toast_id[0]:
            root.after_cancel(toast_id[0])
        toast_id[0] = root.after(9000, toast.place_forget)
    toast.bind("<Button-1>", lambda e: (toast.place_forget(),
                                        shell.open({"system": "field"}.get(
                                            toast_src[0], toast_src[0] if toast_src[0] in Shell.MODS
                                            else "ops"))))
    shell.on_notify = notify

    # heat, under-voltage and battery warnings reach you in whatever workspace you are in
    hlog = S.SessionLog("system", dedup_window=120)

    def health_event(kind, text):               # monitor thread -> UI thread
        hlog.event("alert" if kind != "cool" else "info", text, id=kind)
        ui_q.put(lambda: notify(text, "system"))
    S.on_health(health_event)

    # ---- command palette: Ctrl+K, type a few letters, Enter
    pal = {"f": None}
    ENTRIES = [("home", "Home", "dashboard", ("call", lambda: shell.show("home")))] + \
        [t for g in GROUPS for t in g[2]]

    def close_palette(_=None):
        if pal["f"] is not None:
            pal["f"].destroy()
            pal["f"] = None
        shell.modal = False
        w_ = shell.ws.get(shell.active)
        if w_ is not None:
            w_.focus_set()
        return "break"

    def open_palette(_=None):
        if pal["f"] is not None:
            return close_palette()
        shell.modal = True
        f = tk.Frame(root, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.ACCENT)
        pal["f"] = f
        ent = tk.Entry(f, font=F["sm"], bg=T.SURFACE_2, fg=T.TXT, insertbackground=T.TXT, bd=0,
                       highlightthickness=0, width=34)
        ent.pack(fill="x", padx=8, pady=8, ipady=4)
        lst = tk.Frame(f, bg=T.SURFACE)
        lst.pack(fill="x", padx=8, pady=(0, 8))
        hitlist = []

        def refill(_=None):
            for w_ in lst.winfo_children():
                w_.destroy()
            q_ = ent.get().strip().lower()
            found = [t for t in ENTRIES if all(wd in (t[1] + " " + t[2] + " " + t[0]).lower()
                                               for wd in q_.split())]
            # names that start with what you typed come first
            found.sort(key=lambda t: not t[1].lower().startswith(q_))
            hitlist[:] = found[:8]
            for i_, (k_, title_, sub_, act_) in enumerate(hitlist):
                r_ = tk.Label(lst, text="%s  %-14s %s%s" % (
                    ICON.get(k_, "⌂" if k_ == "home" else "·"), title_, sub_,
                    "   ● open" if k_ in shell.ws and k_ != "home" else ""),
                    font=F["map"], anchor="w", padx=6, pady=2,
                    fg=T.TXT if i_ == 0 else T.TXT_2, bg=T.ACCENT_BG if i_ == 0 else T.SURFACE)
                r_.pack(fill="x")
                r_.bind("<Button-1>", lambda e, a=act_: (close_palette(), do_action(a)))

        def go(_=None):
            if hitlist:
                act_ = hitlist[0][3]
                close_palette()
                do_action(act_)
            return "break"
        ent.bind("<KeyRelease>", lambda e: None if e.keysym in ("Return", "Escape") else refill())
        ent.bind("<Return>", go)
        ent.bind("<Escape>", close_palette)
        ent.bind("<Control-k>", close_palette)
        f.place(relx=0.5, y=T.px(60), anchor="n")
        f.lift()
        refill()
        ent.focus_set()
        return "break"

    root.bind("<Control-k>", open_palette)
    root.bind("<Control-h>", lambda e: (shell.show("home"), "break")[1])
    root.bind("<F1>", lambda e: (shell.show("home"), "break")[1])
    root.bind("<Control-w>", lambda e: (shell.close(shell.active), "break")[1])
    root.bind("<Control-Tab>", lambda e: (shell.cycle(), "break")[1])
    root.bind("<Control-q>", lambda e: on_close())

    slow = {"t": 0, "owner": "free", "mesh": "inactive", "llm": None, "tpv": None}

    def dashboard_data():
        """KPI values from the caches the apps write (worker thread; never blocks the UI)."""
        now = time.time()
        live = {}
        try:
            import sky_app
            srcs = sky_app.load_settings().get("adsb_sources") or []
        except Exception:
            srcs = []
        acs = None
        for src in srcs:
            if src.startswith("http"):
                continue                      # local files only; HTTP waits belong to Sky
            try:
                with open(os.path.join(src, "aircraft.json")) as fh:
                    acs = [a for a in json.load(fh).get("aircraft", [])
                           if isinstance(a, dict) and isinstance(a.get("seen", 99), (int, float))
                           and a.get("seen", 99) < 60]
                break
            except (OSError, ValueError, AttributeError):
                continue
        if acs is not None:
            pos = [a for a in acs if "lat" in a]
            live["air"] = (str(len(acs)), "%d with position · live" % len(pos))
        else:
            live["air"] = ("—", "plane feed off")
        try:
            import aprs as _A
            stn = _A.load_stations(os.path.join(S.CACHE, "aprs_stations.json"), now)
            fresh = sum(1 for x in stn.s.values() if now - x.get("last", 0) < 600)
            live["aprs"] = (str(len(stn.s)), "%d in last 10 min" % fresh if stn.s
                            else "not listening")
        except Exception:
            live["aprs"] = ("—", "")
        nb_txt = "—"
        try:
            import balloons as _B
            m = int(_B.next_launch(now) / 60)
            nb_txt = "NWS launch in %dh%02d" % (m // 60, m % 60)
            sj = S.load_json(os.path.join(S.CACHE, "sondes.json"), {}) or {}
            up = [b for b in sj.get("sondes", []) if isinstance(b, dict)
                  and isinstance(b.get("t"), (int, float)) and now - b["t"] < 900] \
                if isinstance(sj, dict) else []
            live["sonde"] = (str(len(up)), ("%s %s m" % (up[0].get("id", ""),
                                                          format(int(up[0].get("alt", 0)), ",")))
                             if up else nb_txt.replace("NWS launch", "launch"))
        except Exception:
            live["sonde"] = ("—", "")
        sn = S.load_json(os.path.join(S.CACHE, "sensors.json"), {}) or {}
        if isinstance(sn, dict) and isinstance(sn.get("t"), (int, float)) and now - sn["t"] < 86400:
            age = int(now - sn["t"])
            live["sensors"] = (str(int(sn.get("n") or 0)),
                               "heard %s ago" % ("%ds" % age if age < 60 else "%dm" % (age // 60)
                                                 if age < 3600 else "%dh" % (age // 3600)))
        else:
            live["sensors"] = ("—", "not listening")
        mj = S.load_json(os.path.join(S.CACHE, "mesh_nodes.json"), {}) or {}
        if isinstance(mj, dict) and mj.get("nodes") is not None and not mj.get("demo"):
            n = len([x for x in mj["nodes"] if isinstance(x, dict) and not x.get("me")])
            live["mesh"] = (str(n), "with position")
        else:
            live["mesh"] = ("—", "Mesh not open")
        return live, S.SessionLog.recent(60), nb_txt

    def status_work():
        now = time.time()
        if now - slow["t"] > 10:   # the expensive probes: pgrep/systemctl, gpsd, Ollama
            slow["t"] = now
            slow["owner"] = S.rtl_owner()
            try:
                slow["net"] = S.network_status()
            except Exception:
                slow["net"] = None
            slow["mesh"] = S.core.service_state("meshtasticd")
            slow["tpv"] = S.gps_fix(timeout=1.0)
            llm_ = None
            try:
                import urllib.request
                urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1).read()
                llm_ = "local Ollama"
            except Exception:
                pass
            slow["llm"] = llm_
        owner, mesh, tpv, llm = slow["owner"], slow["mesh"], slow["tpv"], slow["llm"]
        live, events, nb_txt = dashboard_data()
        hs = S.core.hackrf_status()
        hp = S.health()
        cap, bst, w, t = hp.get("pct"), hp.get("status", ""), hp.get("watts"), hp.get("temp")
        lvl, uv_seen = hp.get("level"), hp.get("undervolt_seen")

        def ui():

            def setv(k, v, col=T.TXT_2):
                if k in sysrows:
                    sysrows[k].config(text=v, fg=col if col != T.TXT else T.TXT_2)
            setv("Battery", ("%d%%%s" % (cap, " charging" if bst == "Charging" else "")) if cap is not None
                 else "n/a", T.ALERT if cap is not None and cap < 15 else T.TXT)
            ptxt = "%.1f W" % abs(w) if w is not None else "n/a"
            if hp.get("undervolt_now"):
                ptxt += "  under-voltage"
            elif uv_seen:
                ptxt += "  sagged since boot"
            setv("Power", ptxt, T.ALERT if hp.get("undervolt_now") else
                 (T.AMBER if uv_seen else T.TXT))
            setv("CPU", ("%.0f °C%s" % (t, {"hot": "  too hot", "warm": "  warm"}.get(lvl, "")))
                 if t is not None else "n/a",
                 T.ALERT if lvl == "hot" else (T.AMBER if lvl == "warm" else T.TXT))
            if tpv and "lat" in tpv:
                setv("Position", "%.4f, %.4f" % (tpv["lat"], tpv["lon"]))
            else:
                setv("Position", "no fix", T.TXT_3)
            net = slow.get("net") or {}
            if net.get("ssid"):
                sig = net.get("signal")
                bars = "" if sig is None else (" ▂▄▆█" if sig > -60 else " ▂▄▆" if sig > -70 else
                                               " ▂▄" if sig > -80 else " ▂")
                ntxt = "%s%s  %s" % (net["ssid"], bars, net.get("ip") or "")
            elif net.get("ip"):
                ntxt = net["ip"]
            else:
                ntxt = "offline"
            if net.get("tailscale"):
                ntxt += "  ts " + net["tailscale"]
            setv("Network", ntxt, T.TXT if (net.get("ip") or net.get("ssid")) else T.TXT_3)
            rtxt = owner if owner != "free" else "plane map"
            if S.AUTOPILOT["on"]:
                rtxt = "Auto · " + {"rest": "standing down", "yield": "yours for now"}.get(
                    S.AUTOPILOT["mode"], rtxt)
            setv("Radio", rtxt, T.TXT if (owner != "free" or S.AUTOPILOT["on"]) else T.TXT_3)
            hs_txt = {"ready": "HackRF mode", "wrong_mode": "wrong mode", "absent": "not connected"}[hs]
            if S.adsb_device() == "hackrf":
                hs_txt = {"ready": "ADS-B", "wrong_mode": "wrong mode", "absent": "not connected"}[hs]
            setv("H4M", hs_txt, T.TXT if hs == "ready" else (T.ACCENT if hs == "wrong_mode" else T.TXT_3))
            setv("Meshtastic", "running" if mesh == "active" else "stopped",
                 T.TXT if mesh == "active" else T.TXT_3)
            setv("Assistant", llm or "desktop only", T.TXT if llm else T.TXT_3)
            sdr_pill.config(text="SDR " + (owner if owner != "free" else "idle"),
                            bg=S.GREEN if owner != "free" else S.DIM)
            h4m_pill.config(text="H4M", bg={"ready": S.GREEN, "wrong_mode": S.AMBER, "absent": S.DIM}[hs])
            gps_pill.config(text="GPS " + ({2: "2D", 3: "3D"}.get(tpv.get("mode"), "") if tpv else "no fix"),
                            bg=S.GREEN if tpv else S.DIM)
            mesh_pill.config(text="Mesh", bg=S.GREEN if mesh == "active" else S.DIM)
            mark_running()
            for key, (val, sub) in live.items():
                if key in kpi:
                    kpi[key][0].config(text=val)
                    kpi[key][1].config(text=sub)
            act_txt.config(state="normal")
            act_txt.delete("1.0", "end")
            for r in reversed(events[-40:]):
                act_txt.insert("end", "%s  " % r.get("ts", "")[:5], "t")
                act_txt.insert("end", "%-9s " % str(r.get("app", ""))[:9], "app")
                act_txt.insert("end", str(r.get("text", ""))[:70] + "\n",
                               "alert" if r.get("kind") in ("alert", "emergency") else ())
            if not events:
                act_txt.insert("end", "Nothing logged yet today. Contacts, stations and "
                                      "alerts from every app land here.", "t")
            act_txt.config(state="disabled")
            setv("Next balloon", nb_txt)
        ui_q.put(ui)

    def poll():
        while not ui_q.empty():
            try:
                ui_q.get()()
            except Exception:
                pass
        S.reap()
        try:                                    # power/thermal governor (brownout-aware)
            import powergov
            import txguard
            mode, _pol = powergov.poll()
            if mode == "critical" and txguard.is_armed():
                txguard.arm(False)
                notify("Power critical — TX disarmed for safety", "system")
        except Exception:
            pass
        if not status_busy[0]:
            status_busy[0] = True

            def run():
                try:
                    status_work()
                finally:
                    status_busy[0] = False
            S.in_thread(run)
        root.after(3000, poll)

    def handoff_sdrpp():
        """SDR++ outlives this Hub process (quit, or an execv restart): hand its lease to a
        detached watcher that restores the plane map and clears the lease once SDR++ exits."""
        p = procs.get("sdrpp")
        if sdr_lease[0] is not None and p and p.poll() is None:
            # name SDR++ itself as the holder, so other apps don't see the dongle as free
            # once the Hub's pid is gone
            try:
                sdr_lease[0]._write(pid=p.pid)
            except OSError:
                pass
            paused = " ".join(sdr_lease[0].paused)
            script = ("while kill -0 %d 2>/dev/null; do sleep 2; done; "
                      "for s in %s; do sudo -n systemctl start $s; done; "
                      "python3 -c 'import json,sys;p=sys.argv[1];d=json.load(open(p));"
                      "d.update(owner=None,pid=None,paused=[]);json.dump(d,open(p,\"w\"))' '%s'"
                      % (p.pid, paused, S.LEASE_STATE))
            S.fire_and_forget(["bash", "-c", script])
            msg.config(text="SDR++ stays open; the plane map returns when it closes.")
            return True
        return False

    close_wait = [0]

    def on_close():
        if sdr_lease[0] is not None and procs.get("sdrpp") is None and close_wait[0] < 240:
            # SDR++ is still being started (lease acquire in progress): exiting now would kill
            # that thread with readsb already stopped and nobody to restore it
            close_wait[0] += 1
            msg.config(text="Waiting for SDR++ to finish starting…")
            root.after(500, on_close)
            return
        handoff_sdrpp()
        shell.close_all()         # each app stops its radio and restores the plane map
        shell.closing = True
        root.destroy()

    import signal
    root.protocol("WM_DELETE_WINDOW", on_close)
    signal.signal(signal.SIGTERM, lambda *a: root.after(0, on_close))
    signal.signal(signal.SIGINT, lambda *a: root.after(0, on_close))

    def _sigtick():               # lets Python deliver signals while Tk idles
        root.after(250, _sigtick)
    _sigtick()
    home.bind("q", lambda e: on_close())
    shell.show("home")

    # ---- boot splash: the SENTRY wordmark over the window, fades to the dashboard
    def boot_splash():
        if "--no-splash" in sys.argv or getattr(T, "EMBED", None) is None:
            return
        sp = tk.Frame(root, bg=T.BG)
        sp.place(relx=0, rely=0, relwidth=1, relheight=1)
        sp.lift()
        c = tk.Canvas(sp, bg=T.BG, highlightthickness=0)
        c.pack(fill="both", expand=True)

        def paint(_=None):
            c.delete("all")
            w, h = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
            cx, cy = w / 2, h / 2
            q = T.px(16)
            c.create_polygon(cx - q, cy - T.px(26), cx, cy - T.px(26) + q, cx + q, cy - T.px(26),
                             cx, cy - T.px(26) - q, outline=T.ACCENT, fill="", width=2)
            c.create_text(cx, cy + T.px(6), text=T.spaced("SENTRY"), font=F["title"], fill=T.TXT)
            c.create_oval(cx - T.px(58), cy + T.px(30), cx - T.px(53), cy + T.px(35),
                          fill=S.GREEN, outline="")
            c.create_text(cx - T.px(46), cy + T.px(32), text="RX", anchor="w", font=F["lbl"],
                          fill=T.TXT_2)
            c.create_text(cx + T.px(6), cy + T.px(32), text="//  uCONSOLE", anchor="w",
                          font=F["lbl"], fill=T.TXT_3)
            c.create_text(cx, h - T.px(26),
                          text=time.strftime("%d%b%Y %H:%M:%SZ", time.gmtime()).upper(),
                          font=F["lbl"], fill=T.TXT_3)
        c.bind("<Configure>", paint)
        paint()
        c.bind("<Button-1>", lambda e: sp.destroy())
        root.after(1400, sp.destroy)
    if "--no-splash" not in sys.argv:
        root.after(60, boot_splash)
    if "--no-ops" not in sys.argv:
        # the common picture runs from the start so watch rules are armed in the background
        root.after(1500, lambda: shell.open("ops", show=False))
    if "--open" in sys.argv:      # hub.py --open sky : start in that workspace
        i_ = sys.argv.index("--open")
        if len(sys.argv) > i_ + 1 and sys.argv[i_ + 1] in Shell.MODS:
            root.after(2200, lambda k_=sys.argv[i_ + 1]: launch(k_, None))
    poll()
    root.mainloop()


if __name__ == "__main__":
    if "--doctor" in sys.argv:
        import doctor
        sys.exit(doctor.main())
    if "--sitrep" in sys.argv:
        import sitrep
        sys.exit(sitrep.main())
    if "--security" in sys.argv:
        import doctor
        sys.exit(doctor.main())
    if "--backup" in sys.argv:
        i = sys.argv.index("--backup")
        dest = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("-") else None
        path, n = S.backup_configs(dest)
        print("Backed up %d files to %s" % (n, path))
        print("Restore with:  hub --restore %s" % path)
        sys.exit(0)
    if "--restore" in sys.argv:
        i = sys.argv.index("--restore")
        if len(sys.argv) <= i + 1:
            print("usage: hub --restore <backup.tar.gz>")
            sys.exit(2)
        names = S.restore_configs(sys.argv[i + 1])
        print("Restored %d files. Restart any running apps to pick up the settings." % len(names))
        sys.exit(0)
    if "--log" in sys.argv:
        i = sys.argv.index("--log")
        day = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("-") else None
        rows = S.SessionLog.recent(1000, day)
        if not rows:
            print("No session events%s." % ((" for " + day) if day else " today"))
        for r in rows:
            print("%s  %-8s %s" % (r.get("ts", ""), r.get("app", ""), r.get("text", "")))
        sys.exit(0)
    main()
