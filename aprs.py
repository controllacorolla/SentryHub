"""APRS packet decoding (receive-only). Pure functions, no I/O.

Input is what `multimon-ng -a AFSK1200 -A` prints for each frame:
    APRS: SRC>DEST,DIGI1*,WIDE2-1:payload
Handles the position formats people actually transmit around Denver:
uncompressed (! = / @), compressed, Mic-E (most mobile radios and trackers),
objects/items, status, weather and messages.
"""
import math
import re

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


def dist_nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1.0, math.sqrt(a)))


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
