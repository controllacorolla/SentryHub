"""Tests for the CAN / automotive module (pen-test).

Decode tables verified against SAE J1979 (OBD-II mode 01) and ISO 14229 (UDS). Passive decode is
ungated; every transmit onto the bus must pass the engagement gate.
"""
import pytest

import canbus as C
import engagement as E


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_parse_standard_frame():
    f = C.parse_candump("  can0  7E8   [8]  04 41 0C 1A F8 00 00 00")
    assert f["id"] == 0x7E8 and f["dlc"] == 8 and not f["ext"]
    assert f["data"] == bytes([0x04, 0x41, 0x0C, 0x1A, 0xF8, 0, 0, 0])


def test_parse_extended_and_timestamped():
    f = C.parse_candump("(1700000000.123456)  can0  18DAF110   [3]  02 10 01")
    assert f["id"] == 0x18DAF110 and f["ext"] and f["dlc"] == 3


def test_parse_hash_format_and_rtr():
    assert C.parse_candump("  can0  123#DEADBEEF")["data"] == bytes([0xDE, 0xAD, 0xBE, 0xEF])
    assert C.parse_candump("  can0  200#R")["rtr"] is True
    assert C.parse_candump("   ") is None and C.parse_candump("garbage") is None


def test_obd_rpm_speed_decode():
    # RPM = ((A<<8)+B)/4; 0x1AF8 -> 6904/4 = 1726 rpm
    f = C.parse_candump("  can0  7E8   [8]  04 41 0C 1A F8 00 00 00")
    d = C.decode_obd(f)
    assert d["kind"] == "obd_response" and d["name"] == "rpm" and abs(d["value"] - 1726.0) < 1e-6
    # speed = A km/h
    s = C.decode_obd(C.parse_candump("  can0  7E8   [8]  03 41 0D 50 00 00 00 00"))
    assert s["name"] == "speed" and s["value"] == 80.0 and s["ecu"] == 0


def test_obd_request_and_coolant():
    req = C.decode_obd(C.parse_candump("  can0  7DF   [8]  02 01 0C 00 00 00 00 00"))
    assert req["kind"] == "obd_request" and req["pid"] == 0x0C and req["name"] == "rpm"
    cool = C.decode_obd(C.parse_candump("  can0  7E8   [8]  03 41 05 5A 00 00 00 00"))
    assert cool["name"] == "coolant_temp" and cool["value"] == 0x5A - 40  # 90 - 40 = 50 C


def test_uds_request_positive_negative():
    req = C.decode_uds(C.parse_candump("  can0  7E0   [8]  02 10 03 00 00 00 00 00"))
    assert req["kind"] == "uds_request" and req["service"] == "DiagnosticSessionControl"
    pos = C.decode_uds(C.parse_candump("  can0  7E8   [8]  06 50 03 00 32 01 F4 00"))
    assert pos["kind"] == "uds_positive" and pos["service"] == "DiagnosticSessionControl"
    neg = C.decode_uds(C.parse_candump("  can0  7E8   [8]  03 7F 22 31 00 00 00 00"))
    assert neg["kind"] == "uds_negative" and neg["nrc"] == "requestOutOfRange"
    assert neg["service"] == "ReadDataByIdentifier"


def test_uds_write_flag():
    # SecurityAccess (0x27) and WriteDataByIdentifier (0x2E) are state-changing
    assert C.decode_uds(C.parse_candump("  can0  7E0   [3]  02 27 01"))["writes"] is True
    assert C.decode_uds(C.parse_candump("  can0  7E0   [3]  03 2E F1 90 AA"))["writes"] is True
    rd = C.decode_uds(C.parse_candump("  can0  7E0   [8]  03 22 F1 90 00 00 00 00"))
    assert rd["service"] == "ReadDataByIdentifier" and rd["writes"] is False


def test_bus_model_counts_period_and_changed_bytes():
    bus = C.Bus()
    bus.feed(C.parse_candump("  can0  3B2   [2]  00 10"), 0.0)
    bus.feed(C.parse_candump("  can0  3B2   [2]  01 10"), 0.1)
    bus.feed(C.parse_candump("  can0  3B2   [2]  02 10"), 0.2)
    row = bus.rows()[0]
    assert row["count"] == 3 and row["changed"] == [0]       # only byte 0 moved
    assert abs(row["period_ms"] - 100.0) < 1e-6


def test_cansend_argv_std_and_ext():
    assert C.cansend_argv("can0", 0x123, [0xDE, 0xAD]) == ["cansend", "can0", "123#DEAD"]
    assert C.cansend_argv("can0", 0x18DAF110, [0x02, 0x10, 0x01])[2].startswith("18DAF110#")


def test_transmit_is_gated():
    # no engagement -> refused, no argv built
    ok, why, argv = C.prepare_send("can0", 0x7DF, [0x02, 0x01, 0x0C], target="VIN-TESTCAR")
    assert not ok and argv is None and "engagement" in why.lower()
    # open a scoped engagement -> authorized
    E.start("ecu audit", "ROE-9", ["VIN-TESTCAR"], "KD0ABC")
    ok, why, argv = C.prepare_send("can0", 0x7DF, [0x02, 0x01, 0x0C], target="VIN-TESTCAR")
    assert ok and argv == ["cansend", "can0", "7DF#02010C"]
    # out of scope -> refused
    ok, why, argv = C.prepare_send("can0", 0x7DF, [0x02, 0x01, 0x0C], target="VIN-OTHERCAR")
    assert not ok and argv is None


def test_detect_injected():
    assert C.detect(which=lambda n: "/usr/bin/" + n) is True
    assert C.detect(which=lambda n: None) is False


def test_demo_frames_decode():
    dm = C.Demo()
    kinds = {C.decode(C.parse_candump(dm.line()))["kind"] for _ in range(8)}
    assert "obd_response" in kinds and "uds_negative" in kinds
