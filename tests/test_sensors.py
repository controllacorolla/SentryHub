import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sensors as SN


def test_parse_report_valid():
    ln = json.dumps({"model": "Acurite-5n1", "id": 2847, "temperature_C": 11.5,
                     "humidity": 40})
    key, title, r = SN.parse_report(ln)
    assert key == "Acurite-5n1/2847" and "2847" in title and r["humidity"] == 40


def test_parse_report_junk():
    assert SN.parse_report("not json") is None
    assert SN.parse_report('{"no_model": 1}') is None
    assert SN.parse_report('[1,2,3]') is None


def test_parse_report_no_id():
    key, title, r = SN.parse_report(json.dumps({"model": "Schrader"}))
    assert key == "Schrader/?" and title == "Schrader"


def test_primary_reading_prefers_temp():
    assert SN.primary_reading({"temperature_C": 0.0}) == "32.0°F"
    assert SN.primary_reading({"pressure_kPa": 220.0}).endswith("psi")
    assert SN.primary_reading({"humidity": 55}) == "55%"
    assert SN.primary_reading({}) == "signal"


def test_field_formats():
    f = dict((k, fn) for k, _l, fn in SN.FIELDS)
    assert f["temperature_C"](20.0) == "68.0°F  (20.0°C)"
    assert f["pressure_kPa"](220.0).startswith("31.9")
    assert f["battery_ok"](0) == "LOW"
    assert f["rain_mm"](25.4) == "1.00 in"


def test_demo_report_parses():
    for _ in range(20):
        rep = SN.parse_report(SN.demo_report(time.time()))
        assert rep is not None
        key, title, r = rep
        assert "model" in r and "/" in key


def test_rtl433_cmd():
    c = SN.rtl433_cmd("433.92M", 0)
    assert "rtl_433" in c and "json" in c and "-g" not in c
    assert "-g" in SN.rtl433_cmd("915M", 30)


def test_prune_devices_caps_and_keeps_selected():
    devs = {("d%d" % i): {"t": i, "title": "x", "last": {}, "n": 1, "hist": []}
            for i in range(500)}
    SN.prune_devices(devs, sel="d0", cap=400)
    assert len(devs) <= 400
    assert "d0" in devs            # selected survives even though it's oldest
    assert "d499" in devs          # newest survives


def test_rtl433_cmd_hop_cycles_all_bands():
    c = SN.rtl433_cmd("hop", 0)
    assert [c[i + 1] for i, a in enumerate(c) if a == "-f"] == list(SN.HOP_FREQS)
    assert c[c.index("-H") + 1] == str(SN.HOP_SECS)
    assert "hop" not in c
