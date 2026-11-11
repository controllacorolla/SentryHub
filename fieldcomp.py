#!/usr/bin/env python3
"""Field computer - the uConsole away from the bench.

MAP       An offline-capable moving map (the same tile engine as Sky and Ops). Your recorded
          track is drawn over it, waypoints you drop are marked, and the current GPS fix is a
          cursor. Pan, zoom, switch dark / satellite / streets, and mark where you are.
TRIP      Record a track: live distance, moving time, speed, and elevation gain. Export the
          whole thing to a standard .gpx you can open anywhere.
ALMANAC   Sun and moon rise/set and position for where you are now, the moon phase, daylight
          state, and the next ISS pass - for planning a hike, a photo, or a satellite pass.

Receive-only and self-contained: it reads the GPS and draws maps, nothing else.
--demo walks a synthetic track around Denver so the screens work without a GPS fix.
"""
import math
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S          # noqa: E402

DEFAULTS = {"home": {"lat": 39.742, "lon": -104.991, "alt_m": 1609}, "zoom": 13,
            "layer": "dark", "min_move_m": 4.0}
TRACK_DIR = os.path.join(S.DATA, "tracks")
EARTH_R = 6371000.0


# ---- pure geo + track math (tested) ---------------------------------------------------------
def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1, lon1, lat2, lon2):
    """Initial bearing from point 1 to point 2, degrees from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def track_stats(points):
    """points = [(t, lat, lon, alt|None, speed|None), ...] -> summary dict.
    Distance follows the track; moving time ignores stops; elevation gain sums the climbs."""
    out = {"points": len(points), "distance_m": 0.0, "duration_s": 0.0, "moving_s": 0.0,
           "max_speed": 0.0, "gain_m": 0.0, "loss_m": 0.0}
    if len(points) < 2:
        if points:
            out["duration_s"] = 0.0
        return out
    out["duration_s"] = points[-1][0] - points[0][0]
    for (t0, la0, lo0, al0, sp0), (t1, la1, lo1, al1, sp1) in zip(points, points[1:]):
        d = haversine(la0, lo0, la1, lo1)
        dt = t1 - t0
        out["distance_m"] += d
        if dt > 0 and d / dt > 0.5:            # faster than 0.5 m/s counts as moving
            out["moving_s"] += dt
        v = sp1 if sp1 is not None else (d / dt if dt > 0 else 0)
        out["max_speed"] = max(out["max_speed"], v or 0)
        if al0 is not None and al1 is not None:
            dz = al1 - al0
            if dz > 0.5:
                out["gain_m"] += dz
            elif dz < -0.5:
                out["loss_m"] += -dz
    return out


def fmt_dist(m):
    if m < 1000:
        return "%d m" % round(m)
    return "%.2f km" % (m / 1000.0)


def fmt_dur(sec):
    sec = int(max(0, sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return ("%d:%02d:%02d" % (h, m, s)) if h else ("%d:%02d" % (m, s))


def fmt_latlon(lat, lon):
    return "%.5f, %.5f" % (lat, lon)


def moon_phase_name(lit, waxing):
    """Phase name from lit fraction (0..1) and whether it is waxing."""
    if lit < 0.04:
        return "new"
    if lit > 0.96:
        return "full"
    if lit < 0.46:
        return "waxing crescent" if waxing else "waning crescent"
    if lit < 0.54:
        return "first quarter" if waxing else "last quarter"
    return "waxing gibbous" if waxing else "waning gibbous"


def to_gpx(points, waypoints=(), name="uConsole track"):
    """A GPX 1.1 document: one track of the fixes, plus any waypoints. Standard, so it opens
    in every mapping app."""
    import xml.sax.saxutils as sx
    esc = sx.escape
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="uConsole Field Computer" '
           'xmlns="http://www.topografix.com/GPX/1/1">']
    for wp in waypoints:
        lat, lon = wp["lat"], wp["lon"]
        out.append('  <wpt lat="%.6f" lon="%.6f">' % (lat, lon))
        if wp.get("alt") is not None:
            out.append('    <ele>%.1f</ele>' % wp["alt"])
        out.append('    <name>%s</name>' % esc(str(wp.get("name", "wpt"))))
        out.append('  </wpt>')
    out.append('  <trk><name>%s</name><trkseg>' % esc(name))
    for t, lat, lon, alt, _sp in points:
        seg = '    <trkpt lat="%.6f" lon="%.6f">' % (lat, lon)
        if alt is not None:
            seg += '<ele>%.1f</ele>' % alt
        seg += '<time>%s</time>' % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        seg += '</trkpt>'
        out.append(seg)
    out.append('  </trkseg></trk>')
    out.append('</gpx>')
    return "\n".join(out)


def rise_set(elev_fn, lat, lon, day_start_utc, horizon=-0.833, step=300):
    """Scan a day for an object crossing the horizon. elev_fn(lat, lon, t) -> degrees.
    Returns (rise_utc|None, set_utc|None, always_up, always_down)."""
    prev_t, prev_e = None, None
    rise = set_ = None
    seen_up = seen_down = False
    t = day_start_utc
    end = day_start_utc + 86400
    while t <= end:
        e = elev_fn(lat, lon, t) - horizon
        if e > 0:
            seen_up = True
        else:
            seen_down = True
        if prev_e is not None and (prev_e < 0 <= e or prev_e >= 0 > e):
            # linear-interpolate the crossing minute
            frac = prev_e / (prev_e - e) if prev_e != e else 0
            cross = prev_t + frac * (t - prev_t)
            if prev_e < 0 <= e and rise is None:
                rise = cross
            elif prev_e >= 0 > e and set_ is None:
                set_ = cross
        prev_t, prev_e = t, e
        t += step
    return rise, set_, (seen_up and not seen_down), (seen_down and not seen_up)


def local_midnight_utc(now, tz_offset_s):
    """UTC timestamp of local midnight for the day containing `now`."""
    local = now + tz_offset_s
    day = local - (local % 86400)
    return day - tz_offset_s


# ---- demo GPS ------------------------------------------------------------------------------
def demo_fix(now, home):
    """A synthetic fix walking a small loop near home, ~2.5 m/s."""
    ph = (now % 1800) / 1800.0 * 2 * math.pi        # a gentle 30-min loop
    lat = home["lat"] + 0.004 * math.sin(ph)
    lon = home["lon"] + 0.006 * math.sin(ph) * math.cos(ph)
    alt = home.get("alt_m", 1609) + 25 * math.sin(ph * 2)
    return {"lat": lat, "lon": lon, "altMSL": alt, "mode": 3, "speed": 1.4,
            "track": (math.degrees(ph) + 90) % 360}


# ---- the app --------------------------------------------------------------------------------
def main():
    S.single_instance("Field computer")
    demo = "--demo" in sys.argv
    s, spath = S.settings("fieldcomp", DEFAULTS)
    root, F = S.make_root("Field computer")
    import tkinter as tk
    import queue
    import tiles
    import field_status as FS
    T = S.T
    slog = S.SessionLog("fieldcomp")
    home0 = {"lat": float(s["home"]["lat"]), "lon": float(s["home"]["lon"]),
             "alt_m": float(s["home"].get("alt_m", 0))}
    st = {"tab": "map", "closed": False, "track": [], "wpts": [], "recording": False,
          "view": None, "z": int(s.get("zoom", 13)), "follow": True, "fix": None,
          "drag": None, "layer": s.get("layer", "dark")}
    q = queue.Queue()
    tl = tiles.TileLayer(on_ready=lambda: q.put(("tiles", None)))
    tl.layer = st["layer"]

    if not demo and not FS.GPS.get("_thread"):
        FS.GPS["_thread"] = True
        threading.Thread(target=FS.gpsd_thread, daemon=True).start()
    S.start_health()

    top = S.top_bar(root, F, "Field computer", "GPS · maps · almanac" if not demo else "demo")
    fix_pill = S.pill(top, F, "No fix")
    rec_pill = S.pill(top, F, "Not recording")
    if demo:
        S.pill(top, F, "DEMO", S.AMBER)

    tabs_row = tk.Frame(root, bg=T.SURFACE)
    tabs_row.pack(side="top", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="top", fill="x")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    panes = {k: tk.Frame(body, bg=S.BG) for k in ("map", "trip", "almanac")}
    tab_btns = {}

    def show_tab(key):
        st["tab"] = key
        for p in panes.values():
            p.pack_forget()
        panes[key].pack(fill="both", expand=True)
        for k, b in tab_btns.items():
            T.set_btn(b, kind="primary" if k == key else "ghost")
        if key == "map":
            draw_map()
        elif key == "trip":
            render_trip()
        elif key == "almanac":
            render_almanac()

    for key, label in (("map", "Map"), ("trip", "Trip"), ("almanac", "Almanac")):
        b = S.btn(tabs_row, label, lambda k=key: show_tab(k), F, padx=16, pady=6, kind="ghost")
        b.pack(side="left", padx=(T.px(6), 0), pady=T.px(5))
        tab_btns[key] = b

    def save():
        s["zoom"], s["layer"] = st["z"], tl.layer
        try:
            S.save_json(spath, s)
        except OSError:
            pass

    # ================= MAP =================
    mp = panes["map"]
    cv = tk.Canvas(mp, bg=tiles.MAPBG if hasattr(tiles, "MAPBG") else "#0a0c0d",
                   highlightthickness=0)
    cv.pack(side="top", fill="both", expand=True)
    mbar = tk.Frame(mp, bg=T.SURFACE)
    mbar.pack(side="bottom", fill="x")
    tk.Frame(mp, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    mrow = tk.Frame(mbar, bg=T.SURFACE)
    mrow.pack(fill="x", padx=T.px(8), pady=T.px(5))

    def view_center():
        if st["follow"] and st["fix"]:
            return st["fix"]["lat"], st["fix"]["lon"]
        if st["view"]:
            return st["view"]
        return home0["lat"], home0["lon"]

    def draw_map():
        if st["tab"] != "map":
            return
        cv.delete("all")
        w, h = max(cv.winfo_width(), 100), max(cv.winfo_height(), 100)
        vlat, vlon = view_center()
        z = tl.clamp_zoom(st["z"])
        tl.draw(cv, vlat, vlon, z, w, h)
        cpx, cpy = tiles.world_px(vlat, vlon, z)

        def scr(lat, lon):
            px, py = tiles.world_px(lat, lon, z)
            return w / 2 + (px - cpx), h / 2 + (py - cpy)
        # track
        if len(st["track"]) >= 2:
            pts = []
            for _t, la, lo, _al, _sp in st["track"]:
                pts += list(scr(la, lo))
            cv.create_line(*pts, fill=T.ACCENT, width=T.px(2), smooth=True)
        # waypoints
        for wp in st["wpts"]:
            x, y = scr(wp["lat"], wp["lon"])
            k = T.px(4)
            cv.create_oval(x - k, y - k, x + k, y + k, fill=T.NOTE, outline="#07080a")
            cv.create_text(x + k + 2, y, text=wp.get("name", ""), anchor="w", font=F["lbl"],
                           fill=T.NOTE)
        # current position
        if st["fix"]:
            x, y = scr(st["fix"]["lat"], st["fix"]["lon"])
            trk = st["fix"].get("track")
            if trk is not None:
                a = math.radians(trk)
                k = T.px(9)
                pts = []
                for da, dist in ((0, k), (2.4, k * 0.6), (math.pi, k * 0.3), (-2.4, k * 0.6)):
                    pts += [x + dist * math.sin(a + da), y - dist * math.cos(a + da)]
                cv.create_polygon(*pts, fill="#ffffff", outline="#2d72d2", width=1)
            else:
                cv.create_oval(x - 6, y - 6, x + 6, y + 6, fill="#ffffff", outline="#2d72d2",
                               width=2)
        # scale + readout
        cv.create_text(T.px(10), T.px(10), anchor="nw", font=F["lbl"], fill=T.TXT_3,
                       text="%s  z%d  %s" % (tl.layer.upper(), z,
                                             "FOLLOW" if st["follow"] else "FREE"))
        if st["fix"]:
            cv.create_text(w - T.px(10), T.px(10), anchor="ne", font=F["lbl"], fill=T.TXT_3,
                           text=fmt_latlon(st["fix"]["lat"], st["fix"]["lon"]))

    def do_zoom(d):
        st["z"] = tl.clamp_zoom(st["z"] + d)
        save()
        draw_map()

    def on_drag_start(e):
        st["drag"] = (e.x, e.y, view_center())
        st["follow"] = False

    def on_drag(e):
        if not st["drag"]:
            return
        x0, y0, (vlat, vlon) = st["drag"]
        z = tl.clamp_zoom(st["z"])
        cpx, cpy = tiles.world_px(vlat, vlon, z)
        nlat, nlon = tiles.from_world_px(cpx - (e.x - x0), cpy - (e.y - y0), z)
        st["view"] = (nlat, nlon)
        draw_map()
    cv.bind("<Button-1>", on_drag_start)
    cv.bind("<B1-Motion>", on_drag)
    cv.bind("<ButtonRelease-1>", lambda e: st.update(drag=None))
    cv.bind("<Configure>", lambda e: draw_map())
    cv.bind("<Button-4>", lambda e: do_zoom(1))
    cv.bind("<Button-5>", lambda e: do_zoom(-1))
    root.bind("+", lambda e: do_zoom(1))
    root.bind("-", lambda e: do_zoom(-1))

    def mark_here():
        fx = st["fix"] or {"lat": view_center()[0], "lon": view_center()[1]}
        wp = {"lat": fx["lat"], "lon": fx["lon"], "alt": fx.get("altMSL"),
              "name": "WP%d" % (len(st["wpts"]) + 1), "t": time.time()}
        st["wpts"].append(wp)
        slog.event("fieldcomp", "waypoint %s at %s" % (wp["name"],
                                                       fmt_latlon(wp["lat"], wp["lon"])),
                   id="wp%d" % len(st["wpts"]))
        draw_map()

    S.btn(mrow, "Mark here", mark_here, F, padx=12, pady=4, kind="primary").pack(side="left")
    S.btn(mrow, "Center", lambda: st.update(follow=True) or draw_map(), F, padx=10, pady=4,
          kind="ghost").pack(side="left", padx=(T.px(6), 0))

    def cycle_layer():
        tl.cycle()
        save()
        draw_map()
    S.btn(mrow, "Layer", cycle_layer, F, padx=10, pady=4, kind="ghost").pack(
        side="left", padx=(T.px(6), 0))
    S.btn(mrow, "−", lambda: do_zoom(-1), F, padx=12, pady=4, kind="quiet").pack(side="right")
    S.btn(mrow, "+", lambda: do_zoom(1), F, padx=12, pady=4, kind="quiet").pack(
        side="right", padx=(0, T.px(4)))

    # ================= TRIP =================
    tp = panes["trip"]
    thead = tk.Frame(tp, bg=T.SURFACE)
    thead.pack(side="top", fill="x")
    tk.Frame(tp, bg=S.LINE, height=1).pack(side="top", fill="x")
    trow = tk.Frame(thead, bg=T.SURFACE)
    trow.pack(fill="x", padx=T.px(10), pady=T.px(7))
    rec_btn = S.btn(trow, "Start recording", lambda: toggle_record(), F, padx=12, pady=4,
                    kind="primary")
    rec_btn.pack(side="left")
    S.btn(trow, "Clear", lambda: clear_track(), F, padx=10, pady=4, kind="quiet").pack(
        side="left", padx=(T.px(6), 0))
    S.btn(trow, "Export GPX", lambda: export_gpx(), F, padx=10, pady=4, kind="ghost").pack(
        side="left", padx=(T.px(6), 0))
    trip_status = tk.Label(trow, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
    trip_status.pack(side="left", padx=(T.px(12), 0))
    tgrid = tk.Frame(tp, bg=S.BG)
    tgrid.pack(fill="both", expand=True, padx=T.px(16), pady=T.px(14))
    tcells = {}
    for i, (key, label) in enumerate((("distance", "Distance"), ("moving", "Moving time"),
                                      ("duration", "Total time"), ("avg", "Avg speed"),
                                      ("max", "Max speed"), ("gain", "Elevation gain"),
                                      ("alt", "Altitude now"), ("points", "Track points"))):
        r, c = divmod(i, 4)
        tgrid.columnconfigure(c, weight=1, uniform="t")
        cell = tk.Frame(tgrid, bg=T.SURFACE, highlightthickness=1, highlightbackground=S.LINE)
        cell.grid(row=r, column=c, sticky="nsew", padx=T.px(5), pady=T.px(5))
        tk.Label(cell, text=T.spaced(label), font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE,
                 anchor="w").pack(fill="x", padx=T.px(10), pady=(T.px(8), 0))
        v = tk.Label(cell, text="—", font=F["data"], fg=T.TXT, bg=T.SURFACE, anchor="w")
        v.pack(fill="x", padx=T.px(10), pady=(0, T.px(10)))
        tcells[key] = v

    def toggle_record():
        st["recording"] = not st["recording"]
        T.set_btn(rec_btn, "Stop recording" if st["recording"] else "Start recording",
                  "danger" if st["recording"] else "primary")
        rec_pill.config(text="Recording" if st["recording"] else "Not recording",
                        bg=S.GREEN if st["recording"] else S.DIM)
        if st["recording"]:
            slog.event("fieldcomp", "track recording started", id="rec")

    def clear_track():
        st["track"] = []
        render_trip()
        draw_map()

    def export_gpx():
        if not st["track"] and not st["wpts"]:
            trip_status.config(text="nothing to export yet", fg=S.AMBER)
            return
        try:
            os.makedirs(TRACK_DIR, exist_ok=True)
            path = os.path.join(TRACK_DIR, time.strftime("track-%Y%m%d-%H%M%S.gpx"))
            with open(path, "w") as f:
                f.write(to_gpx(st["track"], st["wpts"]))
            trip_status.config(text="saved %s" % path, fg=T.TXT)
            slog.event("fieldcomp", "exported %d pts to %s" % (len(st["track"]),
                                                               os.path.basename(path)), id="gpx")
        except OSError as e:
            trip_status.config(text="export failed: %s" % e, fg=S.AMBER)

    def render_trip():
        stt = track_stats(st["track"])
        tcells["distance"].config(text=fmt_dist(stt["distance_m"]))
        tcells["moving"].config(text=fmt_dur(stt["moving_s"]))
        tcells["duration"].config(text=fmt_dur(stt["duration_s"]))
        avg = (stt["distance_m"] / stt["moving_s"]) if stt["moving_s"] > 0 else 0
        tcells["avg"].config(text="%.1f m/s  %.1f km/h" % (avg, avg * 3.6))
        tcells["max"].config(text="%.1f m/s  %.1f km/h" % (stt["max_speed"], stt["max_speed"] * 3.6))
        tcells["gain"].config(text="↑%d m  ↓%d m" % (round(stt["gain_m"]), round(stt["loss_m"])))
        fx = st["fix"]
        tcells["alt"].config(text=("%d m" % round(fx["altMSL"])) if fx and fx.get("altMSL")
                             is not None else "—")
        tcells["points"].config(text=str(stt["points"]))

    # ================= ALMANAC =================
    ap = panes["almanac"]
    almwrap = tk.Frame(ap, bg=S.BG)
    almwrap.pack(fill="both", expand=True, padx=T.px(16), pady=T.px(14))

    def render_almanac():
        for w in almwrap.winfo_children():
            w.destroy()
        import overwatch as OW
        now = time.time()
        lat, lon = view_center()
        tz = -time.timezone if not time.daylight else -time.altzone
        midnight = local_midnight_utc(now, tz)
        saz, sel = OW.sun_azel(lat, lon, now)
        maz, mel, lit = OW.moon_azel(lat, lon, now)
        srise, sset, sup, sdown = rise_set(lambda la, lo, tt: OW.sun_azel(la, lo, tt)[1],
                                           lat, lon, midnight, horizon=-0.833)
        mrise, mset, _, _ = rise_set(lambda la, lo, tt: OW.moon_azel(la, lo, tt)[1],
                                     lat, lon, midnight, horizon=0.0)

        def clock(ts):
            return time.strftime("%H:%M", time.localtime(ts)) if ts else "—"

        def card(parent, title):
            f = tk.Frame(parent, bg=T.SURFACE, highlightthickness=1, highlightbackground=S.LINE)
            T.section(f, F, title).pack(fill="x", padx=T.px(10), pady=(T.px(8), T.px(4)))
            return f
        cols = tk.Frame(almwrap, bg=S.BG)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1, uniform="a")
        cols.columnconfigure(1, weight=1, uniform="a")

        sun = card(cols, "Sun")
        sun.grid(row=0, column=0, sticky="nsew", padx=(0, T.px(6)), pady=T.px(4))
        for label, val in (("Now", "%d° up, bearing %s" % (round(sel), OW.compass(saz, 8))
                            if sel > 0 else OW.daylight(sel)),
                           ("Sunrise", clock(srise)), ("Sunset", clock(sset)),
                           ("State", OW.daylight(sel))):
            rowf = tk.Frame(sun, bg=T.SURFACE)
            rowf.pack(fill="x", padx=T.px(10), pady=1)
            tk.Label(rowf, text=label, font=F["map"], fg=T.TXT_3, bg=T.SURFACE, width=10,
                     anchor="w").pack(side="left")
            tk.Label(rowf, text=val, font=F["map"], fg=T.TXT, bg=T.SURFACE,
                     anchor="w").pack(side="left")
        tk.Frame(sun, bg=T.SURFACE, height=T.px(8)).pack()

        moon = card(cols, "Moon")
        moon.grid(row=0, column=1, sticky="nsew", padx=(T.px(6), 0), pady=T.px(4))
        lit_later = OW.moon_azel(lat, lon, now + 3600)[2]
        waxing = lit_later >= lit
        phase = moon_phase_name(lit, waxing)
        for label, val in (("Now", "%d° up, bearing %s" % (round(mel), OW.compass(maz, 8))
                            if mel > 0 else "below horizon"),
                           ("Moonrise", clock(mrise)), ("Moonset", clock(mset)),
                           ("Phase", "%s, %d%% lit" % (phase, round(lit * 100)))):
            rowf = tk.Frame(moon, bg=T.SURFACE)
            rowf.pack(fill="x", padx=T.px(10), pady=1)
            tk.Label(rowf, text=label, font=F["map"], fg=T.TXT_3, bg=T.SURFACE, width=10,
                     anchor="w").pack(side="left")
            tk.Label(rowf, text=val, font=F["map"], fg=T.TXT, bg=T.SURFACE,
                     anchor="w").pack(side="left")
        tk.Frame(moon, bg=T.SURFACE, height=T.px(8)).pack()

        # ISS / satellites
        sat = card(almwrap, "Overhead now")
        sat.pack(fill="x", pady=(T.px(8), 0))
        orb = OW.load_orbiters() if not demo else None
        objs = OW.orbiters_now(orb, (lat, lon, home0["alt_m"])) if orb else (
            OW.demo_orbiter(now) if demo else [])
        if objs:
            for o in objs:
                rowf = tk.Frame(sat, bg=T.SURFACE)
                rowf.pack(fill="x", padx=T.px(10), pady=1)
                tk.Label(rowf, text=o["label"], font=F["rowb"], fg=T.NOTE, bg=T.SURFACE,
                         width=14, anchor="w").pack(side="left")
                tk.Label(rowf, text="%d° up, %s, %d km" % (round(o["el"]), OW.compass(o["az"], 8),
                                                           round(o["km"])), font=F["map"],
                         fg=T.TXT, bg=T.SURFACE, anchor="w").pack(side="left")
        else:
            tk.Label(sat, text="No tracked satellites above the horizon. "
                              "(Weather Sats / SSTV download the elements.)", font=F["map"],
                     fg=T.TXT_3, bg=T.SURFACE, anchor="w", wraplength=T.px(560),
                     justify="left").pack(fill="x", padx=T.px(10), pady=(0, T.px(6)))
        tk.Frame(sat, bg=T.SURFACE, height=T.px(6)).pack()
        tk.Label(almwrap, text="For %s  ·  %s" % (fmt_latlon(lat, lon),
                 "live GPS" if (st["fix"] and not demo) else "home / map centre"), font=F["lbl"],
                 fg=T.TXT_3, bg=S.BG).pack(anchor="w", pady=(T.px(8), 0))

    # ---- GPS + recording tick
    def tick():
        now = time.time()
        if demo:
            fx = demo_fix(now, home0)
        else:
            tpv = FS.GPS.get("tpv") if time.time() - (FS.GPS.get("t") or 0) < 30 else None
            fx = None
            if tpv and isinstance(tpv.get("lat"), (int, float)) and (tpv.get("mode") or 0) >= 2:
                fx = {"lat": tpv["lat"], "lon": tpv["lon"],
                      "altMSL": tpv.get("altMSL", tpv.get("alt")),
                      "mode": tpv.get("mode"), "speed": tpv.get("speed"),
                      "track": tpv.get("track")}
        st["fix"] = fx
        if fx:
            fix_pill.config(text="%dD fix" % (fx.get("mode") or 2), bg=S.GREEN)
            if st["recording"]:
                tr = st["track"]
                moved = (not tr or haversine(tr[-1][1], tr[-1][2], fx["lat"], fx["lon"])
                         >= s.get("min_move_m", 4.0))
                if moved:
                    tr.append((now, fx["lat"], fx["lon"], fx.get("altMSL"), fx.get("speed")))
        else:
            fix_pill.config(text="No fix", bg=S.DIM)
        if st["tab"] == "map":
            draw_map()
        elif st["tab"] == "trip":
            render_trip()
        if not st["closed"]:
            root.after(1000, tick)

    def pump():
        got = False
        while not q.empty():
            try:
                q.get_nowait()
                got = True
            except Exception:
                break
        if got and st["tab"] == "map":
            draw_map()
        if not st["closed"]:
            root.after(300, pump)

    def on_close():
        st["closed"] = True
        tl.close()
        save()
        root.destroy()

    S.bind_quit(root, on_close)
    S.header_quit(top, root, F, on_close)

    show_tab("map")
    tick()
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
