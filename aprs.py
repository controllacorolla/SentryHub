"""APRS packet decoding (receive-only). Pure functions, no I/O.

Input is what `multimon-ng -a AFSK1200 -A` prints for each frame:
    APRS: SRC>DEST,DIGI1*,WIDE2-1:payload
Handles the position formats people actually transmit around Denver:
uncompressed (! = / @), compressed, Mic-E (most mobile radios and trackers),
objects/items, status, weather and messages.
"""
import math
import os
import queue
import random
import re
import shutil
import sys
import threading
import time

SYMBOLS = {  # primary table "/" symbol code -> plain name
    "!": "police", "#": "digipeater", "$": "phone", "&": "gateway", "'": "small plane",
    "-": "house", "<": "motorcycle", "=": "rail", ">": "car", "O": "balloon",
    "R": "RV", "U": "bus", "X": "helicopter", "Y": "sailboat", "[": "person", "^": "aircraft",
    "_": "weather", "a": "ambulance", "b": "bicycle", "f": "fire truck", "j": "jeep",
    "k": "truck", "r": "repeater", "s": "boat", "u": "semi", "v": "van", "y": "house+yagi",
    "`": "dish", ";": "campsite", "/": "dot", "\\": "triangle", "@": "hurricane",
}
ALT_SYMBOLS = {"#": "digipeater", "&": "gateway", "-": "house", ">": "car", "_": "weather",
               "a": "ARRL/ARES", "k": "SUV", "n": "node", "j": "jeep", "u": "truck"}

_CALL = re.compile(r"^[A-Z0-9]{1,6}(-[0-9]{1,2})?$")
_UNCOMP = re.compile(r"^(\d{2})([\d ]{2}\.[\d ]{2})([NS])(.)(\d{3})([\d ]{2}\.[\d ]{2})([EW])(.)")
_ALT = re.compile(r"/A=(-?\d{6})")
_CSE_SPD = re.compile(r"^(\d{3})/(\d{3})")


def symbol_name(table, code):
    if table == "/":
        return SYMBOLS.get(code, "station")
    return ALT_SYMBOLS.get(code, "station")


def _printable(s, n=120):
    return "".join(c for c in s if c.isprintable())[:n]


def parse_frame(line):
    """multimon-ng line -> {"src","dst","path","payload","via"} or None."""
    if not isinstance(line, str):
        return None
    line = line.rstrip("\r\n")
    if line.startswith("APRS: "):
        line = line[6:]
    head, sep, payload = line.partition(":")
    if not sep or ">" not in head or not payload:
        return None
    src, _, rest = head.partition(">")
    parts = rest.split(",")
    dst, path = parts[0], parts[1:]
    src = src.strip().upper()
    if not _CALL.match(src) or not dst:
        return None
    heard = [p.rstrip("*") for p in path if p.endswith("*")]
    via = heard[-1] if heard else None           # last digi that repeated it (None = direct)
    if via and via.upper().startswith(("WIDE", "TRACE", "RELAY")):
        via = "a digipeater"
    return {"src": src, "dst": dst.strip().upper(), "path": path,
            "payload": payload, "via": via}


def _uncompressed(s):
    m = _UNCOMP.match(s)
    if not m:
        return None
    la_d, la_m, ns, table, lo_d, lo_m, ew, code = m.groups()
    try:
        lat = int(la_d) + float(la_m.replace(" ", "0")) / 60
        lon = int(lo_d) + float(lo_m.replace(" ", "0")) / 60
    except ValueError:
        return None
    if ns == "S":
        lat = -lat
    if ew == "W":
        lon = -lon
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    out = {"lat": lat, "lon": lon, "table": table, "code": code}
    rest = s[19:]
    cm = _CSE_SPD.match(rest)
    if cm and code != "_":
        c, sp = int(cm.group(1)), int(cm.group(2))
        if 0 < c <= 360:
            out["course"] = c % 360
        out["speed_kt"] = sp
        rest = rest[7:]
    out["comment"] = rest
    return out


def _b91(s):
    v = 0
    for ch in s:
        o = ord(ch) - 33
        if not 0 <= o <= 90:
            return None
        v = v * 91 + o
    return v


def _compressed(s):
    if len(s) < 13:
        return None
    table = s[0]
    y, x = _b91(s[1:5]), _b91(s[5:9])
    if y is None or x is None or table.isdigit():
        return None
    lat = 90 - y / 380926.0
    lon = -180 + x / 190463.0
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    out = {"lat": lat, "lon": lon, "table": table, "code": s[9]}
    c, sp, t = s[10], s[11], s[12]
    if c != " " and ord(t) - 33 >= 0:
        cv, sv = ord(c) - 33, ord(sp) - 33
        if 0 <= cv <= 89:
            out["course"] = (cv * 4) % 360
            out["speed_kt"] = round(1.08 ** sv - 1)
        elif c == "{":
            pass                                   # radio range, not used
        elif ((ord(t) - 33) >> 3) & 3 == 2:        # altitude in cs bytes
            out["alt_ft"] = 1.002 ** (cv * 91 + sv)
    out["comment"] = s[13:]
    return out


def _mic_e(dst, info):
    """Mic-E: latitude lives in the destination callsign, the rest in the info field."""
    d = dst.split("-")[0]
    if len(d) != 6 or len(info) < 9:
        return None
    digits = []
    for ch in d:
        if ch.isdigit():
            digits.append(ch)
        elif "A" <= ch <= "J":
            digits.append(str(ord(ch) - ord("A")))
        elif "P" <= ch <= "Y":
            digits.append(str(ord(ch) - ord("P")))
        elif ch in "KLZ":
            digits.append("0")                     # ambiguity
        else:
            return None
    lat = int("".join(digits[0:2])) + int("".join(digits[2:4])) / 60.0 + \
        int("".join(digits[4:6])) / 6000.0
    north = d[3] >= "P" or d[3] == "Z"
    lon_off = 100 if (d[4] >= "P" or d[4] == "Z") else 0
    west = d[5] >= "P" or d[5] == "Z"
    if not north:
        lat = -lat
    b = [ord(c) - 28 for c in info[1:7]]
    deg = b[0] + lon_off
    if 180 <= deg <= 189:
        deg -= 80
    elif 190 <= deg <= 199:
        deg -= 190
    mins = b[1] - 60 if b[1] >= 60 else b[1]
    lon = deg + (mins + b[2] / 100.0) / 60.0
    if west:
        lon = -lon
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or mins > 59:
        return None
    speed = b[3] * 10 + b[4] // 10
    if speed >= 800:
        speed -= 800
    course = (b[4] % 10) * 100 + b[5]
    if course >= 400:
        course -= 400
    out = {"lat": lat, "lon": lon, "code": info[7], "table": info[8], "speed_kt": speed}
    if 0 < course <= 360:
        out["course"] = course % 360
    rest = info[9:]
    # optional altitude: 3 base-91 chars + "}" , metres above -10 km
    m = re.search(r"(.{3})\}", rest)
    if m:
        v = _b91(m.group(1))
        if v is not None:
            out["alt_ft"] = (v - 10000) * 3.28084
        rest = rest.replace(m.group(0), "", 1)
    out["comment"] = rest.lstrip(">]`'")
    return out


def _weather(s):
    """Weather fields from a position comment or a positionless '_' report."""
    w = {}
    for key, pat, conv in (("wind_dir", r"(?:^|_|c)(\d{3})/(\d{3})", None),
                           ("gust_mph", r"g(\d{3})", int), ("temp_f", r"t(-?\d{2,3})", int),
                           ("rain_1h_in", r"r(\d{3})", lambda v: int(v) / 100.0),
                           ("humidity", r"h(\d{2})", lambda v: 100 if v == "00" else int(v)),
                           ("pressure_mb", r"b(\d{5})", lambda v: int(v) / 10.0)):
        m = re.search(pat, s)
        if not m:
            continue
        if key == "wind_dir":
            w["wind_dir"], w["wind_mph"] = int(m.group(1)) % 360, int(m.group(2))
        else:
            w[key] = conv(m.group(1))
    return w


def decode(frame):
    """Parsed frame -> station report dict (always has "src" and "kind")."""
    p = frame["payload"]
    out = {"src": frame["src"], "via": frame["via"], "kind": "other", "raw": _printable(p)}
    t = p[:1]
    body = None
    if t in "!=":
        body = p[1:]
    elif t in "/@":
        body = p[8:]                                # 7-char timestamp
    elif t in ";":                                  # object: ;NAME_____*DDHHMMz<pos>
        if len(p) >= 18:
            out["src"] = _printable(p[1:10].strip(), 9) or out["src"]
            out["object_of"] = frame["src"]
            out["alive"] = p[10] == "*"
            body = p[18:]
    elif t == ")":                                  # item: )NAME!<pos>
        m = re.match(r"\)([^!_]{3,9})[!_]", p)
        if m:
            out["src"] = _printable(m.group(1).strip(), 9)
            out["object_of"] = frame["src"]
            body = p[len(m.group(0)):]
    elif t in "`'" or (t in "\x1c\x1d" and len(p) > 8):
        pos = _mic_e(frame["dst"], p)
        if pos:
            out.update(pos, kind="position")
    elif t == ">":
        out.update(kind="status", comment=_printable(p[1:]))
    elif t == ":" and len(p) > 11 and p[10] == ":":
        to = p[1:10].strip()
        text = p[11:]
        mid = None
        if "{" in text:
            text, _, mid = text.rpartition("{")
        if to.upper().startswith(("BLN", "NWS")):
            out.update(kind="bulletin", to=to, text=_printable(text))
        elif re.match(r"^(ack|rej)\w+$", text):
            out.update(kind="ack", to=to)
        else:
            out.update(kind="message", to=to, text=_printable(text), msgid=mid)
    elif t == "_":
        out.update(kind="weather", wx=_weather(p[9:]))
    if body is not None:
        pos = _uncompressed(body) if body[:1].isdigit() else _compressed(body)
        if pos:
            out.update(pos, kind="object" if out.get("object_of") else "position")
    if "comment" in out:
        c = out["comment"]
        m = _ALT.search(c)
        if m:
            out["alt_ft"] = int(m.group(1))
            c = c.replace(m.group(0), "")
        if out.get("code") == "_":
            out["wx"] = _weather(c)
            out["kind"] = "weather"
            c = ""
        out["comment"] = _printable(c.strip())
    if "table" in out:
        out["symbol"] = symbol_name(out["table"], out.get("code", ""))
    return out


from geo import dist_nm  # noqa: E402,F401  (consolidated into geo.py, Phase 1a)


class Stations:
    """Everything heard, by callsign: last report, track, counts, digipeaters used."""

    def __init__(self, cap=2000):
        self.s = {}
        self.cap = cap
        self.packets = 0
        self.digis = {}

    def add(self, rep, now):
        self.packets += 1
        if rep.get("via") and rep["via"] != "a digipeater":
            self.digis[rep["via"]] = self.digis.get(rep["via"], 0) + 1
        k = rep["src"]
        st = self.s.get(k)
        if st is None:
            if len(self.s) >= self.cap:
                oldest = min(self.s, key=lambda c: self.s[c]["last"])
                self.s.pop(oldest)
            st = self.s[k] = {"call": k, "first": now, "n": 0, "track": [], "msgs": []}
        st["n"] += 1
        st["last"] = now
        st["via"] = rep.get("via")
        for f in ("symbol", "comment", "speed_kt", "course", "alt_ft", "wx", "object_of"):
            if rep.get(f) not in (None, ""):
                st[f] = rep[f]
        if "lat" in rep:
            st["lat"], st["lon"] = rep["lat"], rep["lon"]
            tr = st["track"]
            if not tr or abs(tr[-1][0] - rep["lat"]) + abs(tr[-1][1] - rep["lon"]) > 1e-4:
                tr.append((rep["lat"], rep["lon"], now))
                del tr[:-300]
        if rep["kind"] in ("message", "bulletin", "status"):
            st["msgs"].append((now, rep["kind"], rep.get("to", ""), rep.get("text") or
                               rep.get("comment", "")))
            del st["msgs"][:-20]
        return st

    def moving(self, st):
        return (st.get("speed_kt") or 0) >= 3 and len(st["track"]) >= 2


def save_stations(stations, path, now, keep_s=86400):
    """Last day of stations, for the next session and for Sitrep. Atomic write."""
    import json
    import os
    keep = {c: dict(st, track=[list(t) for t in st["track"][-60:]], msgs=st["msgs"][-5:])
            for c, st in stations.s.items() if now - st.get("last", 0) < keep_s}
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump({"t": now, "packets": stations.packets, "digis": stations.digis,
                   "stations": keep}, f)
    os.replace(tmp, path)


def load_stations(path, now, keep_s=86400):
    """Inverse of save_stations; anything malformed is dropped, never raised."""
    import json
    out = Stations()
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return out
    if not isinstance(d, dict) or not isinstance(d.get("stations"), dict):
        return out
    for c, st in d["stations"].items():
        try:
            if not isinstance(st, dict) or now - float(st["last"]) > keep_s:
                continue
            st["call"] = str(c)[:12]
            st["n"] = int(st.get("n", 1))
            st["first"] = float(st.get("first", st["last"]))
            st["last"] = float(st["last"])
            st["track"] = [(float(a), float(b), float(t)) for a, b, t in st.get("track", [])
                           if -90 <= float(a) <= 90 and -180 <= float(b) <= 180]
            st["msgs"] = [tuple(m) for m in st.get("msgs", []) if isinstance(m, list)
                          and len(m) == 4]
            if "lat" in st:
                st["lat"], st["lon"] = float(st["lat"]), float(st["lon"])
                if not (-90 <= st["lat"] <= 90 and -180 <= st["lon"] <= 180):
                    st.pop("lat")
                    st.pop("lon")
            out.s[st["call"]] = st
        except (KeyError, TypeError, ValueError):
            continue
    if isinstance(d.get("digis"), dict):
        out.digis = {str(k): int(v) for k, v in d["digis"].items() if isinstance(v, int)}
    return out


# ======================================================================================
# Tk workspace (merged from the former aprs_app.py, Phase 1b).
#
# Hear the ham-radio position network on 144.390 MHz. Receive-only: licensed hams' cars,
# trackers, weather stations, digipeaters and balloons beacon their position; rtl_fm
# demodulates, multimon-ng decodes the 1200-baud AFSK, the decoder above parses it.
# Nothing is transmitted and nothing is uploaded (this is not an iGate). --demo
# synthesizes stations so the display can be exercised without hardware.
#
# suite/skyintel are imported lazily inside main() so that importing aprs.py as a decoder
# library (ops.py, hub.py, tests) stays light and free of the Tk/suite stack.
# ======================================================================================
FREQ = "144.390M"      # North American APRS
DEFAULTS = {"home": {"lat": 39.62, "lon": -104.87}, "gain": 0, "range_nm": 40}
KIND_COL = {"moving": "#e8eaed", "weather": "#7fa7d9", "infra": "#5ec4d4",
            "fixed": "#7d858f", "balloon": "#c8b6ff"}


def pipeline(gain):
    """rtl_fm -> multimon-ng. Fixed argv pieces only; gain is an int from settings."""
    g = " -g %d" % int(gain) if gain else ""
    mm = "multimon-ng -t raw -a AFSK1200 -A /dev/stdin"
    if shutil.which("stdbuf"):
        mm = "stdbuf -oL " + mm          # line-buffer so packets arrive as they're heard
    return "rtl_fm -f %s -M fm -s 22050%s -E dc - 2>/dev/null | %s" % (FREQ, g, mm)


def kind_of(st):
    sym = st.get("symbol", "")
    if sym in ("digipeater", "gateway", "repeater", "node"):
        return "infra"
    if st.get("wx") or sym == "weather":
        return "weather"
    if sym == "balloon":
        return "balloon"
    if Stations.moving(None, st) or sym in ("car", "truck", "van", "jeep", "SUV", "semi",
                                            "bicycle", "motorcycle", "person", "RV", "bus"):
        return "moving"
    return "fixed"


def age(sec):
    sec = int(sec)
    return "%ds" % sec if sec < 60 else ("%dm" % (sec // 60) if sec < 3600 else
                                         "%dh" % (sec // 3600))


class Demo:
    """A few synthetic stations (DEMO-n calls can't belong to anyone)."""

    def __init__(self, home):
        self.h = home
        self.t0 = time.time()
        self.i = 0

    def lines(self):
        t = time.time() - self.t0
        la, lo = self.h["lat"], self.h["lon"]
        out = []
        self.i += 1
        k = self.i % 6
        if k == 0:
            a = t / 40.0
            out.append("APRS: DEMO1-9>APDR16,DEMO7*,WIDE2-1:=%s/%s>%03d/%03d/A=005400 commuting" % (
                _ddmm(la + 0.08 * math.sin(a), False), _ddmm(lo + 0.1 * math.cos(a), True),
                int(math.degrees(a + math.pi / 2)) % 360 or 360, 38))
        elif k == 1:
            out.append("APRS: DEMO2>APRS:!%s/%s_180/005g012t041r000p000h52b10120" % (
                _ddmm(la + 0.05, False), _ddmm(lo - 0.12, True)))
        elif k == 2:
            out.append("APRS: DEMO7>APN391:!%s/%s#PHG7430 W2 digipeater" % (
                _ddmm(la + 0.21, False), _ddmm(lo - 0.33, True)))
        elif k == 3:
            out.append("APRS: DEMO3-7>APK004,DEMO7*:>Hiking Mt Falcon")
        elif k == 4:
            out.append("APRS: DEMO4-11>APRS,WIDE1-1:/%sz%s/%sO%03d/%03d/A=%06d" % (
                time.strftime("%d%H%M", time.gmtime()), _ddmm(la - 0.2 + t / 9000, False),
                _ddmm(lo + 0.3 + t / 3000, True), 75, 22, min(98000, 6000 + int(t * 16))))
        else:
            out.append("APRS: DEMO5>APRS::DEMO1-9  :See you at the swap meet{3")
        return out


def _ddmm(v, is_lon):
    a = abs(v)
    d = int(a)
    m = (a - d) * 60
    if is_lon:
        return "%03d%05.2f%s" % (d, m, "W" if v < 0 else "E")
    return "%02d%05.2f%s" % (d, m, "S" if v < 0 else "N")


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S      # lazy: keep the decoder library importable without the Tk stack
    import skyintel as SI
    STATIONS_PATH = os.path.join(S.CACHE, "aprs_stations.json")    # last 24 h; Sitrep reads it
    S.single_instance("APRS")
    s, spath = S.settings("aprs", DEFAULTS)
    demo = "--demo" in sys.argv or not (shutil.which("rtl_fm") and shutil.which("multimon-ng"))
    root, F = S.make_root("APRS")
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("aprs")
    lease = S.RtlLease("APRS", log=lambda m: None)
    lease.on_preempt = lambda: stop()   # another workspace wants the radio
    q = queue.Queue()
    stations = Stations() if "--demo" in sys.argv else load_stations(STATIONS_PATH,
                                                                      time.time())
    home = dict(s.get("home") or DEFAULTS["home"])
    st = {"proc": None, "on": False, "starting": False, "held": False, "gen": 0, "sel": None,
          "raw": [], "show_raw": False, "last_pkt": None, "rate": []}

    top = S.top_bar(root, F, "APRS", "144.390 MHz · ham position network · receive-only")
    state_pill = S.pill(top, F, "Off")

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    left = tk.Frame(body, bg=T.SURFACE, width=T.px(450))
    left.pack(side="left", fill="y")
    left.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    lp = tk.Frame(left, bg=T.SURFACE)
    lp.pack(fill="both", expand=True, padx=T.px(14), pady=T.px(10))
    T.section(lp, F, "Heard").pack(fill="x")
    lst = tk.Text(lp, bg=T.SURFACE, fg=T.TXT_2, font=F["mono"], bd=0, highlightthickness=0,
                  height=10, wrap="none", state="disabled", cursor="arrow")
    lst.tag_config("hdr", foreground=T.TXT_3)
    lst.tag_config("pick", foreground=S.AMBER)
    for k2, c in KIND_COL.items():
        lst.tag_config(k2, foreground=T.night(c))
    lst.pack(fill="x", pady=(T.px(4), 0))
    summary = tk.Label(lp, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w",
                       justify="left", wraplength=T.px(420))
    summary.pack(fill="x", pady=(0, T.px(8)))
    T.section(lp, F, "Selected").pack(fill="x")
    d_title = tk.Label(lp, text="—", font=F["now"], fg=S.TXT, bg=T.SURFACE, anchor="w")
    d_title.pack(fill="x")
    d_sub = tk.Label(lp, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE, anchor="w",
                     justify="left", wraplength=T.px(420))
    d_sub.pack(fill="x")
    d_body = tk.Label(lp, text="", font=F["mono"], fg=S.TXT, bg=T.SURFACE, anchor="nw",
                      justify="left", wraplength=T.px(420))
    d_body.pack(fill="x", pady=(T.px(4), 0))
    status = tk.Label(lp, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE, anchor="w",
                      justify="left", wraplength=T.px(420))
    status.pack(fill="x", side="bottom")

    right = tk.Frame(body, bg=S.MAPBG)
    right.pack(side="left", fill="both", expand=True)
    mapcv = tk.Canvas(right, bg=S.MAPBG, highlightthickness=0)
    mapcv.pack(fill="both", expand=True)
    rawbox = tk.Text(right, bg=T.night("#0c1014"), fg=T.TXT_2, font=F["map"], bd=0,
                     highlightthickness=0, height=8, wrap="none", state="disabled")
    hits = []

    # ---- drawing ------------------------------------------------------------------------
    def draw_map():
        cv = mapcv
        cv.delete("all")
        hits.clear()
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50:
            return
        nm_r = float(s.get("range_nm") or 40)
        k = (min(w, h) / 2 - 20) / nm_r
        cx, cy = w / 2, h / 2

        def xy(lat, lon):
            d = SI.dist_nm(home["lat"], home["lon"], lat, lon)
            b = math.radians(SI.bearing_deg(home["lat"], home["lon"], lat, lon))
            return cx + d * k * math.sin(b), cy - d * k * math.cos(b)
        for ring in (nm_r / 4, nm_r / 2, nm_r * 3 / 4, nm_r):
            r = ring * k
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=T.night("#1f2a31"))
            cv.create_text(cx + 4, cy - r + 10, text="%g nm" % ring, anchor="w",
                           fill=T.TXT_3, font=F["map"])
        cv.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3, fill=S.GREEN, outline="")
        now = time.time()
        shown = 0
        for c, stn in sorted(stations.s.items(), key=lambda kv: kv[1]["last"]):
            if "lat" not in stn or now - stn["last"] > 3 * 3600:
                continue
            x, y = xy(stn["lat"], stn["lon"])
            if not (-20 < x < w + 20 and -20 < y < h + 20):
                continue
            shown += 1
            kd = kind_of(stn)
            col = T.night(KIND_COL[kd])
            sel = c == st["sel"]
            if sel:
                col = S.AMBER
            fade = now - stn["last"] > 1800
            if len(stn["track"]) >= 2 and kd in ("moving", "balloon"):
                pts = [v for la, lo, _ in stn["track"][-80:] for v in xy(la, lo)]
                cv.create_line(*pts, fill=col, width=2 if sel else 1, dash=(2, 3) if fade else ())
            r = 5 if sel else 4
            if kd == "infra":
                cv.create_rectangle(x - r, y - r, x + r, y + r, outline=col, width=2)
            elif kd == "weather":
                cv.create_oval(x - r, y - r, x + r, y + r, fill=col, outline="")
            else:
                cv.create_oval(x - r, y - r, x + r, y + r, outline=col, width=2,
                               fill=col if kd == "moving" and not fade else "")
            if stn.get("course") is not None and kd == "moving":
                a = math.radians(stn["course"])
                cv.create_line(x, y, x + 14 * math.sin(a), y - 14 * math.cos(a), fill=col)
            if sel or shown <= 40:
                flip = x > w - T.px(140)
                cv.create_text(x - 8 if flip else x + 8, y, anchor="e" if flip else "w",
                               fill=S.TXT if sel else col, font=F["mapb"] if sel else F["map"],
                               text=c + ("  %d kt" % stn["speed_kt"] if kd == "moving" and
                                         stn.get("speed_kt") else ""))
            hits.append((x, y, c))
        y0 = h - 14
        for kd in ("moving", "fixed", "weather", "infra", "balloon"):
            cv.create_text(12, y0, anchor="w", fill=T.night(KIND_COL[kd]), font=F["map"],
                           text="● " + {"infra": "digi / iGate"}.get(kd, kd))
            y0 -= 16
        if not stations.s:
            cv.create_text(w / 2, h / 2 + 40, fill=T.TXT_3, font=F["sm"],
                           text="Listening… Denver usually has a packet every few seconds."
                           if st["on"] else "Press Listen (Space).")

    def detail(stn):
        if not stn:
            d_title.config(text="—")
            d_sub.config(text="tap a station on the map or in the list")
            d_body.config(text="")
            return
        now = time.time()
        kd = kind_of(stn)
        d_title.config(text=stn["call"], fg=T.night(KIND_COL[kd]))
        bits = [stn.get("symbol", "station")]
        if stn.get("object_of"):
            bits.append("object from %s" % stn["object_of"])
        bits.append("heard %s ago · %d packet%s" % (age(now - stn["last"]), stn["n"],
                                                   "" if stn["n"] == 1 else "s"))
        bits.append("direct" if not stn.get("via") else "via %s" % stn["via"])
        d_sub.config(text="  ·  ".join(bits))
        lines = []
        if "lat" in stn:
            d = SI.dist_nm(home["lat"], home["lon"], stn["lat"], stn["lon"])
            b = SI.bearing_deg(home["lat"], home["lon"], stn["lat"], stn["lon"])
            lines.append("%.1f nm  %03d°   %.4f, %.4f" % (d, b, stn["lat"], stn["lon"]))
        mv = []
        if stn.get("speed_kt") is not None and kd == "moving":
            mv.append("%d kt (%d mph)" % (stn["speed_kt"], round(stn["speed_kt"] * 1.15078)))
        if stn.get("course") is not None and kd == "moving":
            mv.append("heading %03d°" % stn["course"])
        if stn.get("alt_ft") is not None:
            mv.append("%s ft" % format(int(stn["alt_ft"]), ","))
        if mv:
            lines.append("   ".join(mv))
        wx = stn.get("wx") or {}
        if wx:
            w = []
            if "temp_f" in wx:
                w.append("%d°F (%.0f°C)" % (wx["temp_f"], (wx["temp_f"] - 32) / 1.8))
            if "wind_mph" in wx:
                w.append("wind %03d° %d mph" % (wx.get("wind_dir", 0), wx["wind_mph"]) +
                         (" g%d" % wx["gust_mph"] if wx.get("gust_mph") else ""))
            if "humidity" in wx:
                w.append("%d%% RH" % wx["humidity"])
            if "pressure_mb" in wx:
                w.append("%.1f mb" % wx["pressure_mb"])
            lines.append("  ".join(w))
        if stn.get("comment"):
            lines.append("“%s”" % stn["comment"][:90])
        for t, kind, to, text in stn["msgs"][-3:]:
            lines.append("%s %s%s" % (time.strftime("%H:%M", time.localtime(t)),
                                       ("→ %s: " % to) if to else "", text[:70]))
        d_body.config(text="\n".join(lines))

    def render():
        now = time.time()
        rows = sorted(stations.s.values(), key=lambda x: -x["last"])
        lst.config(state="normal")
        lst.delete("1.0", "end")
        lst.insert("end", "%-10s %-11s %6s %5s\n" % ("CALL", "TYPE", "RANGE", "AGO"), "hdr")
        for i, stn in enumerate(rows[:10]):
            d = ("%5.1f" % SI.dist_nm(home["lat"], home["lon"], stn["lat"], stn["lon"])
                 if "lat" in stn else "    —")
            tag = "r%d" % i
            lst.insert("end", "%-10s %-11s %6s %5s\n" % (stn["call"][:10],
                                                          (stn.get("symbol") or ("status only" if "lat" not in stn
                                                                    else ""))[:11], d,
                                                          age(now - stn["last"])),
                       (tag, "pick" if stn["call"] == st["sel"] else kind_of(stn)))
            lst.tag_bind(tag, "<Button-1>", lambda e, c=stn["call"]: pick(c))
        lst.config(state="disabled")
        detail(stations.s.get(st["sel"]))
        draw_map()
        n = len([t for t in st["rate"] if now - t < 600])
        digis = sorted(stations.digis.items(), key=lambda kv: -kv[1])[:3]
        summary.config(text="%d station%s · %d packets in the last 10 min%s" % (
            len(stations.s), "" if len(stations.s) == 1 else "s", n,
            ("  ·  busiest digis: " + ", ".join(d for d, _ in digis)) if digis else ""))

    def pick(c):
        st["sel"] = c
        render()

    def on_map_click(e):
        best = min(hits, key=lambda t: (t[0] - e.x) ** 2 + (t[1] - e.y) ** 2, default=None)
        if best and (best[0] - e.x) ** 2 + (best[1] - e.y) ** 2 < 25 ** 2:
            pick(best[2])

    def zoom(f):
        s["range_nm"] = max(5, min(200, round(float(s.get("range_nm") or 40) * f)))
        draw_map()

    mapcv.bind("<Button-1>", on_map_click)
    mapcv.bind("<Configure>", lambda e: draw_map())

    # ---- radio ---------------------------------------------------------------------------
    def worker(gen):
        if demo:
            dm = Demo(home)
            while st["on"] and st["gen"] == gen:
                for ln in dm.lines():
                    q.put(("line", ln))
                time.sleep(1.5)
            return
        with S.errfile(os.path.join(S.CACHE, "aprs.err")) as err:
            p = S.spawn(pipeline(s.get("gain", 0)), shell=True, stdout=__import__(
                "subprocess").PIPE, stderr=err, text=True, errors="replace")
        if st["gen"] == gen:
            st["proc"] = p
        try:
            for line in p.stdout:
                if not st["on"] or st["gen"] != gen:
                    break
                q.put(("line", line))
        finally:
            S.stop_group(p, grace=1.5)
            if st["on"] and st["gen"] == gen:
                q.put(("died", None))

    def begin():
        st["gen"] += 1
        st["on"] = True
        state_pill.config(text="Listening" + (" (demo)" if demo else ""), bg=S.GREEN)
        T.set_btn(listen_btn, "Stop", kind="danger")
        status.config(text="demo traffic - synthetic stations" if demo else
                      "listening on 144.390 MHz - receive-only, nothing uploaded", fg=T.TXT_3)
        threading.Thread(target=worker, args=(st["gen"],), daemon=True).start()

    def start():
        if st["on"] or st["starting"]:
            return
        if demo:
            begin()
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
            st["held"] = True
            begin()
        S.acquire_bg(root, lease, done)

    def stop(sync=False):
        was_starting, st["starting"] = st["starting"], False
        st["on"] = False
        st["gen"] += 1
        p, st["proc"] = st["proc"], None
        if p:
            S.stop_group(p, grace=1.5)
        if not demo and (st["held"] or was_starting):
            st["held"] = False
            S.release_now(lease) if sync else S.release_bg(root, lease)
        state_pill.config(text="Off", bg=S.DIM)
        status.config(text="Stopped. Stations heard so far are kept.", fg=T.TXT_3)
        T.set_btn(listen_btn, "Listen", kind="primary")

    def toggle(_=None):
        stop() if (st["on"] or st["starting"]) else start()

    def toggle_raw(_=None):
        st["show_raw"] = not st["show_raw"]
        if st["show_raw"]:
            rawbox.pack(side="bottom", fill="x", before=mapcv)
        else:
            rawbox.pack_forget()
        T.set_btn(raw_btn, kind="primary" if st["show_raw"] else "ghost")

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    listen_btn = S.btn(bar, "Listen", toggle, F, padx=14, pady=5, kind="primary")
    listen_btn.pack(side="left", padx=(10, 6), pady=6)
    raw_btn = S.btn(bar, "Packets", toggle_raw, F, padx=10, pady=5, kind="ghost")
    raw_btn.pack(side="left", padx=2)
    S.btn(bar, "−", lambda: zoom(1.5), F, padx=10, pady=5, kind="ghost").pack(side="left",
                                                                              padx=(12, 1))
    S.btn(bar, "+", lambda: zoom(1 / 1.5), F, padx=10, pady=5, kind="ghost").pack(side="left")
    S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
        side="right", padx=(2, 10))
    root.bind("<space>", toggle)
    root.bind("p", toggle_raw)
    root.bind("+", lambda e: zoom(1 / 1.5))
    root.bind("-", lambda e: zoom(1.5))

    def pump():
        changed = False
        try:
            for _ in range(200):
                kind, val = q.get_nowait()
                if kind == "died":
                    status.config(text="decoder stopped - see %s" %
                                  os.path.join(S.CACHE, "aprs.err"), fg=S.RED)
                    stop()
                    continue
                f = parse_frame(val)
                if not f:
                    continue
                rep = decode(f)
                now = time.time()
                new = rep["src"] not in stations.s
                stn = stations.add(rep, now)
                st["rate"].append(now)
                del st["rate"][:-2000]
                st["raw"].append(time.strftime("%H:%M:%S ") + val.strip()[6:200])
                del st["raw"][:-200]
                if new:
                    slog.event("aprs", "%s (%s)" % (stn["call"], stn.get("symbol", "?")),
                               id=stn["call"])
                changed = True
        except queue.Empty:
            pass
        except Exception as e:      # keep pumping whatever one packet does
            print("aprs pump: %r" % e, file=sys.stderr)
        if changed:
            render()
            if st["show_raw"]:
                rawbox.config(state="normal")
                rawbox.delete("1.0", "end")
                rawbox.insert("end", "\n".join(st["raw"][-8:]))
                rawbox.config(state="disabled")
        root.after(400, pump)

    saved = [time.time()]

    def save():
        if "--demo" in sys.argv:
            return                 # synthetic stations never land in the real history
        try:
            save_stations(stations, STATIONS_PATH, time.time())
        except OSError:
            pass

    def tick():
        render()                   # keep "ago" columns honest
        if time.time() - saved[0] > 30:          # Ops reads this file
            saved[0] = time.time()
            save()
        root.after(5000, tick)

    def on_close():
        stop(sync=True)
        save()
        try:
            S.save_json(spath, s)
        except OSError:
            pass
        root.destroy()

    S.bind_quit(root, on_close)
    if demo and "--demo" not in sys.argv:
        status.config(text="rtl_fm or multimon-ng missing - showing demo traffic. "
                           "Install:  sudo apt install multimon-ng", fg=S.AMBER)
    render()
    pump()
    root.after(5000, tick)
    if "--listen" in sys.argv or "--demo" in sys.argv:
        root.after(300, start)
    root.mainloop()


if __name__ == "__main__":
    main()
