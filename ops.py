#!/usr/bin/env python3
"""Ops - one picture of everything the uConsole hears.

An analyst-workstation view: every receive-only source the suite has (ADS-B aircraft,
APRS stations, weather balloons, Meshtastic nodes) fused onto one map, a layer rail,
an entity inspector, and a timeline of the day's events from every app.

Ops never touches the radio. It reads what the other apps already produce:
  aircraft    readsb/dump1090 aircraft.json (same sources as Sky)
  APRS        ~/.cache/uconsole-suite/aprs_stations.json  (APRS app)
  balloons    ~/.cache/uconsole-suite/sondes.json         (Balloons app)
  mesh        ~/.cache/uconsole-suite/mesh_nodes.json     (Mesh app)
  timeline    the shared session log (every app)
It shows what was broadcast and heard - positions people and aircraft chose to transmit.
It does not profile anyone (no home/work guessing, no pattern-of-life).

--demo uses Sky's synthetic traffic plus synthetic APRS/balloon/mesh entities.
"""
import json
import math
import os
import queue
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import suite as S          # noqa: E402
import skyintel as SI      # noqa: E402
import aprs as A           # noqa: E402

LAYERS = [  # key, label, colour - greyscale + one cyan for notable, like the workstation
    ("air", "Aircraft", "#e8eaed"),
    ("mil", "Military aircraft", "#5ec4d4"),
    ("aprs", "APRS stations", "#9aa1aa"),
    ("sonde", "Weather balloons", "#c8b6ff"),
    ("mesh", "Mesh nodes", "#7fa7d9"),
]
LAYER_COL = {k: c for k, _, c in LAYERS}
STALE_S = {"air": 60, "mil": 60, "aprs": 3 * 3600, "sonde": 1800, "mesh": 6 * 3600}
APP_COL = {}                 # timeline lanes are greyscale; marks use the accent


# ---- fusion (pure) --------------------------------------------------------------------------
def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def build_entities(acs, stations, sondes, mesh, home, now, mil=None):
    """Every source -> one list of entities with the same shape:
    id, kind, label, sub, lat, lon, alt_ft, course, speed_kt, t, props [(k, v)], notable."""
    out = []
    hl, hn = home
    for a in acs or []:
        try:
            la, lo = _f(a.get("lat")), _f(a.get("lon"))
            if la is None or lo is None:
                continue
            is_mil = bool(mil(a)) if mil else False
            cs = (a.get("flight") or "").strip() or (a.get("r") or "").strip() or \
                (SI.n_number(a.get("hex", "")) or a.get("hex", "").upper())
            alt = a.get("alt_baro")
            alt = 0.0 if alt == "ground" else _f(alt)
            sq = str(a.get("squawk") or "")
            typ = a.get("t") or a.get("desc") or ""
            props = [("Hex", a.get("hex", "").upper()), ("Type", typ or "—"),
                     ("Altitude", "GND" if a.get("alt_baro") == "ground" else
                      ("%s ft" % format(int(alt), ",") if alt is not None else "—")),
                     ("Ground speed", "%d kt" % a["gs"] if _f(a.get("gs")) is not None else "—"),
                     ("Track", "%03d°" % a["track"] if _f(a.get("track")) is not None else "—"),
                     ("Vertical", "%+d fpm" % (a.get("baro_rate") or 0)),
                     ("Squawk", sq or "—"), ("Country", SI.icao_country(a.get("hex", "")) or "—"),
                     ("Signal", "%.1f dB" % a["rssi"] if _f(a.get("rssi")) is not None else "—")]
            out.append({"id": "air:" + a.get("hex", ""), "kind": "mil" if is_mil else "air",
                        "label": cs, "sub": typ, "lat": la, "lon": lo, "alt_ft": alt,
                        "course": _f(a.get("track")), "speed_kt": _f(a.get("gs")),
                        "t": now - (_f(a.get("seen")) or 0), "src": "ADS-B 1090 MHz",
                        "props": props,
                        "notable": is_mil or sq in ("7500", "7600", "7700"),
                        "alert": sq in ("7500", "7600", "7700"), "key": a.get("hex", ""),
                        "vs": _f(a.get("baro_rate"))})
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue          # one malformed record never costs the whole picture
    for c, st in (stations or {}).items():
        try:
            if "lat" not in st:
                continue
            props = [("Symbol", st.get("symbol", "—")), ("Packets", str(st.get("n", 1))),
                     ("Heard", "direct" if not st.get("via") else "via " + str(st["via"]))]
            if st.get("speed_kt") is not None:
                props.append(("Speed", "%d kt" % st["speed_kt"]))
            if st.get("alt_ft") is not None:
                props.append(("Altitude", "%s ft" % format(int(st["alt_ft"]), ",")))
            wx = st.get("wx") or {}
            if "temp_f" in wx:
                props.append(("Temp", "%d°F" % wx["temp_f"]))
            if "wind_mph" in wx:
                props.append(("Wind", "%03d° %d mph" % (wx.get("wind_dir", 0), wx["wind_mph"])))
            if st.get("comment"):
                props.append(("Comment", str(st["comment"])[:60]))
            out.append({"id": "aprs:" + c, "kind": "aprs", "label": c,
                        "sub": st.get("symbol", ""), "lat": st["lat"], "lon": st["lon"],
                        "alt_ft": st.get("alt_ft"), "course": st.get("course"),
                        "speed_kt": st.get("speed_kt"), "t": st.get("last", now),
                        "src": "APRS 144.390 MHz", "props": props, "notable": False, "alert": False,
                        "key": c, "track": [(p[0], p[1]) for p in st.get("track", [])][-60:]})
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue          # one malformed record never costs the whole picture
    for b in sondes or []:
        try:
            la, lo, alt = _f(b.get("lat")), _f(b.get("lon")), _f(b.get("alt"))
            if la is None or lo is None:
                continue
            sid = str(b.get("id", ""))[:20]
            props = [("Model", str(b.get("model") or "—")), ("Phase", str(b.get("phase") or "—")),
                     ("Altitude", "%s m" % format(int(alt), ",") if alt is not None else "—"),
                     ("Climb", "%+.1f m/s" % b["vel_v"] if _f(b.get("vel_v")) is not None
                      else "—")]
            out.append({"id": "sonde:" + sid, "kind": "sonde", "label": sid,
                        "sub": str(b.get("model") or "radiosonde"), "lat": la, "lon": lo,
                        "alt_ft": alt * 3.28084 if alt is not None else None, "course": None,
                        "speed_kt": None, "t": _f(b.get("t")) or now, "src": "Radiosonde 400-406 MHz",
                        "props": props, "notable": True, "alert": False, "key": sid,
                        "vs": (_f(b.get("vel_v")) or 0) * 196.85 if _f(b.get("vel_v")) is not None
                        else None,
                        "track": [tuple(p) for p in b.get("track", []) if len(p) == 2][-120:]})
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue          # one malformed record never costs the whole picture
    for n in mesh or []:
        try:
            la, lo = _f(n.get("lat")), _f(n.get("lon"))
            if la is None or lo is None or n.get("me"):
                continue
            nid = str(n.get("id", ""))[:16]
            props = [("Node", nid), ("Name", str(n.get("long") or "—")),
                     ("SNR", "%.1f dB" % n["snr"] if _f(n.get("snr")) is not None else "—")]
            out.append({"id": "mesh:" + nid, "kind": "mesh",
                        "label": str(n.get("short") or nid[-4:]), "sub": str(n.get("long") or ""),
                        "lat": la, "lon": lo, "alt_ft": None, "course": None, "speed_kt": None,
                        "t": _f(n.get("last")) or now, "src": "Meshtastic LoRa", "props": props,
                        "notable": False, "alert": False, "key": nid})
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue          # one malformed record never costs the whole picture
    # a position off the map (bad decode, corrupt cache) would break the projection
    out = [e for e in out if -85.0 <= e["lat"] <= 85.0 and -180.0 <= e["lon"] <= 180.0]
    for e in out:
        e["dist_nm"] = SI.dist_nm(hl, hn, e["lat"], e["lon"])
        e["brg"] = SI.bearing_deg(hl, hn, e["lat"], e["lon"])
        e["stale"] = now - e["t"] > STALE_S[e["kind"]]
    return out


def match(e, query):
    """Search box: words AND together. Plain words match id/label/type/props; keywords:
    mil, air, aprs, sonde|balloon, mesh, near (<10 nm), high (>FL300), low (<3000 ft AGL-ish),
    fast (>300 kt), moving, alert."""
    q = (query or "").strip().lower()
    if not q:
        return True
    hay = " ".join([e["label"], e["sub"], e["id"]] + ["%s %s" % kv for kv in e["props"]]).lower()
    for w in q.split():
        if w == "mil":
            ok = e["kind"] == "mil"
        elif w in ("air", "aircraft"):
            ok = e["kind"] in ("air", "mil")
        elif w in ("sonde", "balloon", "balloons"):
            ok = e["kind"] == "sonde"
        elif w in ("aprs", "mesh"):
            ok = e["kind"] == w
        elif w == "near":
            ok = e["dist_nm"] < 10
        elif w == "high":
            ok = (e["alt_ft"] or 0) > 30000
        elif w == "low":
            ok = e["alt_ft"] is not None and 0 < e["alt_ft"] < 8500
        elif w == "fast":
            ok = (e["speed_kt"] or 0) > 300
        elif w == "moving":
            ok = (e["speed_kt"] or 0) >= 3
        elif w == "alert":
            ok = e["alert"]
        elif w == "descending":
            ok = (e.get("vs") or 0) < -300
        elif w == "climbing":
            ok = (e.get("vs") or 0) > 300
        elif w.startswith(("within:", "below:", "above:")):
            k, _, v = w.partition(":")
            n = _f(v)
            if n is None:
                ok = False
            elif k == "within":
                ok = e["dist_nm"] <= n
            elif k == "below":
                ok = e["alt_ft"] is not None and e["alt_ft"] < n
            else:
                ok = e["alt_ft"] is not None and e["alt_ft"] > n
        else:
            ok = w in hay
        if not ok:
            return False
    return True


DEFAULT_RULES = [
    {"name": "Emergency squawk", "q": "alert", "on": True},
    {"name": "Military within 25 nm", "q": "mil within:25", "on": True},
    {"name": "Balloon coming down nearby", "q": "sonde descending within:40", "on": True},
    {"name": "Aircraft overhead", "q": "air within:2", "on": False},
]


class Watcher:
    """Saved searches that raise an alert the first time an entity matches. An entity
    re-alerts only after it has stopped matching for `rearm` seconds."""

    def __init__(self, rules, rearm=300):
        self.rules = [{"name": str(r.get("name") or r.get("q"))[:40], "q": str(r["q"]).strip()}
                      for r in (rules or []) if isinstance(r, dict) and r.get("on", True)
                      and str(r.get("q") or "").strip()]
        self.rearm = rearm
        self.active = {}

    def check(self, ents, now):
        fired = []
        for r in self.rules:
            for e in ents:
                if e.get("stale") or not match(e, r["q"]):
                    continue
                key = (r["name"], e["id"])
                if key not in self.active:
                    fired.append({"t": now, "rule": r["name"], "id": e["id"], "key": e["key"],
                                  "label": e["label"], "ack": False,
                                  "text": "%s: %s %s, %.1f nm %03d°" % (
                                      r["name"], e["label"], e["sub"] or "", e["dist_nm"],
                                      e["brg"])})
                self.active[key] = now
        for key in [k for k, t in self.active.items() if now - t > self.rearm]:
            del self.active[key]
        return fired


class History:
    """Rolling snapshots of the picture, for rewind and for trails."""

    def __init__(self, span=3600, step=15):
        self.span, self.step = span, step
        self.snaps = []                     # (t, ents, {id: (lat, lon)})

    def add(self, now, ents):
        if self.snaps and now - self.snaps[-1][0] < self.step:
            return False
        self.snaps.append((now, ents, {e["id"]: (e["lat"], e["lon"]) for e in ents}))
        while self.snaps and now - self.snaps[0][0] > self.span:
            self.snaps.pop(0)
        return True

    def first(self):
        return self.snaps[0][0] if self.snaps else None

    def at(self, t):
        """The newest snapshot taken at or before t (the oldest one if t predates them all)."""
        best = None
        for snap in self.snaps:
            if snap[0] <= t:
                best = snap
            else:
                break
        best = best or (self.snaps[0] if self.snaps else None)
        return best[1] if best else []

    def trail(self, eid, until, secs):
        return [idx[eid] for t, _, idx in self.snaps if until - secs <= t <= until and eid in idx]


def timeline(events, now, span=3600):
    """Session-log rows -> [(t, app, kind, text, id)] within the last `span` seconds."""
    out = []
    for r in events or []:
        t = _f(r.get("t")) if isinstance(r, dict) else None
        if t is None or not (now - span <= t <= now + 5):
            continue
        out.append((t, str(r.get("app", ""))[:12], str(r.get("kind", ""))[:16],
                    str(r.get("text", ""))[:120], str(r.get("id", "") or "")))
    return out


def link_id(ev_app, ev_id, entities):
    """The entity a timeline event refers to, if it's on the map."""
    if not ev_id:
        return None
    pref = {"sky": "air:", "aprs": "aprs:", "balloons": "sonde:", "mesh": "mesh:"}.get(ev_app)
    for e in entities:
        if e["key"] == ev_id and (pref is None or e["id"].startswith(pref)):
            return e["id"]
    return None


BOARD_PATH = os.path.join(S.DATA, "ops_board.json")
BOARD_COLS = ("watching", "logged")


def load_board(path):
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    return {str(k)[:40]: v for k, v in d.items() if v in BOARD_COLS}


def save_board(path, board):
    try:
        S.save_json(path, {k: v for k, v in board.items() if v in BOARD_COLS})
    except OSError:
        pass


# ---- demo extras ------------------------------------------------------------------------------
def demo_extras(home, now):
    la, lo = home
    t = now % 3600
    st = A.Stations()
    for i, (dla, dlo, sym, call) in enumerate(((0.05, -0.12, "_", "DEMO2"),
                                                (0.21, -0.33, "#", "DEMO7"),
                                                (-0.08, 0.16, "-", "DEMO6"))):
        r = A.decode(A.parse_frame("%s>APRS:!%s/%s%s demo" % (
            call, _ddmm(la + dla, False), _ddmm(lo + dlo, True), sym)))
        st.add(r, now - 60 * i)
    a = t / 300.0
    for k in range(6):
        r = A.decode(A.parse_frame("DEMO1-9>APRS:=%s/%s>%03d/038" % (
            _ddmm(la + 0.07 * math.sin(a - k * 0.05), False),
            _ddmm(lo + 0.09 * math.cos(a - k * 0.05), True), 90)))
        st.add(r, now - (5 - k) * 20)
    sonde = [{"id": "LMS6-DEMO01", "lat": la + 0.15 + t / 40000, "lon": lo + 0.25 + t / 15000,
              "alt": min(31000, 1700 + t * 5), "vel_v": 5.0, "model": "LMS6",
              "phase": "ascending", "t": now,
              "track": [(la + 0.15 + k / 40000, lo + 0.25 + k / 15000) for k in range(0, int(t), 60)]}]
    mesh = [{"id": "!a1b2c3d4", "short": "KAPA", "long": "Centennial Roof", "lat": 39.5702,
             "lon": -104.8490, "snr": 6.25, "last": now - 40},
            {"id": "!b2c3d4e5", "short": "GLDN", "long": "Golden Ridge Rptr", "lat": 39.7555,
             "lon": -105.2211, "snr": -4.5, "last": now - 300}]
    return st.s, sonde, mesh


def _ddmm(v, is_lon):
    a = abs(v)
    d = int(a)
    m = (a - d) * 60
    if is_lon:
        return "%03d%05.2f%s" % (d, m, "W" if v < 0 else "E")
    return "%02d%05.2f%s" % (d, m, "S" if v < 0 else "N")


def ago(sec):
    sec = max(0, int(sec))
    return "%ds" % sec if sec < 60 else ("%dm" % (sec // 60) if sec < 3600 else
                                         "%dh%02d" % (sec // 3600, sec % 3600 // 60))


# ---- app ---------------------------------------------------------------------------------------
def main():
    S.single_instance("Ops")
    demo = "--demo" in sys.argv
    import sky_app
    import tiles
    s, spath = S.settings("ops", {"layers": [k for k, _, _ in LAYERS], "z": 9,
                                  "home": {"lat": 39.62, "lon": -104.87}, "imagery": "sat"})
    root, F = S.make_root("Ops")
    import tkinter as tk
    T = S.T
    sky_set = sky_app.load_settings()
    feed = sky_app.DemoFeed() if demo else sky_app.AdsbFeed(sky_set["adsb_sources"])
    mil_pref = sky_set.get("mil_prefixes") or sky_app.MIL_PREFIXES_DEFAULT
    home0 = (float(s["home"]["lat"]), float(s["home"]["lon"]))
    st = {"ents": [], "sel": None, "q": "", "layers": set(s.get("layers") or []),
          "events": [], "home": home0, "src": {}, "drag": None, "follow": False,
          "view": "map", "tool": "select", "measure": [], "menu": None, "scroll": 0,
          "board": {} if demo else load_board(BOARD_PATH), "hist": History(), "at": None,
          "live": [], "alerts": [], "panels": True, "tlx": (0, 1)}
    if not isinstance(s.get("rules"), list):
        s["rules"] = [dict(r) for r in DEFAULT_RULES]
    watcher = [Watcher(s["rules"])]
    slog = S.SessionLog("ops")

    def ref():
        """'Now' for ages: the replay time when rewound, else the clock."""
        return st["at"] or time.time()

    def hotkey(seq, fn):
        """Shortcut that stays out of the way while you type in the search box."""
        root.bind(seq, lambda e: None if root.focus_get() is search else fn())
    view = {"lat": home0[0], "lon": home0[1], "z": int(s.get("z", 9))}
    q = queue.Queue()

    # ---- top bar: title + per-source health
    top = S.top_bar(root, F, "Ops", "common picture · receive-only")
    chips = {}
    for key, label in (("air", "ADS-B"), ("aprs", "APRS"), ("sonde", "SONDE"), ("mesh", "MESH")):
        chips[key] = S.pill(top, F, label)

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)

    # ---- left rail: search, layers, entity list
    left = tk.Frame(body, bg=T.SURFACE, width=T.px(205), highlightthickness=1,
                    highlightbackground=T.LINE_HI)
    left.pack_propagate(False)
    lp = tk.Frame(left, bg=T.SURFACE)
    lp.pack(fill="both", expand=True, padx=T.px(10), pady=T.px(8))
    srow = tk.Frame(lp, bg=T.SURFACE_2, highlightthickness=1, highlightbackground=S.LINE)
    srow.pack(fill="x")
    tk.Label(srow, text="⌕", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE_2).pack(side="left",
                                                                            padx=(6, 2))
    search = tk.Entry(srow, font=F["mono"], bg=T.SURFACE_2, fg=S.TXT, insertbackground=S.TXT,
                      bd=0, highlightthickness=0)
    search.pack(side="left", fill="x", expand=True, ipady=T.px(3))
    T.section(lp, F, "Layers").pack(fill="x", pady=(T.px(8), T.px(2)))
    layer_rows = {}

    def toggle_layer(k):
        st["layers"] ^= {k}
        s["layers"] = sorted(st["layers"])
        refresh_ui()

    for k, label, col in LAYERS:
        r = tk.Frame(lp, bg=T.SURFACE, cursor="hand2")
        r.pack(fill="x", pady=1)
        box = tk.Canvas(r, width=T.px(12), height=T.px(12), bg=T.SURFACE, highlightthickness=0)
        box.pack(side="left", padx=(0, 6))
        lab = tk.Label(r, text=label, font=F["map"], fg=S.TXT, bg=T.SURFACE, anchor="w")
        lab.pack(side="left", fill="x", expand=True)
        cnt = tk.Label(r, text="0", font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
        cnt.pack(side="right")
        for wdg in (r, box, lab, cnt):
            wdg.bind("<Button-1>", lambda e, kk=k: toggle_layer(kk))
        layer_rows[k] = (box, lab, cnt, col)
    ent_hdr = T.section(lp, F, "Entities", right="")
    ent_hdr.pack(fill="x", pady=(T.px(8), T.px(2)))
    cards = tk.Canvas(lp, bg=T.SURFACE, highlightthickness=0)
    cards.pack(fill="both", expand=True)
    card_hits = []

    # ---- right: inspector
    right = tk.Frame(body, bg=T.SURFACE, width=T.px(225), highlightthickness=1,
                     highlightbackground=T.LINE_HI)
    right.pack_propagate(False)
    rp = tk.Frame(right, bg=T.SURFACE)
    rp.pack(fill="both", expand=True, padx=T.px(12), pady=T.px(8))
    al_hdr = T.section(rp, F, "Alerts", right="")
    al_hdr.pack(fill="x")
    al_cv = tk.Canvas(rp, bg=T.SURFACE, highlightthickness=0, height=T.px(64))
    al_cv.pack(fill="x", pady=(T.px(2), T.px(8)))
    al_hits = []

    def draw_alerts():
        al_cv.delete("all")
        al_hits.clear()
        w = al_cv.winfo_width()
        open_ = [a for a in st["alerts"] if not a["ack"]]
        al_hdr.winfo_children()[-1].config(text="%d new" % len(open_) if open_ else "",
                                           fg=S.RED if open_ else T.TXT_3)
        rows = (open_ + [a for a in st["alerts"] if a["ack"]])[:3]
        if not rows:
            al_cv.create_text(0, 4, anchor="nw", font=F["map"], fill=T.TXT_3, width=w,
                              text="None. %d rule%s armed - press r to edit." % (
                                  len(watcher[0].rules), "" if len(watcher[0].rules) == 1
                                  else "s"))
            return
        rh = T.px(21)
        for i, a in enumerate(rows):
            y = i * rh
            col = S.RED if not a["ack"] else T.TXT_3
            al_cv.create_rectangle(0, y + 2, 3, y + rh - 2, fill=col, outline="")
            al_cv.create_text(8, y + rh / 2, anchor="w", font=F["map"],
                              fill=S.TXT if not a["ack"] else T.TXT_3,
                              text=("%s %s · %s" % (time.strftime("%H:%M", time.localtime(a["t"])),
                                                    a["label"], a["rule"]))[:int(w / 7)])
            al_hits.append((y, y + rh, a))

    def on_alert(ev):
        for y0, y1, a in al_hits:
            if y0 <= ev.y <= y1:
                a["ack"] = True
                select(a["id"], center=True)
                return

    def ack_all(_=None):
        for a in st["alerts"]:
            a["ack"] = True
        refresh_ui()

    al_cv.bind("<Button-1>", on_alert)
    al_cv.bind("<Configure>", lambda e: draw_alerts())
    T.section(rp, F, "Inspector").pack(fill="x")
    i_chip = tk.Label(rp, text="", font=F["lbl"], fg=T.BG, bg=T.SURFACE, padx=6, pady=1)
    i_chip.pack(anchor="w", pady=(T.px(6), 0))
    i_title = tk.Label(rp, text="Nothing selected", font=F["h"], fg=S.TXT, bg=T.SURFACE,
                       anchor="w")
    i_title.pack(fill="x")
    i_sub = tk.Label(rp, text="Tap an entity on the map or in the list.", font=F["map"],
                     fg=T.TXT_3, bg=T.SURFACE, anchor="w", justify="left",
                     wraplength=T.px(200))
    i_sub.pack(fill="x")
    i_props = tk.Frame(rp, bg=T.SURFACE)
    i_props.pack(fill="x", pady=(T.px(8), 0))
    i_events_hdr = T.section(rp, F, "Related events")
    i_events = tk.Label(rp, text="", font=F["map"], fg=T.TXT_2, bg=T.SURFACE, anchor="nw",
                        justify="left", wraplength=T.px(200))

    # ---- centre: map over timeline
    centre = tk.Frame(body, bg=S.MAPBG)
    centre.pack(side="left", fill="both", expand=True)
    tl = tk.Canvas(centre, bg=T.SURFACE, highlightthickness=0, height=T.px(78))
    tl.pack(side="bottom", fill="x")
    tk.Frame(centre, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    tbar = tk.Frame(centre, bg=T.BG)
    tbar.pack(side="top", fill="x")
    tk.Frame(centre, bg=S.LINE, height=1).pack(side="top", fill="x")
    tools = {}

    def tool_btn(key, text, cmd):
        b = S.btn(tbar, text, cmd, F, font="map", padx=8, pady=2, kind="ghost")
        b.pack(side="left", padx=(4, 0), pady=4)
        tools[key] = b
        return b

    dtg = tk.Label(tbar, text="", font=F["map"], fg=T.TXT_2, bg=T.BG)
    dtg.pack(side="right", padx=8)
    cv = tk.Canvas(centre, bg=S.MAPBG, highlightthickness=0)
    cv.pack(fill="both", expand=True)
    board = tk.Frame(centre, bg=S.BG)
    GAP = 8

    def place_panels(_=None):
        """Panels float over a full-bleed map; p hides them."""
        if not st["panels"]:
            left.place_forget()
            right.place_forget()
            return
        y = tbar.winfo_height() + 1 + GAP
        hh = max(60, body.winfo_height() - y - tl.winfo_height() - 1 - GAP)
        left.place(x=GAP, y=y, width=T.px(205), height=hh)
        right.place(relx=1.0, x=-GAP, y=y, anchor="ne", width=T.px(225), height=hh)
        left.lift()
        right.lift()

    def inset():
        """Canvas x-range not covered by the panels."""
        w = cv.winfo_width()
        if not st["panels"]:
            return 0, w
        return T.px(205) + 2 * GAP, w - T.px(225) - 2 * GAP
    body.bind("<Configure>", place_panels)
    root.after(150, place_panels)
    basemap = tiles.TileLayer(on_ready=lambda ok: root.after(0, draw_map), workers=2)
    basemap.layer = s.get("imagery") if s.get("imagery") in tiles.LAYER_ORDER else "sat"
    hits, tl_hits = [], []

    def proj(lat, lon):
        w, h = cv.winfo_width(), cv.winfo_height()
        cx, cy = tiles.world_px(view["lat"], view["lon"], view["z"])
        x, y = tiles.world_px(lat, lon, view["z"])
        return w / 2 + (x - cx), h / 2 + (y - cy)

    def visible():
        return [e for e in st["ents"] if e["kind"] in st["layers"] and match(e, st["q"])]

    placed = []

    def draw_entity(e, sel):
        x, y = proj(e["lat"], e["lon"])
        col = T.night(LAYER_COL[e["kind"]])
        if e["alert"]:
            col = S.RED
        if e["stale"]:
            col = T._mix(col, T.MAPBG, 0.55)
        tr = e.get("track") or []
        if not tr:                          # no track of its own: build one from history
            tr = st["hist"].trail(e["id"], ref(), 1800 if sel else 120)
        if len(tr) >= 2:
            pts = [c for la, lo in tr for c in proj(la, lo)]
            cv.create_line(*pts, fill=T._mix(col, T.MAPBG, 0.4), width=1)
        k = e["kind"]
        r = 6
        if k in ("air", "mil"):
            a = math.radians(e["course"] or 0)
            p = [(0, -r - 3), (r - 1, r), (0, r - 3), (-r + 1, r)]
            pts = []
            for px_, py_ in p:
                pts += [x + px_ * math.cos(a) - py_ * math.sin(a),
                        y + px_ * math.sin(a) + py_ * math.cos(a)]
            cv.create_polygon(*pts, fill=col if k == "mil" else "", outline=col, width=1.5)
            if e["speed_kt"]:
                ln = min(40, 6 + e["speed_kt"] / 12)          # one-minute leader line
                cv.create_line(x + (r + 3) * math.sin(a), y - (r + 3) * math.cos(a),
                               x + ln * math.sin(a), y - ln * math.cos(a), fill=col)
        elif k == "aprs":
            cv.create_polygon(x, y - r, x + r, y, x, y + r, x - r, y, outline=col, fill="",
                              width=1.5)
        elif k == "sonde":
            cv.create_oval(x - r, y - r - 3, x + r, y + r - 3, outline=col, width=2)
            cv.create_line(x, y + r - 3, x, y + r + 5, fill=col)
        else:
            pts = []
            for i in range(6):
                an = math.radians(60 * i + 30)
                pts += [x + r * math.cos(an), y + r * math.sin(an)]
            cv.create_polygon(*pts, outline=col, fill="", width=1.5)
        if sel:                             # corner brackets around the selection
            b = r + 7
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                cv.create_line(x + sx * b, y + sy * (b - 5), x + sx * b, y + sy * b,
                               x + sx * (b - 5), y + sy * b, fill=T.ACCENT, width=2)
        alt = ("FL%03d" % round(e["alt_ft"] / 100) if (e["alt_ft"] or 0) >= 18000 else
               ("%d" % round(e["alt_ft"] / 100) if e["alt_ft"] else ""))
        txt = e["label"] + ("  " + alt if alt else "")
        if sel or view["z"] >= 8 or e["notable"]:
            tid = cv.create_text(x + r + 8, y - 2, anchor="w", text=txt, font=F["map"],
                                 fill=S.TXT if sel else col)
            bb = cv.bbox(tid)
            if not sel and any(bb[0] < o[2] and o[0] < bb[2] and bb[1] < o[3] and o[1] < bb[3]
                               for o in placed):
                cv.delete(tid)              # declutter: never stack labels on each other
                tid = None
            elif bb:
                placed.append(bb)
            if sel and tid:
                bb = cv.bbox(tid)
                rid = cv.create_rectangle(bb[0] - 3, bb[1] - 1, bb[2] + 3, bb[3] + 1,
                                          fill=T.ACCENT_BG, outline=T.ACCENT)
                cv.tag_raise(tid, rid)
        hits.append((x, y, e["id"]))

    def draw_map():
        cv.delete("all")
        hits.clear()
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50:
            return
        basemap.draw(cv, view["lat"], view["lon"], view["z"], w, h)
        k = tiles.px_per_nm(view["lat"], view["z"])
        hx, hy = proj(*st["home"])
        for nm in (5, 10, 25, 50, 100, 200):
            r = nm * k
            if 25 < r < 2 * max(w, h):
                cv.create_oval(hx - r, hy - r, hx + r, hy + r, outline=T.RING, dash=(2, 4))
                cv.create_text(hx + r * 0.707 + 4, hy - r * 0.707, anchor="w", text="%d nm" % nm,
                               fill=T.TXT_3, font=F["map"])
        cv.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4, outline=S.GREEN, width=2)
        vis = visible()
        placed.clear()
        # notable/selected first so they win the label space
        for e in sorted(vis, key=lambda e: (e["id"] != st["sel"], not e["notable"],
                                            e["dist_nm"])):
            draw_entity(e, e["id"] == st["sel"])
        for e in vis:                       # board "watching" ring
            if st["board"].get(e["id"]) == "watching":
                x, y = proj(e["lat"], e["lon"])
                for rr in (14, 20):
                    cv.create_oval(x - rr, y - rr, x + rr, y + rr, outline=T.ACCENT, dash=(3, 3))
        hot = {a["id"] for a in st["alerts"] if not a["ack"]}
        for e in vis:                       # unacknowledged alert: red double ring
            if e["id"] in hot:
                x, y = proj(e["lat"], e["lon"])
                for rr in (13, 19):
                    cv.create_oval(x - rr, y - rr, x + rr, y + rr, outline=S.RED, width=2)
        m = st["measure"]
        if m:
            pts = [proj(*p) for p in m]
            for x, y in pts:
                cv.create_oval(x - 4, y - 4, x + 4, y + 4, outline=S.TXT, fill=T.ACCENT)
            if len(m) == 2:
                (x0, y0), (x1, y1) = pts
                cv.create_line(x0, y0, x1, y1, fill=S.TXT, dash=(6, 3), width=2)
                d = SI.dist_nm(m[0][0], m[0][1], m[1][0], m[1][1])
                b = SI.bearing_deg(m[0][0], m[0][1], m[1][0], m[1][1])
                tid = cv.create_text((x0 + x1) / 2, (y0 + y1) / 2 - 12, font=F["mapb"],
                                     fill=S.TXT, text="%.2f nm  ·  %.1f km  ·  %03d°" % (
                                         d, d * 1.852, b))
                bb = cv.bbox(tid)
                rid = cv.create_rectangle(bb[0] - 6, bb[1] - 3, bb[2] + 6, bb[3] + 3,
                                          fill=T.SURFACE, outline=T.LINE_HI)
                cv.tag_raise(tid, rid)
            else:
                cv.create_text(pts[0][0] + 10, pts[0][1], anchor="w", font=F["map"],
                               fill=S.TXT, text="tap the second point")
        # map chrome: legend of counts + scale
        x_l, x_r = inset()
        bulk = basemap.bulk_status()
        bits = ["%d shown" % len(vis), "z%d" % view["z"],
                "DEMO · SYNTHETIC ENTITIES, NOT REAL" if demo else "live"]
        if bulk.get("active"):
            bits.append("saving map for offline %d/%d" % (bulk.get("done", 0),
                                                           bulk.get("total", 0)))
        cv.create_text(x_l + 4, h - 8, anchor="sw", font=F["map"], fill=T.TXT_3,
                       text=" · ".join(bits))
        if st["at"]:
            cv.create_text((x_l + x_r) / 2, 10, anchor="n", font=F["mapb"], fill=T.NOTE,
                           text="REPLAY  %s  (-%s)   ·   press L for live" % (
                               time.strftime("%H:%M:%S", time.localtime(st["at"])),
                               ago(time.time() - st["at"])))

    def draw_timeline():
        tl.delete("all")
        tl_hits.clear()
        w, h = tl.winfo_width(), tl.winfo_height()
        if w < 50:
            return
        now = time.time()
        span = 3600
        x0, x1 = T.px(76), w - 10
        st["tlx"] = (x0, x1)
        apps = sorted({ev[1] for ev in st["events"]} | {"sky", "aprs", "balloons"})[:5]
        lane_h = (h - 22) / max(1, len(apps))
        for i, app in enumerate(apps):
            y = 6 + lane_h * (i + 0.5)
            tl.create_text(8, y, anchor="w", text=app.upper()[:9], font=F["lbl"],
                           fill=T.TXT_3)
            tl.create_line(x0, y, x1, y, fill=T.LINE)
        for m in range(0, 61, 10):
            x = x1 - (x1 - x0) * m / 60
            tl.create_line(x, h - 16, x, h - 12, fill=T.TXT_3)
            tl.create_text(x, h - 2, anchor="s", text="now" if m == 0 else "-%dm" % m,
                           font=F["map"], fill=T.TXT_3)
        for t, app, kind, text, eid in st["events"]:
            if app not in apps:
                continue
            x = x1 - (x1 - x0) * (now - t) / span
            y = 6 + lane_h * (apps.index(app) + 0.5)
            col = T.ACCENT
            if kind in ("alert", "emergency"):
                col = S.RED
            tl.create_rectangle(x - 2, y - 5, x + 2, y + 5, fill=col, outline="")
            tl_hits.append((x, y, app, text, eid, t))
        first = st["hist"].first()
        if first:                           # how far back the picture can be rewound
            xf = max(x0, x1 - (x1 - x0) * (now - first) / span)
            tl.create_line(xf, h - 17, x1, h - 17, fill=T.ACCENT, width=2)
        xp = x1 if not st["at"] else x1 - (x1 - x0) * (now - st["at"]) / span
        tl.create_line(xp, 2, xp, h - 14, fill=T.NOTE if st["at"] else T.TXT_2)
        tl.create_polygon(xp - 4, 0, xp + 4, 0, xp, 6, fill=T.NOTE if st["at"] else T.TXT_2,
                          outline="")

    def inspector():
        for wdg in i_props.winfo_children():
            wdg.destroy()
        e = next((x for x in st["ents"] if x["id"] == st["sel"]), None)
        if not e:
            i_chip.config(text="", bg=T.SURFACE)
            i_title.config(text="Nothing selected")
            i_sub.config(text="Tap an entity on the map or in the list. Type in the search "
                              "box: words like mil, near, high, fast, aprs, sonde.")
            i_events_hdr.pack_forget()
            i_events.pack_forget()
            return
        col = T.night(LAYER_COL[e["kind"]])
        i_chip.config(text=dict((k, l) for k, l, _ in LAYERS)[e["kind"]].upper(), bg=col)
        i_title.config(text=e["label"])
        i_sub.config(text="%s\n%.1f nm %03d° · seen %s ago%s" % (
            e["src"], e["dist_nm"], e["brg"], ago(ref() - e["t"]),
            " · STALE" if e["stale"] else ""))
        for r, (k, v) in enumerate(e["props"]):
            tk.Label(i_props, text=k, font=F["map"], fg=T.TXT_3, bg=T.SURFACE,
                     anchor="w").grid(row=r, column=0, sticky="w", padx=(0, 8))
            tk.Label(i_props, text=v, font=F["map"], fg=S.RED if (k == "Squawk" and e["alert"])
                     else S.TXT, bg=T.SURFACE, anchor="w", wraplength=T.px(140),
                     justify="left").grid(row=r, column=1, sticky="w")
        rel = [ev for ev in st["events"] if ev[4] and ev[4] == e["key"]][-4:]
        i_events_hdr.pack(fill="x", pady=(T.px(10), T.px(2)))
        i_events.pack(fill="x")
        i_events.config(text="\n".join("%s  %s" % (time.strftime("%H:%M", time.localtime(t)),
                                                   text[:60]) for t, _, _, text, _ in rel)
                        or "none in the last hour")

    def entity_list():
        """Stack of entity cards (icon · title · chips), Maven-detection style."""
        vis = sorted(visible(), key=lambda e: (not e["alert"], not e["notable"], e["dist_nm"]))
        cards.delete("all")
        card_hits.clear()
        w = cards.winfo_width()
        ch = T.px(46)
        gap = T.px(5)
        maxs = max(0, len(vis) * (ch + gap) - cards.winfo_height())
        st["scroll"] = max(0, min(st["scroll"], maxs))
        y = -st["scroll"]
        now = ref()
        for e in vis[:80]:
            if y > cards.winfo_height():
                break
            if y + ch >= 0:
                sel = e["id"] == st["sel"]
                col = S.RED if e["alert"] else T.night(LAYER_COL[e["kind"]])
                cards.create_rectangle(1, y, w - 2, y + ch, fill=T.SURFACE_2,
                                       outline=T.ACCENT if sel else T.LINE, width=2 if sel else 1)
                cards.create_rectangle(1, y, 4, y + ch, fill=col, outline="")
                ix, iy = T.px(16), y + ch / 2
                cards.create_polygon(ix, iy - 7, ix + 7, iy, ix, iy + 7, ix - 7, iy,
                                     fill=T._mix(col, T.SURFACE_2, 0.25), outline=col)
                cards.create_text(T.px(30), y + T.px(5), anchor="nw", text=e["label"][:14],
                                  font=F["mapb"], fill=S.TXT if not e["stale"] else T.TXT_3)
                pinned = st["board"].get(e["id"])
                if pinned:
                    cards.create_text(w - 8, y + T.px(5), anchor="ne", text=pinned.upper(),
                                      font=F["lbl"], fill=T.ACCENT)
                sub = "%s · %.1f nm · %s" % ((e["sub"] or e["kind"])[:10], e["dist_nm"],
                                             ago(now - e["t"]))
                cards.create_text(T.px(30), y + T.px(25), anchor="nw", text=sub, font=F["map"],
                                  fill=T.TXT_3)
                card_hits.append((y, y + ch, e["id"]))
            y += ch + gap
        if not vis:
            cards.create_text(w / 2, T.px(30), text="nothing matches", font=F["map"],
                              fill=T.TXT_3)
        ent_hdr.winfo_children()[-1].config(text="%d" % len(vis))

    def on_card(ev):
        for y0, y1, eid in card_hits:
            if y0 <= ev.y <= y1:
                select(eid, center=True)
                return

    def on_card_scroll(d):
        st["scroll"] = max(0, st["scroll"] + d * T.px(51) * 2)
        entity_list()

    cards.bind("<Button-1>", on_card)
    cards.bind("<Button-4>", lambda e: on_card_scroll(-1))
    cards.bind("<Button-5>", lambda e: on_card_scroll(1))
    cards.bind("<Configure>", lambda e: entity_list())

    def refresh_ui():
        for k, (box, lab, cnt, col) in layer_rows.items():
            on = k in st["layers"]
            box.delete("all")
            sz = T.px(12)
            box.create_rectangle(1, 1, sz - 1, sz - 1, outline=T.night(col),
                                 fill=T.night(col) if on else "")
            lab.config(fg=S.TXT if on else T.TXT_3)
            cnt.config(text=str(sum(1 for e in st["ents"] if e["kind"] == k)))
        now = time.time()
        for key, chip in chips.items():
            info = st["src"].get(key)
            n = sum(1 for e in st["ents"] if e["kind"] in ((key,) if key != "air"
                                                          else ("air", "mil")))
            if info is None:
                chip.config(text="%s —" % key.upper().replace("AIR", "ADS-B"), bg=S.DIM)
            else:
                fresh = now - info < (10 if key == "air" else 600)
                name = key.upper().replace("AIR", "ADS-B")
                chip.config(text="%s %d" % (name, n) if fresh else
                            "%s %d · %s old" % (name, n, ago(now - info)),
                            bg=S.GREEN if fresh else S.DIM)
        entity_list()
        draw_alerts()
        inspector()
        if st["view"] == "board":
            draw_board()
        else:
            draw_map()
        draw_timeline()

    def select(eid, center=False):
        st["sel"] = eid
        e = next((x for x in st["ents"] if x["id"] == eid), None)
        if e and center:
            view["lat"], view["lon"] = e["lat"], e["lon"]
        refresh_ui()

    # ---- interaction
    def on_press(e):
        st["drag"] = (e.x, e.y, view["lat"], view["lon"], False)

    def on_motion(e):
        if not st["drag"]:
            return
        x0, y0, la0, lo0, moved = st["drag"]
        if abs(e.x - x0) + abs(e.y - y0) > 5:
            cx, cy = tiles.world_px(la0, lo0, view["z"])
            view["lat"], view["lon"] = tiles.from_world_px(cx - (e.x - x0), cy - (e.y - y0),
                                                           view["z"])
            st["drag"] = (x0, y0, la0, lo0, True)
            draw_map()

    def unproj(x, y):
        w, h = cv.winfo_width(), cv.winfo_height()
        cx, cy = tiles.world_px(view["lat"], view["lon"], view["z"])
        return tiles.from_world_px(cx + (x - w / 2), cy + (y - h / 2), view["z"])

    def close_menu(_=None):
        if st["menu"]:
            st["menu"].destroy()
            st["menu"] = None

    def context_menu(e):
        """Right-click (or long-press) menu, like the workstation's: act on what's under it."""
        close_menu()
        best = min(hits, key=lambda t: (t[0] - e.x) ** 2 + (t[1] - e.y) ** 2, default=None)
        eid = best[2] if best and (best[0] - e.x) ** 2 + (best[1] - e.y) ** 2 < 28 ** 2 else None
        lat, lon = unproj(e.x, e.y)
        m = tk.Frame(cv, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.LINE_HI)
        st["menu"] = m
        ent = next((x for x in st["ents"] if x["id"] == eid), None)
        head = ent["label"] if ent else "%.4f, %.4f" % (lat, lon)
        tk.Label(m, text=head, font=F["mapb"], fg=S.TXT, bg=T.SURFACE, anchor="w",
                 padx=10, pady=4).pack(fill="x")
        tk.Frame(m, bg=T.LINE, height=1).pack(fill="x")
        items = []
        if ent:
            items += [("◎  Inspect", lambda: select(eid)),
                      ("◉  Watch on board", lambda: set_board(eid, "watching")),
                      ("✓  Log it", lambda: set_board(eid, "logged"))]
            if st["board"].get(eid):
                items.append(("✕  Remove from board", lambda: set_board(eid, None)))
        items += [("⟷  Measure from here", lambda: start_measure(lat, lon)),
                  ("⌖  Distance from me", lambda: (st.update(measure=[st["home"], (lat, lon)]),
                                                   draw_map())),
                  ("✛  Center map here", lambda: (view.update(lat=lat, lon=lon), draw_map())),
                  ("⧉  Copy position", lambda: copy_pos(lat, lon))]
        for text, cmd in items:
            b = tk.Label(m, text=text, font=F["map"], fg=T.TXT_2, bg=T.SURFACE, anchor="w",
                         padx=10, pady=3, cursor="hand2")
            b.pack(fill="x")
            b.bind("<Enter>", lambda ev, bb=b: bb.config(bg=T.ACCENT_BG, fg=S.TXT))
            b.bind("<Leave>", lambda ev, bb=b: bb.config(bg=T.SURFACE, fg=T.TXT_2))
            b.bind("<Button-1>", lambda ev, c=cmd: (close_menu(), c()))
        m.update_idletasks()
        x = min(e.x + 4, cv.winfo_width() - m.winfo_reqwidth() - 4)
        y = min(e.y + 4, cv.winfo_height() - m.winfo_reqheight() - 4)
        m.place(x=max(0, x), y=max(0, y))

    def start_measure(lat, lon):
        st["measure"] = [(lat, lon)]
        set_tool("measure")
        draw_map()

    def copy_pos(lat, lon):
        root.clipboard_clear()
        root.clipboard_append("%.5f, %.5f" % (lat, lon))
        i_sub.config(text="Copied %.5f, %.5f" % (lat, lon))

    def set_tool(t):
        st["tool"] = t
        if t != "measure":
            st["measure"] = []
        for k in ("select", "measure"):
            T.set_btn(tools[k], kind="primary" if k == t else "ghost")
        draw_map()

    def on_release(e):
        d = st["drag"]
        st["drag"] = None
        if st["menu"]:
            close_menu()
            return
        if d and not d[4] and st["tool"] == "measure":
            pt = unproj(e.x, e.y)
            st["measure"] = [pt] if len(st["measure"]) != 1 else st["measure"] + [pt]
            draw_map()
            return
        if d and not d[4]:
            best = min(hits, key=lambda t: (t[0] - e.x) ** 2 + (t[1] - e.y) ** 2, default=None)
            if best and (best[0] - e.x) ** 2 + (best[1] - e.y) ** 2 < 28 ** 2:
                select(best[2])
            else:
                select(None)

    def zoom(d):
        view["z"] = max(5, min(14, view["z"] + d))
        s["z"] = view["z"]
        draw_map()

    def scrub(t):
        """Show the picture as it was at time t (None or ~now = live)."""
        now = time.time()
        first = st["hist"].first()
        if t is None or first is None or t >= now - 10:
            st["at"], st["ents"] = None, st["live"]
        else:
            st["at"] = max(first, t)
            st["ents"] = st["hist"].at(st["at"])
        T.set_btn(tools["live"], text="● Live" if not st["at"] else "▶ Go live",
                  kind="ghost" if not st["at"] else "primary")
        refresh_ui()

    def scrub_x(x):
        x0, x1 = st["tlx"]
        scrub(time.time() - (x1 - min(x1, max(x0, x))) / max(1, x1 - x0) * 3600)

    def step(mins):
        scrub((st["at"] or time.time()) + mins * 60)

    def on_tl_click(e):
        best = min(tl_hits, key=lambda t: (t[0] - e.x) ** 2 + (t[1] - e.y) ** 2, default=None)
        if not best or (best[0] - e.x) ** 2 + (best[1] - e.y) ** 2 > 12 ** 2:
            scrub_x(e.x)                    # empty track: move the playhead there
            return
        x, y, app, text, eid, t = best
        target = link_id(app, eid, st["ents"])
        if target:
            select(target, center=True)
        else:
            i_sub.config(text="%s  %s: %s" % (time.strftime("%H:%M:%S", time.localtime(t)),
                                              app, text))

    def on_search(_=None):
        st["q"] = search.get()
        refresh_ui()

    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_motion)
    cv.bind("<ButtonRelease-1>", on_release)
    cv.bind("<Button-4>", lambda e: zoom(1))
    cv.bind("<Button-5>", lambda e: zoom(-1))
    cv.bind("<Configure>", lambda e: draw_map())
    cv.bind("<Button-3>", context_menu)
    long_press = {"id": None}

    def lp_start(e):
        long_press["id"] = root.after(650, lambda: (context_menu(e), st.update(drag=None)))

    def lp_cancel(_=None):
        if long_press["id"]:
            root.after_cancel(long_press["id"])
            long_press["id"] = None
    cv.bind("<ButtonPress-1>", lambda e: (lp_start(e), on_press(e)), add=False)
    cv.bind("<B1-Motion>", lambda e: (lp_cancel() if st["drag"] and st["drag"][4] else None,
                                      on_motion(e)), add=False)
    cv.bind("<ButtonRelease-1>", lambda e: (lp_cancel(), on_release(e)), add=False)
    hotkey("m", lambda: set_tool("measure" if st["tool"] != "measure" else "select"))
    hotkey("b", lambda: set_view("board" if st["view"] == "map" else "map"))
    hotkey("i", lambda: cycle_imagery())
    hotkey("p", lambda: toggle_panels())
    hotkey("l", lambda: scrub(None))
    hotkey("[", lambda: step(-1))
    hotkey("]", lambda: step(1))
    hotkey("a", lambda: ack_all())
    hotkey("r", lambda: edit_rules())
    tl.bind("<Configure>", lambda e: draw_timeline())
    tl.bind("<Button-1>", on_tl_click)
    tl.bind("<B1-Motion>", lambda e: scrub_x(e.x))
    search.bind("<KeyRelease>", on_search)
    search.bind("<Escape>", lambda e: (search.delete(0, "end"), on_search(), root.focus_set()))
    root.bind("/", lambda e: None if root.focus_get() is search
              else (search.focus_set(), "break")[1])
    hotkey("+", lambda: zoom(1))
    hotkey("=", lambda: zoom(1))
    hotkey("-", lambda: zoom(-1))
    hotkey("h", lambda: (view.update(lat=st["home"][0], lon=st["home"][1]), draw_map()))
    for i, (k, _, _) in enumerate(LAYERS):
        hotkey(str(i + 1), lambda kk=k: toggle_layer(kk))

    # ---- board: a spotter's triage board (new / watching / logged), saved between sessions
    COLS = (("new", "New", "unboarded entities, nearest first"),
            ("watching", "Watching", "ringed on the map"),
            ("logged", "Logged", "seen it, noted it"))

    def set_board(eid, col):
        if col:
            st["board"][eid] = col
        else:
            st["board"].pop(eid, None)
        if not demo:                      # demo entities never land on the real board
            save_board(BOARD_PATH, st["board"])
        refresh_ui()

    def draw_board():
        for wdg in board.winfo_children():
            wdg.destroy()
        ents = {e["id"]: e for e in st["ents"]}
        for ci, (key, title, hint) in enumerate(COLS):
            col = tk.Frame(board, bg=T.SURFACE, highlightthickness=1,
                           highlightbackground=T.LINE)
            col.grid(row=0, column=ci, sticky="nsew", padx=4, pady=6)
            board.columnconfigure(ci, weight=1, uniform="c")
            if key == "new":
                ids = [e["id"] for e in sorted(visible(), key=lambda e: e["dist_nm"])
                       if e["id"] not in st["board"]][:8]
            else:
                ids = [i for i, c in st["board"].items() if c == key]
            hdr = tk.Frame(col, bg=T.SURFACE)
            hdr.pack(fill="x", padx=8, pady=(6, 2))
            tk.Label(hdr, text=title.upper(), font=F["lbl"], fg=S.TXT, bg=T.SURFACE).pack(
                side="left")
            tk.Label(hdr, text=str(len(ids)), font=F["lbl"], fg=T.BG, bg=T.TXT_3,
                     padx=5).pack(side="left", padx=6)
            tk.Label(col, text=hint, font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w").pack(
                fill="x", padx=8)
            for eid in ids[:8]:
                e = ents.get(eid)
                card = tk.Frame(col, bg=T.SURFACE_2, highlightthickness=1,
                                highlightbackground=T.ACCENT if eid == st["sel"] else T.LINE)
                card.pack(fill="x", padx=6, pady=3)
                kc = T.night(LAYER_COL[e["kind"]]) if e else T.TXT_3
                tk.Frame(card, bg=kc, width=3).pack(side="left", fill="y")
                inner = tk.Frame(card, bg=T.SURFACE_2)
                inner.pack(side="left", fill="x", expand=True, padx=6, pady=3)
                name = e["label"] if e else eid.split(":", 1)[-1]
                tk.Label(inner, text=name, font=F["mapb"], fg=S.TXT, bg=T.SURFACE_2,
                         anchor="w").pack(fill="x")
                sub = ("%s · %.1f nm · %s ago" % ((e["sub"] or e["kind"])[:12], e["dist_nm"],
                                                   ago(time.time() - e["t"]))) if e \
                    else "not heard right now"
                tk.Label(inner, text=sub, font=F["map"], fg=T.TXT_3, bg=T.SURFACE_2,
                         anchor="w").pack(fill="x")
                acts = tk.Frame(inner, bg=T.SURFACE_2)
                acts.pack(fill="x", pady=(2, 0))
                for k2, t2 in (("watching", "Watch"), ("logged", "Log"), (None, "Clear")):
                    if k2 == key or (k2 is None and key == "new"):
                        continue
                    S.btn(acts, t2, lambda i=eid, c=k2: set_board(i, c), F, font="map",
                          padx=6, pady=0, kind="ghost").pack(side="left", padx=(0, 4))
                if e:
                    S.btn(acts, "▸", lambda i=eid: (set_view("map"), select(i, center=True)),
                          F, font="map", padx=6, pady=0, kind="quiet").pack(side="right")
        board.rowconfigure(0, weight=1)

    def set_view(v):
        st["view"] = v
        if v == "board":
            cv.pack_forget()
            board.pack(fill="both", expand=True,
                       padx=((T.px(205) + 2 * GAP, T.px(225) + 2 * GAP) if st["panels"] else 0))
            draw_board()
        else:
            board.pack_forget()
            cv.pack(fill="both", expand=True)
            draw_map()
        for k in ("map", "board"):
            T.set_btn(tools[k], kind="primary" if k == v else "ghost")

    def cycle_imagery():
        order = ["sat", "dark", "streets"]
        cur = basemap.layer if basemap.layer in order else "sat"
        basemap.layer = order[(order.index(cur) + 1) % len(order)]
        s["imagery"] = basemap.layer
        T.set_btn(tools["img"], text="◫ " + tiles.LAYERS[basemap.layer]["label"])
        draw_map()

    tool_btn("map", "Map", lambda: set_view("map"))
    tool_btn("board", "Board", lambda: set_view("board"))
    tk.Frame(tbar, bg=T.LINE, width=1).pack(side="left", fill="y", padx=6, pady=6)
    tool_btn("select", "Select", lambda: set_tool("select"))
    tool_btn("measure", "Measure", lambda: set_tool("measure"))
    tool_btn("img", "◫ " + tiles.LAYERS[basemap.layer]["label"], cycle_imagery)
    def download_offline():
        """Save the current imagery ~60 nm around home (zoom 6-13) for use with no network."""
        if basemap.bulk_status().get("active"):
            basemap.cancel_bulk()
            i_sub.config(text="Offline map download cancelled.")
            return
        la, lo = st["home"]
        dla = 1.0
        dlo = 1.0 / max(0.2, math.cos(math.radians(la)))
        n = basemap.download_bbox(basemap.layer, la - dla, lo - dlo, la + dla, lo + dlo, 6, 13,
                                  limit=6000)
        i_sub.config(text=("Saving %d map tiles (about %d MB) for offline use. Tap Offline "
                           "again to cancel." % (n, round(n * 0.02))) if n else
                     "This area is already saved for offline use.")

    def toggle_panels():
        st["panels"] = not st["panels"]
        place_panels()
        set_view(st["view"])

    def edit_rules():
        import settings_ui
        schema = [("Watch rules", [
            {"key": "rules", "label": "Rules", "type": "table",
             "columns": [("name", "Name", "str"), ("q", "Search", "str"), ("on", "On", "bool")],
             "help": "Search words: mil air aprs sonde mesh alert near high fast moving "
                     "climbing descending within:NM below:FT above:FT, or any callsign/type."},
            {"key": "speak_alerts", "label": "Speak new alerts", "type": "bool"},
        ])]

        def on_save(new):
            s.update(rules=new.get("rules") or [], speak_alerts=bool(new.get("speak_alerts")))
            watcher[0] = Watcher(s["rules"])
            try:
                S.save_json(spath, s)
            except OSError:
                pass
            refresh_ui()
        settings_ui.open_settings(root, F, "Ops watch rules", schema,
                                  {"rules": s["rules"],
                                   "speak_alerts": bool(s.get("speak_alerts", True))},
                                  on_save, width=700)

    tool_btn("dl", "⇩ Offline", download_offline)
    tool_btn("rules", "Rules", edit_rules)
    live_b = S.btn(tbar, "● Live", lambda: scrub(None), F, font="map", padx=8, pady=2,
                   kind="ghost")
    live_b.pack(side="right", padx=(0, 4), pady=4)
    tools["live"] = live_b
    T.set_btn(tools["map"], kind="primary")
    T.set_btn(tools["select"], kind="primary")

    def tick_dtg():
        dtg.config(text="" if not st["at"] else "REPLAY " + time.strftime(
            "%H:%M:%SZ", time.gmtime(st["at"])), fg=T.NOTE)
        root.after(1000, tick_dtg)
    tick_dtg()

    # bottom bar
    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x", before=body)
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x", before=bar)
    for txt, cmd in (("+", lambda: zoom(1)), ("−", lambda: zoom(-1)),
                     ("Home", lambda: (view.update(lat=st["home"][0], lon=st["home"][1]),
                                       draw_map()))):
        S.btn(bar, txt, cmd, F, padx=10, pady=4, kind="ghost").pack(side="left", padx=(6, 0),
                                                                   pady=5)
    tk.Label(bar, text="/ search · hold for actions · m measure · "
                       "b board · [ ] rewind · L live · p panels · r rules",
             font=F["map"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left", padx=12)
    S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=4, kind="quiet").pack(
        side="right", padx=(2, 10))

    # ---- data worker: everything slow happens here, never on the Tk thread
    def worker():
        while not st.get("closed"):
            now = time.time()
            try:
                acs, _, status, rcv = feed.snapshot()
                src = {}
                if status in ("live", "demo") or demo:
                    src["air"] = now
                if demo:
                    stations, sondes, mesh = demo_extras(home0, now)
                    src.update(aprs=now, sonde=now, mesh=now)
                else:
                    sa = A.load_stations(os.path.join(S.CACHE, "aprs_stations.json"), now)
                    stations = sa.s
                    try:
                        src["aprs"] = os.path.getmtime(os.path.join(S.CACHE, "aprs_stations.json"))
                    except OSError:
                        pass
                    sj = S.load_json(os.path.join(S.CACHE, "sondes.json"), {}) or {}
                    sondes = [b for b in sj.get("sondes", []) if isinstance(b, dict)] \
                        if isinstance(sj, dict) else []
                    if isinstance(sj, dict) and sj.get("t"):
                        src["sonde"] = _f(sj["t"]) or 0
                    mj = S.load_json(os.path.join(S.CACHE, "mesh_nodes.json"), {}) or {}
                    mesh = [] if not isinstance(mj, dict) or mj.get("demo") else \
                        [n for n in mj.get("nodes", []) if isinstance(n, dict)]
                    if isinstance(mj, dict) and mj.get("t") and not mj.get("demo"):
                        src["mesh"] = _f(mj["t"]) or 0
                home = rcv if (rcv and not demo) else home0
                ents = build_entities(acs, stations, sondes, mesh, home, now,
                                      mil=lambda a: sky_app.is_military_ac(a, mil_pref))
                evs = timeline(S.SessionLog.recent(800), now)
                if demo:
                    evs += demo_events(ents, now)
                q.put((ents, evs, src, home))
            except Exception as e:      # a bad file must never kill the picture
                print("ops worker: %r" % e, file=sys.stderr)
            time.sleep(2.0)

    def demo_events(ents, now):
        out = []
        for i, e in enumerate(ents[:12]):
            app = {"air": "sky", "mil": "sky", "aprs": "aprs", "sonde": "balloons",
                   "mesh": "mesh"}[e["kind"]]
            out.append((now - 240 * i - 30, app, "contact", "%s %s" % (e["label"], e["sub"]),
                        e["key"]))
        out.append((now - 900, "sensors", "sensor", "Acurite-Tower #4021 21.4°C", ""))
        return out

    def say(text):
        try:
            import sitrep
            sitrep.speak(text)
        except Exception:
            pass

    def pump():
        got = None
        try:
            while True:
                got = q.get_nowait()
        except queue.Empty:
            pass
        if got:
            st["live"], st["events"], st["src"], st["home"] = got
            now = time.time()
            st["hist"].add(now, st["live"])
            for a in watcher[0].check(st["live"], now):
                st["alerts"].insert(0, a)
                note = getattr(T.EMBED, "notify", None)
                if note:                  # workstation: alert banner over any workspace
                    note(a["text"], "ops")
                del st["alerts"][50:]
                if not demo:              # demo alerts never reach the real log or speaker
                    slog.event("alert", a["text"], id=a["key"])
                    if s.get("speak_alerts", True):
                        threading.Thread(target=say, args=(a["text"],), daemon=True).start()
            if not st["at"]:
                st["ents"] = st["live"]
            refresh_ui()
        root.after(1000, pump)

    def on_close():
        st["closed"] = True                 # ends the data worker
        feed.stopped = True
        try:
            S.save_json(spath, s)
        except OSError:
            pass
        root.destroy()

    S.bind_quit(root, on_close)

    def esc(e):
        """Escape peels back one layer: menu, measure, search, then the board, then quits."""
        if st["menu"]:
            close_menu()
        elif st["tool"] != "select":
            set_tool("select")
        elif root.focus_get() is search:
            root.focus_set()
        elif st["view"] != "map":
            set_view("map")
        elif getattr(root, "embedded", False):
            root.go_home()                # in the workstation Esc never closes a workspace
        else:
            on_close()
        return "break"
    root.bind("<Escape>", esc)
    threading.Thread(target=worker, daemon=True).start()
    refresh_ui()
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
