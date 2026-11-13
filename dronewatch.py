#!/usr/bin/env python3
"""DroneWatch — passive Drone Remote ID detector (OpenDroneID / ASTM F3411-22a, BLE only).

Receive-only. Listens for the Bluetooth broadcasts that drones and their ground stations are
required to send (Remote ID) and shows who is flying, where, and where the operator is standing.
Nothing is transmitted.

This module is the pure decoder + contact model + demo + integration hooks; the Tk workspace
(main) lives at the bottom and is embedded as a tab in the Sky workspace (sky.py).

Byte layouts and scale factors are taken verbatim from the opendroneid-core-c reference
(libopendroneid/opendroneid.h and .c) — NOT guessed. Each ODID message is 25 bytes; bitfields
are little-endian / least-significant-bit first.
"""
import os
import struct
import sys
import time

# ---- constants (opendroneid-core-c) -------------------------------------------------------
ODID_MESSAGE_SIZE = 25
ODID_ID_SIZE = 20
ODID_STR_SIZE = 23
ODID_PACK_MAX_MESSAGES = 9

# ASTM Remote ID carried in a BLE Service Data AD for 16-bit UUID 0xFFFA, with the
# application designator 0x0D, then a 1-byte message counter, then the ODID message(s).
ODID_SERVICE_UUID16 = 0xFFFA
ODID_SERVICE_UUID = "0000fffa-0000-1000-8000-00805f9b34fb"
ODID_AD_APP_CODE = 0x0D

MSG_BASIC_ID = 0
MSG_LOCATION = 1
MSG_AUTH = 2
MSG_SELF_ID = 3
MSG_SYSTEM = 4
MSG_OPERATOR_ID = 5
MSG_PACK = 0xF
MSG_NAMES = {0: "Basic ID", 1: "Location", 2: "Authentication", 3: "Self-ID",
             4: "System", 5: "Operator ID", 0xF: "Message Pack"}

ALT_DIV, ALT_ADDER = 0.5, 1000          # altitude = enc*0.5 - 1000 (metres)
SPEED_DIV = (0.25, 0.75)
VSPEED_DIV = 0.5
LATLON_DIV = 1e7
INV_TIMESTAMP = 0xFFFF
SYSTEM_EPOCH = 1546300800               # 2019-01-01 00:00:00 UTC, Unix seconds

UA_TYPES = {0: "None/Unknown", 1: "Aeroplane", 2: "Multirotor", 3: "Gyroplane",
            4: "Hybrid Lift", 5: "Ornithopter", 6: "Glider", 7: "Kite",
            8: "Free Balloon", 9: "Captive Balloon", 10: "Airship",
            11: "Parachute", 12: "Rocket", 13: "Tethered", 14: "Ground Obstacle",
            15: "Other"}
ID_TYPES = {0: "None", 1: "Serial", 2: "CAA Reg", 3: "UTM UUID", 4: "Session ID"}
OP_STATUS = {0: "Undeclared", 1: "Ground", 2: "Airborne", 3: "Emergency",
             4: "RID Failure"}
DESC_TYPES = {0: "Text", 1: "Emergency", 2: "Ext Status"}
OP_LOC_TYPES = {0: "Takeoff", 1: "Dynamic", 2: "Fixed"}


# ---- low-level helpers --------------------------------------------------------------------
def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _i8(x):
    return x - 256 if x >= 128 else x


def _text(raw):
    """ODID ASCII string field -> clean str (null-terminated, printable only)."""
    s = bytes(raw).split(b"\x00", 1)[0]
    return "".join(c for c in s.decode("ascii", "replace") if 32 <= ord(c) < 127).strip()


def _alt(enc):
    v = enc * ALT_DIV - ALT_ADDER
    return None if enc == 0 else v          # 0 encodes "unknown" (-1000 m sentinel)


def header(b):
    """(message_type, protocol_version) from byte 0."""
    return (b[0] >> 4) & 0x0F, b[0] & 0x0F


# ---- per-message decoders (input: one 25-byte message) ------------------------------------
def decode_basic_id(b):
    idt = (b[1] >> 4) & 0x0F
    uat = b[1] & 0x0F
    return {"id_type": idt, "id_type_name": ID_TYPES.get(idt, "?"),
            "ua_type": uat, "ua_type_name": UA_TYPES.get(uat, "?"),
            "uas_id": _text(b[2:2 + ODID_ID_SIZE])}


def decode_location(b):
    status = (b[1] >> 4) & 0x0F
    height_type = (b[1] >> 2) & 0x01
    ew = (b[1] >> 1) & 0x01
    smult = b[1] & 0x01
    direction = b[2] + (180 if ew else 0)
    direction = None if b[2] > 179 else direction
    speed = (b[3] * SPEED_DIV[1] + 255 * SPEED_DIV[0]) if smult else b[3] * SPEED_DIV[0]
    vspeed = _i8(b[4]) * VSPEED_DIV
    lat = _i32(b, 5) / LATLON_DIV
    lon = _i32(b, 9) / LATLON_DIV
    ts_raw = _u16(b, 21)
    return {"status": status, "status_name": OP_STATUS.get(status, "?"),
            "height_agl_type": "AGL" if height_type else "above-takeoff",
            "lat": lat, "lon": lon,
            "alt_baro_m": _alt(_u16(b, 13)), "alt_geo_m": _alt(_u16(b, 15)),
            "height_m": _alt(_u16(b, 17)),
            "direction_deg": direction, "speed_mps": speed, "vspeed_mps": vspeed,
            "timestamp_tenths": None if ts_raw == INV_TIMESTAMP else ts_raw / 10.0}


def decode_system(b):
    ts = _u32(b, 20)
    return {"operator_location_type": b[1] & 0x03,
            "operator_location_name": OP_LOC_TYPES.get(b[1] & 0x03, "?"),
            "classification_type": (b[1] >> 2) & 0x07,
            "operator_lat": _i32(b, 2) / LATLON_DIV,
            "operator_lon": _i32(b, 6) / LATLON_DIV,
            "area_count": _u16(b, 10), "area_radius_m": b[12] * 10,
            "area_ceiling_m": _alt(_u16(b, 13)), "area_floor_m": _alt(_u16(b, 15)),
            "category_eu": (b[17] >> 4) & 0x0F, "class_eu": b[17] & 0x0F,
            "operator_alt_m": _alt(_u16(b, 18)),
            "timestamp_unix": (SYSTEM_EPOCH + ts) if ts else None}


def decode_operator_id(b):
    return {"operator_id_type": b[1], "operator_id": _text(b[2:2 + ODID_ID_SIZE])}


def decode_self_id(b):
    return {"desc_type": b[1], "desc_type_name": DESC_TYPES.get(b[1], "?"),
            "description": _text(b[2:2 + ODID_STR_SIZE])}


_DECODERS = {MSG_BASIC_ID: decode_basic_id, MSG_LOCATION: decode_location,
             MSG_SYSTEM: decode_system, MSG_OPERATOR_ID: decode_operator_id,
             MSG_SELF_ID: decode_self_id}


def decode_message(b):
    """Decode one 25-byte ODID message to a dict. Returns None if too short."""
    b = bytes(b)
    if len(b) < ODID_MESSAGE_SIZE:
        return None
    mtype, ver = header(b)
    out = {"type": mtype, "type_name": MSG_NAMES.get(mtype, "Unknown"), "proto": ver}
    fn = _DECODERS.get(mtype)
    if fn:
        out.update(fn(b[:ODID_MESSAGE_SIZE]))
    return out


def decode_pack(b):
    """Decode a Message Pack (type 0xF) -> list of message dicts."""
    b = bytes(b)
    if len(b) < 3:
        return []
    size = b[1] or ODID_MESSAGE_SIZE
    count = min(b[2], ODID_PACK_MAX_MESSAGES)
    out = []
    for i in range(count):
        off = 3 + i * size
        if off + ODID_MESSAGE_SIZE <= len(b):
            m = decode_message(b[off:off + ODID_MESSAGE_SIZE])
            if m:
                out.append(m)
    return out


def decode_payload(b):
    """A single message or a pack -> always a list of message dicts."""
    b = bytes(b)
    if not b:
        return []
    mtype, _ = header(b)
    return decode_pack(b) if mtype == MSG_PACK else ([decode_message(b)] if decode_message(b) else [])


def decode_service_data(data):
    """Decode the BLE Service Data (UUID 0xFFFA) payload: optional [0x0D][counter] framing
    followed by an ODID message or pack. Returns a list of message dicts."""
    b = bytes(data)
    if len(b) >= 2 and b[0] == ODID_AD_APP_CODE:
        b = b[2:]                           # strip app code + message counter
    return decode_payload(b)


# ---- encoders (for --demo and round-trip tests; inverse of the decoders) -------------------
def _enc_alt(m):
    if m is None:
        return 0
    return max(0, min(0xFFFF, round((m + ALT_ADDER) / ALT_DIV)))


def _hdr(mtype, ver=2):
    return bytes([((mtype & 0xF) << 4) | (ver & 0xF)])


def encode_basic_id(uas_id, ua_type=2, id_type=1):
    b = bytearray(ODID_MESSAGE_SIZE)
    b[0] = _hdr(MSG_BASIC_ID)[0]
    b[1] = ((id_type & 0xF) << 4) | (ua_type & 0xF)
    raw = uas_id.encode("ascii", "replace")[:ODID_ID_SIZE]
    b[2:2 + len(raw)] = raw
    return bytes(b)


def encode_location(lat, lon, alt_geo=None, height=None, direction=0.0, speed=0.0,
                    vspeed=0.0, status=2, timestamp_tenths=0.0):
    b = bytearray(ODID_MESSAGE_SIZE)
    b[0] = _hdr(MSG_LOCATION)[0]
    ew = 1 if direction >= 180 else 0
    smult = 0 if speed <= 255 * SPEED_DIV[0] else 1
    b[1] = ((status & 0xF) << 4) | (ew << 1) | smult
    b[2] = int(round(direction - 180)) & 0xFF if ew else int(round(direction)) & 0xFF
    b[3] = (round(speed / SPEED_DIV[0]) if not smult
            else min(255, round((speed - 255 * SPEED_DIV[0]) / SPEED_DIV[1]))) & 0xFF
    b[4] = int(round(vspeed / VSPEED_DIV)) & 0xFF
    struct.pack_into("<i", b, 5, int(round(lat * LATLON_DIV)))
    struct.pack_into("<i", b, 9, int(round(lon * LATLON_DIV)))
    struct.pack_into("<H", b, 13, _enc_alt(alt_geo))      # baro (reuse geo)
    struct.pack_into("<H", b, 15, _enc_alt(alt_geo))
    struct.pack_into("<H", b, 17, _enc_alt(height))
    struct.pack_into("<H", b, 21, round(timestamp_tenths * 10) & 0xFFFF)
    return bytes(b)


def encode_system(op_lat, op_lon, op_alt=None, op_loc_type=1, timestamp_unix=None):
    b = bytearray(ODID_MESSAGE_SIZE)
    b[0] = _hdr(MSG_SYSTEM)[0]
    b[1] = op_loc_type & 0x03
    struct.pack_into("<i", b, 2, int(round(op_lat * LATLON_DIV)))
    struct.pack_into("<i", b, 6, int(round(op_lon * LATLON_DIV)))
    struct.pack_into("<H", b, 18, _enc_alt(op_alt))
    struct.pack_into("<I", b, 20, 0 if not timestamp_unix else int(timestamp_unix - SYSTEM_EPOCH))
    return bytes(b)


def encode_operator_id(operator_id, id_type=0):
    b = bytearray(ODID_MESSAGE_SIZE)
    b[0] = _hdr(MSG_OPERATOR_ID)[0]
    b[1] = id_type & 0xFF
    raw = operator_id.encode("ascii", "replace")[:ODID_ID_SIZE]
    b[2:2 + len(raw)] = raw
    return bytes(b)


def encode_self_id(description, desc_type=0):
    b = bytearray(ODID_MESSAGE_SIZE)
    b[0] = _hdr(MSG_SELF_ID)[0]
    b[1] = desc_type & 0xFF
    raw = description.encode("ascii", "replace")[:ODID_STR_SIZE]
    b[2:2 + len(raw)] = raw
    return bytes(b)


def encode_pack(messages):
    b = bytearray(3 + ODID_MESSAGE_SIZE * len(messages))
    b[0] = _hdr(MSG_PACK)[0]
    b[1] = ODID_MESSAGE_SIZE
    b[2] = len(messages)
    for i, m in enumerate(messages):
        b[3 + i * ODID_MESSAGE_SIZE:3 + (i + 1) * ODID_MESSAGE_SIZE] = m
    return bytes(b)


def service_data(payload):
    """Wrap an ODID message/pack in the ASTM BLE service-data framing (app code + counter)."""
    service_data._ctr = (getattr(service_data, "_ctr", 0) + 1) & 0xFF
    return bytes([ODID_AD_APP_CODE, service_data._ctr]) + bytes(payload)


# ---- contact model ------------------------------------------------------------------------
class Drones:
    """Aggregates ODID messages into per-aircraft contacts, keyed by the BLE source address
    (legacy adverts carry one message type each; only Basic ID carries the UAS ID, so messages
    from the same device are tied together by its Bluetooth address). Fusion/alert hooks below."""

    def __init__(self, stale_s=30, drop_s=120, trail_max=200):
        self.by_addr = {}
        self.stale_s = stale_s
        self.drop_s = drop_s
        self.trail_max = trail_max
        self.on_new = None          # callback(contact) on first sight of a new UAS
        self.on_update = None       # callback(contact) on every update (for alert rules)

    def ingest(self, addr, messages, now=None, rssi=None):
        """Feed decoded message dicts (from one advert) for a BLE address. Returns True if this
        is the first time this aircraft is seen."""
        now = time.time() if now is None else now
        is_new = addr not in self.by_addr
        c = self.by_addr.get(addr)
        if c is None:
            c = {"addr": addr, "first": now, "trail": [], "uas_id": None,
                 "ua_type": None, "ua_type_name": None, "loc": None, "sys": None,
                 "operator_id": None, "self_id": None, "rssi": None}
            self.by_addr[addr] = c
        for m in messages:
            t = m.get("type")
            if t == MSG_BASIC_ID:
                if m.get("uas_id"):
                    c["uas_id"] = m["uas_id"]
                c["ua_type"] = m.get("ua_type")
                c["ua_type_name"] = m.get("ua_type_name")
            elif t == MSG_LOCATION:
                c["loc"] = m
                if m.get("lat") or m.get("lon"):
                    c["trail"].append((m["lat"], m["lon"], now))
                    del c["trail"][:-self.trail_max]
            elif t == MSG_SYSTEM:
                c["sys"] = m
            elif t == MSG_OPERATOR_ID:
                c["operator_id"] = m.get("operator_id")
            elif t == MSG_SELF_ID:
                c["self_id"] = m.get("description")
        c["last"] = now
        if rssi is not None:
            c["rssi"] = rssi
        if is_new and self.on_new:
            self.on_new(c)
        if self.on_update:
            self.on_update(c)
        return is_new

    def prune(self, now=None):
        now = time.time() if now is None else now
        for addr in [a for a, c in self.by_addr.items() if now - c["last"] > self.drop_s]:
            del self.by_addr[addr]

    def active(self, now=None):
        now = time.time() if now is None else now
        return [c for c in self.by_addr.values() if now - c["last"] <= self.stale_s]

    def label(self, c):
        return c.get("uas_id") or ("BLE " + str(c["addr"])[-8:])

    def fusion_contact(self, c):
        """Clean, decoder-agnostic contact dict for the Phase 3 fusion engine (the documented
        hook): a single identity with position/altitude/type/timestamp."""
        loc = c.get("loc") or {}
        sys = c.get("sys") or {}
        return {"source": "dronewatch", "id": self.label(c), "uas_id": c.get("uas_id"),
                "ble_addr": c["addr"], "type": "drone", "ua_type": c.get("ua_type_name"),
                "lat": loc.get("lat"), "lon": loc.get("lon"),
                "alt_m": loc.get("alt_geo_m"), "height_m": loc.get("height_m"),
                "speed_mps": loc.get("speed_mps"), "heading_deg": loc.get("direction_deg"),
                "operator_lat": sys.get("operator_lat"), "operator_lon": sys.get("operator_lon"),
                "operator_id": c.get("operator_id"),
                "timestamp": c.get("last"), "rssi": c.get("rssi")}

    def fusion_contacts(self, now=None):
        return [self.fusion_contact(c) for c in self.active(now)]


# ---- demo source --------------------------------------------------------------------------
class Demo:
    """Synthetic Remote ID traffic so the tab works with no Bluetooth adapter: one drone flying
    a racetrack around home with its operator parked nearby, plus a second drone that appears
    then disappears (to exercise contact aging). Emits (addr, payload_bytes, rssi) adverts."""

    def __init__(self, home):
        self.home = home
        self.t0 = time.time()

    def _racetrack(self, lat0, lon0, t, r_nm=0.4, period=40.0):
        import math
        a = (t % period) / period * 2 * math.pi
        dlat = (r_nm / 60.0) * math.sin(a)
        dlon = (r_nm / 60.0) * math.cos(a) / max(0.2, math.cos(math.radians(lat0)))
        hdg = (math.degrees(a) + 90) % 360
        return lat0 + dlat, lon0 + dlon, hdg

    def adverts(self, now=None):
        now = time.time() if now is None else now
        t = now - self.t0
        la, lo = self.home["lat"], self.home["lon"]
        out = []
        # Drone 1: always present, full set of message types (as a BT5 message pack).
        d1_lat, d1_lon, hdg = self._racetrack(la, lo, t)
        op_lat, op_lon = la + 0.002, lo - 0.001           # operator parked, offset from drone
        pack = encode_pack([
            encode_basic_id("DEMO-SERIAL-0001", ua_type=2, id_type=1),
            encode_location(d1_lat, d1_lon, alt_geo=120.0, height=90.0, direction=hdg,
                            speed=12.0, vspeed=0.5, status=2, timestamp_tenths=(t % 3600) % 60),
            encode_system(op_lat, op_lon, op_alt=1610.0, op_loc_type=1,
                          timestamp_unix=now),
            encode_operator_id("FAA-OP-DEMO-12345"),
            encode_self_id("Mapping survey - demo"),
        ])
        out.append(("AA:BB:CC:00:00:01", service_data(pack), -58))
        # Drone 2: appears t=10..40s then goes away, as separate legacy adverts (one msg each).
        if 10 <= (t % 80) < 40:
            d2_lat, d2_lon, h2 = self._racetrack(la + 0.01, lo + 0.01, t, r_nm=0.2, period=25)
            out.append(("AA:BB:CC:00:00:02", service_data(encode_basic_id("DEMO-QUAD-0002",
                       ua_type=2, id_type=1)), -72))
            out.append(("AA:BB:CC:00:00:02", service_data(encode_location(
                d2_lat, d2_lon, alt_geo=60.0, height=55.0, direction=h2, speed=6.0,
                vspeed=0.0, timestamp_tenths=(t % 60))), -72))
        return out


# ======================================================================================
# Tk workspace — embedded as a tab in the Sky workspace (sky.py), or standalone.
# suite/tiles/bleak are imported lazily inside main() so the decoder stays light to import.
# DroneWatch uses the Bluetooth adapter, NOT the SDR, so it takes no RtlLease.
# ======================================================================================
DEFAULTS = {"home": {"lat": 39.62, "lon": -104.87}, "range_nm": 1.0,
            "alert_floor_m": None, "speak": True}

UA_GLYPH = {1: "✈", 2: "✦", 3: "✦", 6: "◇", 8: "○", 9: "○", 10: "⬯", 12: "▲"}


def main(parent=None):
    import queue
    import threading
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    import skyintel as SI
    if parent is None:
        S.single_instance("DroneWatch")
    s, spath = S.settings("dronewatch", DEFAULTS)
    root, F = S.make_root("DroneWatch", parent=parent)
    import tkinter as tk
    T = S.T
    home = dict(s.get("home") or DEFAULTS["home"])
    slog = S.SessionLog("dronewatch")

    import importlib.util
    have_bleak = importlib.util.find_spec("bleak") is not None
    demo = ("--demo" in sys.argv) or not have_bleak

    q = queue.Queue()
    drones = Drones()
    st = {"on": False, "gen": 0, "sel": None, "status": "Idle", "last": 0.0}

    import alerts as _alerts            # Phase 3c/3d: alert + fusion engines wired in
    import fusion as _fusion
    alert_engine = _alerts.AlertEngine()
    fusion_engine = _fusion.FusionEngine()

    def deliver_alert(a):
        st["status"] = "⚠ " + a["text"]
        try:
            status.config(text=st["status"], fg=S.AMBER)
        except Exception:
            pass
        if "speak" in a.get("delivery", []) and s.get("speak", True):
            try:
                S.notify("DroneWatch", a["text"])
            except Exception:
                pass
    alert_engine.deliver = deliver_alert
    alert_engine.add_rule({"id": "new", "name": "Drone detected", "type": "presence",
                           "params": {"match": {"type": "drone"}}, "delivery": ["banner", "speak"]})
    _floor = s.get("alert_floor_m")
    if _floor:
        alert_engine.add_rule({"id": "low", "name": "Drone below %d m" % _floor,
                               "type": "threshold", "delivery": ["banner"],
                               "params": {"field": "alt_m", "op": "<", "value": _floor}})

    def announce(c):
        slog.event("dronewatch", "Drone %s" % drones.label(c), id=c["addr"])

    def feed_engines(c):
        ev = drones.fusion_contact(c)       # the documented fusion hook
        ev["type"] = "drone"
        ev["ts"] = time.time()
        fusion_engine.submit(ev)
        alert_engine.feed(ev)               # the documented alert hook
    drones.on_new = announce
    drones.on_update = feed_engines

    top = S.top_bar(root, F, "DroneWatch", "Remote ID · BLE · receive-only")
    state_pill = S.pill(top, F, "Off")

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    left = tk.Frame(body, bg=T.SURFACE, width=T.px(470))
    left.pack(side="left", fill="y")
    left.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    lp = tk.Frame(left, bg=T.SURFACE)
    lp.pack(fill="both", expand=True, padx=T.px(14), pady=T.px(10))
    T.section(lp, F, "Contacts").pack(fill="x")
    lst = tk.Text(lp, bg=T.SURFACE, fg=T.TXT_2, font=F["mono"], bd=0, highlightthickness=0,
                  height=10, wrap="none", state="disabled", cursor="arrow")
    lst.tag_config("hdr", foreground=T.TXT_3)
    lst.tag_config("pick", foreground=S.AMBER)
    lst.pack(fill="x", pady=(T.px(4), 0))
    T.section(lp, F, "Detail").pack(fill="x", pady=(T.px(8), 0))
    d_title = tk.Label(lp, text="—", font=F["now"], fg=S.TXT, bg=T.SURFACE, anchor="w")
    d_title.pack(fill="x")
    d_body = tk.Label(lp, text="tap a contact", font=F["mono"], fg=T.TXT_2, bg=T.SURFACE,
                      anchor="nw", justify="left", wraplength=T.px(440))
    d_body.pack(fill="x", pady=(T.px(4), 0))
    status = tk.Label(lp, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE, anchor="w",
                      justify="left", wraplength=T.px(440))
    status.pack(fill="x", side="bottom")

    right = tk.Frame(body, bg=S.MAPBG)
    right.pack(side="left", fill="both", expand=True)
    mapcv = tk.Canvas(right, bg=S.MAPBG, highlightthickness=0)
    mapcv.pack(fill="both", expand=True)
    hits = []

    def draw_map():
        cv = mapcv
        cv.delete("all")
        hits.clear()
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50:
            return
        import math
        nm_r = float(s.get("range_nm") or 1.0)
        k = (min(w, h) / 2 - 20) / nm_r
        cx, cy = w / 2, h / 2

        def xy(lat, lon):
            d = SI.dist_nm(home["lat"], home["lon"], lat, lon)
            b = math.radians(SI.bearing_deg(home["lat"], home["lon"], lat, lon))
            return cx + d * k * math.sin(b), cy - d * k * math.cos(b)
        for ring in (nm_r / 3, nm_r * 2 / 3, nm_r):
            r = ring * k
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=T.night("#1f2a31"))
            cv.create_text(cx + 4, cy - r + 10, text="%.2f nm" % ring, anchor="w",
                           fill=T.TXT_3, font=F["map"])
        cv.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3, fill=S.GREEN, outline="")
        now = time.time()
        for c in sorted(drones.active(now), key=lambda c: c["last"]):
            loc, sysm = c.get("loc") or {}, c.get("sys") or {}
            sel = c["addr"] == st["sel"]
            col = S.AMBER if sel else T.night("#c8b6ff")
            if loc.get("lat") or loc.get("lon"):
                x, y = xy(loc["lat"], loc["lon"])
                trail = [v for la, lo, _ in c["trail"][-80:] for v in xy(la, lo)]
                if len(trail) >= 4:
                    cv.create_line(*trail, fill=col, width=2 if sel else 1)
                if sysm.get("operator_lat"):
                    ox, oy = xy(sysm["operator_lat"], sysm["operator_lon"])
                    cv.create_line(x, y, ox, oy, fill=T.night("#5ec4d4"), dash=(2, 3))
                    cv.create_rectangle(ox - 4, oy - 4, ox + 4, oy + 4,
                                        outline=T.night("#5ec4d4"), width=2)
                    cv.create_text(ox + 7, oy, text="OP", anchor="w", fill=T.night("#5ec4d4"),
                                   font=F["map"])
                g = UA_GLYPH.get(c.get("ua_type"), "✦")
                cv.create_text(x, y, text=g, fill=col, font=F["now"])
                cv.create_text(x + 9, y, text=drones.label(c), anchor="w",
                               fill=S.TXT if sel else col, font=F["map"])
                hits.append((x, y, c["addr"]))
        if not drones.active(now):
            cv.create_text(w / 2, h / 2 + 40, fill=T.TXT_3, font=F["sm"],
                           text="Scanning for Remote ID…" if st["on"] else "Press Scan.")

    def fmt_m(v, unit="m"):
        return "—" if v is None else "%d %s" % (round(v), unit)

    def rows(now):
        out = []
        for c in sorted(drones.active(now), key=lambda c: -c["last"]):
            loc = c.get("loc") or {}
            d = "—"
            if loc.get("lat") or loc.get("lon"):
                d = "%.2f" % SI.dist_nm(home["lat"], home["lon"], loc["lat"], loc["lon"])
            out.append((c, d, loc))
        return out

    def render():
        now = time.time()
        lst.config(state="normal")
        lst.delete("1.0", "end")
        lst.insert("end", "%-16s %-9s %5s %5s\n" % ("ID", "TYPE", "nm", "alt"), "hdr")
        for i, (c, d, loc) in enumerate(rows(now)):
            tag = "r%d" % i
            alt = loc.get("alt_geo_m")
            lst.insert("end", "%-16s %-9s %5s %5s\n" % (
                drones.label(c)[:16], (c.get("ua_type_name") or "?")[:9], d,
                "—" if alt is None else str(round(alt))),
                (tag, "pick" if c["addr"] == st["sel"] else ""))
            lst.tag_bind(tag, "<Button-1>", lambda e, a=c["addr"]: pick(a))
        lst.config(state="disabled")
        detail()
        draw_map()
        status.config(text="%d active · %s · updated %s" % (
            len(drones.active(now)), st["status"],
            time.strftime("%H:%M:%S", time.localtime(st["last"])) if st["last"] else "—"))

    def detail():
        c = drones.by_addr.get(st["sel"])
        if not c:
            d_title.config(text="—")
            d_body.config(text="tap a contact")
            return
        loc, sysm = c.get("loc") or {}, c.get("sys") or {}
        d_title.config(text=drones.label(c))
        now = time.time()
        lines = ["%s · %s" % (c.get("ua_type_name") or "?", c.get("addr")),
                 "seen %ds · first %ds ago · RSSI %s" % (
                     round(now - c["last"]), round(now - c["first"]),
                     "—" if c.get("rssi") is None else c["rssi"])]
        if loc.get("lat") or loc.get("lon"):
            lines.append("%.5f, %.5f  %s" % (loc["lat"], loc["lon"], loc.get("status_name", "")))
            lines.append("alt %s MSL · %s AGL · %s · %s" % (
                fmt_m(loc.get("alt_geo_m")), fmt_m(loc.get("height_m")),
                "—" if loc.get("speed_mps") is None else "%.1f m/s" % loc["speed_mps"],
                "—" if loc.get("direction_deg") is None else "%03d°" % loc["direction_deg"]))
            lines.append("vspeed %s" % ("—" if loc.get("vspeed_mps") is None
                                        else "%+.1f m/s" % loc["vspeed_mps"]))
        if c.get("operator_id"):
            lines.append("operator %s" % c["operator_id"])
        if sysm.get("operator_lat"):
            lines.append("operator @ %.5f, %.5f  (%s)" % (
                sysm["operator_lat"], sysm["operator_lon"], sysm.get("operator_location_name", "")))
        if c.get("self_id"):
            lines.append("“%s”" % c["self_id"])
        d_body.config(text="\n".join(lines))

    def pick(addr):
        st["sel"] = addr
        render()

    def on_map_click(e):
        best = min(hits, key=lambda t: (t[0] - e.x) ** 2 + (t[1] - e.y) ** 2, default=None)
        if best and (best[0] - e.x) ** 2 + (best[1] - e.y) ** 2 < 25 ** 2:
            pick(best[2])
    mapcv.bind("<Button-1>", on_map_click)
    mapcv.bind("<Configure>", lambda e: draw_map())

    def worker_demo(gen):
        dm = Demo(home)
        while st["on"] and st["gen"] == gen:
            for addr, payload, rssi in dm.adverts():
                q.put((addr, payload, rssi))
            time.sleep(1.0)

    def worker_ble(gen):
        import asyncio
        from bleak import BleakScanner

        async def run():
            def cb(dev, adv):
                sd = getattr(adv, "service_data", None) or {}
                p = sd.get(ODID_SERVICE_UUID)
                if p:
                    q.put((dev.address, bytes(p), getattr(adv, "rssi", None)))
            scanner = BleakScanner(detection_callback=cb)
            await scanner.start()
            try:
                while st["on"] and st["gen"] == gen:
                    await asyncio.sleep(0.5)
            finally:
                await scanner.stop()
        try:
            asyncio.run(run())
        except Exception as e:
            q.put(("__error__", repr(e), None))

    def start():
        if st["on"]:
            return
        st["gen"] += 1
        st["on"] = True
        st["status"] = "Demo" if demo else "Scanning"
        state_pill.config(text=st["status"], bg=S.GREEN)
        T.set_btn(scan_btn, "Stop", kind="danger")
        threading.Thread(target=worker_demo if demo else worker_ble,
                         args=(st["gen"],), daemon=True).start()

    def stop():
        st["on"] = False
        st["gen"] += 1
        st["status"] = "Off"
        state_pill.config(text="Off", bg=S.DIM)
        T.set_btn(scan_btn, "Scan", kind="primary")

    def toggle(_=None):
        stop() if st["on"] else start()

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    scan_btn = S.btn(bar, "Scan", toggle, F, padx=14, pady=5, kind="primary")
    scan_btn.pack(side="left", padx=(10, 6), pady=6)
    S.btn(bar, "−", lambda: zoom(1.5), F, padx=10, pady=5, kind="ghost").pack(side="left", padx=(12, 1))
    S.btn(bar, "+", lambda: zoom(1 / 1.5), F, padx=10, pady=5, kind="ghost").pack(side="left")
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))
    root.bind("<space>", toggle)

    def zoom(f):
        s["range_nm"] = max(0.1, min(10, round(float(s.get("range_nm") or 1.0) * f, 2)))
        draw_map()

    def pump():
        changed = False
        try:
            for _ in range(500):
                addr, payload, rssi = q.get_nowait()
                if addr == "__error__":
                    st["status"] = "BLE error"
                    status.config(text="Bluetooth scan failed: %s" % str(payload)[:80])
                    continue
                msgs = decode_service_data(payload)
                if msgs:
                    drones.ingest(addr, msgs, rssi=rssi)
                    st["last"] = time.time()
                    changed = True
        except queue.Empty:
            pass
        except Exception as e:
            print("dronewatch pump: %r" % e, file=sys.stderr)
        if changed:
            render()
        root.after(400, pump)

    def tick():
        drones.prune()
        fusion_engine.prune()
        render()
        root.after(3000, tick)

    def on_close():
        stop()
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()

    S.bind_quit(root, on_close)
    if demo and not have_bleak and "--demo" not in sys.argv:
        status.config(text="bleak not installed — showing demo. Install: pip install bleak")
    render()
    pump()
    root.after(3000, tick)
    if "--demo" in sys.argv or "--scan" in sys.argv:
        root.after(300, start)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
