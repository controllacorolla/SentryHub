"""Tests for dronewatch — OpenDroneID/ASTM F3411 BLE Remote ID decode, contacts, demo.

The hand-built byte sequences are packed independently (struct), so they verify the decoder's
byte OFFSETS against the opendroneid-core-c layout, not just encode/decode symmetry.
"""
import struct

import dronewatch as D


def _msg(mtype, ver=2):
    b = bytearray(25)
    b[0] = ((mtype & 0xF) << 4) | (ver & 0xF)
    return b


# ---- header + Basic ID --------------------------------------------------------------------
def test_header_nibbles():
    assert D.header(bytes([0x12])) == (1, 2)       # type 1 (Location), proto 2
    assert D.header(bytes([0xF0])) == (0xF, 0)     # message pack


def test_basic_id_offsets():
    b = _msg(D.MSG_BASIC_ID)
    b[1] = (1 << 4) | 2                 # id_type=1 (Serial), ua_type=2 (Multirotor)
    b[2:2 + 7] = b"ABC1234"
    m = D.decode_message(bytes(b))
    assert m["type_name"] == "Basic ID"
    assert m["id_type"] == 1 and m["id_type_name"] == "Serial"
    assert m["ua_type"] == 2 and m["ua_type_name"] == "Multirotor"
    assert m["uas_id"] == "ABC1234"


# ---- Location: exact offsets + scale factors ----------------------------------------------
def test_location_offsets_and_scales():
    b = _msg(D.MSG_LOCATION)
    b[1] = (2 << 4) | (0 << 1) | 0      # status=Airborne, EW=0, speedMult=0
    b[2] = 90                           # direction 90 deg
    b[3] = 40                           # speed = 40 * 0.25 = 10 m/s
    b[4] = 4                            # vspeed = 4 * 0.5 = 2 m/s
    struct.pack_into("<i", b, 5, 397392000)     # lat 39.7392
    struct.pack_into("<i", b, 9, -1049903000)   # lon -104.9903
    struct.pack_into("<H", b, 13, round((120 + 1000) / 0.5))   # baro 120 m
    struct.pack_into("<H", b, 15, round((120 + 1000) / 0.5))   # geo 120 m
    struct.pack_into("<H", b, 17, round((90 + 1000) / 0.5))    # height 90 m
    struct.pack_into("<H", b, 21, 1234)         # timestamp 123.4 s
    m = D.decode_message(bytes(b))
    assert m["status_name"] == "Airborne"
    assert abs(m["lat"] - 39.7392) < 1e-6
    assert abs(m["lon"] - (-104.9903)) < 1e-6
    assert abs(m["alt_geo_m"] - 120.0) < 0.01
    assert abs(m["height_m"] - 90.0) < 0.01
    assert m["direction_deg"] == 90
    assert abs(m["speed_mps"] - 10.0) < 1e-9
    assert abs(m["vspeed_mps"] - 2.0) < 1e-9
    assert abs(m["timestamp_tenths"] - 123.4) < 1e-9


def test_location_ew_direction_and_speed_multiplier():
    b = _msg(D.MSG_LOCATION)
    b[1] = (2 << 4) | (1 << 1) | 1      # EW=1 (adds 180), speedMult=1
    b[2] = 10                           # direction 10 -> 190
    b[3] = 100                          # speed = 100*0.75 + 255*0.25 = 138.75
    m = D.decode_message(bytes(b))
    assert m["direction_deg"] == 190
    assert abs(m["speed_mps"] - (100 * 0.75 + 255 * 0.25)) < 1e-9


def test_location_negative_vspeed_and_invalid_fields():
    b = _msg(D.MSG_LOCATION)
    b[4] = (256 - 6) & 0xFF             # vspeed = -6 * 0.5 = -3 m/s
    struct.pack_into("<H", b, 13, 0)    # altitude 0 -> unknown
    struct.pack_into("<H", b, 21, 0xFFFF)   # invalid timestamp
    b[2] = 200                          # direction > 179 -> invalid
    m = D.decode_message(bytes(b))
    assert abs(m["vspeed_mps"] - (-3.0)) < 1e-9
    assert m["alt_baro_m"] is None
    assert m["timestamp_tenths"] is None
    assert m["direction_deg"] is None


# ---- System: operator position + epoch ----------------------------------------------------
def test_system_offsets_and_epoch():
    b = _msg(D.MSG_SYSTEM)
    b[1] = (0 << 2) | 2                 # classification=0, operator_location_type=2 (Fixed)
    struct.pack_into("<i", b, 2, 397300000)     # op lat 39.73
    struct.pack_into("<i", b, 6, -1049000000)   # op lon -104.9
    struct.pack_into("<H", b, 18, round((1610 + 1000) / 0.5))   # op alt 1610 m
    struct.pack_into("<I", b, 20, 1000)         # ts = epoch + 1000 s
    m = D.decode_message(bytes(b))
    assert m["operator_location_name"] == "Fixed"
    assert abs(m["operator_lat"] - 39.73) < 1e-6
    assert abs(m["operator_lon"] - (-104.9)) < 1e-6
    assert abs(m["operator_alt_m"] - 1610.0) < 0.01
    assert m["timestamp_unix"] == D.SYSTEM_EPOCH + 1000


def test_operator_and_self_id():
    b = _msg(D.MSG_OPERATOR_ID)
    b[2:2 + 9] = b"OP-123456"
    assert D.decode_message(bytes(b))["operator_id"] == "OP-123456"
    b = _msg(D.MSG_SELF_ID)
    b[1] = 1
    b[2:2 + 11] = b"Hello world"
    m = D.decode_message(bytes(b))
    assert m["desc_type_name"] == "Emergency" and m["description"] == "Hello world"


# ---- round-trip, pack, service-data framing -----------------------------------------------
def test_encode_decode_roundtrip_location():
    raw = D.encode_location(39.5, -104.8, alt_geo=200.0, height=150.0, direction=270.0,
                            speed=15.0, vspeed=-1.0, timestamp_tenths=42.0)
    m = D.decode_message(raw)
    assert abs(m["lat"] - 39.5) < 1e-6 and abs(m["lon"] - (-104.8)) < 1e-6
    assert abs(m["alt_geo_m"] - 200.0) < 0.5 and abs(m["height_m"] - 150.0) < 0.5
    assert m["direction_deg"] == 270 and abs(m["speed_mps"] - 15.0) < 0.3
    assert abs(m["vspeed_mps"] - (-1.0)) < 1e-9


def test_pack_decode():
    pack = D.encode_pack([D.encode_basic_id("UAS-1"), D.encode_location(39.6, -104.9)])
    msgs = D.decode_pack(pack)
    assert [m["type"] for m in msgs] == [D.MSG_BASIC_ID, D.MSG_LOCATION]
    assert msgs[0]["uas_id"] == "UAS-1"


def test_service_data_framing_single_and_pack():
    one = D.service_data(D.encode_basic_id("UAS-2"))
    assert one[0] == D.ODID_AD_APP_CODE
    msgs = D.decode_service_data(one)
    assert msgs[0]["uas_id"] == "UAS-2"
    pk = D.service_data(D.encode_pack([D.encode_basic_id("UAS-3"), D.encode_self_id("hi")]))
    out = D.decode_service_data(pk)
    assert {m["type"] for m in out} == {D.MSG_BASIC_ID, D.MSG_SELF_ID}


# ---- contact model ------------------------------------------------------------------------
def test_drones_ingest_merges_and_flags_new():
    seen = []
    d = D.Drones()
    d.on_new = lambda c: seen.append(c["addr"])
    basic = D.decode_message(D.encode_basic_id("UAS-X", ua_type=2))
    loc = D.decode_message(D.encode_location(39.6, -104.9, alt_geo=100.0))
    assert d.ingest("AA:01", [basic], now=1000.0) is True
    assert d.ingest("AA:01", [loc], now=1001.0) is False
    c = d.by_addr["AA:01"]
    assert c["uas_id"] == "UAS-X" and c["loc"]["lat"] and len(c["trail"]) == 1
    assert seen == ["AA:01"]


def test_drones_fusion_contact_shape():
    d = D.Drones()
    d.ingest("AA:02", [D.decode_message(D.encode_basic_id("UAS-Y"))], now=10.0)
    d.ingest("AA:02", [D.decode_message(D.encode_location(39.7, -104.8, alt_geo=130.0))], now=11.0)
    d.ingest("AA:02", [D.decode_message(D.encode_system(39.72, -104.81))], now=12.0)
    fc = d.fusion_contacts(now=12.0)[0]
    assert fc["source"] == "dronewatch" and fc["id"] == "UAS-Y" and fc["type"] == "drone"
    assert fc["lat"] and fc["operator_lat"] and fc["timestamp"] == 12.0


def test_drones_aging():
    d = D.Drones(stale_s=30, drop_s=60)
    d.ingest("AA:03", [D.decode_message(D.encode_basic_id("UAS-Z"))], now=0.0)
    assert len(d.active(now=10.0)) == 1
    assert len(d.active(now=100.0)) == 0      # stale
    d.prune(now=100.0)
    assert "AA:03" not in d.by_addr           # dropped


# ---- demo ---------------------------------------------------------------------------------
def test_demo_emits_decodable_full_message_set():
    demo = D.Demo({"lat": 39.62, "lon": -104.87})
    adverts = demo.adverts(now=demo.t0 + 5)        # drone 2 not yet present (appears at t=10)
    assert any(a[0] == "AA:BB:CC:00:00:01" for a in adverts)
    addr, payload, rssi = adverts[0]
    msgs = D.decode_service_data(payload)
    types = {m["type"] for m in msgs}
    assert {D.MSG_BASIC_ID, D.MSG_LOCATION, D.MSG_SYSTEM, D.MSG_OPERATOR_ID, D.MSG_SELF_ID} <= types


def test_demo_second_drone_ages_in_and_out():
    demo = D.Demo({"lat": 39.62, "lon": -104.87})
    present = any(a[0] == "AA:BB:CC:00:00:02" for a in demo.adverts(now=demo.t0 + 20))
    absent = any(a[0] == "AA:BB:CC:00:00:02" for a in demo.adverts(now=demo.t0 + 50))
    assert present and not absent
