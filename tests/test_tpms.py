"""Tests for the TPMS analyzer (Phase 6 #12)."""
import tpms


def test_parse_tpms_kpa():
    line = '{"model":"Toyota","type":"TPMS","id":"a1b2","pressure_kPa":230.0,' \
           '"temperature_C":22.0,"battery_ok":1,"rssi":-55}'
    r = tpms.parse_tpms(line)
    assert r["id"] == "a1b2" and r["pressure_kpa"] == 230.0 and r["temp_c"] == 22.0


def test_parse_tpms_psi_converted():
    r = tpms.parse_tpms('{"model":"Ford-TPMS","id":"9","pressure_PSI":32.0}')
    assert abs(r["pressure_kpa"] - 32.0 * 6.89476) < 0.1


def test_parse_non_tpms_ignored():
    assert tpms.parse_tpms('{"model":"Acurite","type":"Temperature","id":"5"}') is None
    assert tpms.parse_tpms("not json") is None


def test_rssi_to_distance_monotonic():
    near = tpms.rssi_to_distance_m(-40)
    far = tpms.rssi_to_distance_m(-80)
    assert near < far and tpms.rssi_to_distance_m(None) is None


def test_vehicles_group_sensors_by_time():
    v = tpms.Vehicles(group_window_s=5)
    for i, sid in enumerate(["t1", "t2", "t3", "t4"]):
        v.add({"id": sid, "pressure_kpa": 230}, now=100 + i * 0.5)   # 4 tires close together
    v.add({"id": "other", "pressure_kpa": 210}, now=150)             # a different car, later
    groups = v.vehicle_candidates(now=155)                           # all within the 60 s window
    assert ["t1", "t2", "t3", "t4"] in groups
    assert ["other"] in groups
