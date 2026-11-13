#!/usr/bin/env python3
"""Balloons - track NWS weather balloons (radiosondes) with radiosonde_auto_rx. Receive-only.

Denver (NWS 72469 / KDNR) flies Lockheed Martin LMS-6 sondes in the 400-406 MHz band,
launched about 11:00 and 23:00 UTC. auto_rx scans the band and decodes them; this app
runs it only when you want it (it needs the single RTL dongle, so it takes the radio
lease like every other app), keeps every output on this machine, and shows the flights.

Privacy/security defaults written into auto_rx's config, regardless of its own defaults:
  web UI bound to 127.0.0.1 (auto_rx defaults to 0.0.0.0)
  payload summaries sent to 127.0.0.1 only (auto_rx defaults to LAN broadcast)
  SondeHub upload OFF (auto_rx defaults to ON) - opt in from Settings with a callsign
"""
import configparser
import io
import json
import math
import os
import queue
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import suite as S           # noqa: E402
import skyintel as SI       # noqa: E402

ARX_ROOT = os.path.join(S.DATA, "radiosonde_auto_rx")
ARX_DIR = os.path.join(ARX_ROOT, "auto_rx")
ARX_PY = os.path.join(S.DATA, "radiosonde_venv", "bin", "python")
FEED_PATH = os.path.join(S.CACHE, "sondes.json")      # Sky reads this to draw balloons
SUMMARY_PORT = 55673
LAUNCH_HOURS_UTC = (11, 23)        # NWS synoptic launches, ~1 h before 12Z / 00Z
DEFAULTS = {"home": {"lat": 39.62, "lon": -104.87, "alt_m": 1750},
            "min_freq": 400.05, "max_freq": 406.0, "upload": False, "callsign": "",
            "auto": False}


# ---- auto_rx configuration --------------------------------------------------------------
def make_station_cfg(example_text, home, s):
    """Fill auto_rx's station.cfg.example with our station and SAFE defaults."""
    cp = configparser.RawConfigParser()
    cp.optionxform = str                       # keep key case as in the example
    cp.read_string(example_text)

    def put(sec, key, val):
        if not cp.has_section(sec):
            cp.add_section(sec)
        cp.set(sec, key, str(val))
    put("sdr", "sdr_type", "RTLSDR")
    put("sdr", "sdr_quantity", 1)
    put("sdr_1", "device_idx", 0)
    put("search_params", "min_freq", "%.3f" % float(s.get("min_freq", 400.05)))
    put("search_params", "max_freq", "%.3f" % float(s.get("max_freq", 406.0)))
    put("location", "station_lat", "%.5f" % float(home["lat"]))
    put("location", "station_lon", "%.5f" % float(home["lon"]))
    put("location", "station_alt", "%.0f" % float(home.get("alt_m") or 0))
    # keep everything on this machine unless the user opts in
    put("web", "web_host", "127.0.0.1")
    put("web", "web_control", "False")
    put("oziplotter", "payload_summary_enabled", "True")
    put("oziplotter", "payload_summary_host", "127.0.0.1")
    put("oziplotter", "payload_summary_port", SUMMARY_PORT)
    upload = bool(s.get("upload")) and bool(str(s.get("callsign") or "").strip())
    put("sondehub", "sondehub_enabled", "True" if upload else "False")
    put("habitat", "uploader_callsign", (s.get("callsign") or "CHANGEME").strip() or "CHANGEME")
    put("habitat", "upload_listener_position", "True" if upload else "False")
    for sec, key in (("aprs", "aprs_enabled"), ("aprs", "station_beacon_enabled"),
                     ("email", "email_enabled"), ("rotator", "rotator_enabled")):
        if cp.has_section(sec):
            put(sec, key, "False")
    out = io.StringIO()
    cp.write(out)
    return out.getvalue()


def installed():
    return os.path.isfile(os.path.join(ARX_DIR, "auto_rx.py")) and os.path.isfile(ARX_PY)


# ---- telemetry --------------------------------------------------------------------------
def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_summary(data):
    """One auto_rx PAYLOAD_SUMMARY UDP datagram -> normalised dict, or None."""
    try:
        p = json.loads(data.decode("utf-8", "replace") if isinstance(data, bytes) else data)
    except ValueError:
        return None
    if not isinstance(p, dict) or p.get("type") != "PAYLOAD_SUMMARY":
        return None
    lat, lon, alt = _num(p.get("latitude")), _num(p.get("longitude")), _num(p.get("altitude"))
    sid = "".join(c for c in str(p.get("callsign") or "") if c.isprintable())[:24]
    if not sid or lat is None or lon is None or alt is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and -500 <= alt <= 60000):
        return None
    out = {"id": sid, "lat": lat, "lon": lon, "alt": alt,
           "model": str(p.get("model") or "")[:16], "freq": str(p.get("freq") or "")[:16]}
    for k in ("temp", "humidity", "pressure", "vel_v", "vel_h", "heading", "batt", "sats",
              "snr", "speed"):
        v = _num(p.get(k))
        if v is None or (k != "temp" and v == -1.0) or (k == "temp" and v < -200):
            continue                                  # auto_rx: -1 / -273 mean "unknown"
        out[k] = v
    if "vel_h" not in out and out.get("speed") is not None and out["speed"] >= 0:
        out["vel_h"] = out["speed"] / 3.6         # payload summary speed is km/h
    return out


class SondeTracker:
    """Flights by serial: track, peak altitude, burst, rough landing estimate."""

    def __init__(self):
        self.s = {}

    def add(self, t, now=None):
        now = now or time.time()
        f = self.s.setdefault(t["id"], {"id": t["id"], "track": [], "max_alt": t["alt"],
                                         "burst": None, "first": now})
        f.update(t)
        f["last"] = now
        tr = f["track"]
        if not tr or (tr[-1][0], tr[-1][1]) != (t["lat"], t["lon"]):
            tr.append((t["lat"], t["lon"], t["alt"], now))
            del tr[:-2000]
        if t["alt"] > f["max_alt"]:
            f["max_alt"] = t["alt"]
        vv = t.get("vel_v")
        if f["burst"] is None and f["max_alt"] > 5000 and \
                ((vv is not None and vv < -3) or t["alt"] < f["max_alt"] - 300):
            f["burst"] = {"alt": f["max_alt"], "t": now}      # balloon popped
        return f

    def phase(self, f, now=None):
        now = now or time.time()
        if now - f["last"] > 300:
            return "lost"
        vv = f.get("vel_v")
        if f["burst"]:
            return "landed" if (vv is not None and abs(vv) < 1 and f["alt"] < 4000) else "descending"
        if vv is not None and vv > 1:
            return "ascending"
        return "on ground" if f["alt"] < 2500 else "level"

    def landing(self, f, ground_m=1600):
        """Very rough landing point for a descending sonde: hold current drift and descent
        rate to the ground. Real chasers use wind models; this is a direction, not a spot."""
        vv, vh, hd = f.get("vel_v"), f.get("vel_h"), f.get("heading")
        if not f["burst"] or vv is None or vv > -1 or vh is None or hd is None or hd < 0:
            return None
        secs = max(0.0, (f["alt"] - ground_m) / -vv)
        lat, lon = SI.offset(f["lat"], f["lon"], hd, vh * secs / 1852.0)
        return {"lat": lat, "lon": lon, "secs": secs}

    def flights(self, now=None):
        now = now or time.time()
        return sorted(self.s.values(), key=lambda f: -f["last"])

    def dump(self, path, now=None):
        now = now or time.time()
        live = [{"id": f["id"], "lat": f["lat"], "lon": f["lon"], "alt": f["alt"],
                 "vel_v": f.get("vel_v"), "model": f.get("model"), "phase": self.phase(f, now),
                 "track": [(a, b) for a, b, _, _ in f["track"][-120:]], "t": f["last"]}
                for f in self.s.values() if now - f["last"] < 3600]
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w") as fh:
            json.dump({"t": now, "sondes": live}, fh)
        os.replace(tmp, path)


def next_launch(now=None):
    """Seconds until the next ~11:00/23:00 UTC NWS launch."""
    now = now or time.time()
    g = time.gmtime(now)
    day0 = now - (g.tm_hour * 3600 + g.tm_min * 60 + g.tm_sec)
    for add_day in (0, 1):
        for h in LAUNCH_HOURS_UTC:
            t = day0 + add_day * 86400 + h * 3600
            if t > now:
                return t - now
    return None


# ---- the app ----------------------------------------------------------------------------
def main(parent=None):
    # parent: a tab host (the Sky shell) supplies a workspace-like frame to render into; it
    # owns the instance lock and lifecycle, so skip single_instance. parent=None is unchanged.
    if parent is None:
        S.single_instance("Balloons")
    s, spath = S.settings("balloons", DEFAULTS)
    root, F = S.make_root("Balloons", parent=parent)
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("balloons")
    lease = S.RtlLease("Balloons", log=lambda m: None)
    lease.on_preempt = lambda: stop()   # another workspace wants the radio
    q = queue.Queue()
    trk = SondeTracker()
    st = {"proc": None, "starting": False, "listening": False, "auto_win": None, "sel": None}

    top = S.top_bar(root, F, "Balloons", "NWS radiosondes · 400-406 MHz · receive-only")
    state_pill = S.pill(top, F, "Off")
    launch_pill = S.pill(top, F, "")

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    left = tk.Frame(body, bg=T.SURFACE, width=T.px(440))
    left.pack(side="left", fill="y")
    left.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    lp = tk.Frame(left, bg=T.SURFACE)
    lp.pack(fill="both", expand=True, padx=T.px(14), pady=T.px(12))
    T.section(lp, F, "Flights").pack(fill="x")
    flights_box = tk.Text(lp, bg=T.SURFACE, fg=T.TXT_2, font=F["mono"], bd=0,
                          highlightthickness=0, height=6, wrap="none", state="disabled",
                          cursor="arrow")
    flights_box.tag_config("pick", foreground=S.AMBER)
    flights_box.tag_config("hdr", foreground=T.TXT_3)
    flights_box.pack(fill="x", pady=(T.px(4), T.px(8)))
    T.section(lp, F, "Selected").pack(fill="x")
    d_title = tk.Label(lp, text="—", font=F["now"], fg=S.TXT, bg=T.SURFACE, anchor="w")
    d_title.pack(fill="x")
    d_sub = tk.Label(lp, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE, anchor="w")
    d_sub.pack(fill="x")
    d_grid = tk.Frame(lp, bg=T.SURFACE)
    d_grid.pack(fill="x", pady=(T.px(6), 0))
    rows = {}
    for r, (k1, k2) in enumerate((("ALT", "CLIMB"), ("PEAK", "PHASE"), ("TEMP", "HUMID"),
                                  ("PRESS", "BATT"), ("RANGE", "BRG"))):
        for c, k in enumerate((k1, k2)):
            cell = tk.Frame(d_grid, bg=T.SURFACE)
            cell.grid(row=r, column=c, sticky="w", pady=1)
            d_grid.columnconfigure(c, weight=1)
            tk.Label(cell, text=k, font=F["map"], fg=T.TXT_3, bg=T.SURFACE, width=6,
                     anchor="w").pack(side="left")
            v = tk.Label(cell, text="—", font=F["mono"], fg=S.TXT, bg=T.SURFACE, anchor="w")
            v.pack(side="left")
            rows[k] = v
    status = tk.Label(lp, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE, anchor="w",
                      justify="left", wraplength=T.px(410))
    status.pack(fill="x", side="bottom")
    prof = tk.Canvas(lp, bg=T.night("#10151a"), highlightthickness=0, height=T.px(90))
    prof.pack(fill="x", side="bottom", pady=(T.px(8), T.px(6)))

    mapcv = tk.Canvas(body, bg=S.MAPBG, highlightthickness=0)
    mapcv.pack(side="left", fill="both", expand=True)

    home = dict(s.get("home") or DEFAULTS["home"])

    # ---- drawing -----------------------------------------------------------------------
    def draw_map():
        cv = mapcv
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50:
            return
        fl = [f for f in trk.flights() if time.time() - f["last"] < 7200]
        far = max([10.0] + [SI.dist_nm(home["lat"], home["lon"], la, lo)
                            for f in fl for la, lo, _, _ in f["track"][-400:]])
        nm_r = 10 * math.ceil(far * 1.15 / 10)
        k = (min(w, h) / 2 - 24) / nm_r
        cx, cy = w / 2, h / 2

        def xy(lat, lon):
            d = SI.dist_nm(home["lat"], home["lon"], lat, lon)
            b = math.radians(SI.bearing_deg(home["lat"], home["lon"], lat, lon))
            return cx + d * k * math.sin(b), cy - d * k * math.cos(b)
        for ring in (nm_r / 4, nm_r / 2, nm_r * 3 / 4, nm_r):
            r = ring * k
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=T.night("#1f2a31"))
            cv.create_text(cx + 4, cy - r + 10, text="%d nm" % round(ring), anchor="w",
                           fill=T.TXT_3, font=F["map"])
        cv.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3, fill=S.GREEN, outline="")
        cv.create_text(cx + 8, cy + 8, text="you", anchor="nw", fill=T.TXT_3, font=F["map"])
        for f in fl:
            sel = f["id"] == st["sel"]
            col = S.AMBER if sel else T.night("#e8eaed")
            pts = [c for la, lo, _, _ in f["track"][-600:] for c in xy(la, lo)]
            if len(pts) >= 4:
                cv.create_line(*pts, fill=col, width=2 if sel else 1)
            x, y = xy(f["lat"], f["lon"])
            cv.create_oval(x - 6, y - 6, x + 6, y + 6, outline=col, width=2)
            cv.create_line(x, y + 6, x, y + 14, fill=col)
            if f["burst"] and len(f["track"]) > 2:
                bx, by = next(((xy(la, lo)) for la, lo, al, _ in f["track"]
                               if al >= f["burst"]["alt"] - 1), (x, y))
                if math.hypot(bx - x, by - y) > T.px(60):
                    cv.create_text(min(bx, w - T.px(70)), by - 12, text="✶ burst %s m" % format(int(f["burst"]["alt"]), ","),
                                   fill=S.RED, font=F["map"])
            land = trk.landing(f)
            if land:
                lx, ly = xy(land["lat"], land["lon"])
                cv.create_line(x, y, lx, ly, fill=col, dash=(3, 4))
                far_enough = math.hypot(lx - x, ly - y) > T.px(60)
                cv.create_text(min(lx, w - T.px(50)), ly + (12 if far_enough else 0),
                               text="✕ ~landing" if far_enough else "✕", fill=col, font=F["map"])
            flip = x > w - T.px(190)                   # keep labels on the canvas
            lx0, a1, a2 = (x - 10, "se", "ne") if flip else (x + 10, "sw", "nw")
            cv.create_text(lx0, y - 2, anchor=a1, font=F["mapb"], fill=S.TXT if not sel else col,
                           text="%s  %s" % (f["id"], f.get("model", "")))
            cv.create_text(lx0, y, anchor=a2, font=F["map"], fill=col,
                           text="%s m  %s" % (format(int(f["alt"]), ","), trk.phase(f)))
        if not fl:
            cv.create_text(w / 2, h / 2 + 40, fill=T.TXT_3, font=F["sm"],
                           text="No balloons heard yet." if st["proc"] else
                           "Press Listen near a launch time (about 11:00 / 23:00 UTC).")

    def draw_profile(f):
        prof.delete("all")
        w, h = prof.winfo_width(), int(prof.winfo_height())
        if w < 40 or not f or len(f["track"]) < 2:
            return
        t0, t1 = f["track"][0][3], f["track"][-1][3]
        hi = max(1000.0, f["max_alt"])
        pts = []
        n = len(f["track"])
        for i, (_, _, al, t) in enumerate(f["track"]):
            fx = (t - t0) / (t1 - t0) if t1 - t0 >= 1 else i / (n - 1)
            pts += [4 + fx * (w - 8), h - 6 - al / hi * (h - 18)]
        prof.create_line(*pts, fill=S.GREEN, width=1.5)
        prof.create_text(4, 2, anchor="nw", fill=T.TXT_3, font=F["map"],
                         text="altitude  ·  peak %s m" % format(int(f["max_alt"]), ","))

    def render():
        fl = trk.flights()
        flights_box.config(state="normal")
        flights_box.delete("1.0", "end")
        flights_box.insert("end", "%-12s %-6s %-9s %7s %6s\n" % ("SERIAL", "TYPE", "FREQ",
                                                                 "ALT m", "RANGE"), "hdr")
        for i, f in enumerate(fl[:6]):
            d = SI.dist_nm(home["lat"], home["lon"], f["lat"], f["lon"])
            tag = "f%d" % i
            flights_box.insert("end", "%-12s %-6s %-9s %7s %5.0fnm\n" % (
                f["id"][:12], (f.get("model") or "")[:6], f.get("freq", "").replace(" MHz", "")[:9],
                format(int(f["alt"]), ","), d), (tag,) + (("pick",) if f["id"] == st["sel"] else ()))
            flights_box.tag_bind(tag, "<Button-1>", lambda e, fid=f["id"]: (st.update(sel=fid),
                                                                           render()))
        flights_box.config(state="disabled")
        f = trk.s.get(st["sel"]) or (fl[0] if fl else None)
        if f and not st["sel"]:
            st["sel"] = f["id"]
        if f:
            d = SI.dist_nm(home["lat"], home["lon"], f["lat"], f["lon"])
            b = SI.bearing_deg(home["lat"], home["lon"], f["lat"], f["lon"])
            d_title.config(text=f["id"])
            d_sub.config(text="%s  ·  %s  ·  heard %ds ago" % (f.get("model", ""), f.get("freq", ""),
                                                                int(time.time() - f["last"])))
            vv = f.get("vel_v")
            vals = {"ALT": "%s m" % format(int(f["alt"]), ","),
                    "CLIMB": "%+.1f m/s" % vv if vv is not None else "—",
                    "PEAK": "%s m" % format(int(f["max_alt"]), ","), "PHASE": trk.phase(f),
                    "TEMP": "%.1f°C" % f["temp"] if f.get("temp") is not None else "—",
                    "HUMID": "%.0f%%" % f["humidity"] if f.get("humidity") is not None else "—",
                    "PRESS": "%.0f hPa" % f["pressure"] if f.get("pressure") is not None else "—",
                    "BATT": "%.1f V" % f["batt"] if f.get("batt") is not None else "—",
                    "RANGE": "%.1f nm" % d, "BRG": "%03d°" % b}
            for k2, v in vals.items():
                rows[k2].config(text=v)
            draw_profile(f)
        draw_map()

    # ---- auto_rx process -----------------------------------------------------------------
    def listener():
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sk.bind(("127.0.0.1", SUMMARY_PORT))       # localhost only
        except OSError as e:
            q.put(("status", "can't listen on 127.0.0.1:%d (%s)" % (SUMMARY_PORT, e)))
            return
        sk.settimeout(1.0)
        while st["listening"]:
            try:
                data, _ = sk.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            t = parse_summary(data)
            if t:
                q.put(("telem", t))
        sk.close()

    def start(reason="manual"):
        if st["proc"] or st["starting"]:
            return
        if not installed():
            status.config(text="auto_rx isn't installed. Run once:  bash %s" %
                          os.path.join(HERE, "install_radiosonde.sh"), fg=S.AMBER)
            return
        st["starting"] = True
        state_pill.config(text="Starting", bg=S.AMBER)
        status.config(text="Taking the SDR from the plane map…", fg=T.TXT_3)

        def done(ok, err):
            if not st["starting"]:
                return
            st["starting"] = False
            if not ok:
                state_pill.config(text="Off", bg=S.DIM)
                status.config(text="SDR busy: %s" % str(err)[:80], fg=S.RED)
                return
            try:
                ex = open(os.path.join(ARX_DIR, "station.cfg.example")).read()
                with open(os.path.join(ARX_DIR, "station.cfg"), "w") as fh:
                    fh.write(make_station_cfg(ex, home, s))
                logf = S.errfile(os.path.join(S.CACHE, "auto_rx.log"))
                st["proc"] = subprocess.Popen([ARX_PY, "auto_rx.py"], cwd=ARX_DIR,
                                              stdout=logf, stderr=subprocess.STDOUT,
                                              start_new_session=True)
                logf.close()
            except OSError as e:
                S.release_bg(root, lease)
                state_pill.config(text="Off", bg=S.DIM)
                status.config(text="couldn't start auto_rx: %s" % e, fg=S.RED)
                return
            st["listening"] = True
            threading.Thread(target=listener, daemon=True).start()
            state_pill.config(text="Scanning", bg=S.GREEN)
            T.set_btn(listen_btn, "Stop", kind="danger")
            status.config(text="auto_rx scanning (%s). Its web UI is local only: "
                               "http://127.0.0.1:5000" % reason, fg=T.TXT_3)
            slog.event("balloons", "auto_rx started (%s)" % reason)
        S.acquire_bg(root, lease, done)

    def stop(sync=False):
        was_starting, st["starting"] = st["starting"], False
        st["listening"] = False
        p, st["proc"] = st["proc"], None
        if p:
            S.stop_group(p, grace=6.0)      # auto_rx's rtl_fm/rtl_power children go with it
        if p or was_starting:
            S.release_now(lease) if sync else S.release_bg(root, lease)
        state_pill.config(text="Off", bg=S.DIM)
        try:
            T.set_btn(listen_btn, "Listen", kind="primary")
        except Exception:
            pass

    def toggle(_=None):
        stop() if (st["proc"] or st["starting"]) else start()

    def toggle_auto(_=None):
        s["auto"] = not s["auto"]
        try:
            S.save_json(spath, s)
        except OSError:
            pass
        T.set_btn(auto_btn, "Auto: ON" if s["auto"] else "Auto: off",
                  kind="primary" if s["auto"] else "ghost")
        status.config(text="Auto: listens from 15 min before each launch time for 2.5 h"
                      if s["auto"] else "Auto off", fg=T.TXT_3)

    def auto_tick():
        if not s["auto"]:
            return
        now = time.time()
        g = time.gmtime(now)
        day0 = now - (g.tm_hour * 3600 + g.tm_min * 60 + g.tm_sec)
        win = None
        for add in (-1, 0):
            for hr in LAUNCH_HOURS_UTC:
                t = day0 + add * 86400 + hr * 3600
                if t - 900 <= now <= t + 9000:
                    win = t
        if win and not st["proc"] and not st["starting"] and st["auto_win"] != win:
            st["auto_win"] = win
            start("launch %02d:00Z" % time.gmtime(win).tm_hour)
        elif not win and st["auto_win"] and st["proc"]:
            st["auto_win"] = None
            stop()

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    listen_btn = S.btn(bar, "Listen", toggle, F, padx=14, pady=5, kind="primary")
    listen_btn.pack(side="left", padx=(10, 6), pady=6)
    auto_btn = S.btn(bar, "Auto: ON" if s["auto"] else "Auto: off", toggle_auto, F, padx=10,
                     pady=5, kind="primary" if s["auto"] else "ghost")
    auto_btn.pack(side="left", padx=2)
    S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
        side="right", padx=(2, 10))
    root.bind("<space>", toggle)
    root.bind("a", toggle_auto)
    mapcv.bind("<Configure>", lambda e: draw_map())

    last_dump = [0.0]
    last_render = [0.0]

    def pump():
        changed = False
        try:
            while True:
                item = q.get_nowait()
                if item[0] == "telem":
                    f = trk.add(item[1])
                    changed = True
                    if len(f["track"]) == 1:
                        slog.event("balloons", "new sonde %s %s %s" % (f["id"], f.get("model", ""),
                                                                      f.get("freq", "")), id=f["id"])
                elif item[0] == "status":
                    status.config(text=item[1], fg=S.AMBER)
        except queue.Empty:
            pass
        try:
            if st["proc"] and st["proc"].poll() is not None:
                status.config(text="auto_rx exited - see %s" % os.path.join(S.CACHE, "auto_rx.log"),
                              fg=S.RED)
                stop()
            auto_tick()
            nl = next_launch()
            if nl is not None:
                m = int(nl / 60)
                launch_pill.config(text="launch in %dh%02d" % (m // 60, m % 60),
                                   bg=S.DIM)
            if changed or (trk.s and time.time() - last_render[0] > 2):
                last_render[0] = time.time()
                render()
            if changed and time.time() - last_dump[0] > 5:
                last_dump[0] = time.time()
                try:
                    trk.dump(FEED_PATH)
                except OSError:
                    pass
        except Exception as e:     # keep pumping
            print("balloons pump: %r" % e, file=sys.stderr)
        root.after(500, pump)

    def on_close():
        stop(sync=True)
        root.destroy()

    S.bind_quit(root, on_close)
    if not installed():
        status.config(text="auto_rx isn't installed yet. One-time setup (needs internet, "
                           "~5 min):  bash %s" % os.path.join(HERE, "install_radiosonde.sh"),
                      fg=S.AMBER)
    for path in sys.argv[1:]:                  # replay a captured summary log: --replay FILE
        if path.startswith("--replay="):
            try:
                lines = open(path.split("=", 1)[1]).read().splitlines()[-5000:]
                t0 = time.time() - len(lines)          # replay at 1 frame/s, ending now
                for i, ln in enumerate(lines):
                    t = parse_summary(ln.strip())
                    if t:
                        trk.add(t, now=t0 + i)
            except OSError:
                pass
    if "--listen" in sys.argv and installed():
        root.after(300, lambda: start("autopilot"))
    render()
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
