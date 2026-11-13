#!/usr/bin/env python3
"""
Field status: GPS (gpsd), satellite sky plot, battery, CPU temperature/clock, fan,
throttling, plus a thermal history graph, CSV logging and a CPU load test for
checking the Omega heatsink.
"""

import collections
import csv
import glob
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402

GPS = {"tpv": None, "sky": None, "t": 0, "state": "starting"}


def gps_read(sock):
    """Read gpsd reports from a connected socket into GPS until EOF.
    A quiet gpsd (no receiver attached, or idle) is not a dead one: recv() timeouts just
    keep waiting instead of reporting "gpsd isn't running"."""
    buf = b""
    while True:
        try:
            chunk = sock.recv(8192)
        except socket.timeout:
            if GPS["state"] not in ("fix", "nofix"):
                GPS["state"] = "waiting"
            continue
        if not chunk:
            return
        buf += chunk
        *lines, buf = buf.split(b"\n")
        for ln in lines:
            try:
                m = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(m, dict):
                continue            # m.get() on a list/number would kill this thread for good
            if m.get("class") == "TPV":
                mode = m.get("mode", 0)
                GPS["tpv"], GPS["t"] = m, time.time()
                GPS["state"] = "fix" if isinstance(mode, int) and mode >= 2 else "nofix"
            elif m.get("class") == "SKY" and m.get("satellites") is not None:
                GPS["sky"] = m


def gpsd_thread():
    while True:
        try:
            with socket.create_connection(("127.0.0.1", 2947), timeout=5) as sock:
                sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
                sock.settimeout(10)
                GPS["state"] = "waiting"
                gps_read(sock)
            time.sleep(1)           # gpsd closed on us: don't reconnect in a tight loop
        except OSError:
            GPS["state"] = "nogpsd"
            time.sleep(5)


def cpu_freq_mhz():
    fs = []
    for p in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"):
        v = S.read(p)
        if v and v.isdigit():
            fs.append(int(v) / 1000)
    return sum(fs) / len(fs) if fs else None


_prev_cpu = [None]


def cpu_percent():
    try:
        vals = [int(x) for x in open("/proc/stat").readline().split()[1:]]
    except OSError:
        return None
    idle, total = vals[3] + vals[4], sum(vals)
    prev = _prev_cpu[0]
    _prev_cpu[0] = (idle, total)
    if not prev or total == prev[1]:
        return None
    return 100.0 * (1 - (idle - prev[0]) / (total - prev[1]))


def fan():
    """(rpm or None, pwm% or None)."""
    rpm = pwm = None
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        for f in glob.glob(os.path.join(d, "fan*_input")):
            v = S.read(f)
            if v and v.isdigit():
                rpm = int(v)
        for f in glob.glob(os.path.join(d, "pwm[0-9]")):
            v = S.read(f)
            if v and v.isdigit():
                pwm = round(int(v) / 255 * 100)
    if pwm is None:
        for d in glob.glob("/sys/class/thermal/cooling_device*"):
            if "fan" in (S.read(os.path.join(d, "type")) or ""):
                cur, mx = S.read(os.path.join(d, "cur_state")), S.read(os.path.join(d, "max_state"))
                if cur and mx and mx.isdigit() and int(mx) > 0:
                    pwm = round(int(cur) / int(mx) * 100)
    return rpm, pwm


THROTTLE_BITS = {0: "under-voltage now", 1: "freq capped now", 2: "throttled now",
                 3: "soft temp limit now", 16: "under-voltage seen", 17: "freq capped seen",
                 18: "throttled seen", 19: "soft temp limit seen"}


def throttled():
    if not shutil.which("vcgencmd"):
        return None
    rc, out = S.run(["vcgencmd", "get_throttled"], timeout=3)
    if rc != 0 or "=" not in out:
        return None
    try:
        v = int(out.split("=")[1].strip(), 16)
    except ValueError:
        return None
    return [txt for bit, txt in THROTTLE_BITS.items() if v & (1 << bit)]


def meminfo():
    m = {}
    try:
        for ln in open("/proc/meminfo"):
            k, v = ln.split(":")
            m[k] = int(v.split()[0])
        return (m["MemTotal"] - m["MemAvailable"]) / 1024, m["MemTotal"] / 1024
    except (OSError, KeyError, ValueError):
        return None, None


def main():
    S.single_instance("Field Status")
    root, F = S.make_root("Field Status")
    import tkinter as tk
    if not GPS.get("_thread"):              # one reader, however often the workspace reopens
        GPS["_thread"] = True
        threading.Thread(target=gpsd_thread, daemon=True).start()

    S.power_banner(root, F).pack(side="top", fill="x")
    top = S.top_bar(root, F, "Field Status", "uConsole")
    gps_pill = S.pill(top, F, "GPS")
    bat_pill = S.pill(top, F, "Battery")
    temp_pill = S.pill(top, F, "CPU")
    T = S.T

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)

    # left: GPS
    leftw = tk.Frame(body, bg=T.SURFACE, width=S.T.px(330))
    leftw.pack(side="left", fill="y")
    leftw.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    left = tk.Frame(leftw, bg=T.SURFACE)
    left.pack(fill="both", expand=True, padx=18, pady=16)
    T.section(left, F, "Position").pack(fill="x", pady=(0, 8))
    pos_lbl = tk.Label(left, text="", font=F["mono"], fg=S.TXT, bg=T.SURFACE, justify="left",
                       anchor="nw")
    pos_lbl.pack(fill="x")
    sec_sky = T.section(left, F, "Satellites")
    sec_sky.pack(fill="x", pady=(18, 0))
    sky = tk.Canvas(left, bg=T.SURFACE, highlightthickness=0, height=S.T.px(250))
    sky.pack(fill="both", expand=True, pady=(4, 0))
    tmap = tk.Canvas(left, bg=S.MAPBG, highlightthickness=0, height=S.T.px(250))
    import tiles as TL
    basemap = TL.TileLayer(on_ready=lambda ok: root.after(0, lambda: tile_tick()),
                           workers=1 if S.low_power() else 3)
    fcfg = S.load_json(os.path.join(S.CFG, "field.json"), {}) or {}
    basemap.layer = fcfg.get("map_layer", "dark") if fcfg.get("map_layer") in TL.LAYER_ORDER else "dark"
    mview = {"z": int(fcfg.get("map_zoom", 14)), "mode": "sky", "job": None}
    track = {"pts": [], "on": False, "path": None, "dist_m": 0.0, "t0": None, "saved": 0}

    def tile_tick():
        if mview["job"] is None:
            mview["job"] = root.after(120, lambda: (mview.__setitem__("job", None), draw_track_map()))

    def save_fcfg():
        d = S.load_json(os.path.join(S.CFG, "field.json"), {}) or {}
        d["map_zoom"], d["map_layer"] = mview["z"], basemap.layer
        try:
            S.save_json(os.path.join(S.CFG, "field.json"), d)
        except OSError:
            pass

    def show_mode(mode):
        mview["mode"] = mode
        if mode == "sky":
            tmap.pack_forget()
            sky.pack(fill="both", expand=True, pady=(4, 0))
            sec_sky.winfo_children()[0].config(text=T.spaced("Satellites"))
            draw_sky()
        else:
            sky.pack_forget()
            tmap.pack(fill="both", expand=True, pady=(4, 0))
            sec_sky.winfo_children()[0].config(text=T.spaced("Track"))
            draw_track_map()

    def draw_track_map():
        tmap.delete("all")
        w, h = tmap.winfo_width(), tmap.winfo_height()
        if w < 20 or mview["mode"] != "track":
            return
        g = GPS["tpv"] or {}
        if track["pts"]:
            clat, clon = track["pts"][-1][1], track["pts"][-1][2]
        elif g.get("mode", 0) >= 2:
            clat, clon = g["lat"], g["lon"]
        else:
            clat, clon = 39.715, -104.76
            tmap.create_text(w / 2, 16, text="Waiting for a GPS fix", fill=T.TXT_3, font=F["map"])
        z = mview["z"]
        missing = basemap.draw(tmap, clat, clon, z, w, h)
        cx0, cy0 = TL.world_px(clat, clon, z)

        def proj(la, lo):
            x, y = TL.world_px(la, lo, z)
            return w / 2 + (x - cx0), h / 2 + (y - cy0)

        if len(track["pts"]) > 1:
            coords = []
            for _, la, lo, _alt in track["pts"][-3000:]:
                coords += proj(la, lo)
            tmap.create_line(*coords, fill=T.ACCENT, width=2)
            sx, sy = proj(track["pts"][0][1], track["pts"][0][2])
            tmap.create_rectangle(sx - 4, sy - 4, sx + 4, sy + 4, outline=T.TXT_2)
        if g.get("mode", 0) >= 2:
            x, y = proj(g["lat"], g["lon"])
            trk = g.get("track")
            if trk is not None and (g.get("speed") or 0) > 0.5:
                a = math.radians(trk)
                pts = [(0, -9), (6, 7), (0, 4), (-6, 7)]
                poly = []
                for px, py in pts:
                    poly += [x + px * math.cos(a) - py * math.sin(a), y + px * math.sin(a) + py * math.cos(a)]
                tmap.create_polygon(*poly, fill=T.ACCENT, outline="")
            else:
                tmap.create_oval(x - 6, y - 6, x + 6, y + 6, outline=T.ACCENT, width=2)
                tmap.create_oval(x - 2, y - 2, x + 2, y + 2, fill=T.ACCENT, outline="")
            if g.get("eph"):
                r = g["eph"] * TL.px_per_nm(clat, z) / 1852.0
                if 8 < r < w:
                    tmap.create_oval(x - r, y - r, x + r, y + r, outline=T.ACCENT_BG)
        T.scale_bar(tmap, 12, h - 12, TL.px_per_nm(clat, z) / 1.852, F, unit="km")
        if track["on"]:
            dur = int(time.time() - track["t0"]) if track["t0"] else 0
            tmap.create_text(w - 10, 8, anchor="ne", fill=T.ACCENT, font=F["map"],
                             text="REC  %.2f km  %02d:%02d" % (track["dist_m"] / 1000, dur // 60, dur % 60))
        elif track["pts"]:
            tmap.create_text(w - 10, 8, anchor="ne", fill=T.TXT_3, font=F["map"],
                             text="%.2f km  ·  %d points" % (track["dist_m"] / 1000, len(track["pts"])))
        if missing and not basemap.online:
            tmap.create_text(12, 8, anchor="nw", fill=T.TXT_3, font=F["map"], text="offline tiles")

    def mzoom(d):
        z = max(6, min(17, mview["z"] + d))
        if z != mview["z"]:
            mview["z"] = z
            save_fcfg()
            draw_track_map()

    def mlayer():
        basemap.cycle()
        save_fcfg()
        draw_track_map()

    tmap.bind("<Button-4>", lambda e: mzoom(+1))
    tmap.bind("<Button-5>", lambda e: mzoom(-1))
    tmap.bind("<Button-1>", lambda e: mlayer())
    sw = tk.Frame(sec_sky, bg=T.SURFACE)
    sw.pack(side="right")
    for t, m in (("Sats", "sky"), ("Track", "track")):
        S.btn(sw, t, lambda m=m: show_mode(m), F, padx=6, pady=0, kind="quiet").pack(side="left")
    for t, d in (("−", -1), ("+", +1)):
        S.btn(sw, t, lambda d=d: mzoom(d), F, padx=6, pady=0, kind="quiet").pack(side="left")

    # right: system + history
    right = tk.Frame(body, bg=S.BG)
    right.pack(side="left", fill="both", expand=True, padx=22, pady=16)
    T.section(right, F, "System").pack(fill="x", pady=(0, 8))
    tiles = tk.Frame(right, bg=S.BG)
    tiles.pack(fill="x")
    tile_lbls = {}
    for i, key in enumerate(("Battery", "Power", "CPU temp", "CPU clock", "CPU load", "Fan",
                             "Memory", "Disk")):
        f = tk.Frame(tiles, bg=S.BG)
        f.grid(row=i // 4, column=i % 4, sticky="nsew", padx=(0, 12), pady=(0, 14))
        tiles.columnconfigure(i % 4, weight=1, uniform="t")
        tk.Label(f, text=key, font=F["sm"], fg=T.TXT_3, bg=S.BG, anchor="w").pack(fill="x")
        v = tk.Label(f, text="—", font=F["data"], fg=S.TXT, bg=S.BG, anchor="w")
        v.pack(fill="x")
        sub = tk.Label(f, text="", font=F["map"], fg=T.TXT_3, bg=S.BG, anchor="w")
        sub.pack(fill="x")
        sp = tk.Canvas(f, bg=S.BG, highlightthickness=0, height=S.T.px(24))
        sp.pack(fill="x", pady=(4, 0))
        tile_lbls[key] = (v, sub, sp)
    tile_hist = {k: collections.deque(maxlen=120) for k in tile_lbls}
    warn = tk.Label(right, text="", font=F["sm"], fg=S.AMBER, bg=S.BG, anchor="w")
    warn.pack(fill="x")
    T.section(right, F, "Thermal history").pack(fill="x", pady=(6, 4))
    ctl = tk.Frame(right, bg=S.BG)
    ctl.pack(side="bottom", fill="x")
    graph = tk.Canvas(right, bg=S.BG, highlightthickness=0, height=S.T.px(60))
    graph.pack(fill="both", expand=True, pady=(0, 8))

    hist = collections.deque(maxlen=900)  # 15 min @ 1 Hz
    st = {"csv": None, "csvw": None, "load": None, "load_until": 0}

    def toggle_csv():
        if st["csv"]:
            st["csv"].close()
            st["csv"] = st["csvw"] = None
            S.set_btn(csv_btn, "Record CSV", "ghost")
            warn.config(text="Saved log in %s" % S.DATA, fg=S.MUTED)
        else:
            path = os.path.join(S.DATA, time.strftime("thermal_%Y%m%d_%H%M%S.csv"))
            st["csv"] = open(path, "w", newline="")
            st["csvw"] = csv.writer(st["csv"])
            st["csvw"].writerow(["time", "cpu_c", "cpu_mhz", "cpu_pct", "fan_rpm", "fan_pct",
                                 "batt_pct", "watts", "load_test"])
            S.set_btn(csv_btn, "Stop recording", "danger")
            warn.config(text="Recording to " + path, fg=S.MUTED)

    def toggle_load():
        if st["load"]:
            S.stop_group(st["load"], grace=1)
            st["load"] = None
            S.set_btn(load_btn, "Run 10-min load test", "ghost")
            return
        n = os.cpu_count() or 4
        if shutil.which("stress-ng"):
            cmd = ["stress-ng", "--cpu", str(n), "--timeout", "600s", "--quiet"]
        else:
            cmd = [sys.executable, "-c",
                   "import multiprocessing as m,time\n"
                   "def b():\n t=time.time()+600\n while time.time()<t: pass\n"
                   "ps=[m.Process(target=b) for _ in range(%d)]\n[p.start() for p in ps]\n"
                   "[p.join() for p in ps]" % n]
        st["load"] = S.spawn(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        S.set_btn(load_btn, "Stop load test", "danger")

    def write_gpx():
        if not track["pts"]:
            return None
        path = track["path"] or os.path.join(S.DATA, time.strftime("track_%Y%m%d_%H%M%S.gpx",
                                                                   time.localtime(track["pts"][0][0])))
        track["path"] = path
        os.makedirs(S.DATA, exist_ok=True)
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<gpx version="1.1" creator="uconsole-suite Field Status" xmlns="http://www.topografix.com/GPX/1/1">',
               "<trk><name>%s</name><trkseg>" % time.strftime("%Y-%m-%d %H:%M", time.localtime(track["pts"][0][0]))]
        for t, la, lo, alt in track["pts"]:
            ele = ("<ele>%.1f</ele>" % alt) if alt is not None else ""
            out.append('<trkpt lat="%.7f" lon="%.7f">%s<time>%s</time></trkpt>' % (
                la, lo, ele, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))))
        out.append("</trkseg></trk></gpx>")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(out))
        os.replace(tmp, path)
        track["saved"] = len(track["pts"])
        return path

    def toggle_track():
        if track["on"]:
            track["on"] = False
            p = write_gpx()
            S.set_btn(trk_btn, "Record track", "ghost")
            warn.config(text=("Track saved: %s" % p) if p else "No positions recorded (no fix).", fg=S.MUTED)
        else:
            track.update({"pts": [], "on": True, "path": None, "dist_m": 0.0, "t0": time.time(), "saved": 0})
            S.set_btn(trk_btn, "Stop track", "danger")
            show_mode("track")
            warn.config(text="Recording GPS track (saved as GPX in %s when you stop)." % S.DATA, fg=S.MUTED)

    def track_sample(g):
        if not track["on"] or g.get("mode", 0) < 2 or "lat" not in g:
            return
        la, lo = g["lat"], g["lon"]
        alt = g.get("altMSL", g.get("alt"))
        if track["pts"]:
            _, pla, plo, _ = track["pts"][-1]
            d = S.core.dist_nm(pla, plo, la, lo) * 1852.0 if hasattr(S.core, "dist_nm") else \
                math.hypot((la - pla) * 110574, (lo - plo) * 111320 * math.cos(math.radians(la)))
            if d < max(3.0, (g.get("eph") or 0) * 0.5):
                return
            track["dist_m"] += d
        track["pts"].append((time.time(), la, lo, alt))
        if len(track["pts"]) - track["saved"] >= 60:
            write_gpx()          # autosave every ~60 points so a crash or dead battery keeps the track

    trk_btn = S.btn(ctl, "Record track", toggle_track, F)
    trk_btn.pack(side="left", padx=(0, 8))
    csv_btn = S.btn(ctl, "Record CSV", toggle_csv, F)
    csv_btn.pack(side="left")
    load_btn = S.btn(ctl, "Run 10-min load test", toggle_load, F)
    load_btn.pack(side="left", padx=8)
    S.btn(ctl, "Quit", lambda: on_close(), F, kind="quiet").pack(side="right")

    def draw_sky():
        sky.delete("all")
        w, h = sky.winfo_width(), sky.winfo_height()
        if w < 20:
            return
        cx, cy, R = w / 2, h / 2 + 4, min(w, h) / 2 - 22
        for el in (0, 30, 60):
            r = R * (90 - el) / 90
            sky.create_oval(cx - r, cy - r, cx + r, cy + r, outline=S.T.RING)
        sky.create_line(cx - R, cy, cx + R, cy, fill=S.T.RING)
        T.compass_ring(sky, cx, cy, R, F, labels=False)
        for el in (30, 60):
            sky.create_text(cx + 3, cy - R * (90 - el) / 90, text="%d°" % el, fill=T.TXT_3,
                            font=F["map"], anchor="sw")
        sky.create_line(cx, cy - R, cx, cy + R, fill=S.T.RING)
        for t, x, y in (("N", cx, cy - R - 10), ("E", cx + R + 10, cy), ("S", cx, cy + R + 10),
                        ("W", cx - R - 10, cy)):
            sky.create_text(x, y, text=t, fill=S.T.TXT_3, font=F["map"])
        sats = (GPS["sky"] or {}).get("satellites") or []
        used = 0
        for sv in sats:
            az, el = sv.get("az"), sv.get("el")
            if az is None or el is None or el < 0:
                continue
            r = R * (90 - el) / 90
            x, y = cx + r * math.sin(math.radians(az)), cy - r * math.cos(math.radians(az))
            if sv.get("used"):
                used += 1
                sky.create_oval(x - 5, y - 5, x + 5, y + 5, fill=T.TRACK, outline="")
            else:
                sky.create_oval(x - 5, y - 5, x + 5, y + 5, outline=T.TXT_3, width=1.2)
            sky.create_text(x + 8, y, text="%s" % sv.get("PRN", sv.get("svid", "")),
                            fill=T.TXT_2 if sv.get("used") else T.TXT_3, font=F["map"], anchor="w")
        sky.create_text(w - 2, 2, anchor="ne", text="%d used / %d seen" % (used, len(sats)), fill=T.TXT_3,
                        font=F["map"])

    def draw_graph():
        graph.delete("all")
        w, h = graph.winfo_width(), graph.winfo_height()
        if w < 50 or len(hist) < 2:
            graph.create_text(w / 2, h / 2, text="Collecting thermal history…", fill=S.DIM,
                              font=F["sm"])
            return
        pad_l = F["map"].measure("90°") + 10
        pad_b = F["map"].metrics("linespace") + 6
        pad_t = F["map"].metrics("linespace") + 6
        gw, gh = w - pad_l - 10, h - pad_b - pad_t
        temps = [r[1] for r in hist if r[1] is not None]
        lo = min(30, int(min(temps) // 10 * 10)) if temps else 30
        hi = max(90, int(max(temps) // 10 * 10 + 10)) if temps else 90
        for v in range(lo, hi + 1, 10):
            y = pad_t + gh * (1 - (v - lo) / (hi - lo))
            graph.create_line(pad_l, y, w - 10, y, fill=S.GRID)
            graph.create_text(pad_l - 6, y, text="%d°" % v, anchor="e", fill=S.DIM, font=F["map"])
        t0, t1 = hist[0][0], hist[-1][0]
        span = max(60, t1 - t0)

        def xy(t, v, vlo, vhi):
            return pad_l + gw * (1 - (t1 - t) / span), pad_t + gh * (1 - (v - vlo) / (vhi - vlo))

        for idx, col, vlo, vhi in ((3, T.TXT_3, 0, 100), (5, T.TXT_2, 0, 100), (1, S.AMBER, lo, hi)):
            pts = []
            for r in hist:
                if r[idx] is not None:
                    pts += xy(r[0], r[idx], vlo, vhi)
            if len(pts) >= 4:
                graph.create_line(*pts, fill=col, width=2 if idx == 1 else 1)
        lx = pad_l + 4
        for txt, col in (("CPU °C", S.AMBER), ("CPU load %", T.TXT_3), ("Fan %", T.TXT_2)):
            graph.create_text(lx, 2, anchor="nw", font=F["map"], fill=col, text=txt)
            lx += F["map"].measure(txt) + T.px(18)
        graph.create_text(w - 12, h - 4, anchor="se", font=F["map"], fill=S.DIM,
                          text="last %d min" % max(1, round(span / 60)))
        if st["load"]:
            graph.create_text(w - 12, 4, anchor="ne", font=F["mapb"], fill=S.RED,
                              text="Load test running")

    thr_state = {"v": None, "t": 0, "busy": False}

    def refresh_throttle():
        if thr_state["busy"] or time.time() - thr_state["t"] < 10:
            return
        thr_state["busy"] = True

        def work():
            try:
                thr_state["v"] = throttled()
            finally:
                thr_state["t"] = time.time()
                thr_state["busy"] = False
        S.in_thread(work)

    def sample():
        try:
            _sample()
        except Exception as e:
            warn.config(text="Display error: %s" % str(e)[:80], fg=S.RED)
        root.after(1000, sample)

    def _sample():
        now = time.time()
        t = S.cpu_temp()
        mhz = cpu_freq_mhz()
        pct = cpu_percent()
        rpm, pwm = fan()
        cap, bst, volts, watts = S.battery()
        hist.append((now, t, mhz, pct, rpm, pwm))
        if st["csvw"]:
            st["csvw"].writerow([time.strftime("%Y-%m-%d %H:%M:%S"), t, mhz and round(mhz),
                                 pct and round(pct, 1), rpm, pwm, cap, watts and round(watts, 2),
                                 1 if st["load"] else 0])
            st["csv"].flush()
        if st["load"] and st["load"].poll() is not None:
            st["load"] = None
            S.set_btn(load_btn, "Run 10-min load test", "ghost")

        # tiles
        def tile(k, v, sub="", col=S.TXT, num=None, vmax=None):
            tile_lbls[k][0].config(text=v, fg=col)
            tile_lbls[k][1].config(text=sub)
            sp = tile_lbls[k][2]
            tile_hist[k].append(num)
            sp.delete("all")
            w = sp.winfo_width()
            if w > 20:
                sp.create_line(0, 23, w, 23, fill=S.LINE)
                T.sparkline(sp, 0, 2, w, 20, list(tile_hist[k]), color=col if col != S.TXT else T.TXT_2,
                            fill=T._mix(T.TXT_3, S.BG, 0.75), vmax=vmax)
        tile("Battery", "%d%%" % cap if cap is not None else "—", bst,
             S.RED if cap is not None and cap < 15 else S.TXT, cap, 100)
        tile("Power", "%.1f W" % abs(watts) if watts is not None else "—",
             "%.2f V" % volts if volts else "", num=abs(watts) if watts is not None else None)
        tile("CPU temp", "%.0f°C" % t if t is not None else "—", "",
             S.RED if t and t >= 80 else (S.AMBER if t and t >= 70 else S.TXT), t, 90)
        tile("CPU clock", "%.0f MHz" % mhz if mhz else "—", "%d cores" % (os.cpu_count() or 0),
             num=mhz)
        la = os.getloadavg()
        tile("CPU load", "%.0f%%" % pct if pct is not None else "—", "load %.2f" % la[0],
             num=pct, vmax=100)
        tile("Fan", ("%d rpm" % rpm) if rpm else ("%d%%" % pwm if pwm is not None else "—"),
             ("%d%% PWM" % pwm if rpm and pwm is not None else
              ("" if pwm is not None or rpm else "no fan sensor exposed")), num=rpm or pwm)
        used, total = meminfo()
        tile("Memory", "%.1f GB" % (used / 1024) if used else "—",
             "of %.1f GB" % (total / 1024) if total else "", num=used, vmax=total)
        du = shutil.disk_usage("/")
        tile("Disk", "%d%%" % (du.used * 100 / du.total), "%.0f GB free" % (du.free / 1e9),
             num=du.used * 100 / du.total, vmax=100)
        refresh_throttle()
        thr = thr_state["v"]
        warn.config(text=("Throttling: " + ", ".join(thr)) if thr else "", fg=S.AMBER)

        # pills
        temp_pill.config(text="CPU %s" % ("%.0f°C" % t if t else "n/a"),
                         bg=S.DIM if t is None else (S.RED if t >= 80 else (S.AMBER if t >= 70 else S.GREEN)))
        bat_pill.config(text="Battery %s" % ("%d%%" % cap if cap is not None else "n/a"),
                        bg=S.RED if cap is not None and cap < 15 else (S.GREEN if cap else S.DIM))
        g = GPS["tpv"] or {}
        gs = GPS["state"]
        if gs == "nogpsd":
            gps_pill.config(text="GPS no gpsd", bg=S.DIM)
            pos_lbl.config(text="gpsd isn't running.\n\nOn the AIO board the GPS (/dev/ttyAMA0)\n"
                           "may be owned by meshtasticd. Run\n  sudo systemctl start gpsd\n"
                           "or see the Mesh app for its position.")
        else:
            fix = g.get("mode", 0)
            gps_pill.config(text="GPS %s" % {0: "no data", 1: "no fix", 2: "2D fix", 3: "3D fix"}.get(fix, "?"),
                            bg=S.GREEN if fix == 3 else (S.AMBER if fix == 2 else S.DIM))
            if fix >= 2:
                spd = g.get("speed")
                alt = g.get("altMSL", g.get("alt"))
                lines = ["%.6f°  %.6f°" % (g["lat"], g["lon"]),
                         "Alt   %s" % ("%.0f ft (%.0f m)" % (alt * 3.28084, alt) if alt is not None else "—"),
                         "Speed %s" % ("%.1f mph" % (spd * 2.23694) if spd is not None else "—"),
                         "Track %s" % ("%03.0f°" % g["track"] if g.get("track") is not None else "—"),
                         "Error ±%s" % ("%.0f m" % g["eph"] if g.get("eph") else "—"),
                         "Time  %s" % (g.get("time", "")[11:19] + " UTC")]
                pos_lbl.config(text="\n".join(lines))
            else:
                pos_lbl.config(text="Waiting for a fix…\n\nGo outside with a clear view of the sky.\n"
                               "A cold start can take a few minutes.")
        track_sample(g)
        if mview["mode"] == "sky":
            draw_sky()
        else:
            draw_track_map()
        draw_graph()

    def on_close():
        if track["on"]:
            write_gpx()
        if st["load"]:
            S.stop_group(st["load"], grace=1)
        if st["csv"]:
            st["csv"].close()
        root.destroy()

    S.bind_quit(root, on_close)
    root.bind("q", lambda e: on_close())
    if "--track" in sys.argv:
        root.after(400, toggle_track)
    root.after(300, sample)
    root.mainloop()


if __name__ == "__main__":
    main()
