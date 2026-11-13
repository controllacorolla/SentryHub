#!/usr/bin/env python3
"""
Weather-satellite passes and capture for the uConsole.

NOAA-15/18/19 (APT) were all decommissioned in 2025, so this targets the Meteor-M2 3
and M2 4 LRPT downlinks at 137 MHz, decoded by SatDump. Predicts passes with Skyfield
from Celestrak TLEs, alerts before each pass, and (if armed) records + decodes it,
then shows the images.
"""

import glob
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402

DEFAULTS = {
    "satellites": [
        {"name": "METEOR-M2 3", "norad": 57166, "freq": 137.9},
        {"name": "METEOR-M2 4", "norad": 59051, "freq": 137.9},
    ],
    "min_elevation": 25,
    "auto_capture": False,
    "home": {"lat": 39.62, "lon": -104.87, "alt_m": 1750},
    "source": "rtlsdr",        # or "hackrf" to capture on the H4M (map keeps running)
    "gain": 40,
    "samplerate": 1024000,
    "tle_urls": ["https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle"],
}
TLE_PATH = os.path.join(S.CACHE, "weather.tle")
CAP_DIR = os.path.join(S.DATA, "wxsat")


def fetch_tles(s, force=False, path=None):
    TLE_PATH = path or globals()["TLE_PATH"]   # other apps (SSTV) keep their own TLE file
    if not force and os.path.exists(TLE_PATH) and time.time() - os.path.getmtime(TLE_PATH) < 86400:
        return "cached"
    want = {str(x["norad"]) for x in s["satellites"]}
    for url in s["tle_urls"]:
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                txt = r.read().decode()
            if any(("1 %s" % n) in txt for n in want):
                open(TLE_PATH, "w").write(txt)
                return "updated"
        except Exception:
            continue
    # per-satellite fallback
    out = []
    for n in want:
        try:
            with urllib.request.urlopen("https://celestrak.org/NORAD/elements/gp.php?CATNR=%s&FORMAT=tle"
                                        % n, timeout=15) as r:
                out.append(r.read().decode().strip())
        except Exception:
            pass
    if out:
        open(TLE_PATH, "w").write("\n".join(out) + "\n")
        return "updated"
    return "offline" if os.path.exists(TLE_PATH) else "none"


def load_sats(s, path=None):
    from skyfield.api import EarthSatellite, load
    ts = load.timescale()
    try:
        lines = [l.rstrip() for l in open(path or TLE_PATH) if l.strip()]
    except OSError:
        return ts, []
    sats = []
    for want in s["satellites"]:
        for i in range(len(lines) - 1):
            if lines[i].startswith("1 %05d" % want["norad"]) and lines[i + 1].startswith("2 "):
                sats.append((want, EarthSatellite(lines[i], lines[i + 1], want["name"], ts)))
                break
    return ts, sats


class PassSet:
    """Set of passes keyed by (satellite, AOS) with a tolerance: predict() is re-run hourly and
    after Settings, and skyfield's rise time moves by seconds with a new t0 or new TLEs, so an
    exact-float key silently drops an armed pass (and re-fires its alerts)."""

    def __init__(self, tol=120.0):
        self.tol, self.keys = tol, []

    def _find(self, p):
        for k in self.keys:
            if k[0] == p["sat"] and abs(k[1] - p["aos"]) < self.tol:
                return k
        return None

    def __contains__(self, p):
        return self._find(p) is not None

    def add(self, p):
        if p not in self:
            self.keys.append((p["sat"], p["aos"]))

    def discard(self, p):
        k = self._find(p)
        if k:
            self.keys.remove(k)


def predict(s, home, hours=48, path=None):
    from skyfield.api import wgs84
    ts, sats = load_sats(s, path)
    obs = wgs84.latlon(home["lat"], home["lon"], elevation_m=home.get("alt_m", 0))
    t0 = ts.now()
    t1 = ts.tt_jd(t0.tt + hours / 24)
    passes = []
    for meta, sat in sats:
        try:
            times, evs = sat.find_events(obs, t0, t1, altitude_degrees=10.0)
        except Exception:
            continue
        cur = {}
        for t, e in zip(times, evs):
            if e == 0:
                cur = {"aos": t}
            elif e == 1 and "aos" in cur:
                alt, az, _ = (sat - obs).at(t).altaz()
                cur["max"] = alt.degrees
                cur["tca"] = t
            elif e == 2 and "aos" in cur and "max" in cur:
                cur["los"] = t
                track = []
                ground = []
                n = 40
                for k in range(n + 1):
                    tk = ts.tt_jd(cur["aos"].tt + (cur["los"].tt - cur["aos"].tt) * k / n)
                    alt, az, _ = (sat - obs).at(tk).altaz()
                    track.append((az.degrees, alt.degrees))
                    try:
                        sp = wgs84.subpoint(sat.at(tk))
                        ground.append((sp.latitude.degrees, sp.longitude.degrees))
                    except Exception:
                        pass
                north = track[0][0] < 90 or track[0][0] > 270
                passes.append({"sat": meta["name"], "freq": meta["freq"],
                               "aos": cur["aos"].utc_datetime().timestamp(),
                               "los": cur["los"].utc_datetime().timestamp(),
                               "max": round(cur["max"], 1), "track": track, "ground": ground,
                               "dir": "southbound" if north else "northbound"})
                cur = {}
    passes.sort(key=lambda p: p["aos"])
    if path is not None:
        return passes          # another app's satellites: don't overwrite the weather cache
    try:
        import json as _json
        slim = [{"sat": x["sat"], "aos": x["aos"], "los": x["los"], "max": x["max"]} for x in passes]
        with open(os.path.join(S.CACHE, "wx_passes.json"), "w") as f:
            _json.dump(slim, f)
    except Exception:
        pass
    return passes


LONG_DIR = {"N": "north", "NE": "northeast", "E": "east", "SE": "southeast", "S": "south",
            "SW": "southwest", "W": "west", "NW": "northwest"}


def satdump_cmd(s, p, outdir, legacy):
    dur = int(p["los"] - time.time()) + 30
    cmd = ["satdump"] + (["legacy"] if legacy else []) + [
        "live", "meteor_m2-x_lrpt", outdir, "--source", s["source"],
        "--samplerate", str(int(s["samplerate"])), "--frequency", "%.4fe6" % p["freq"],
        "--timeout", str(max(60, dur))]
    if s["source"] == "rtlsdr":
        cmd += ["--gain", str(s["gain"])]
    else:
        cmd += ["--lna_gain", "32", "--vga_gain", "24"]
    return cmd


def main():
    S.single_instance("Weather Sats")
    s, spath = S.settings("wxsat", DEFAULTS)
    if not S.core.H4M_ENABLED:
        s["source"] = "rtlsdr"
    os.makedirs(CAP_DIR, exist_ok=True)
    root, F = S.make_root("Weather Sats")
    import tkinter as tk

    ev = queue.Queue()
    st = {"passes": [], "sel": 0, "armed": PassSet(), "capturing": None, "home": dict(s["home"]),
          "imgs": [], "img_refs": [], "alerted": PassSet(), "alerted_hu": PassSet(),
          "tried": PassSet(), "tle": "…"}

    top = S.top_bar(root, F, "Weather Sats", "Meteor-M LRPT")
    T = S.T
    tle_pill = S.pill(top, F, "TLE")
    cap_pill = S.pill(top, F, "Idle")
    next_lbl = tk.Label(top, text="", font=F["sm"], fg=T.TXT_2, bg=T.SURFACE)
    next_lbl.pack(side="right", padx=20)

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)

    leftw = tk.Frame(body, bg=T.SURFACE, width=S.T.px(340))
    leftw.pack(side="left", fill="y")
    leftw.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    left = tk.Frame(leftw, bg=T.SURFACE)
    left.pack(fill="both", expand=True, padx=16, pady=14)
    T.section(left, F, "Passes · next 48 h", right="● = capture").pack(fill="x", pady=(0, 8))
    plist = tk.Text(left, bg=T.SURFACE, fg=S.TXT, font=F["map"], bd=0, highlightthickness=0,
                    cursor="hand2", wrap="none", spacing1=6, spacing3=6)
    ctl = tk.Frame(left, bg=T.SURFACE)
    ctl.pack(side="bottom", fill="x", pady=(8, 0))
    plist.pack(fill="both", expand=True)
    plist.tag_config("pick", background=T.ACCENT_BG)
    plist.tag_config("good", foreground=S.TXT)
    plist.tag_config("low", foreground=T.TXT_3)
    plist.tag_config("armed", foreground=T.ACCENT)

    mid = tk.Frame(body, bg=S.BG, width=S.T.px(350))
    mid.pack(side="left", fill="y", padx=20, pady=14)
    mid.pack_propagate(False)
    sec_track = T.section(mid, F, "Pass track")
    sec_track.pack(fill="x", pady=(0, 4))
    polar = tk.Canvas(mid, bg=S.BG, highlightthickness=0, height=S.T.px(230))
    polar.pack(fill="x")
    gmap = tk.Canvas(mid, bg=S.MAPBG, highlightthickness=0, height=S.T.px(230))
    import tiles as TL
    gbase = TL.TileLayer(on_ready=lambda ok: root.after(0, lambda: gtick()), workers=2)
    gbase.layer = "dark"
    gview = {"mode": "sky", "z": 4, "job": None}

    def gtick():
        if gview["job"] is None:
            gview["job"] = root.after(150, lambda: (gview.__setitem__("job", None), draw_ground()))

    def draw_ground():
        gmap.delete("all")
        w, h = gmap.winfo_width(), gmap.winfo_height()
        if w < 20 or gview["mode"] != "ground":
            return
        home = st.get("home") or {"lat": 39.62, "lon": -104.87}
        z = gview["z"]
        gbase.draw(gmap, home["lat"], home["lon"], z, w, h)
        cx0, cy0 = TL.world_px(home["lat"], home["lon"], z)

        def proj(la, lo):
            x, y = TL.world_px(la, lo, z)
            return w / 2 + (x - cx0), h / 2 + (y - cy0)

        hx, hy = proj(home["lat"], home["lon"])
        # 10° elevation footprint for an ~830 km orbit ≈ 2,400 km ground radius
        r = 2400 * TL.px_per_nm(home["lat"], z) / 1.852
        gmap.create_oval(hx - r, hy - r, hx + r, hy + r, outline=T.RING, dash=(3, 4))
        gmap.create_oval(hx - 4, hy - 4, hx + 4, hy + 4, outline=S.TXT, width=1.5)
        gmap.create_text(hx + 8, hy, text="You", fill=T.TXT_2, font=F["map"], anchor="w")
        if not st["passes"]:
            return
        p = st["passes"][st["sel"]]
        g = p.get("ground") or []
        if len(g) < 2:
            gmap.create_text(w / 2, 14, text="Ground track needs a prediction refresh", fill=T.TXT_3,
                             font=F["map"])
            return
        pts = []
        for la, lo in g:
            pts += proj(la, lo)
        good = p["max"] >= s["min_elevation"]
        gmap.create_line(*pts, fill=S.AMBER if good else T.TXT_3, width=2)
        gmap.create_oval(pts[0] - 4, pts[1] - 4, pts[0] + 4, pts[1] + 4, outline=S.TXT, width=1.5)
        gmap.create_text(pts[0] + 8, pts[1], text="AOS", fill=T.TXT_3, font=F["map"], anchor="w")
        gmap.create_rectangle(pts[-2] - 3, pts[-1] - 3, pts[-2] + 3, pts[-1] + 3, fill=T.TXT_2, outline="")
        gmap.create_text(pts[-2] + 8, pts[-1], text="LOS", fill=T.TXT_3, font=F["map"], anchor="w")
        now = time.time()
        if p["aos"] <= now <= p["los"]:
            k = (now - p["aos"]) / (p["los"] - p["aos"]) * (len(g) - 1)
            la, lo = g[int(k)]
            x, y = proj(la, lo)
            gmap.create_oval(x - 8, y - 8, x + 8, y + 8, outline=S.TXT, width=2)
        gmap.create_text(w - 6, h - 4, anchor="se", text=p["sat"], fill=T.TXT_2, font=F["map"])

    def set_track_mode(mode):
        gview["mode"] = mode
        if mode == "sky":
            gmap.pack_forget()
            polar.pack(fill="x", before=prof)
            draw_polar()
        else:
            polar.pack_forget()
            gmap.pack(fill="x", before=prof)
            draw_ground()

    gsw = tk.Frame(sec_track, bg=S.BG)
    gsw.pack(side="right")
    for t, m in (("Sky", "sky"), ("Ground", "ground")):
        S.btn(gsw, t, lambda m=m: set_track_mode(m), F, padx=6, pady=0, kind="quiet").pack(side="left")
    gmap.bind("<Button-4>", lambda e: (gview.__setitem__("z", min(7, gview["z"] + 1)), draw_ground()))
    gmap.bind("<Button-5>", lambda e: (gview.__setitem__("z", max(3, gview["z"] - 1)), draw_ground()))
    prof = tk.Canvas(mid, bg=S.BG, highlightthickness=0, height=S.T.px(80))
    prof.pack(fill="x", pady=(6, 0))
    pinfo = tk.Label(mid, text="", font=F["sm"], fg=S.TXT, bg=S.BG, justify="left",
                     anchor="nw", wraplength=S.T.px(330))
    arm_slot = tk.Frame(mid, bg=S.BG)
    arm_slot.pack(side="bottom", fill="x", pady=(6, 0))
    pinfo.pack(fill="both", expand=True, pady=(8, 0))

    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    right = tk.Frame(body, bg=S.BG)
    right.pack(side="left", fill="both", expand=True, padx=16, pady=14)
    T.section(right, F, "Latest images").pack(fill="x", pady=(0, 6))
    gallery = tk.Canvas(right, bg=S.BG, highlightthickness=0)
    gallery.pack(fill="both", expand=True)
    logl = tk.Label(right, text="", font=F["map"], fg=T.TXT_3, bg=S.BG, anchor="w", justify="left",
                    wraplength=S.T.px(360))
    logl.pack(fill="x")

    def log(m):
        S.core.file_log("[wxsat] " + m)
        ev.put(("log", m))

    # ------------------------------------------------------------ data
    def refresh_passes(force=False):
        def work():
            tpv = S.gps_fix(timeout=2)
            if tpv and "lat" in tpv:
                st["home"] = {"lat": tpv["lat"], "lon": tpv["lon"],
                              "alt_m": tpv.get("altMSL", tpv.get("alt", s["home"]["alt_m"])) or 0}
            try:
                st["tle"] = fetch_tles(s, force)
                ps = predict(s, st["home"])
            except ImportError:
                ev.put(("err", "skyfield not installed - re-run the suite installer"))
                return
            except Exception as e:
                ev.put(("err", "Pass prediction failed: %s" % str(e)[:120]))
                return
            ev.put(("passes", ps))
        S.in_thread(work)

    def fmt_pass(p):
        a = datetime.fromtimestamp(p["aos"])
        mins = (p["los"] - p["aos"]) / 60
        star = "●" if p in st["armed"] or (s["auto_capture"] and p["max"] >= s["min_elevation"]) else " "
        return " %s  %s   %-5s  %3.0f°  %3.0f min  %s" % (star, a.strftime("%a %H:%M"),
                                                       p["sat"].replace("METEOR-", "").replace("M2 ", "M2-"),
                                                       p["max"], mins, "S" if p["dir"] == "southbound" else "N")

    def draw_list():
        plist.config(state="normal")
        plist.delete("1.0", "end")
        for i, p in enumerate(st["passes"]):
            tags = ["good" if p["max"] >= s["min_elevation"] else "low"]
            if p in st["armed"] or (s["auto_capture"] and p["max"] >= s["min_elevation"]):
                tags.append("armed")
            if i == st["sel"]:
                tags.append("pick")
            plist.insert("end", fmt_pass(p) + "\n", tuple(tags))
        if not st["passes"]:
            plist.insert("end", "No passes yet - need TLEs (internet) and Skyfield.\n", "low")
        plist.config(state="disabled")

    def pick(e):
        i = int(plist.index("@%d,%d" % (e.x, e.y)).split(".")[0]) - 1
        if 0 <= i < len(st["passes"]):
            st["sel"] = i
            draw_list()
            draw_polar()

    plist.bind("<Button-1>", pick)

    def draw_polar():
        draw_ground()
        polar.delete("all")
        w, h = polar.winfo_width(), polar.winfo_height()
        if w < 20:
            return
        cx, cy, R = w / 2, h / 2, min(w, h) / 2 - 24
        for el in (0, 30, 60):
            r = R * (90 - el) / 90
            polar.create_oval(cx - r, cy - r, cx + r, cy + r, outline=T.RING)
            if el:
                polar.create_text(cx + 3, cy - r, text="%d°" % el, anchor="sw", fill=T.TXT_3, font=F["map"])
        for t, x, y in (("N", cx, cy - R - 12), ("E", cx + R + 12, cy), ("S", cx, cy + R + 12),
                        ("W", cx - R - 12, cy)):
            polar.create_text(x, y, text=t, fill=T.TXT_3, font=F["map"])
        T.compass_ring(polar, cx, cy, R, F, labels=False)
        if not st["passes"]:
            pinfo.config(text="")
            return
        p = st["passes"][st["sel"]]
        # elevation profile
        prof.delete("all")
        pw, ph = prof.winfo_width(), prof.winfo_height()
        if pw > 40:
            lab_w = F["map"].measure("90°") + 6
            x0, y0 = lab_w, F["map"].metrics("linespace") // 2
            gw, gh = pw - lab_w - 6, ph - y0 - F["map"].metrics("linespace") - 6
            for el in (0, 30, 60, 90):
                yy = y0 + gh * (1 - el / 90)
                prof.create_line(x0, yy, x0 + gw, yy, fill=T.RING)
                prof.create_text(x0 - 4, yy, text="%d°" % el, anchor="e", fill=T.TXT_3, font=F["map"])
            ptsp = []
            n = len(p["track"]) - 1
            for i, (az, el) in enumerate(p["track"]):
                ptsp += [x0 + gw * i / n, y0 + gh * (1 - max(0, el) / 90)]
            prof.create_polygon(x0, y0 + gh, *ptsp, x0 + gw, y0 + gh,
                                fill=T._mix(T.ACCENT, S.BG, 0.85), outline="")
            prof.create_line(*ptsp, fill=S.AMBER, width=1.5, smooth=True)
            mins = (p["los"] - p["aos"]) / 60
            for m in range(0, int(mins) + 1, 2):
                xx = x0 + gw * m / mins
                prof.create_line(xx, y0 + gh, xx, y0 + gh + 4, fill=T.TXT_3)
                prof.create_text(xx, y0 + gh + 6, text="%d" % m, anchor="n", fill=T.TXT_3,
                                 font=F["map"])
            minel = s["min_elevation"]
            ym = y0 + gh * (1 - minel / 90)
            prof.create_line(x0, ym, x0 + gw, ym, fill=T.AMBER_DIM, dash=(3, 3))
        pts = []
        for az, el in p["track"]:
            r = R * (90 - max(0, el)) / 90
            pts += [cx + r * math.sin(math.radians(az)), cy - r * math.cos(math.radians(az))]
        good = p["max"] >= s["min_elevation"]
        polar.create_line(*pts, fill=S.AMBER if good else T.TXT_3, width=2, smooth=True)
        polar.create_oval(pts[0] - 4, pts[1] - 4, pts[0] + 4, pts[1] + 4, outline=T.TXT, width=1.5)
        polar.create_text(pts[0] + 8, pts[1], text="AOS", fill=T.TXT_3, font=F["map"], anchor="w")
        polar.create_rectangle(pts[-2] - 3, pts[-1] - 3, pts[-2] + 3, pts[-1] + 3, fill=T.TXT_2, outline="")
        polar.create_text(pts[-2] + 8, pts[-1], text="LOS", fill=T.TXT_3, font=F["map"], anchor="w")
        draw_now_marker()
        a, l = datetime.fromtimestamp(p["aos"]), datetime.fromtimestamp(p["los"])
        armed = p in st["armed"] or (s["auto_capture"] and good)
        pinfo.config(text=(
            "%s   %.3f MHz LRPT\n%s – %s   %d min\nMax %.0f°   %s   rises %s\n\n%s\n\n%s" % (
                p["sat"], p["freq"], a.strftime("%a %H:%M"), l.strftime("%H:%M"),
                (p["los"] - p["aos"]) / 60, p["max"], p["dir"],
                compass(p["track"][0][0]),
                ("Set to capture." if armed else "Not set to capture.") +
                (" Below %d°, expect a weak image." % s["min_elevation"] if not good else ""),
                "Needs a 137 MHz V-dipole or QFH outdoors; the uConsole whip won't work. %s" % (
                    "Captures on the built-in SDR (map pauses during the pass)."
                    if s["source"] == "rtlsdr" else "Captures on the H4M.")))
            )
        S.set_btn(arm_btn, "Cancel capture" if p in st["armed"] else "Capture this pass",
                  "primary" if p not in st["armed"] else "ghost")

    def draw_now_marker():
        polar.delete("now")
        if not st["passes"]:
            return
        p = st["passes"][st["sel"]]
        now = time.time()
        if p["aos"] <= now <= p["los"]:
            w, h = polar.winfo_width(), polar.winfo_height()
            cx, cy, R = w / 2, h / 2, min(w, h) / 2 - 24
            k = (now - p["aos"]) / (p["los"] - p["aos"]) * (len(p["track"]) - 1)
            az, el = p["track"][int(k)]
            r = R * (90 - max(0, el)) / 90
            x, y = cx + r * math.sin(math.radians(az)), cy - r * math.cos(math.radians(az))
            polar.create_oval(x - 8, y - 8, x + 8, y + 8, outline=S.TXT, width=2, tags="now")

    def compass(az):
        return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((az + 22.5) // 45) % 8]

    def arm():
        if not st["passes"]:
            return
        p = st["passes"][st["sel"]]
        if p in st["armed"]:
            st["armed"].discard(p)
        else:
            st["armed"].add(p)
        draw_list()
        draw_polar()

    def toggle_auto():
        s["auto_capture"] = not s["auto_capture"]
        S.save_json(spath, s)
        S.set_btn(auto_btn, "Auto ≥%d°: %s" % (s["min_elevation"], "on" if s["auto_capture"] else "off"),
                  "primary" if s["auto_capture"] else "ghost")
        draw_list()
        draw_polar()

    arm_btn = S.btn(arm_slot, "Capture this pass", arm, F, kind="primary")
    arm_btn.pack(side="left")
    auto_btn = S.btn(ctl, "", toggle_auto, F, padx=10, pady=4)
    auto_btn.pack(side="left")
    S.set_btn(auto_btn, "Auto ≥%d°: %s" % (s["min_elevation"], "on" if s["auto_capture"] else "off"),
              "primary" if s["auto_capture"] else "ghost")
    S.btn(ctl, "Refresh TLEs", lambda: refresh_passes(True), F, padx=10, pady=4, kind="quiet").pack(side="right")

    WX_SCHEMA = [
        ("Capture", [
            {"key": "source", "label": "Capture radio", "type": "choice",
             "choices": ([("rtlsdr", "Built-in SDR"), ("hackrf", "H4M")] if S.core.H4M_ENABLED
                         else [("rtlsdr", "Built-in SDR")])},
            {"key": "gain", "label": "Gain", "type": "float", "min": 0, "max": 49.6, "step": 2, "unit": "dB"},
            {"key": "min_elevation", "label": "Auto-capture passes above", "type": "int", "min": 10, "max": 80,
             "step": 5, "unit": "°"},
            {"key": "auto_capture", "label": "Auto-capture", "type": "bool"},
        ]),
        ("Location", [
            {"key": "home.lat", "label": "Latitude", "type": "float", "min": -90, "max": 90,
             "help": "overridden by GPS when there is a fix"},
            {"key": "home.lon", "label": "Longitude", "type": "float", "min": -180, "max": 180},
            {"key": "home.alt_m", "label": "Altitude", "type": "float", "unit": "m"},
        ]),
        ("Satellites", [
            {"key": "satellites", "label": "Tracked satellites", "type": "table",
             "columns": [("name", "Name", "str"), ("norad", "NORAD", "int"), ("freq", "MHz", "float")],
             "template": {"name": "METEOR-M2 x", "norad": 0, "freq": 137.1}},
            {"key": "tle_urls", "label": "TLE sources", "type": "list"},
        ]),
    ]

    def open_settings():
        import settings_ui

        def on_save(new):
            s.clear()
            s.update(new)
            S.save_json(spath, s)
            st["home"] = dict(s["home"])
            S.set_btn(auto_btn, "Auto ≥%d°: %s" % (s["min_elevation"], "on" if s["auto_capture"] else "off"),
                      "primary" if s["auto_capture"] else "ghost")
            refresh_passes(False)
        settings_ui.open_settings(root, F, "Weather Sats settings", WX_SCHEMA, s, on_save, path=spath)

    S.btn(ctl, "Settings", open_settings, F, padx=10, pady=4, kind="quiet").pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------ capture
    def is_wanted(p):
        return p in st["armed"] or (s["auto_capture"] and p["max"] >= s["min_elevation"])

    def capture(p):
        st["capturing"] = p
        outdir = os.path.join(CAP_DIR, datetime.fromtimestamp(p["aos"]).strftime("%Y%m%d_%H%M_") +
                              p["sat"].replace(" ", "_"))
        os.makedirs(outdir, exist_ok=True)
        ev.put(("cap", "Waiting for %s" % p["sat"]))
        while time.time() < p["aos"] - 20:
            if st["capturing"] is not p:
                return
            if not is_wanted(p):          # "Cancel capture" (or Auto off) while waiting
                st["capturing"] = None
                ev.put(("cap", "Idle"))
                return
            time.sleep(1)
        lease = S.RtlLease("Weather sat", log=log) if s["source"] == "rtlsdr" else None
        try:
            if not shutil.which("satdump"):
                raise RuntimeError("SatDump isn't installed (satdump not on PATH)")
            if lease:
                lease.acquire()
            ev.put(("cap", "Recording %s" % p["sat"]))
            for legacy in (False, True):
                cmd = satdump_cmd(s, p, outdir, legacy)
                log("$ " + " ".join(cmd))
                with open(os.path.join(outdir, "satdump.log"), "w") as errf:
                    proc = S.spawn(cmd, stdout=errf, stderr=subprocess.STDOUT)
                t0 = time.time()
                while proc.poll() is None and time.time() < p["los"] + 90:
                    time.sleep(1)
                S.stop_group(proc, grace=10)
                out = open(os.path.join(outdir, "satdump.log")).read()
                if time.time() - t0 < 15 and re.search(r"unknown|usage|invalid|not found", out, re.I):
                    log("SatDump rejected that syntax, trying the other CLI form")
                    continue
                break
        except Exception as e:
            log("Capture failed: %s" % e)
        finally:
            if lease:
                lease.release()
            st["capturing"] = None
        imgs = sorted(glob.glob(os.path.join(outdir, "**", "*.png"), recursive=True),
                      key=os.path.getsize, reverse=True)
        if imgs:
            S.notify("Weather sat", "%s: %d images decoded" % (p["sat"], len(imgs)))
            log("%d images in %s" % (len(imgs), outdir))
        else:
            log("No images from this pass (weak signal, antenna, or SatDump error - see satdump.log)")
        ev.put(("cap", "Idle"))
        ev.put(("gallery", None))

    def scheduler():
        now = time.time()
        for p in st["passes"]:
            good = p["max"] >= s["min_elevation"]
            wanted = p in st["armed"] or (s["auto_capture"] and good)
            if p["los"] < now:
                continue
            # heads-up for every good pass, captured or not: time to walk outside and point the antenna
            if good and 0 < p["aos"] - now < 600 and p not in st["alerted_hu"]:
                st["alerted_hu"].add(p)
                rises = compass(p["track"][0][0])
                S.notify("Weather sat pass in 10 min", "%s rises %s, max %.0f°" % (p["sat"], rises, p["max"]))
                if shutil.which("espeak-ng"):
                    S.fire_and_forget(["espeak-ng", "-s", "150",
                                       "Weather satellite pass in ten minutes. %s rises in the %s, "
                                       "maximum %d degrees." % (p["sat"].replace("-", " "), LONG_DIR.get(rises, rises),
                                                               round(p["max"]))])
            if not wanted:
                continue
            if p["aos"] - now < 300 and p not in st["alerted"]:
                st["alerted"].add(p)
                S.notify("Weather sat pass in 5 min", "%s, max %.0f°" % (p["sat"], p["max"]))
            if p["aos"] - now < 60 and not st["capturing"] and p not in st["tried"]:
                # one attempt per pass: a capture that fails fast (busy SDR, SatDump error)
                # must not be relaunched every second for the whole pass, bouncing readsb
                # and overwriting satdump.log with each retry
                st["tried"].add(p)
                st["capturing"] = p     # set before the thread runs: no double start
                threading.Thread(target=capture, args=(p,), daemon=True).start()
                break
        # countdown
        up = [p for p in st["passes"] if p["los"] > now and p["max"] >= s["min_elevation"]]
        if up:
            p = up[0]
            d = p["aos"] - now
            next_lbl.config(text="Next good pass · %s in %s" % (
                p["sat"][-4:].strip(), "now!" if d <= 0 else ("%dh %02dm" % (d // 3600, d % 3600 // 60)
                                                             if d >= 3600 else "%dm %02ds" % (d // 60, d % 60))))
        if st["passes"] and st["passes"][0]["los"] < now - 60:
            st["passes"] = [p for p in st["passes"] if p["los"] > now - 60]
            st["sel"] = 0
            draw_list()
        draw_now_marker()
        root.after(1000, scheduler)

    # ------------------------------------------------------------ gallery
    thumbs = {}  # (path, mtime, col_w) -> PhotoImage
    gal_w = [0]

    def thumb(path, col_w):
        key = (path, os.path.getmtime(path), col_w)
        if key in thumbs:
            return thumbs[key]
        try:
            from PIL import Image, ImageTk
            im = Image.open(path)
            im.thumbnail((col_w, 240))
            th = ImageTk.PhotoImage(im)
        except Exception:
            try:
                im = tk.PhotoImage(file=path)
            except tk.TclError:
                return None
            f = max(1, math.ceil(im.width() / col_w), math.ceil(im.height() / 240))
            th = im.subsample(f, f)
        # keep the cache small
        for k in [k for k in thumbs if k[0] == path]:
            del thumbs[k]
        if len(thumbs) > 12:
            thumbs.pop(next(iter(thumbs)))
        thumbs[key] = th
        return th

    def draw_gallery():
        gallery.delete("all")
        st["img_refs"] = []
        dirs = sorted(glob.glob(os.path.join(CAP_DIR, "*")), reverse=True)
        imgs = []
        for d in dirs:
            imgs = sorted(glob.glob(os.path.join(d, "**", "*.png"), recursive=True),
                          key=os.path.getsize, reverse=True)[:6]
            if imgs:
                gallery.create_text(10, 8, anchor="nw", fill=T.TXT_3, font=F["map"],
                                    text=os.path.basename(d))
                break
        if not imgs:
            gallery.create_text(gallery.winfo_width() / 2, gallery.winfo_height() / 2,
                                text="No captures yet", fill=S.DIM, font=F["sm"])
            return
        w = max(200, gallery.winfo_width())
        col_w = (w - 30) // 2
        x, y = 10, 28
        for i, path in enumerate(imgs):
            th = thumb(path, col_w)
            if th is None:
                continue
            st["img_refs"].append(th)
            item = gallery.create_image(x, y, anchor="nw", image=th)
            gallery.tag_bind(item, "<Button-1>", lambda e, p=path: open_img(p))
            if i % 2:
                x, y = 10, y + th.height() + 8
            else:
                x = 20 + col_w

    def open_img(path):
        for v in ("eog", "ristretto", "feh", "gpicview", "xdg-open"):
            if shutil.which(v):
                S.fire_and_forget([v, path])
                return

    def on_gal_cfg(e):
        if e.width != gal_w[0]:
            gal_w[0] = e.width
            draw_gallery()
    gallery.bind("<Configure>", on_gal_cfg)

    def pump():
        while not ev.empty():
            e = ev.get()
            if e[0] == "passes":
                st["passes"], st["sel"] = e[1], 0
                tle_pill.config(text="TLE " + st["tle"], bg=S.GREEN if st["tle"] in ("updated", "cached")
                                else (S.AMBER if st["tle"] == "offline" else S.RED))
                draw_list()
                draw_polar()
            elif e[0] == "err":
                logl.config(text=e[1], fg=S.RED)
            elif e[0] == "log":
                logl.config(text=e[1], fg=S.MUTED)
            elif e[0] == "cap":
                cap_pill.config(text=e[1], bg=S.RED if e[1].startswith("Rec") else
                                (S.AMBER if e[1].startswith("Wait") else S.DIM))
            elif e[0] == "gallery":
                draw_gallery()
        root.after(200, pump)

    def on_close():
        was = st["capturing"]
        st["capturing"] = None
        if was and S.core.pids_named("satdump"):
            def stop():
                S.core.kill_pids(S.core.pids_named("satdump"), grace=3)
                if s["source"] == "rtlsdr":
                    S.RtlLease("Weather sat").release()
            th = threading.Thread(target=stop, daemon=True)
            th.start()

            def check():
                if th.is_alive():
                    root.after(300, check)
                else:
                    root.destroy()
            check()
        else:
            root.destroy()

    polar.bind("<Configure>", lambda e: draw_polar())
    gmap.bind("<Configure>", lambda e: draw_ground())
    S.header_quit(top, root, F, on_close)
    S.bind_quit(root, on_close)
    root.bind("q", lambda e: on_close())
    refresh_passes()
    pump()
    scheduler()
    def hourly():
        refresh_passes()
        root.after(3600 * 1000, hourly)
    root.after(3600 * 1000, hourly)
    root.mainloop()


if __name__ == "__main__":
    main()
