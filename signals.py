#!/usr/bin/env python3
"""Signals: ambient data decoded out of the air and shown as it arrives.

Two sources, both public, broadcast telemetry - the same character as ADS-B, nothing
person-to-person:
  - ACARS: VHF aircraft data link (position reports, weather, maintenance). Needs `acarsdec`.
  - Sensors: rtl_433 ISM-band devices (weather stations, TPMS, utility meters) in the clear
    on 433/868/915 MHz. Needs `rtl_433` (in Debian).

Both use the built-in RTL-SDR via the shared lease, so starting one pauses the plane map only
if ADS-B is on the built-in SDR (it isn't by default - it's on the H4M).
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402

DEFAULTS = {
    "source": "sensors",          # "acars" | "sensors" | "vdl2"
    "gain": 40,
    # US ACARS VHF channels (MHz). acarsdec takes them as arguments.
    "acars_freqs": [131.550, 130.025, 129.125, 130.450, 131.125, 136.900],
    # command templates - {gain} and {freqs} are filled in. Editable so a different acarsdec/
    # rtl_433 version is a one-line change, not a rebuild.
    # acarsdec 4.x CLI (the installed v4.3.1 rejects the old 3.x "-o 1 ... -r 0"): JSON lines
    # on stdout, rtl dongle 0, gain in dB
    "acars_cmd": "acarsdec --output json:file:path=- --rtlsdr 0 -g {gain} {freqs}",
    "rtl433_cmd": "rtl_433 -d 0 -g {gain} -F json -M time:unix",
    # VDL Mode 2 via dumpvdl2 (JSON out). US common VDL2 freqs in Hz. Needs dumpvdl2 on PATH.
    "vdl2_cmd": "dumpvdl2 --rtlsdr 0 --gain {gain} --output decoded:json:file:path=- "
                "136650000 136700000 136800000 136975000",
    "sensor_hide_after_min": 60,  # drop a device from the table if unheard this long
}


# shipped defaults that turned out broken; a settings file still holding one verbatim is
# upgraded on load (a hand-edited command is left alone)
OLD_DEFAULTS = {
    "acars_cmd": ["acarsdec -o 1 -g {gain} -r 0 {freqs}"],
    "vdl2_cmd": ["dumpvdl2 --rtlsdr 0 --gain {gain} --output decoded:json:file:path=- "
                 "136650000 136800000 136975000 136975000"],
}


def migrate(s):
    """Replace known-broken stored default commands with the current defaults. True if changed."""
    changed = False
    for k, olds in OLD_DEFAULTS.items():
        if s.get(k) in olds:
            s[k] = DEFAULTS[k]
            changed = True
    return changed


def _airline(flight):
    return re.sub(r"\d.*$", "", (flight or "").strip())[:3]


class Decoder:
    """Runs a decoder subprocess and parses its stdout lines on a worker thread."""

    def __init__(self, on_line, on_status):
        self.on_line, self.on_status = on_line, on_status
        self.proc = None
        self.lease = None
        try:
            self.lease = S.RtlLease("Signals", log=lambda m: on_status("log", m))
        except Exception:
            self.lease = None
        self.lock = threading.Lock()
        self.gen = 0               # bumped by every start/stop request: stale starts abort

    def start_async(self, argv):
        """start() on a worker thread: acquiring the SDR stops readsb, which can take
        tens of seconds. Status still arrives through on_status."""
        self.gen += 1
        g = self.gen
        threading.Thread(target=self.start, args=(argv, g), daemon=True).start()

    def stop_async(self):
        self.gen += 1
        g = self.gen

        def run():
            if g == self.gen:      # a Start pressed after this Stop wins
                self.stop()
        threading.Thread(target=run, daemon=True).start()

    def start(self, argv, gen=None):
        if gen is not None and gen != self.gen:
            return
        self.stop(release=False)   # keep the lease: releasing here would bounce readsb
        with self.lock:
            if gen is not None and gen != self.gen:
                return             # Stop was pressed before we got here
            if self.lease:
                try:
                    self.lease.acquire()
                    if gen is not None and gen != self.gen:
                        self.lease.release()     # Stop arrived while we took the radio
                        return
                except Exception as e:
                    # acquire may already have paused readsb: give it back
                    try:
                        self.lease.release()
                    except Exception:
                        pass
                    self.on_status("error", str(e))
                    return
            try:
                # errors="replace": one non-UTF-8 byte (ACARS text, noise) must not kill
                # the reader thread and leave the decoder blocked on a full pipe
                self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, text=True, bufsize=1,
                                             errors="replace", start_new_session=True)
            except FileNotFoundError:
                self.on_status("missing", argv[0])
                if self.lease:
                    self.lease.release()
                return
            except Exception as e:
                self.on_status("error", str(e))
                if self.lease:
                    self.lease.release()
                return
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        self.on_status("running", " ".join(argv))

    def _read(self, proc):
        err_tail = []
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line.strip():
                    err_tail.append(line)
                    del err_tail[:-8]
                    self.on_line(line)
        except Exception as e:     # never skip the release/status below
            err_tail.append("reader error: %s" % e)
            S.stop_group(proc)
        rc = proc.wait()
        with self.lock:
            if self.proc is proc:
                self.proc = None
                if self.lease:
                    self.lease.release()
                if rc not in (0, -15, -2):
                    self.on_status("error", "decoder exited (%s): %s" % (rc, " / ".join(err_tail[-2:])))
                else:
                    self.on_status("stopped", "")

    def stop(self, release=True):
        with self.lock:
            p, self.proc = self.proc, None
        if p and p.poll() is None:
            S.stop_group(p)
        if release and self.lease:
            self.lease.release()

    def running(self):
        return self.proc is not None and self.proc.poll() is None


def build_argv(s):
    if s["source"] == "acars":
        freqs = " ".join("%.3f" % f for f in s.get("acars_freqs", []))
        tmpl = s.get("acars_cmd") or DEFAULTS["acars_cmd"]
        return tmpl.format(gain=int(s["gain"]), freqs=freqs).split()
    if s["source"] == "vdl2":
        tmpl = s.get("vdl2_cmd") or DEFAULTS["vdl2_cmd"]
        return tmpl.format(gain=int(s["gain"])).split()
    tmpl = s.get("rtl433_cmd") or DEFAULTS["rtl433_cmd"]
    return tmpl.format(gain=int(s["gain"])).split()


def parse_vdl2(line):
    """dumpvdl2 JSON line -> an ACARS-shaped dict, or None. dumpvdl2 nests the ACARS payload
    under vdl2.avlc.acars; we dig it out loosely and fall back to a raw line."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        d = json.loads(line)
    except ValueError:
        return None
    v = d.get("vdl2", d)
    avlc = v.get("avlc", {}) if isinstance(v, dict) else {}
    acars = avlc.get("acars") if isinstance(avlc, dict) else None
    if isinstance(acars, dict):
        return {"reg": (acars.get("reg") or "").strip(), "flight": (acars.get("flight") or "").strip(),
                "label": str(acars.get("label", "")).strip(),
                "text": (acars.get("msg_text") or acars.get("text") or "").strip(),
                "t": time.time()}
    # no ACALS payload (link-mgmt frame etc.) - keep a terse raw record so the user sees activity
    src = avlc.get("src", {}) if isinstance(avlc, dict) else {}
    addr = src.get("addr") if isinstance(src, dict) else None
    return {"reg": "", "flight": "", "label": "VDL2",
            "text": "frame from %s" % addr if addr else line[:80], "t": time.time()}


def parse_acars(line):
    """Return a dict for a decoded ACARS message, or None. Accepts JSON or acarsdec oneline text."""
    line = line.strip()
    try:
        d = json.loads(line)
        if isinstance(d, dict):
            reg = d.get("registration") or d.get("tail") or d.get("reg") or ""
            flight = d.get("flight") or d.get("fid") or ""
            return {"reg": reg.strip(), "flight": flight.strip(),
                    "label": str(d.get("label", "")).strip(),
                    "text": (d.get("text") or d.get("message") or d.get("msgtext") or "").strip(),
                    "t": time.time()}
    except ValueError:
        pass
    if line.startswith(("#", "[", "ACARS", "--")) or len(line) < 3:
        return None
    # acarsdec -o 1 oneline: "<freq> <level> <err> <reg> <mode> <label> <block> <flight> <text...>"
    m = re.match(r"^\S+\s+[-\d.]+\s+\d+\s+([.\w-]+)\s+(\S)\s+(\S+)\s+\S*\s*(\S*)\s*(.*)$", line)
    if m:
        return {"reg": m.group(1).lstrip("."), "flight": m.group(4).strip(), "label": m.group(3),
                "text": m.group(5).strip(), "t": time.time()}
    return {"reg": "", "flight": "", "label": "", "text": line, "t": time.time()}


def parse_sensor(line):
    try:
        d = json.loads(line)
    except ValueError:
        return None
    if not isinstance(d, dict) or "model" not in d:
        return None
    key = "%s/%s" % (d.get("model"), d.get("id", d.get("channel", "")))
    # pick the human-interesting readings, in a stable order
    fields = []
    for k, label, unit, conv in (
        ("temperature_C", "temp", "°C", lambda v: v),
        ("temperature_F", "temp", "°F", lambda v: (v - 32) * 5 / 9),
        ("humidity", "hum", "%", lambda v: v),
        ("wind_avg_km_h", "wind", "km/h", lambda v: v),
        ("rain_mm", "rain", "mm", lambda v: v),
        ("pressure_kPa", "press", "kPa", lambda v: v),
        ("pressure_PSI", "tire", "PSI", lambda v: v),
        ("battery_ok", "batt", "", lambda v: "ok" if v else "low"),
        ("consumption", "meter", "", lambda v: v)):
        if k in d and d[k] is not None:
            try:
                val = conv(d[k])
                if k == "temperature_F":
                    fields.append(("temp", "%.1f°C" % val))
                elif unit and isinstance(val, (int, float)):
                    fields.append((label, ("%.1f%s" % (val, unit)) if val % 1 else ("%d%s" % (val, unit))))
                else:
                    fields.append((label, "%s%s" % (val, unit)))
            except Exception:
                pass
    return {"key": key, "model": d.get("model"), "id": str(d.get("id", d.get("channel", ""))),
            "fields": fields, "t": time.time()}


def main():
    S.single_instance("Signals")
    s, spath = S.settings("signals", DEFAULTS)
    if migrate(s):
        try:
            S.save_json(spath, s)
        except OSError:
            pass
    root, F = S.make_root("Signals")
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("signals")

    top = S.top_bar(root, F, "Signals", "Built-in SDR")
    state_pill = S.pill(top, F, "Off")
    src_pill = S.pill(top, F, s["source"].upper())

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)

    # left control column
    leftw = tk.Frame(body, bg=T.SURFACE, width=S.T.px(300))
    leftw.pack(side="left", fill="y")
    leftw.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    left = tk.Frame(leftw, bg=T.SURFACE)
    left.pack(fill="both", expand=True, padx=16, pady=16)

    T.section(left, F, "Source").pack(fill="x", pady=(0, 6))
    srow = tk.Frame(left, bg=T.SURFACE)
    srow.pack(fill="x", pady=(0, 12))
    src_btns = {}

    play = [None]
    dec = [None]

    def set_source(src):
        if s["source"] == src and dec[0] and dec[0].running():
            return
        was_running = dec[0] and dec[0].running()
        if was_running:
            stop()
        s["source"] = src
        S.save_json(spath, s)
        src_pill.config(text=src.upper())
        for k, b in src_btns.items():
            S.set_btn(b, kind="primary" if k == src else "ghost")
        show_view()
        if was_running:
            start()

    import shutil as _sh
    sources = [("sensors", "Sensors (rtl_433)"), ("acars", "ACARS (aircraft)")]
    if _sh.which("dumpvdl2"):   # only offer VDL2 when the decoder is actually installed
        sources.append(("vdl2", "VDL2 (aircraft data)"))
    for key, lab in sources:
        b = S.btn(srow, lab, lambda k=key: set_source(k), F, padx=10, pady=4,
                  kind="primary" if s["source"] == key else "ghost")
        b.pack(fill="x", pady=2)
        src_btns[key] = b

    gain_row = tk.Frame(left, bg=T.SURFACE)
    gain_row.pack(fill="x", pady=(0, 12))
    tk.Label(gain_row, text="Gain", font=F["sm"], fg=S.MUTED, bg=T.SURFACE).pack(side="left")
    gain_val = tk.Label(gain_row, text="%d dB" % int(s["gain"]), font=F["mono"], fg=S.TXT, bg=T.SURFACE)
    gain_val.pack(side="left", padx=8)

    def bump_gain(d):
        s["gain"] = max(0, min(49, int(s["gain"]) + d))
        gain_val.config(text="%d dB" % int(s["gain"]))
        S.save_json(spath, s)
        if dec[0] and dec[0].running():
            restart()
    S.btn(gain_row, "+", lambda: bump_gain(2), F, padx=10, pady=2, kind="quiet").pack(side="right")
    S.btn(gain_row, "−", lambda: bump_gain(-2), F, padx=10, pady=2, kind="quiet").pack(side="right")

    play_btn = S.btn(left, "Start", lambda: toggle(), F, padx=10, pady=6, kind="primary")
    play_btn.pack(fill="x")
    play[0] = play_btn

    status = tk.Label(left, text="", font=F["map"], fg=S.MUTED, bg=T.SURFACE, anchor="nw",
                      justify="left", wraplength=S.T.px(268))
    status.pack(fill="x", pady=(10, 0))

    tools = tk.Frame(left, bg=T.SURFACE)
    tools.pack(side="bottom", fill="x")

    logbox = tk.Text(left, height=6, bg=S.BG, fg=T.TXT_2, font=F["map"], bd=0, highlightthickness=0,
                     wrap="word", padx=8, pady=6)
    log_shown = [False]

    def toggle_log():
        log_shown[0] = not log_shown[0]
        if log_shown[0]:
            logbox.pack(fill="x", pady=(10, 0), before=tools)
        else:
            logbox.pack_forget()

    # main view area (swapped per source)
    main = tk.Frame(body, bg=S.BG)
    main.pack(side="left", fill="both", expand=True)

    # ACARS feed
    acars_wrap = tk.Frame(main, bg=S.BG)
    acars_txt = tk.Text(acars_wrap, bg=S.BG, fg=S.TXT, font=F["sm"], bd=0, highlightthickness=0,
                        wrap="word", padx=18, pady=14, spacing1=3, state="disabled")
    acars_txt.tag_config("meta", foreground=T.TXT_3, font=F["map"])
    acars_txt.tag_config("reg", foreground=T.ACCENT, font=F["smb"])
    acars_txt.tag_config("label", foreground=T.TXT_2, font=F["map"])
    acars_txt.pack(fill="both", expand=True)

    # Sensors table
    sensor_wrap = tk.Frame(main, bg=S.BG)
    sensor_head = tk.Frame(sensor_wrap, bg=S.BG)
    sensor_head.pack(fill="x", padx=18, pady=(14, 4))
    tk.Label(sensor_head, text="Devices heard", font=F["lbl"], fg=T.TXT_3, bg=S.BG).pack(side="left")
    sensor_count = tk.Label(sensor_head, text="", font=F["map"], fg=T.TXT_3, bg=S.BG)
    sensor_count.pack(side="right")
    sensor_rows = tk.Frame(sensor_wrap, bg=S.BG)
    sensor_rows.pack(fill="both", expand=True, padx=18)

    devices = {}       # key -> record
    acars_lines = []   # recent parsed dicts
    sky_flights = {"set": set(), "t": 0}

    def show_view():
        acars_wrap.pack_forget()
        sensor_wrap.pack_forget()
        (acars_wrap if s["source"] in ("acars", "vdl2") else sensor_wrap).pack(fill="both", expand=True)

    def draw_sensors():
        now = time.time()
        hide = s.get("sensor_hide_after_min", 60) * 60
        for k in [k for k, v in devices.items() if now - v["t"] > hide]:
            devices.pop(k, None)
        for w in sensor_rows.winfo_children():
            w.destroy()
        items = sorted(devices.values(), key=lambda v: (-v["t"]))
        for v in items:
            row = tk.Frame(sensor_rows, bg=S.BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=v["model"], font=F["smb"], fg=S.TXT, bg=S.BG, anchor="w",
                     width=20).pack(side="left")
            tk.Label(row, text=v["id"], font=F["map"], fg=T.TXT_3, bg=S.BG, width=8,
                     anchor="w").pack(side="left")
            vals = "   ".join("%s %s" % (lab, val) for lab, val in v["fields"])
            tk.Label(row, text=vals, font=F["mono"], fg=S.TXT, bg=S.BG, anchor="w").pack(side="left")
            tk.Label(row, text="%s ago · ×%d" % (S.core.ago(v["t"]) if hasattr(S.core, "ago")
                     else "%ds" % (now - v["t"]), v["count"]), font=F["map"], fg=T.TXT_3,
                     bg=S.BG, anchor="e").pack(side="right")
        sensor_count.config(text="%d device%s" % (len(items), "" if len(items) == 1 else "s"))
        if not items:
            tk.Label(sensor_rows, text="Listening… sensors appear as they transmit (seconds to minutes).",
                     font=F["sm"], fg=T.TXT_3, bg=S.BG).pack(anchor="w", pady=20)

    def sky_flight_set():
        if time.time() - sky_flights["t"] < 5:
            return sky_flights["set"]
        out = set()
        try:
            for src in S.core.DEFAULT_SETTINGS["adsb_sources"]:
                try:
                    if src.startswith("http"):
                        import urllib.request
                        data = json.loads(urllib.request.urlopen(src + "/aircraft.json", timeout=1).read())
                    else:
                        with open(os.path.join(src, "aircraft.json")) as f:
                            data = json.load(f)
                    for a in data.get("aircraft", []):
                        fl = (a.get("flight") or "").strip()
                        if fl:
                            out.add(fl)
                    break
                except Exception:
                    continue
        except Exception:
            pass
        sky_flights["set"], sky_flights["t"] = out, time.time()
        return out

    def draw_acars():
        acars_txt.config(state="normal")
        acars_txt.delete("1.0", "end")
        flights = sky_flight_set()
        for d in acars_lines[-40:]:
            hhmm = time.strftime("%H:%M:%S", time.localtime(d["t"]))
            acars_txt.insert("end", hhmm + "  ", "meta")
            head = d["reg"] or "?"
            if d["flight"]:
                head += " / " + d["flight"]
            acars_txt.insert("end", head, "reg")
            on_map = d["flight"] and d["flight"] in flights
            if on_map:
                acars_txt.insert("end", "  ●on map", "meta")
            if d["label"]:
                acars_txt.insert("end", "  [%s]" % d["label"], "label")
            acars_txt.insert("end", "\n")
            if d["text"]:
                acars_txt.insert("end", d["text"] + "\n", ())
        acars_txt.config(state="disabled")
        acars_txt.see("end")

    # thread-safe plumbing
    q = __import__("queue").Queue()

    def on_line(line):
        q.put(("line", line))

    def on_status(kind, detail):
        q.put(("status", kind, detail))

    def pump():
        dirty_sensor = False
        dirty_acars = False
        while not q.empty():
            item = q.get()
            if item[0] == "line":
                line = item[1]
                if s["source"] in ("acars", "vdl2"):
                    d = parse_acars(line) if s["source"] == "acars" else parse_vdl2(line)
                    if d:
                        acars_lines.append(d)
                        del acars_lines[:-200]
                        dirty_acars = True
                        slog.event(s["source"], "%s %s" % (d.get("flight") or d.get("reg") or "?",
                                                           (d.get("text") or "")[:60]),
                                   id=d.get("reg"), flight=d.get("flight"), label=d.get("label"))
                else:
                    rec = parse_sensor(line)
                    if rec:
                        cur = devices.get(rec["key"])
                        rec["count"] = (cur["count"] + 1) if cur else 1
                        devices[rec["key"]] = rec
                        if cur is None:   # log the first time each sensor appears, not every ping
                            summary = " ".join("%s %s" % (lbl, val) for lbl, val in rec.get("fields", []))
                            slog.event("sensor", "%s %s" % (rec.get("model", "sensor"), summary),
                                       id=rec["key"], model=rec.get("model"))
                        dirty_sensor = True
                if log_shown[0]:
                    logbox.insert("end", line[:200] + "\n")
                    logbox.see("end")
            else:
                _, kind, detail = item
                if kind == "running":
                    state_pill.config(text="Decoding", bg=S.GREEN)
                    S.set_btn(play[0], "Stop", "danger")
                    status.config(text="Running:\n" + detail, fg=S.MUTED)
                elif kind == "missing":
                    active[0] = False
                    state_pill.config(text="Missing", bg=S.RED)
                    S.set_btn(play[0], "Start", "primary")
                    tool = detail
                    hint = ("rtl_433 isn't installed.  sudo apt install rtl-433" if tool == "rtl_433"
                            else "acarsdec isn't installed. It's not in Debian - build it from "
                                 "github.com/TLeconte/acarsdec, or edit the command in Settings.")
                    status.config(text=hint, fg=S.RED)
                elif kind in ("stopped", "idle"):
                    active[0] = False
                    state_pill.config(text="Off", bg=S.DIM)
                    S.set_btn(play[0], "Start", "primary")
                elif kind == "error":
                    active[0] = False
                    state_pill.config(text="Fault", bg=S.RED)
                    S.set_btn(play[0], "Start", "primary")
                    status.config(text=detail, fg=S.RED)
                elif kind == "log" and log_shown[0]:
                    logbox.insert("end", detail + "\n")
                    logbox.see("end")
        if dirty_sensor and s["source"] == "sensors":
            draw_sensors()
        if dirty_acars and s["source"] in ("acars", "vdl2"):
            draw_acars()
        root.after(300, pump)

    def periodic():
        if s["source"] == "sensors":
            draw_sensors()
        root.after(5000, periodic)

    active = [False]           # what the user asked for, independent of process state

    def start():
        active[0] = True
        argv = build_argv(s)
        if not dec[0]:
            dec[0] = Decoder(on_line, on_status)
            if dec[0].lease:
                dec[0].lease.on_preempt = lambda: stop(sync=True)   # another workspace wants the radio
        state_pill.config(text="Starting", bg=S.AMBER)
        dec[0].start_async(argv)

    def stop(sync=False):
        active[0] = False
        if dec[0]:
            if sync:
                dec[0].gen += 1
                dec[0].stop()           # quitting: release before the process exits
            else:
                dec[0].stop_async()
        state_pill.config(text="Off", bg=S.DIM)
        S.set_btn(play[0], "Start", "primary")

    def toggle():
        if active[0]:          # also cancels a start that's still taking the radio
            stop()
        else:
            start()

    def restart():
        # settings changed: start() swaps the decoder but keeps the radio, so the plane
        # map isn't bounced (stop+start used to release and re-take it)
        if active[0]:
            start()

    S.btn(tools, "Log", toggle_log, F, padx=10, pady=4, kind="quiet").pack(side="left")
    S.btn(tools, "Settings", lambda: edit_settings(), F, padx=10, pady=4, kind="quiet").pack(side="left")
    S.btn(tools, "Quit", lambda: on_close(), F, padx=10, pady=4, kind="quiet").pack(side="right")

    SIG_SCHEMA = [
        ("Decoder", [
            {"key": "source", "label": "Default source", "type": "choice",
             "choices": [("sensors", "Sensors (rtl_433)"), ("acars", "ACARS (aircraft)")]
             + ([("vdl2", "VDL2 (aircraft data)")] if _sh.which("dumpvdl2") else [])},
            {"key": "gain", "label": "Gain", "type": "float", "min": 0, "max": 49, "step": 2, "unit": "dB"},
            {"key": "sensor_hide_after_min", "label": "Forget a sensor after", "type": "int",
             "min": 5, "max": 1440, "step": 15, "unit": "min"},
        ]),
        ("ACARS", [
            {"key": "acars_freqs", "label": "ACARS frequencies (MHz)", "type": "numlist"},
            {"key": "acars_cmd", "label": "acarsdec command", "type": "str",
             "help": "{gain} and {freqs} are filled in"},
        ]),
        ("Sensors", [
            {"key": "rtl433_cmd", "label": "rtl_433 command", "type": "str", "help": "{gain} is filled in"},
        ]),
    ]

    def edit_settings():
        import settings_ui

        def on_save(new):
            s.clear()
            s.update(new)
            S.save_json(spath, s)
            for k, b in src_btns.items():
                S.set_btn(b, kind="primary" if k == s["source"] else "ghost")
            src_pill.config(text=s["source"].upper())
            gain_val.config(text="%d dB" % int(s["gain"]))
            show_view()
            if dec[0] and dec[0].running():
                restart()
        settings_ui.open_settings(root, F, "Signals settings", SIG_SCHEMA, s, on_save, path=spath)

    def on_close():
        stop(sync=True)
        root.destroy()

    S.bind_quit(root, on_close)
    root.bind("q", lambda e: on_close())
    root.bind("<space>", lambda e: toggle())
    show_view()
    draw_sensors()
    pump()
    periodic()
    root.mainloop()


if __name__ == "__main__":
    main()
