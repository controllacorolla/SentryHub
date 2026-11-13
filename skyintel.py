"""Offline aircraft intelligence for Sky.

Everything here is derived from what an aircraft broadcasts plus fixed public allocation
tables - no network, no database. Pure functions so it can all be tested.
"""
import math
import time

# ---- US N-number from the ICAO 24-bit address -----------------------------------------
# The FAA hands out A00001..ADF7C7 to N1..N99999 in a fixed order, so the tail number of
# any US civil aircraft can be computed from its transponder address alone.
_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ"        # the FAA never uses I or O
_DIGITS = "0123456789"
_ALL = _CHARSET + _DIGITS
_SUFFIX = 1 + len(_CHARSET) * (1 + len(_CHARSET))   # 601: "", A, AA..AZ, B, BA..
_B4 = 1 + len(_CHARSET) + len(_DIGITS)              # 35
_B3 = len(_DIGITS) * _B4 + _SUFFIX                  # 951
_B2 = len(_DIGITS) * _B3 + _SUFFIX                  # 10111
_B1 = len(_DIGITS) * _B2 + _SUFFIX                  # 101711
US_FIRST, US_LAST = 0xA00001, 0xADF7C7


def _suffix(off):
    if off == 0:
        return ""
    first = _CHARSET[(off - 1) // (len(_CHARSET) + 1)]
    rem = (off - 1) % (len(_CHARSET) + 1)
    return first if rem == 0 else first + _CHARSET[rem - 1]


def _suffix_off(letters):
    off = _CHARSET.index(letters[0]) * (len(_CHARSET) + 1) + 1
    if len(letters) == 2:
        off += _CHARSET.index(letters[1]) + 1
    return off


def n_number(hex_):
    """'a835af' -> 'N628TS'; None outside the US civil block."""
    try:
        i = int(str(hex_), 16) - US_FIRST
    except ValueError:
        return None
    if i < 0 or i > US_LAST - US_FIRST:
        return None
    out = "N%d" % (i // _B1 + 1)
    rem = i % _B1
    for bucket in (_B2, _B3):
        if rem < _SUFFIX:
            return out + _suffix(rem)
        rem -= _SUFFIX
        out += str(rem // bucket)
        rem %= bucket
    if rem < _SUFFIX:
        return out + _suffix(rem)
    rem -= _SUFFIX
    out += str(rem // _B4)
    rem %= _B4
    return out if rem == 0 else out + _ALL[rem - 1]


def n_to_hex(tail):
    """'N628TS' -> 'a835af' (inverse of n_number); None if not a valid N-number."""
    t = str(tail).strip().upper()
    if len(t) < 2 or len(t) > 6 or t[0] != "N" or t[1] not in "123456789":
        return None
    s = t[2:]
    out = (int(t[1]) - 1) * _B1
    for bucket in (_B2, _B3, _B4):
        if not s:
            return "%06x" % (US_FIRST + out)
        if s[0] in _CHARSET:   # 1-2 letter suffix after 1, 2 or 3 digits ends the tail
            if len(s) > 2 or any(c not in _CHARSET for c in s):
                return None
            return "%06x" % (US_FIRST + out + _suffix_off(s))
        if s[0] not in _DIGITS:
            return None
        out += _SUFFIX + int(s[0]) * bucket
        s = s[1:]
    # after four digits: optionally one final letter or digit
    if not s:
        return "%06x" % (US_FIRST + out)
    if len(s) == 1 and s in _ALL:
        return "%06x" % (US_FIRST + out + _ALL.index(s) + 1)
    return None


# ---- country of registration from the ICAO address block -------------------------------
_BLOCKS = [  # (first, last, country) - ICAO Annex 10 Vol III allocations
    (0x008000, 0x00FFFF, "South Africa"), (0x010000, 0x017FFF, "Egypt"),
    (0x06A000, 0x06A3FF, "Qatar"), (0x0AC000, 0x0ACFFF, "Colombia"),
    (0x0D0000, 0x0D7FFF, "Mexico"), (0x100000, 0x1FFFFF, "Russia"),
    (0x300000, 0x33FFFF, "Italy"), (0x340000, 0x37FFFF, "Spain"),
    (0x380000, 0x3BFFFF, "France"), (0x3C0000, 0x3FFFFF, "Germany"),
    (0x400000, 0x43FFFF, "United Kingdom"), (0x440000, 0x447FFF, "Austria"),
    (0x448000, 0x44FFFF, "Belgium"), (0x458000, 0x45FFFF, "Denmark"),
    (0x460000, 0x467FFF, "Finland"), (0x468000, 0x46FFFF, "Greece"),
    (0x470000, 0x477FFF, "Hungary"), (0x478000, 0x47FFFF, "Norway"),
    (0x480000, 0x487FFF, "Netherlands"), (0x488000, 0x48FFFF, "Poland"),
    (0x490000, 0x497FFF, "Portugal"), (0x498000, 0x49FFFF, "Czechia"),
    (0x4A0000, 0x4A7FFF, "Romania"), (0x4A8000, 0x4AFFFF, "Sweden"),
    (0x4B0000, 0x4B7FFF, "Switzerland"), (0x4B8000, 0x4BFFFF, "Turkey"),
    (0x4CA000, 0x4CAFFF, "Ireland"), (0x4CC000, 0x4CCFFF, "Iceland"),
    (0x4D0000, 0x4D03FF, "Luxembourg"), (0x508000, 0x50FFFF, "Ukraine"),
    (0x710000, 0x717FFF, "Saudi Arabia"), (0x718000, 0x71FFFF, "South Korea"),
    (0x738000, 0x73FFFF, "Israel"), (0x750000, 0x757FFF, "Malaysia"),
    (0x758000, 0x75FFFF, "Philippines"), (0x768000, 0x76FFFF, "Singapore"),
    (0x780000, 0x7BFFFF, "China"), (0x7C0000, 0x7FFFFF, "Australia"),
    (0x800000, 0x83FFFF, "India"), (0x840000, 0x87FFFF, "Japan"),
    (0x880000, 0x887FFF, "Thailand"), (0x896000, 0x896FFF, "UAE"),
    (0x899000, 0x8993FF, "Taiwan"), (0x8A0000, 0x8A7FFF, "Indonesia"),
    (0xA00000, 0xAFFFFF, "United States"), (0xC00000, 0xC3FFFF, "Canada"),
    (0xC80000, 0xC87FFF, "New Zealand"), (0xE00000, 0xE3FFFF, "Argentina"),
    (0xE40000, 0xE7FFFF, "Brazil"), (0xE80000, 0xE80FFF, "Chile"),
    (0xE84000, 0xE84FFF, "Peru"),
]


def icao_country(hex_):
    try:
        v = int(str(hex_), 16)
    except ValueError:
        return ""
    for lo, hi, name in _BLOCKS:
        if lo <= v <= hi:
            return name
    return ""


# ---- what the transponder fields mean ---------------------------------------------------
SQUAWKS = {   # US / FAA meanings (JO 7110.65 and AIM 4-1-20)
    "1200": "VFR", "1202": "VFR glider", "1255": "firefighting", "1276": "ADIZ, no contact",
    "1277": "search & rescue", "4000": "military ops area", "7400": "drone lost link",
    "7500": "HIJACK", "7600": "RADIO FAILURE", "7700": "EMERGENCY", "7777": "military intercept",
}

CATEGORIES = {
    "A1": "light", "A2": "small", "A3": "large", "A4": "high-vortex large", "A5": "heavy",
    "A6": "high performance", "A7": "rotorcraft", "B1": "glider", "B2": "balloon",
    "B3": "parachutist", "B4": "ultralight", "B6": "drone", "B7": "space vehicle",
    "C1": "emergency vehicle", "C2": "service vehicle", "C3": "obstacle",
}

SOURCES = {   # readsb "type": how this position reached us
    "adsb_icao": "ADS-B", "adsb_icao_nt": "ADS-B (non-transponder)", "adsr_icao": "ADS-R",
    "tisb_icao": "TIS-B", "tisb_trackfile": "TIS-B", "tisb_other": "TIS-B",
    "adsb_other": "ADS-B (anon)", "adsr_other": "ADS-R", "mlat": "MLAT", "mode_s": "Mode S",
    "adsc": "ADS-C", "other": "other",
}


def relayed(source_type):
    """True when the position was rebroadcast by a ground station (TIS-B, ADS-R) or
    computed (MLAT): it says nothing about how far *this* antenna can hear."""
    t = str(source_type or "")
    return t.startswith(("tisb", "adsr", "mlat", "adsc"))


def fl(alt_ft):
    """Altitude as a controller would say it: FL350 above 18,000 ft, else 9,500."""
    if alt_ft is None:
        return ""
    a = int(round(alt_ft))
    return "FL%03d" % round(a / 100.0) if a >= 18000 else format(a, ",")


def flight_phase(alt, vr, gs, ground, near=None):
    """('climbing', detail) etc. near = (ident, dist_nm, field_elev_ft) of the nearest
    airport, so phase is judged against the field, not sea level (Denver is 5,400 ft)."""
    vr = vr or 0
    if ground:
        if gs and gs >= 40:
            return "rolling", ""
        return ("taxiing" if gs and gs > 4 else "on ground"), ""
    if alt is None:
        return "", ""
    ident, dist, elev = near if near else (None, 999.0, 0)
    agl = alt - (elev if dist < 30 else 0)
    if dist < 15 and agl < 4500 and vr < -300:
        return "approach", ident or ""
    if dist < 12 and agl < 3500 and vr > 300:
        return "departure", ident or ""
    if vr > 500:
        return "climbing", ""
    if vr < -500:
        return "descending", ""
    if alt >= 18000:
        return "cruise", ""
    return "level", ""


# ---- geometry ---------------------------------------------------------------------------
# Geometry consolidated into geo.py (Phase 1a); re-exported here so the modules
# that import skyintel.dist_nm / skyintel.bearing_deg keep working unchanged.
from geo import bearing_deg, dist_nm  # noqa: E402,F401


def offset(lat, lon, brg, nm):
    """Point nm from (lat, lon) along brg - flat-earth, fine for a map outline."""
    r = math.radians(brg)
    return (lat + nm * math.cos(r) / 60.0,
            lon + nm * math.sin(r) / (60.0 * max(0.05, math.cos(math.radians(lat)))))


def cpa(lat0, lon0, lat, lon, track, gs):
    """Closest point of approach to (lat0, lon0) if the aircraft holds track and speed.
    Returns (miss_distance_nm, seconds_until). seconds_until is 0 when it's receding."""
    k = math.cos(math.radians(lat0))
    px, py = (lon - lon0) * 60.0 * k, (lat - lat0) * 60.0
    if track is None or not gs:
        return math.hypot(px, py), 0.0
    r = math.radians(track)
    vx, vy = gs * math.sin(r) / 3600.0, gs * math.cos(r) / 3600.0
    v2 = vx * vx + vy * vy
    t = -(px * vx + py * vy) / v2
    if t <= 0:
        return math.hypot(px, py), 0.0
    return math.hypot(px + vx * t, py + vy * t), t


def overhead(lat0, lon0, a, miss_nm=1.5, within_s=600):
    """Seconds until this airborne contact passes within miss_nm of (lat0, lon0), or None."""
    if "lat" not in a or a.get("alt_baro") == "ground":
        return None
    d, t = cpa(lat0, lon0, a["lat"], a["lon"], a.get("track"), a.get("gs"))
    if t > 0 and d <= miss_nm and t <= within_s:
        return t
    return None


def mmss(sec):
    sec = int(max(0, sec))
    return "%d:%02d" % (sec // 60, sec % 60)


# ---- airline + route ---------------------------------------------------------------------
# ADS-B carries the callsign, never the route. Airline is decodable offline from the
# callsign's ICAO prefix; the route needs a lookup (adsbdb) and then a sanity check,
# because callsign->route databases go stale and miss irregular flights.
AIRLINES = {
    "AAL": "American", "AAY": "Allegiant", "ABX": "ABX Air", "ACA": "Air Canada",
    "AFR": "Air France", "AMX": "Aeromexico", "ANA": "All Nippon", "ASA": "Alaska",
    "ASH": "Mesa", "BAW": "British Airways", "CKS": "Kalitta", "CPZ": "Compass",
    "DAL": "Delta", "DLH": "Lufthansa", "EDV": "Endeavor", "EJA": "NetJets",
    "EJM": "Executive Jet Mgmt", "ENY": "Envoy", "FDX": "FedEx", "FFT": "Frontier",
    "GJS": "GoJet", "GTI": "Atlas Air", "ICE": "Icelandair", "JBU": "JetBlue",
    "LXJ": "Flexjet", "NKS": "Spirit", "RCH": "USAF Air Mobility", "RPA": "Republic",
    "SCX": "Sun Country", "SKW": "SkyWest", "SWA": "Southwest", "UAL": "United",
    "UPS": "UPS", "VOI": "Volaris", "WJA": "WestJet",
}


def airline_of(callsign):
    cs = str(callsign or "").strip().upper()
    if len(cs) >= 4 and cs[:3].isalpha() and cs[3].isdigit():
        return AIRLINES.get(cs[:3], "")
    return ""


def route_eligible(callsign):
    """Only scheduled-style callsigns (ABC123) have published routes; N-numbers don't."""
    cs = str(callsign or "").strip().upper()
    return 4 <= len(cs) <= 8 and cs[:3].isalpha() and cs[3].isdigit() and cs.isalnum()


def _airport(d):
    if not isinstance(d, dict):
        return None
    try:
        return {"icao": str(d.get("icao_code") or ""), "iata": str(d.get("iata_code") or ""),
                "name": str(d.get("name") or ""), "city": str(d.get("municipality") or ""),
                "lat": float(d["latitude"]), "lon": float(d["longitude"])}
    except (KeyError, TypeError, ValueError):
        return None


def parse_adsbdb(obj):
    """adsbdb /v0/callsign/<cs> JSON -> {"orig","mid","dest","airline"} or None."""
    try:
        fr = obj["response"]["flightroute"]
    except (KeyError, TypeError):
        return None
    o, d = _airport(fr.get("origin")), _airport(fr.get("destination"))
    if not o or not d:
        return None
    al = fr.get("airline") if isinstance(fr.get("airline"), dict) else {}
    return {"orig": o, "mid": _airport(fr.get("midpoint")), "dest": d,
            "airline": str(al.get("name") or "")}


def _code(ap):
    return ap.get("iata") or ap.get("icao") or "?"


def route_short(rt):
    legs = [rt["orig"]] + ([rt["mid"]] if rt.get("mid") else []) + [rt["dest"]]
    return " → ".join(_code(a) for a in legs)


def route_cities(rt):
    legs = [rt["orig"]] + ([rt["mid"]] if rt.get("mid") else []) + [rt["dest"]]
    return " → ".join(a.get("city") or a.get("name") or _code(a) for a in legs)


def route_check(lat, lon, rt):
    """Where the aircraft sits on its listed route. Returns {"plausible", "total",
    "flown", "to_go"} or None. Implausible = far off the great circle or outside the
    leg: the listing is probably for a different day's flight."""
    legs = [rt["orig"]] + ([rt["mid"]] if rt.get("mid") else []) + [rt["dest"]]
    R = 3440.065
    best = None
    done_before = 0.0
    total = sum(dist_nm(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(legs, legs[1:]))
    for a, b in zip(legs, legs[1:]):
        d12 = dist_nm(a["lat"], a["lon"], b["lat"], b["lon"])
        if d12 < 1:
            continue
        d13 = dist_nm(a["lat"], a["lon"], lat, lon)
        dt = math.radians(bearing_deg(a["lat"], a["lon"], lat, lon) -
                          bearing_deg(a["lat"], a["lon"], b["lat"], b["lon"]))
        xt = math.asin(max(-1.0, min(1.0, math.sin(d13 / R) * math.sin(dt)))) * R
        at = math.acos(max(-1.0, min(1.0, math.cos(d13 / R) /
                                     max(1e-9, math.cos(xt / R))))) * R
        if math.cos(dt) < 0:
            at = -at
        tol = max(100.0, 0.15 * d12)
        ok = abs(xt) <= tol and -tol <= at <= d12 + tol
        flown = done_before + max(0.0, min(d12, at))
        cand = {"plausible": ok, "total": total, "flown": flown, "to_go": total - flown,
                "xt": abs(xt)}
        if best is None or (ok and not best["plausible"]) or \
                (ok == best["plausible"] and cand["xt"] < best["xt"]):
            best = cand
        done_before += d12
    return best


def infer_route(phase, where):
    """What we can say with no lookup at all: arriving at / departing from a local field."""
    if phase == "approach" and where:
        return "→ %s (on approach)" % where
    if phase == "departure" and where:
        return "%s → (departing)" % where
    return ""


class RouteCache:
    """callsign -> route, persisted. Hits keep 3 days, misses 12 h (charters, GA, military
    and stale listings simply aren't in the database)."""
    HIT_TTL, MISS_TTL = 3 * 86400, 12 * 3600

    def __init__(self, data=None):
        self.d = {}
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(v.get("t"), (int, float)):
                    self.d[str(k)] = v
        self.dirty = False

    def get(self, cs, now=None):
        """(route or None, state) with state 'hit' | 'miss' | 'unknown'."""
        now = now or time.time()
        e = self.d.get(str(cs).upper())
        if not e:
            return None, "unknown"
        ttl = self.HIT_TTL if e.get("route") else self.MISS_TTL
        if now - e["t"] > ttl:
            return None, "unknown"
        return (e["route"], "hit") if e.get("route") else (None, "miss")

    def put(self, cs, route, now=None):
        self.d[str(cs).upper()] = {"t": now or time.time(), "route": route}
        if len(self.d) > 3000:   # keep the file small: drop the oldest
            for k in sorted(self.d, key=lambda k2: self.d[k2]["t"])[:500]:
                del self.d[k]
        self.dirty = True

    def to_json(self):
        return self.d


# ---- runways in use -----------------------------------------------------------------------
def runway_ends(rwys, ids):
    """[(lat1, lon1, lat2, lon2)] + [(id1, id2)] -> one entry per landable direction.
    The id painted at a threshold is the direction you face standing on it."""
    ends = []
    for (la1, lo1, la2, lo2), (id1, id2) in zip(rwys, ids):
        L = dist_nm(la1, lo1, la2, lo2)
        ends.append({"id": id1, "lat": la1, "lon": lo1, "len": L,
                     "hdg": bearing_deg(la1, lo1, la2, lo2)})
        ends.append({"id": id2, "lat": la2, "lon": lo2, "len": L,
                     "hdg": bearing_deg(la2, lo2, la1, lo1)})
    return ends


def runway_use(a, ends, field_elev):
    """('arr', '16R') / ('dep', '25') when the aircraft is unmistakably on a runway's final
    or climb-out, else None. Final: descending, low, within 1 nm of the extended centreline
    and before the threshold. Climb-out: climbing, past the far end on the same line."""
    if "lat" not in a or a.get("alt_baro") == "ground" or a.get("track") is None:
        return None
    alt = a.get("alt_baro")
    if not isinstance(alt, (int, float)):
        alt = a.get("alt_geom")
    if not isinstance(alt, (int, float)):
        return None
    agl = alt - field_elev
    vr = a.get("baro_rate") or a.get("geom_rate") or 0
    best = None
    for e in ends:
        off = abs((a["track"] - e["hdg"] + 180) % 360 - 180)
        if off > 20:
            continue
        k = math.cos(math.radians(e["lat"]))
        px, py = (a["lon"] - e["lon"]) * 60.0 * k, (a["lat"] - e["lat"]) * 60.0
        ux, uy = math.sin(math.radians(e["hdg"])), math.cos(math.radians(e["hdg"]))
        along, cross = px * ux + py * uy, abs(px * uy - py * ux)
        if cross > 1.0:
            continue
        if -12.0 <= along <= -0.2 and agl < 4500 and vr <= -200:
            cand = ("arr", e["id"], cross)
        elif e["len"] + 0.2 <= along <= e["len"] + 10.0 and agl < 5000 and vr >= 300:
            cand = ("dep", e["id"], cross)
        else:
            continue
        if best is None or cand[2] < best[2]:      # parallels: the closer centreline wins
            best = cand
    return best[:2] if best else None


class RunwayWatch:
    """Which runways an airport is using, from unique aircraft seen on final/climb-out
    in the last 20 minutes."""
    WINDOW = 1200

    def __init__(self):
        self.ev = {}   # (airport, kind, runway) -> {hex: last_seen}

    def note(self, airport, kind, rwy, hx, now=None):
        self.ev.setdefault((airport, kind, rwy), {})[hx] = now or time.time()

    def active(self, airport, now=None):
        now = now or time.time()
        out = {"arr": [], "dep": []}
        for key in list(self.ev):
            ap, kind, rwy = key
            d = self.ev[key]
            for hx in [hx for hx, t in d.items() if now - t > self.WINDOW]:
                del d[hx]
            if not d:
                del self.ev[key]
                continue
            if ap == airport:
                out[kind].append((rwy, len(d)))
        for kind in out:
            out[kind].sort(key=lambda x: (-x[1], x[0]))
        return out

    def label(self, airport, now=None):
        act = self.active(airport, now)
        bits = []
        if act["arr"]:
            bits.append("ARR " + " ".join(r for r, _ in act["arr"]))
        if act["dep"]:
            bits.append("DEP " + " ".join(r for r, _ in act["dep"]))
        return "  ".join(bits)


# ---- logbook: every airframe you've seen, per day ----------------------------------------
class Logbook:
    """One entry per airframe per day, plus lifetime first-seen dates for types and
    airframes so 'new to your sky' can be flagged. Fed only with live, real traffic."""
    MAX_LIFE = 100000

    def __init__(self, day=None, life=None, today=None):
        self.date = today or time.strftime("%Y-%m-%d")
        d = day if isinstance(day, dict) and day.get("date") == self.date else {}
        ent = d.get("ent") if isinstance(d.get("ent"), dict) else {}   # corrupt file: start clean
        need = ("calls", "first", "last")
        self.ent = {k: v for k, v in ent.items()
                    if isinstance(v, dict) and all(n in v for n in need)
                    and isinstance(v["calls"], list)}
        lf = life if isinstance(life, dict) else {}
        self.types = dict(lf.get("types") or {}) if isinstance(lf.get("types"), dict) else {}
        self.frames = dict(lf.get("frames") or {}) if isinstance(lf.get("frames"), dict) else {}
        self.dirty = False

    def see(self, a, here, now=None):
        """Record one sighting. Returns the entry (new or updated)."""
        now = now or time.time()
        hx = str(a.get("hex") or "").lower()
        if not hx:
            return None
        e = self.ent.get(hx)
        typ = str(a.get("t") or "").strip().upper()
        if e is None:
            e = self.ent[hx] = {
                "hex": hx, "calls": [], "reg": "", "type": typ, "desc": "",
                "country": icao_country(hx), "mil": False, "first": now, "last": now,
                "closest": None, "closest_alt": None, "max_alt": None,
                "new_type": bool(typ) and typ not in self.types,
                "new_frame": hx not in self.frames}
            if typ and typ not in self.types:
                self.types[typ] = self.date
            if hx not in self.frames and len(self.frames) < self.MAX_LIFE:
                self.frames[hx] = self.date
        e["last"] = now
        cs = str(a.get("flight") or "").strip().upper()
        if cs and cs not in e["calls"]:
            e["calls"].append(cs)
            del e["calls"][:-4]
        if not e["type"] and typ:
            e["type"] = typ
            e["new_type"] = typ not in self.types
            self.types.setdefault(typ, self.date)
        e["reg"] = e["reg"] or str(a.get("r") or "").strip() or (n_number(hx) or "")
        e["desc"] = e["desc"] or str(a.get("desc") or "")
        e["mil"] = e["mil"] or bool(a.get("_mil"))
        alt = a.get("alt_baro")
        alt = alt if isinstance(alt, (int, float)) else None
        if alt is not None and (e["max_alt"] is None or alt > e["max_alt"]):
            e["max_alt"] = int(alt)
        if "lat" in a and here:
            d = round(dist_nm(here[0], here[1], a["lat"], a["lon"]), 1)
            if e["closest"] is None or d < e["closest"]:
                e["closest"], e["closest_alt"] = d, (int(alt) if alt is not None else None)
        self.dirty = True
        return e

    def entries(self, key="first"):
        rows = list(self.ent.values())
        if key == "closest":
            rows.sort(key=lambda e: (e["closest"] is None, e["closest"] or 0))
        elif key == "type":
            rows.sort(key=lambda e: (e["type"] or "~", e["first"]))
        elif key == "last":
            rows.sort(key=lambda e: -e["last"])
        else:
            rows.sort(key=lambda e: e["first"])
        return rows

    def summary(self):
        rows = self.ent.values()
        types = {e["type"] for e in rows if e["type"]}
        return {"aircraft": len(self.ent), "types": len(types),
                "mil": sum(1 for e in rows if e["mil"]),
                "new_types": sorted({e["type"] for e in rows if e.get("new_type") and e["type"]}),
                "new_frames": sum(1 for e in rows if e.get("new_frame"))}

    def day_json(self):
        return {"date": self.date, "ent": self.ent}

    def life_json(self):
        return {"types": self.types, "frames": self.frames}

    def csv(self):
        import csv
        import io
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["first_seen", "last_seen", "hex", "callsigns", "registration", "type",
                    "description", "country", "military", "closest_nm", "closest_alt_ft",
                    "max_alt_ft", "new_type", "new_airframe"])
        for e in self.entries():
            w.writerow([time.strftime("%H:%M:%S", time.localtime(e["first"])),
                        time.strftime("%H:%M:%S", time.localtime(e["last"])), e["hex"],
                        " ".join(e["calls"]), e["reg"], e["type"], e["desc"], e["country"],
                        int(e["mil"]), e["closest"], e["closest_alt"], e["max_alt"],
                        int(bool(e.get("new_type"))), int(bool(e.get("new_frame")))])
        return out.getvalue()


# ---- receiver coverage: how far this antenna actually hears, per direction --------------
class Coverage:
    """Farthest directly-received position in each 10-degree sector, all-time and today.
    This is the antenna's real reception pattern: lopsided lobes mean terrain, a wall,
    or a bad ground plane in that direction."""
    BINS = 36
    MAX_NM = 300.0   # beyond this a position is bogus at 1090 MHz line of sight

    def __init__(self, data=None, today=None):
        today = today or time.strftime("%Y-%m-%d")
        d = data if isinstance(data, dict) else {}

        def ok(v):
            return isinstance(v, list) and len(v) == self.BINS and \
                all(isinstance(x, (int, float)) for x in v)
        self.all = list(d["all"]) if ok(d.get("all")) else [0.0] * self.BINS
        same_day = d.get("date") == today
        self.today = list(d["today"]) if same_day and ok(d.get("today")) else [0.0] * self.BINS
        self.date = today
        self.dirty = False

    def add(self, lat0, lon0, a):
        if "lat" not in a or relayed(a.get("type")):
            return False
        d = dist_nm(lat0, lon0, a["lat"], a["lon"])
        if not 0.5 < d < self.MAX_NM:
            return False
        today = time.strftime("%Y-%m-%d")
        if today != self.date:
            self.today, self.date = [0.0] * self.BINS, today
        b = int(bearing_deg(lat0, lon0, a["lat"], a["lon"]) // (360 / self.BINS)) % self.BINS
        grew = False
        for arr in (self.all, self.today):
            if d > arr[b]:
                arr[b] = round(d, 1)
                grew = True
        self.dirty = self.dirty or grew
        return grew

    def outline(self, scope="today"):
        """[(sector-centre bearing, nm), ...] for sectors that have heard anything."""
        arr = self.today if scope == "today" else self.all
        step = 360 / self.BINS
        return [(i * step + step / 2, v) for i, v in enumerate(arr) if v > 0]

    def summary(self, scope="today"):
        arr = self.today if scope == "today" else self.all
        heard = sum(1 for v in arr if v > 0)
        if not heard:
            return ""
        i = max(range(self.BINS), key=lambda j: arr[j])
        return "max %.0f nm @ %03d°  ·  %d/%d sectors" % (arr[i], i * 10 + 5, heard, self.BINS)

    def to_json(self):
        return {"all": self.all, "today": self.today, "date": self.date}
