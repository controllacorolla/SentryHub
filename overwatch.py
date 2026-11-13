#!/usr/bin/env python3
"""Overwatch - the whole device at once.

DOME      Everything above and around you, on one sky dome centred on where the GPS says you
          are: aircraft (ADS-B) arcing across with trails, weather balloons, the navigation
          satellites the GPS chip is tracking right now, the ISS and weather satellites, the
          Sun and Moon, and - on the horizon ring - APRS stations and mesh nodes by bearing.
AUTOPILOT The one radio, shared automatically. A director rotates it between the plane map,
          APRS and sensors, makes room for weather-balloon launch windows, stands down when
          the CPU is hot or the battery is low, and gets out of the way the moment you use
          the radio yourself.
VOICE     Optional spoken call-outs through the speaker: something passing overhead, a new
          balloon, a military aircraft, a heat or power warning.

Receive-only. Nothing here transmits, and nothing is inferred about people: it shows where
things are now, not where they have been.
--demo runs on synthetic traffic.
"""
import collections
import math
import os
import queue
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S          # noqa: E402

DEFAULTS = {"home": {"lat": 39.62, "lon": -104.87, "alt_m": 1750},
            "voice": False, "labels": True, "trails": True, "gps_sats": True,
            "air_min": 8, "aprs_min": 4, "sensors_min": 2, "sonde_min": 10,
            "overhead_deg": 60}
MODES = {"air": ("Plane map", None), "aprs": ("APRS", "aprs"), "sensors": ("Sensors", "sensors"),
         "sonde": ("Balloons", "sonde")}
LEASE = {"aprs": "APRS", "sensors": "Sensors", "sonde": "Balloons"}   # who holds the radio
SONDE_WINDOW_S = (10 * 60, 110 * 60)      # listen from 10 min before a launch to 110 min after
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW",
           "NW", "NNW")
COMPASS_WORDS = {"N": "north", "NE": "north-east", "E": "east", "SE": "south-east", "S": "south",
                 "SW": "south-west", "W": "west", "NW": "north-west"}


# ---- geometry + ephemeris: consolidated into astro.py (Phase 1a) ----------------------------
# Re-exported so overwatch's own code and fieldcomp (OW.sun_azel/moon_azel/daylight) are unchanged.
from astro import (_ecef, _ecl_to_radec, _jd, _radec_to_azel, _sun_lon,  # noqa: E402,F401
                   azel, daylight, moon_azel, sun_azel)


def compass(az, points=16):
    step = 16 // points
    return COMPASS[(int((az % 360) / (360 / points) + 0.5) % points) * step]


def dome_r(el, r):
    """Radius on the dome for an elevation. Not linear: almost everything in the air sits
    under 30 degrees, so the low sky gets about half the dome instead of a third."""
    return r * (1.0 - (min(90.0, max(0.0, el)) / 90.0) ** 0.65)


def project(az, el, cx, cy, r):
    """Dome -> canvas: zenith at the centre, horizon on the rim, north up, east right."""
    rr = dome_r(el, r)
    a = math.radians(az)
    return cx + rr * math.sin(a), cy - rr * math.cos(a)


def sky_objects(ents, home, now, max_age=None):
    """Fused entities -> dome objects with az/el/range, highest first."""
    out = []
    for e in ents:
        alt_m = (e.get("alt_ft") or 0.0) * 0.3048
        if e["kind"] in ("aprs", "mesh"):
            alt_m = max(alt_m, home[2])                # ground stations: put them on the horizon
        try:
            az, el, rng = azel(home, e["lat"], e["lon"], alt_m)
        except (ValueError, TypeError, OverflowError):
            continue
        out.append({"id": e["id"], "kind": e["kind"], "label": e.get("label") or e["id"],
                    "sub": e.get("sub") or "", "az": az, "el": el, "km": rng,
                    "alt_ft": e.get("alt_ft"), "course": e.get("course"),
                    "kt": e.get("speed_kt"), "notable": bool(e.get("notable")),
                    "ground": e["kind"] in ("aprs", "mesh")})
    out.sort(key=lambda o: -o["el"])
    return out


def gps_sats(sky):
    """gpsd SKY report -> [{prn, az, el, snr, used}] for satellites with a known direction."""
    out = []
    for s in (sky or {}).get("satellites") or []:
        if not isinstance(s, dict):
            continue
        az, el = s.get("az"), s.get("el")
        if not isinstance(az, (int, float)) or not isinstance(el, (int, float)):
            continue
        out.append({"prn": s.get("PRN"), "az": float(az) % 360, "el": float(el),
                    "snr": s.get("ss") or 0, "used": bool(s.get("used")),
                    "sys": {0: "G", 1: "S", 2: "E", 3: "C", 6: "R"}.get(s.get("gnssid"), "")})
    return out


# ---- the director (pure) --------------------------------------------------------------------
def in_sonde_window(now, launch_hours=(11, 23)):
    """True while a routine weather-balloon flight is likely in the air."""
    g = time.gmtime(now)
    sec = g.tm_hour * 3600 + g.tm_min * 60 + g.tm_sec
    for h in launch_hours:
        dt = (sec - h * 3600 + 43200) % 86400 - 43200      # seconds since that launch, +-12 h
        if -SONDE_WINDOW_S[0] <= dt <= SONDE_WINDOW_S[1]:
            return True
    return False


def rotation(plan, now):
    """Wall-clock rotation through plan=[[mode, minutes], ...]: (mode, slot_start, slot_end).
    Stateless, so it survives a restart and can be drawn ahead of time."""
    plan = [(m, max(1, int(mins))) for m, mins in plan if m in MODES]
    if not plan:
        return "air", now, now + 60
    cycle = sum(mins for _, mins in plan) * 60
    start = now - (now % cycle)
    for m, mins in plan:
        if now < start + mins * 60:
            return m, start, start + mins * 60
        start += mins * 60
    return plan[0][0], now, now + 60


def plans(s):
    """Settings (minutes per app; 0 leaves an app out) -> the two rotations the director uses:
    the everyday one, and the one for a weather-balloon launch window."""
    def mins(k):
        try:
            return max(0, int(s.get(k + "_min") or 0))
        except (TypeError, ValueError):
            return 0
    plan = [[m, mins(m)] for m in ("air", "aprs", "sensors") if mins(m) > 0] or [["air", 10]]
    sonde = [["sonde", mins("sonde")]] if mins("sonde") > 0 else []
    if sonde:
        sonde += [[m, max(1, min(mins(m), 4))] for m in ("air", "aprs") if mins(m) > 0]
    return {"plan": plan, "sonde_plan": sonde or plan}


def direct(now, cfg, ctx):
    """What the radio should be doing: (mode, until, reason).
    mode is a MODES key, or 'rest' (stood down), 'yield' (you have the radio), 'off'.
    ctx: on, hot, low_batt, holder (who has the radio), mine (holder was started by the
    director), can (modes this device can run)."""
    if not ctx.get("on"):
        return "off", None, "Autopilot is off - the radio does what you tell it."
    if ctx.get("hot"):
        return "rest", None, "Standing down: the CPU is over its heat limit."
    if ctx.get("low_batt"):
        return "rest", None, "Standing down: battery is low."
    if ctx.get("holder") and not ctx.get("mine"):
        return "yield", None, "You are using the radio (%s). Autopilot resumes when it is free." \
            % ctx["holder"]
    can = ctx.get("can") or set(MODES)
    sonde = "sonde" in can and in_sonde_window(now) and \
        any(p[0] == "sonde" for p in cfg.get("sonde_plan") or [])
    plan = cfg.get("sonde_plan") if sonde else cfg.get("plan")
    plan = [p for p in (plan or []) if p[0] in can] or [["air", 10]]
    mode, _, end = rotation(plan, now)
    why = "Balloon launch window - sharing the radio with the sonde band." if sonde else \
        "Rotation: %s." % " → ".join("%s %dm" % (MODES[m][0], int(mins)) for m, mins in plan)
    return mode, end, why


def schedule(now, cfg, can, minutes=45):
    """The next `minutes` of the rotation as [(mode, start, end)] for the timeline strip."""
    out, t, guard = [], now, 0
    while t < now + minutes * 60 and guard < 200:
        guard += 1
        sonde = "sonde" in can and in_sonde_window(t) and \
            any(p[0] == "sonde" for p in cfg.get("sonde_plan") or [])
        plan = [p for p in ((cfg.get("sonde_plan") if sonde else cfg.get("plan")) or [])
                if p[0] in can] or [["air", 10]]
        mode, start, end = rotation(plan, t)
        if out and out[-1][0] == mode and abs(out[-1][2] - t) < 2:
            out[-1] = (mode, out[-1][1], end)
        else:
            out.append((mode, max(start, now), end))
        t = end + 0.5
    return out


# ---- call-outs (pure) -----------------------------------------------------------------------
class Caller:
    """Decides what is worth saying out loud, and never repeats itself."""

    def __init__(self, overhead_deg=60, repeat_s=900, gap_s=20):
        self.overhead_deg, self.repeat_s, self.gap_s = overhead_deg, repeat_s, gap_s
        self.said, self.last = {}, 0.0

    def _once(self, key, now):
        if now - self.said.get(key, -1e9) < self.repeat_s:
            return False
        self.said[key] = now
        if len(self.said) > 400:
            self.said = {k: t for k, t in self.said.items() if now - t < self.repeat_s}
        return True

    def calls(self, objs, now):
        out = []
        for o in objs:
            if o["ground"]:
                continue
            name = spoken_name(o["label"])
            if o["kind"] in ("air", "mil") and o["el"] >= self.overhead_deg and \
                    self._once(("over", o["id"]), now):
                alt = o.get("alt_ft") or 0
                out.append("%s overhead, %s, %s." % (
                    "Military aircraft" if o["kind"] == "mil" else "Aircraft", name,
                    "%d thousand feet" % round(alt / 1000) if alt >= 1500 else "low"))
            elif o["kind"] == "mil" and o["el"] > 0 and self._once(("mil", o["id"]), now):
                out.append("Military aircraft %s, %s, %d kilometres." % (
                    name, COMPASS_WORDS[compass(o["az"], 8)], round(o["km"])))
            elif o["kind"] == "sonde" and self._once(("sonde", o["id"]), now):
                out.append("Weather balloon %s, %s, %d degrees up." % (
                    name, COMPASS_WORDS[compass(o["az"], 8)], max(0, round(o["el"]))))
        if out and now - self.last < self.gap_s:
            return []                     # too soon after the last one; these stay marked said
        if out:
            self.last = now
        return out[:2]


def spoken_name(label):
    """'UAL1234' -> 'U A L 12 34' reads badly; keep letters spaced and digits as digits."""
    if not str(label).strip():
        return "unknown"
    label = str(label).strip().split()[0]
    head = "".join(c for c in label if c.isalpha())[:4]
    tail = "".join(c for c in label if c.isdigit())
    return (" ".join(head) + (" " + " ".join(tail) if tail else "")).strip() or "unknown"


# ---- satellites (optional: needs skyfield and a cached element set) -------------------------
def load_orbiters():
    try:
        from skyfield.api import EarthSatellite, load, wgs84
    except Exception:
        return None
    want = {25544: "ISS"}
    try:
        import wxsat
        ws, _ = S.settings("wxsat", wxsat.DEFAULTS)
        for sat in ws.get("satellites") or []:
            want[int(sat["norad"])] = str(sat["name"])
    except Exception:
        pass
    ts = load.timescale()
    sats = {}
    for fn in ("weather.tle", "sstv.tle"):
        try:
            lines = [ln.rstrip() for ln in open(os.path.join(S.CACHE, fn)) if ln.strip()]
        except OSError:
            continue
        for i in range(len(lines) - 1):
            if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
                try:
                    norad = int(lines[i][2:7])
                except ValueError:
                    continue
                if norad in want and norad not in sats:
                    try:
                        sats[norad] = EarthSatellite(lines[i], lines[i + 1], want[norad], ts)
                    except Exception:
                        pass
    return {"ts": ts, "wgs84": wgs84, "sats": sats} if sats else None


def orbiters_now(orb, home):
    out = []
    if not orb:
        return out
    obs = orb["wgs84"].latlon(home[0], home[1], elevation_m=home[2])
    t = orb["ts"].now()
    for norad, sat in orb["sats"].items():
        try:
            alt, az, dist = (sat - obs).at(t).altaz()
            if alt.degrees > -3:
                out.append({"id": "sat:%d" % norad, "kind": "sat", "label": sat.name,
                            "sub": "satellite", "az": az.degrees, "el": alt.degrees,
                            "km": dist.km, "ground": False, "notable": False})
        except Exception:
            continue
    return out


def demo_orbiter(now):
    """A synthetic pass, clearly labelled, so the satellite layer can be seen without TLEs."""
    ph = (now % 600) / 600.0
    return [{"id": "sat:demo", "kind": "sat", "label": "ISS (demo)", "sub": "satellite",
             "az": (220 + 180 * ph) % 360, "el": 70 * math.sin(math.pi * ph), "km": 420 + 900 * abs(
                 0.5 - ph), "ground": False, "notable": False}]


def demo_gps(now):
    sats = []
    for i in range(11):
        az = (i * 33 + now / 40.0) % 360
        el = 12 + (i * 17) % 70
        sats.append({"PRN": i + 2, "az": az, "el": el, "ss": 18 + (i * 7) % 28, "used": i % 4 != 3,
                     "gnssid": 0 if i < 8 else 2})
    return {"satellites": sats}


# ---- the app --------------------------------------------------------------------------------
def main():
    S.single_instance("Overwatch")
    demo = "--demo" in sys.argv
    import ops as O
    import aprs as A
    import sky_app
    import field_status as FS
    s, spath = S.settings("overwatch", DEFAULTS)
    root, F = S.make_root("Overwatch")
    import tkinter as tk
    T = S.T
    embedded = getattr(root, "embedded", False)
    shell = T.EMBED if embedded else None
    sky_set = sky_app.load_settings()
    feed = sky_app.DemoFeed() if demo else sky_app.AdsbFeed(sky_set["adsb_sources"])
    mil_pref = sky_set.get("mil_prefixes") or sky_app.MIL_PREFIXES_DEFAULT
    home0 = (float(s["home"]["lat"]), float(s["home"]["lon"]), float(s["home"].get("alt_m", 0)))
    if not demo and not FS.GPS.get("_thread"):
        FS.GPS["_thread"] = True
        threading.Thread(target=FS.gpsd_thread, daemon=True).start()
    S.start_health()
    slog = S.SessionLog("overwatch")
    caller = Caller(overhead_deg=float(s.get("overhead_deg") or 60))
    cfg = [plans(s)]
    can = {"air", "sonde"} if demo else {"air"}
    if demo or (shutil.which("rtl_fm") and shutil.which("multimon-ng")):
        can.add("aprs")
    if demo or shutil.which("rtl_433"):
        can.add("sensors")
    try:
        import balloons
        if balloons.installed():
            can.add("sonde")
    except Exception:
        pass
    st = {"objs": [], "gps": [], "sun": (0, -90), "moon": (0, -90, 0), "home": home0,
          "fix": False, "sel": None, "auto": False, "mode": "off", "until": None, "why": "",
          "child": None, "closed": False, "trails": {}, "src": "", "hits": [], "t": 0,
          "yield_t": 0.0, "counts": collections.Counter()}
    q = queue.Queue()

    # ---- chrome
    top = S.top_bar(root, F, "Overwatch", "everything above you · receive-only")
    auto_pill = S.pill(top, F, "Autopilot off")
    pos_pill = S.pill(top, F, "Position")
    sky_pill = S.pill(top, F, "Sky")
    if demo:
        S.pill(top, F, "DEMO", S.AMBER)
    bar = tk.Frame(root, bg=T.BG)
    bar.pack(side="bottom", fill="x", padx=T.px(10), pady=T.px(6))
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    body = tk.Frame(root, bg=T.BG)
    body.pack(fill="both", expand=True)
    side = tk.Frame(body, bg=T.SURFACE, width=T.px(300))
    side.pack(side="right", fill="y")
    side.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="right", fill="y")
    cv = tk.Canvas(body, bg=T.BG, highlightthickness=0)
    cv.pack(side="left", fill="both", expand=True)

    def sect(title, right=""):
        f = T.section(side, F, title, right=right)
        f.pack(fill="x", padx=T.px(12), pady=(T.px(10), T.px(3)))
        return f

    radio_sec = sect("Radio", "autopilot")
    now_lbl = tk.Label(side, text="—", font=F["now"], fg=T.TXT, bg=T.SURFACE, anchor="w")
    now_lbl.pack(fill="x", padx=T.px(12))
    why_lbl = tk.Label(side, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w",
                       justify="left", wraplength=T.px(276))
    why_lbl.pack(fill="x", padx=T.px(12))
    strip = tk.Canvas(side, bg=T.SURFACE, highlightthickness=0, height=T.px(40))
    strip.pack(fill="x", padx=T.px(12), pady=(T.px(6), 0))
    sect("Sources", "tap to open")
    srcf = tk.Frame(side, bg=T.SURFACE)
    srcf.pack(fill="x", padx=T.px(6))
    srcf.columnconfigure(1, weight=1)
    srow = {}
    for i, (k, name, app) in enumerate((("air", "Aircraft", "sky"), ("aprs", "APRS", "aprs"),
                                        ("sensors", "Sensors", "sensors"),
                                        ("sonde", "Balloons", "sonde"), ("mesh", "Mesh", "mesh"))):
        n_ = tk.Label(srcf, text=name, font=F["map"], fg=T.TXT_2, bg=T.SURFACE, anchor="w",
                      padx=T.px(6), pady=1)
        v_ = tk.Label(srcf, text="—", font=F["map"], fg=T.TXT, bg=T.SURFACE, anchor="w")
        x_ = tk.Label(srcf, text="", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE, anchor="e",
                      padx=T.px(6))
        n_.grid(row=i, column=0, sticky="ew")
        v_.grid(row=i, column=1, sticky="ew", padx=(T.px(4), 0))
        x_.grid(row=i, column=2, sticky="ew")
        srow[k] = (n_, v_, x_)
        for w_ in (n_, v_, x_):
            w_.config(cursor="hand2")
            w_.bind("<Button-1>", lambda e, a_=app: shell.open(a_) if shell is not None else None)
            w_.bind("<Enter>", lambda e, r=(n_, v_, x_): [c.config(bg=T.HOVER) for c in r])
            w_.bind("<Leave>", lambda e, r=(n_, v_, x_): [c.config(bg=T.SURFACE) for c in r])
    astro = tk.Label(side, text="", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE, anchor="w")
    astro.pack(fill="x", padx=T.px(12), pady=(T.px(4), 0))
    sect("Highest in the sky", "el · bearing · range")
    over = tk.Text(side, bg=T.SURFACE, fg=T.TXT_2, font=F["map"], bd=0, highlightthickness=0,
                   height=7, wrap="none", state="disabled", cursor="arrow")
    over.tag_config("hi", foreground=T.TXT)
    over.tag_config("note", foreground=T.NOTE)
    over.tag_config("dim", foreground=T.TXT_3)
    over.tag_config("cur", background=T.ACCENT_BG)
    over.pack(fill="both", expand=True, padx=T.px(12), pady=(0, T.px(6)))
    # ---- data worker: files and sockets only, never Tk
    def worker():
        orb, orb_t = None, 0.0
        while not st["closed"]:
            now = time.time()
            try:
                acs, _, status, rcv = feed.snapshot()
                if demo:
                    stations, sondes, mesh = O.demo_extras(home0[:2], now)
                    sky = demo_gps(now)
                    tpv = None
                else:
                    stations = A.load_stations(os.path.join(S.CACHE, "aprs_stations.json"), now).s
                    sj = S.load_json(os.path.join(S.CACHE, "sondes.json"), {}) or {}
                    sondes = [b for b in sj.get("sondes", []) if isinstance(b, dict)] \
                        if isinstance(sj, dict) else []
                    mj = S.load_json(os.path.join(S.CACHE, "mesh_nodes.json"), {}) or {}
                    mesh = [] if not isinstance(mj, dict) or mj.get("demo") else \
                        [n for n in mj.get("nodes", []) if isinstance(n, dict)]
                    sky = FS.GPS.get("sky")
                    tpv = FS.GPS.get("tpv") if time.time() - (FS.GPS.get("t") or 0) < 30 else None
                home, fix = home0, False
                if tpv and isinstance(tpv.get("lat"), (int, float)) and \
                        isinstance(tpv.get("lon"), (int, float)) and (tpv.get("mode") or 0) >= 2:
                    alt = tpv.get("altMSL", tpv.get("alt"))
                    home = (tpv["lat"], tpv["lon"],
                            float(alt) if isinstance(alt, (int, float)) else home0[2])
                    fix = True
                elif rcv and not demo:
                    home = (rcv[0], rcv[1], home0[2])
                ents = O.build_entities(acs, stations, sondes, mesh, home[:2], now,
                                        mil=lambda a: sky_app.is_military_ac(a, mil_pref))
                objs = sky_objects(ents, home, now)
                if demo:
                    objs += demo_orbiter(now)
                else:
                    if now - orb_t > 1800:
                        orb, orb_t = load_orbiters(), now
                    objs += orbiters_now(orb, home)
                objs.sort(key=lambda o: -o["el"])
                info = {"launch_s": 0}
                try:
                    info["aprs_t"] = max([x.get("last", 0) for x in stations.values()] or [0])
                except Exception:
                    pass
                sn = S.load_json(os.path.join(S.CACHE, "sensors.json"), {}) or {}
                if demo:
                    info.update(sensors_n=3, sensors_t=now - 40)
                elif isinstance(sn, dict) and isinstance(sn.get("t"), (int, float)) \
                        and now - sn["t"] < 6 * 3600:
                    info.update(sensors_n=int(sn.get("n") or 0), sensors_t=sn["t"])
                try:
                    import balloons as _B
                    info["launch_s"] = _B.next_launch(now) or 0
                except Exception:
                    pass
                q.put({"objs": objs, "gps": gps_sats(sky), "home": home, "fix": fix, "info": info,
                       "sun": sun_azel(home[0], home[1], now),
                       "moon": moon_azel(home[0], home[1], now),
                       "src": status, "t": now})
            except Exception as e:                 # a bad file must never kill the picture
                q.put({"err": str(e)[:80]})
            for _ in range(20):
                if st["closed"]:
                    return
                time.sleep(0.1)
    threading.Thread(target=worker, daemon=True, name="overwatch").start()

    # ---- the dome
    import tkinter.font as tkfont
    F_w = {k: tkfont.Font(font=F[k]).measure("0") for k in ("mapb", "lbl")}

    def geom():
        w, h = max(cv.winfo_width(), 200), max(cv.winfo_height(), 200)
        r = min(w, h) / 2 - T.px(30)
        return w / 2, h / 2, r

    def kind_col(o):
        if o["kind"] == "mil" or o["kind"] == "sonde" or o.get("notable"):
            return T.NOTE
        if o["kind"] == "sat":
            return T.ACCENT
        return T.TXT

    def draw():
        cv.delete("all")
        cx, cy, r = geom()
        st["hits"] = []
        # sky: subtly lighter by day
        sun_el = st["sun"][1]
        fill = T.SURFACE if sun_el > -6 else T.BG
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=T.LINE_HI, width=2)
        for el in (10, 30, 60):
            rr = dome_r(el, r)
            if abs(el - caller.overhead_deg) > 1:
                cv.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=T.LINE, dash=(2, 4))
            cv.create_text(cx + 4, cy - rr - 2, text="%d°" % el, font=F["lbl"], fill=T.TXT_3,
                           anchor="sw")
        ro = dome_r(caller.overhead_deg, r)
        cv.create_oval(cx - ro, cy - ro, cx + ro, cy + ro, outline=T.LINE_HI)
        cv.create_text(cx, cy + ro + 2, text="O V E R H E A D", font=F["lbl"], fill=T.TXT_3,
                       anchor="n")
        cv.create_line(cx - r, cy, cx + r, cy, fill=T.LINE)
        cv.create_line(cx, cy - r, cx, cy + r, fill=T.LINE)
        for az in range(0, 360, 10):
            a = math.radians(az)
            k = 8 if az % 90 == 0 else (5 if az % 30 == 0 else 3)
            cv.create_line(cx + r * math.sin(a), cy - r * math.cos(a),
                           cx + (r + T.px(k)) * math.sin(a), cy - (r + T.px(k)) * math.cos(a),
                           fill=T.LINE_HI)
        for az, name in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            a = math.radians(az)
            cv.create_text(cx + (r + T.px(19)) * math.sin(a), cy - (r + T.px(19)) * math.cos(a),
                           text=name, font=F["smb"], fill=T.TXT if az == 0 else T.TXT_2)
        cv.create_line(cx - 5, cy, cx + 5, cy, fill=T.TXT_3)
        cv.create_line(cx, cy - 5, cx, cy + 5, fill=T.TXT_3)

        # sun and moon
        saz, sel_ = st["sun"]
        if sel_ > -3:
            x, y = project(saz, sel_, cx, cy, r)
            g = T.px(7)
            for k in range(8):
                a = math.radians(k * 45)
                cv.create_line(x + (g + 2) * math.cos(a), y + (g + 2) * math.sin(a),
                               x + (g + 6) * math.cos(a), y + (g + 6) * math.sin(a), fill=T.TXT_2)
            cv.create_oval(x - g, y - g, x + g, y + g, fill=T.TXT, outline="")
            cv.create_text(x, y + g + 8, text="SUN", font=F["lbl"], fill=T.TXT_2, anchor="n")
        maz, mel, lit = st["moon"]
        if mel > -3:
            x, y = project(maz, mel, cx, cy, r)
            g = T.px(6)
            cv.create_oval(x - g, y - g, x + g, y + g, fill=T.BG, outline=T.TXT_2)
            cv.create_arc(x - g, y - g, x + g, y + g, start=90, extent=-360 * lit, fill=T.TXT_2,
                          outline="")
            cv.create_text(x, y + g + 3, text="MOON %d%%" % round(lit * 100), font=F["lbl"],
                           fill=T.TXT_3, anchor="n")

        # the navigation satellites the GPS chip is tracking
        if s.get("gps_sats", True):
            for g_ in st["gps"]:
                if g_["el"] < 0:
                    continue
                x, y = project(g_["az"], g_["el"], cx, cy, r)
                k = T.px(3)
                cv.create_rectangle(x - k, y - k, x + k, y + k,
                                    fill=T.TXT_3 if g_["used"] else "", outline=T.TXT_3)
                if s.get("labels", True):
                    cv.create_text(x + k + 3, y, text="%s%s" % (g_["sys"], g_["prn"]),
                                   font=F["lbl"], fill=T.TXT_3, anchor="w")

        # trails: where each thing has been across your sky
        if s.get("trails", True):
            for oid, tr in st["trails"].items():
                pts = []
                for az, el in tr:
                    pts.extend(project(az, el, cx, cy, r))
                if len(pts) >= 4:
                    cv.create_line(*pts, fill=T.LINE_HI, width=1, smooth=True)

        ground, boxes = 0, []

        def free(x0, y0, x1, y1):
            """Claim a label box unless it would sit on one already drawn."""
            for a0, b0, a1, b1 in boxes:
                if x0 < a1 and a0 < x1 and y0 < b1 and b0 < y1:
                    return False
            boxes.append((x0, y0, x1, y1))
            return True
        cw, lh = F_w["mapb"], T.px(13)
        order = sorted(st["objs"], key=lambda o: (o["id"] != st["sel"], o["kind"] == "air",
                                                  -o["el"]))
        for o in order:
            sel = o["id"] == st["sel"]
            col = kind_col(o)
            if o["ground"]:
                if ground >= 14 and not sel:
                    continue
                ground += 1
                a = math.radians(o["az"])
                x0, y0 = cx + (r + T.px(3)) * math.sin(a), cy - (r + T.px(3)) * math.cos(a)
                x1, y1 = cx + (r + T.px(11)) * math.sin(a), cy - (r + T.px(11)) * math.cos(a)
                cv.create_line(x0, y0, x1, y1, fill=T.ACCENT if sel else T.TXT_2, width=2)
                st["hits"].append((x1, y1, o["id"]))
                if sel:
                    cv.create_text(x1 + 8 * math.sin(a), y1 - 8 * math.cos(a), text=o["label"],
                                   font=F["lbl"], fill=T.TXT,
                                   anchor="w" if 0 < o["az"] < 180 else "e")
                continue
            if o["el"] < -2:
                continue
            x, y = project(o["az"], o["el"], cx, cy, r)
            st["hits"].append((x, y, o["id"]))
            k = T.px(5)
            if o["kind"] in ("air", "mil"):
                crs = math.radians(o.get("course") or 0.0)
                pts = []
                for da, dist in ((0, k * 1.5), (2.5, k), (math.pi, k * 0.4), (-2.5, k)):
                    pts += [x + dist * math.sin(crs + da), y - dist * math.cos(crs + da)]
                cv.create_polygon(*pts, fill=col, outline="")
            elif o["kind"] == "sonde":
                cv.create_polygon(x, y - k, x + k, y, x, y + k, x - k, y, fill="", outline=col,
                                  width=2)
            else:
                cv.create_oval(x - k, y - k, x + k, y + k, outline=col, width=2)
                cv.create_line(x - k - 3, y, x + k + 3, y, fill=col)
            if sel:
                cv.create_oval(x - k * 2.4, y - k * 2.4, x + k * 2.4, y + k * 2.4,
                               outline=T.ACCENT, width=2)
                cv.create_line(cx, cy, x, y, fill=T.ACCENT, dash=(3, 3))
            if s.get("labels", True):
                sub = "%d°" % round(o["el"])
                if o.get("alt_ft"):
                    sub += "  FL%03d" % round(o["alt_ft"] / 100) if o["alt_ft"] >= 18000 else \
                        "  %s ft" % format(int(o["alt_ft"]), ",")
                wid = max(len(o["label"]) * cw, len(sub) * F_w["lbl"]) + 6
                # try right of the mark, then left; skip the label rather than pile them up
                for lx, anc in ((x + k + 5, "w"), (x - k - 5, "e")):
                    x0 = lx if anc == "w" else lx - wid
                    if sel or free(x0, y - lh, x0 + wid, y + lh):
                        cv.create_text(lx, y - 2, text=o["label"], font=F["mapb"], fill=col,
                                       anchor="s" + anc)
                        cv.create_text(lx, y, text=sub, font=F["lbl"], fill=T.TXT_3,
                                       anchor="n" + anc)
                        break

        w = cv.winfo_width()
        cv.create_text(T.px(10), T.px(8), anchor="nw", font=F["lbl"], fill=T.TXT_3,
                       text="%s  %.4f, %.4f  %d m" % ("GPS FIX" if st["fix"] else "HOME (no GPS fix)",
                                                      st["home"][0], st["home"][1], st["home"][2]))
        cv.create_text(w - T.px(10), T.px(8), anchor="ne", font=F["lbl"], fill=T.TXT_3,
                       text="NORTH UP · HORIZON AT THE RIM")
        o = next((x for x in st["objs"] if x["id"] == st["sel"]), None)
        hh = cv.winfo_height()
        if o is None:
            cv.create_text(T.px(10), hh - T.px(8), anchor="sw", font=F["lbl"], fill=T.TXT_3,
                           text="TAP ANYTHING · ↑ ↓ STEP THROUGH WHAT IS UP")
        else:
            what = {"air": "AIRCRAFT", "mil": "MILITARY AIRCRAFT", "sonde": "WEATHER BALLOON",
                    "sat": "SATELLITE", "aprs": "APRS STATION", "mesh": "MESH NODE"}[o["kind"]]
            lines = [("Look %s (%03d°), %d° up" % (compass(o["az"]), round(o["az"]) % 360,
                                                     max(0, round(o["el"]))))
                     if not o["ground"] else "Bearing %s (%03d°)" % (compass(o["az"]),
                                                                     round(o["az"]) % 360),
                     ("%.1f km away" % o["km"]) if o["km"] < 10000 else "in orbit"]
            if o.get("alt_ft"):
                lines.append("%s ft" % format(int(o["alt_ft"]), ","))
            if o.get("kt"):
                lines.append("%d kt, heading %03d°" % (o["kt"], (o.get("course") or 0) % 360))
            y = hh - T.px(8)
            for ln in reversed(lines):
                cv.create_text(T.px(10), y, anchor="sw", font=F["map"], fill=T.TXT_2, text=ln)
                y -= T.px(15)
            cv.create_text(T.px(10), y, anchor="sw", font=F["smb"], fill=kind_col(o),
                           text=o["label"])
            cv.create_text(T.px(10), y - T.px(19), anchor="sw", font=F["lbl"], fill=T.TXT_3,
                           text=T.spaced(what) if len(what) < 12 else what)
        if demo:
            cv.create_text(w - T.px(10), cv.winfo_height() - T.px(8), anchor="se", font=F["lbl"],
                           fill=T.ACCENT, text="DEMO · SYNTHETIC TRAFFIC, NOT REAL")
        else:
            hold = S.radio_holder()
            cv.create_text(w - T.px(10), cv.winfo_height() - T.px(8), anchor="se", font=F["lbl"],
                           fill=T.TXT_3,
                           text=("PLANE MAP PAUSED · RADIO ON %s" % hold.upper()) if hold else
                           {"live": "PLANE MAP LIVE"}.get(st["src"], "PLANE MAP: NO DATA"))

    def draw_strip():
        strip.delete("all")
        w, h = max(strip.winfo_width(), 50), strip.winfo_height()
        now = time.time()
        span = 30 * 60
        y0, y1 = T.px(4), h - T.px(16)
        if not st["auto"]:
            strip.create_rectangle(0, y0, w, y1, outline=T.LINE, fill="")
            strip.create_text(w / 2, (y0 + y1) / 2, text="press A to share the radio automatically",
                              font=F["lbl"], fill=T.TXT_3)
            return
        shade = {"air": T.LINE, "aprs": T.FILL, "sensors": T.LINE_HI, "sonde": T.NOTE}
        short = {"air": "AIR", "aprs": "APRS", "sensors": "433", "sonde": "SONDE"}
        for mode, a, b in schedule(now, cfg[0], can, 30):
            x0 = (a - now) / span * w
            x1 = min(w, (b - now) / span * w)
            if x1 <= x0 + 1:
                continue
            strip.create_rectangle(x0, y0, x1 - 1, y1, fill=shade.get(mode, T.LINE), outline="")
            if x1 - x0 > T.px(26):
                strip.create_text(x0 + 4, (y0 + y1) / 2, text=short[mode], anchor="w",
                                  font=F["lbl"],
                                  fill=T.BG if mode in ("sonde",) else T.TXT)
        for m in (0, 10, 20, 30):
            x = m * 60 / span * w
            strip.create_text(min(max(x, 0), w), h - 2, text="now" if m == 0 else "+%dm" % m,
                              font=F["lbl"], fill=T.TXT_3,
                              anchor="sw" if m == 0 else ("se" if m == 30 else "s"))

    def render_side():
        objs = st["objs"]
        up = [o for o in objs if not o["ground"] and o["el"] > 0]
        info = st.get("info") or {}
        now = time.time()
        sched = schedule(now, cfg[0], can) if st["auto"] else []
        holder = S.radio_holder()

        def state(k):
            if k == "mesh":
                return ""
            if k == "air":
                live = st["src"] in ("live", "demo")
                return "● live" if live and (demo or not holder) else ("paused" if holder else "")
            if k not in can:
                return "not set up"
            if holder == LEASE.get(MODES[k][1]) or (demo and st["mode"] == k):
                return "● listening"
            nxt = next((a_ for m_, a_, _ in sched if m_ == k and a_ > now + 1), None)
            if nxt:
                left = int(nxt - now)
                return "in %d:%02d" % (left // 60, left % 60)
            return ""

        def age(t):
            return "" if not t else " · " + O.ago(max(0, now - t))
        n_air = sum(1 for o in objs if o["kind"] in ("air", "mil"))
        n_aprs = sum(1 for o in objs if o["kind"] == "aprs")
        n_sonde = sum(1 for o in objs if o["kind"] == "sonde")
        n_mesh = sum(1 for o in objs if o["kind"] == "mesh")
        vals = {"air": "%d  (%d above you)" % (n_air, sum(1 for o in up if o["kind"] in ("air", "mil")))
                if n_air else "none heard",
                "aprs": ("%d station%s%s" % (n_aprs, "" if n_aprs == 1 else "s",
                                             age(info.get("aprs_t")))) if n_aprs else "none heard",
                "sensors": ("%d device%s%s" % (info["sensors_n"], "" if info["sensors_n"] == 1
                                               else "s", age(info.get("sensors_t"))))
                if info.get("sensors_n") else "none heard",
                "sonde": ("%d in the air" % n_sonde) if n_sonde else
                ("launch in %dh%02d" % divmod(int(info.get("launch_s", 0) // 60), 60)),
                "mesh": ("%d node%s" % (n_mesh, "" if n_mesh == 1 else "s")) if n_mesh else "none"}
        for k, (n_, v_, x_) in srow.items():
            txt = state(k)
            v_.config(text=vals[k], fg=T.NOTE if (k == "sonde" and n_sonde) else
                      (T.TXT if not vals[k].startswith("none") else T.TXT_3))
            x_.config(text=txt, fg=T.ACCENT if txt.startswith("●") else T.TXT_3)
        saz, sel_ = st["sun"]
        maz, mel, lit = st["moon"]
        used = sum(1 for g_ in st["gps"] if g_["used"])
        astro.config(text="SUN %s  ·  MOON %s %d%%  ·  GPS %s" % (
            ("%d° %s" % (round(sel_), compass(saz, 8))) if sel_ > 0 else daylight(sel_).split()[0],
            ("%d° %s" % (round(mel), compass(maz, 8))) if mel > 0 else "down", round(lit * 100),
            ("%d/%d sats" % (used, len(st["gps"]))) if st["gps"] else "no sky data"))
        over.config(state="normal")
        over.delete("1.0", "end")
        st["over_ids"] = [o["id"] for o in up[:7]]
        for o in up[:7]:
            tag = "note" if kind_col(o) == T.NOTE else "hi"
            tags = (tag, "cur") if o["id"] == st["sel"] else (tag,)
            over.insert("end", "%-10s" % o["label"][:10], tags)
            over.insert("end", " %3d° %-3s %5s\n" % (
                round(o["el"]), compass(o["az"]),
                ("%d km" % round(o["km"])) if o["km"] < 10000 else "orbit"),
                ("dim", "cur") if o["id"] == st["sel"] else ("dim",))
        if not up:
            over.insert("end", "Nothing above the horizon yet.\n"
                               "Aircraft appear when the plane map\nhears them.", "dim")
        over.config(state="disabled")
        fix = st["fix"]
        pos_pill.config(text="GPS fix" if fix else "Home position", bg=S.GREEN if fix else S.DIM)
        sky_pill.config(text="%d in the sky" % len(up), bg=S.GREEN if up else S.DIM)

    # ---- the director: actuates the pure decision above through the workstation
    def set_child(mode):
        """Make the radio do `mode`. Only ever closes a workspace the director opened."""
        key = MODES[mode][1] if mode in MODES else None
        cur = st["child"]
        if cur == key:
            return
        if cur and shell is not None and cur in shell.ws:
            if shell.active == cur:
                # you are looking at it: it is yours now. Never close a workspace under you.
                st["child"] = None
                return
            shell.close(cur)
        st["child"] = None
        if key and shell is not None and not demo:
            if key in shell.ws:
                return                      # you have it open: leave your workspace alone
            if shell.open(key, ["--listen"], show=False) is None:
                st["child"] = key
                slog.event("info", "Autopilot: radio to %s" % MODES[mode][0], id="ap:" + mode)

    def director():
        now = time.time()
        hp = S.health()
        holder = S.radio_holder()
        mine = st["child"] is not None and holder == LEASE.get(st["child"])
        if holder and not mine:
            st["yield_t"] = now               # you are on the radio: remember when
        ctx = {"on": st["auto"], "hot": hp.get("level") == "hot", "low_batt": hp.get("low_batt"),
               "holder": holder, "mine": mine, "can": can}
        mode, until, why = direct(now, cfg[0], ctx)
        if mode in MODES and not holder and now - st["yield_t"] < 20:
            mode, until, why = "yield", None, "Radio just came free - resuming in a moment."
        if mode != st["mode"]:
            set_child(mode if mode in MODES else "air")
        st["mode"], st["until"], st["why"] = mode, until, why
        S.AUTOPILOT.update(on=st["auto"], mode=mode, until=until,
                           sched=schedule(now, cfg[0], can, 30) if st["auto"] and mode in MODES
                           else [])
        if embedded is False and st["auto"]:
            why = "Open Overwatch from the Hub to let Autopilot drive the radio."
        name = {"off": "Manual", "rest": "Standing down", "yield": "Yours"}.get(
            mode, MODES.get(mode, ("", ""))[0])
        if until and mode in MODES:
            left = max(0, int(until - now))
            radio_sec.right.config(text="next in %d:%02d" % (left // 60, left % 60))
        else:
            radio_sec.right.config(text="autopilot " + ("on" if st["auto"] else "off"))
        now_lbl.config(text=name, fg=T.TXT if mode in MODES else T.TXT_2)
        why_lbl.config(text=why)
        auto_pill.config(text="Autopilot " + ("on" if st["auto"] else "off"),
                         bg=S.GREEN if st["auto"] and mode in MODES else
                         (S.AMBER if st["auto"] else S.DIM))

    def toggle_auto(_=None):
        st["auto"] = not st["auto"]
        st["mode"] = "?"                                  # force the director to act now
        if not st["auto"]:
            set_child("air")
        T.set_btn(auto_btn, "Autopilot: ON" if st["auto"] else "Autopilot: off",
                  kind="primary" if st["auto"] else "ghost")
        director()
        draw_strip()

    def toggle(key, btn, name):
        def f(_=None):
            s[key] = not s.get(key)
            T.set_btn(btn[0], "%s: %s" % (name, "ON" if s[key] else "off"),
                      kind="primary" if s[key] and key == "voice" else "ghost")
            try:
                S.save_json(spath, s)
            except OSError:
                pass
            if key == "voice" and s[key]:
                say("Voice on.")
            draw()
        return f

    def say(text):
        if shutil.which("espeak-ng"):
            S.fire_and_forget(["espeak-ng", "-s", "150", text])

    def health_say(kind, text):                 # monitor thread: speaking needs no Tk
        if s.get("voice") and not st["closed"] and not demo:
            say(text.replace("°C", " degrees").replace(" - ", ". "))
    S.on_health(health_say)

    auto_btn = S.btn(bar, "Autopilot: off", toggle_auto, F, padx=12, pady=5, kind="ghost")
    auto_btn.pack(side="left")
    vb, lb, tb, gb = [None], [None], [None], [None]
    for holder_, key, name, hot in ((vb, "voice", "Voice", "v"), (lb, "labels", "Labels", "l"),
                                    (tb, "trails", "Trails", "t"), (gb, "gps_sats", "GPS sats", "g")):
        fn = toggle(key, holder_, name)
        holder_[0] = S.btn(bar, "%s: %s" % (name, "ON" if s.get(key) else "off"), fn, F, padx=10,
                           pady=5, kind="primary" if s.get(key) and key == "voice" else "ghost")
        holder_[0].pack(side="left", padx=(T.px(6), 0))
        root.bind(hot, fn)
    root.bind("a", toggle_auto)

    def click(e):
        best, bd = None, T.px(22) ** 2
        for x, y, oid in st["hits"]:
            d = (x - e.x) ** 2 + (y - e.y) ** 2
            if d < bd:
                best, bd = oid, d
        st["sel"] = best
        draw()
        render_side()
    cv.bind("<Button-1>", click)

    def pick_row(e):                              # tap a row in "Highest in the sky"
        i = int(over.index("@%d,%d" % (e.x, e.y)).split(".")[0]) - 1
        ids = st.get("over_ids") or []
        if 0 <= i < len(ids):
            st["sel"] = ids[i]
            draw()
            render_side()
        return "break"
    over.bind("<Button-1>", pick_row)

    def step_sel(d):
        ids = [o["id"] for o in st["objs"] if not o["ground"] and o["el"] > 0]
        if ids:
            i = ids.index(st["sel"]) + d if st["sel"] in ids else 0
            st["sel"] = ids[i % len(ids)]
            draw()
            render_side()
    root.bind("<Down>", lambda e: step_sel(1))
    root.bind("<Up>", lambda e: step_sel(-1))
    cv.bind("<Configure>", lambda e: draw())

    def pump():
        got = None
        while not q.empty():
            got = q.get()
        if got and "err" not in got:
            st.update(objs=got["objs"], gps=got["gps"], home=got["home"], fix=got["fix"],
                      sun=got["sun"], moon=got["moon"], src=got["src"], t=got["t"],
                      info=got["info"])
            live = set()
            for o in got["objs"]:
                if o["ground"] or o["el"] < -2:
                    continue
                live.add(o["id"])
                tr = st["trails"].setdefault(o["id"], collections.deque(maxlen=90))
                if not tr or abs(tr[-1][0] - o["az"]) + abs(tr[-1][1] - o["el"]) > 0.3:
                    tr.append((o["az"], o["el"]))
            for oid in [k for k in st["trails"] if k not in live]:
                del st["trails"][oid]
            if s.get("voice") and not demo:
                for line in caller.calls(got["objs"], got["t"]):
                    say(line)
                    slog.event("info", line, id=line[:40])
            draw()
            render_side()
        director()
        draw_strip()
        root.after(1000, pump)

    def on_close():
        st["closed"] = True
        if health_say in S._HEALTH["watch"]:
            S._HEALTH["watch"].remove(health_say)
        S.AUTOPILOT.update(on=False, mode="off", until=None, sched=[])
        feed.stopped = True
        if st["child"] and shell is not None and st["child"] in shell.ws:
            shell.close(st["child"])                  # give the radio back to the plane map
        st["child"] = None
        root.destroy()

    def edit_settings():
        import settings_ui
        schema = [("Autopilot - minutes on each app per round (0 leaves it out)", [
            {"key": "air_min", "label": "Plane map", "type": "int", "min": 0, "max": 60},
            {"key": "aprs_min", "label": "APRS", "type": "int", "min": 0, "max": 60},
            {"key": "sensors_min", "label": "Sensors", "type": "int", "min": 0, "max": 60},
            {"key": "sonde_min", "label": "Balloons (launch windows only)", "type": "int",
             "min": 0, "max": 60, "help": "around 11:00 and 23:00 UTC, when routine flights go up"},
        ]), ("Dome", [
            {"key": "overhead_deg", "label": "Call it overhead above (degrees)", "type": "int",
             "min": 30, "max": 85},
        ])]

        def saved(ns):
            s.update(ns)
            S.save_json(spath, s)
            cfg[0] = plans(s)
            caller.overhead_deg = float(s.get("overhead_deg") or 60)
            st["mode"] = "?"
            draw()
        settings_ui.open_settings(root, F, "Overwatch settings", schema, s, saved, path=spath)

    S.btn(bar, "Quit" if not embedded else "Close", on_close, F, padx=10, pady=5,
          kind="quiet").pack(side="right")
    S.btn(bar, "Settings", edit_settings, F, padx=10, pady=5, kind="quiet").pack(
        side="right", padx=(0, T.px(6)))
    S.bind_quit(root, on_close)
    if "--auto" in sys.argv:
        root.after(500, toggle_auto)
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
