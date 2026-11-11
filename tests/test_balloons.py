import configparser
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import balloons as B  # noqa: E402

EX = os.path.join(os.path.dirname(__file__), "fixtures", "auto_rx_station.cfg.example")
HOME = {"lat": 39.62, "lon": -104.87, "alt_m": 1750}
ARX = "/tmp/arx_src/radiosonde_auto_rx/auto_rx"


def cfg(**kw):
    s = dict(B.DEFAULTS, **kw)
    cp = configparser.RawConfigParser()
    cp.read_string(B.make_station_cfg(open(EX).read(), HOME, s))
    return cp


def test_safe_defaults_override_auto_rx_defaults():
    cp = cfg()
    assert cp.get("web", "web_host") == "127.0.0.1"
    assert cp.get("oziplotter", "payload_summary_host") == "127.0.0.1"
    assert cp.getint("oziplotter", "payload_summary_port") == B.SUMMARY_PORT
    assert cp.getboolean("sondehub", "sondehub_enabled") is False
    assert cp.getboolean("habitat", "upload_listener_position") is False
    assert cp.getboolean("aprs", "aprs_enabled") is False
    assert cp.getboolean("web", "web_control") is False
    assert float(cp.get("search_params", "max_freq")) == 406.0
    assert float(cp.get("location", "station_lat")) == pytest.approx(39.62)


def test_upload_needs_callsign():
    assert cfg(upload=True, callsign="")["sondehub"]["sondehub_enabled"] == "False"
    cp = cfg(upload=True, callsign="KD0ABC")
    assert cp.getboolean("sondehub", "sondehub_enabled") is True
    assert cp.get("habitat", "uploader_callsign") == "KD0ABC"


@pytest.mark.skipif(not os.path.isdir(ARX), reason="auto_rx source not available")
def test_real_auto_rx_parses_our_config(tmp_path):
    sys.path.insert(0, ARX)
    try:
        from autorx.config import read_auto_rx_config
    except Exception as e:      # missing optional deps in the test env
        pytest.skip("autorx import: %r" % e)
    p = tmp_path / "station.cfg"
    p.write_text(B.make_station_cfg(open(EX).read(), HOME, dict(B.DEFAULTS)))
    c = read_auto_rx_config(str(p), no_sdr_test=True)
    assert c, "auto_rx rejected the generated config"
    assert c["web_host"] == "127.0.0.1"
    assert c["sondehub_enabled"] is False
    assert c["payload_summary_host"] == "127.0.0.1"


def summary(**kw):
    p = {"type": "PAYLOAD_SUMMARY", "station": "x", "callsign": "LMS6-123456",
         "latitude": 39.75, "longitude": -104.87, "altitude": 3000.0, "speed": 36.0,
         "heading": 90.0, "time": "12:00:00", "comment": "Radiosonde", "model": "LMS6",
         "freq": "403.0000 MHz", "temp": -12.5, "humidity": -1, "pressure": -1.0,
         "vel_v": 5.0, "batt": -1}
    p.update(kw)
    return json.dumps(p).encode()


def test_parse_summary():
    t = B.parse_summary(summary())
    assert t["id"] == "LMS6-123456" and t["model"] == "LMS6"
    assert t["vel_h"] == pytest.approx(10.0)          # 36 km/h
    assert "humidity" not in t and "batt" not in t      # -1 = unknown
    assert t["temp"] == -12.5
    assert B.parse_summary(summary(temp=-273.0)).get("temp") is None


@pytest.mark.parametrize("bad", [b"", b"not json", b"[]", b'{"type":"OTHER"}',
                                 summary(latitude="NaN"), summary(latitude=95),
                                 summary(callsign=""), summary(altitude=1e9),
                                 b"\xff\xfe\x00"])
def test_parse_summary_rejects(bad):
    assert B.parse_summary(bad) is None


def test_tracker_flight_lifecycle(tmp_path):
    trk = B.SondeTracker()
    t0 = 1_000_000.0
    alt = 1700.0
    for i in range(400):                               # ascent at 5 m/s, 10 s steps
        alt += 50
        trk.add(B.parse_summary(summary(altitude=alt, latitude=39.75 + i * 1e-4)), now=t0 + i * 10)
    f = trk.s["LMS6-123456"]
    assert trk.phase(f, now=t0 + 3990) == "ascending" and f["burst"] is None
    peak = alt
    for i in range(400, 420):                          # burst: falling at 30 m/s
        alt -= 300
        trk.add(B.parse_summary(summary(altitude=alt, vel_v=-30.0)), now=t0 + i * 10)
    assert f["burst"]["alt"] == pytest.approx(peak)
    assert trk.phase(f, now=t0 + 4190) == "descending"
    land = trk.landing(f)
    assert land and land["secs"] > 0 and land["lon"] > f["lon"]   # drifting east
    assert trk.phase(f, now=t0 + 4190 + 600) == "lost"
    p = tmp_path / "s.json"
    trk.dump(str(p), now=t0 + 4200)
    d = json.load(open(p))
    assert d["sondes"][0]["id"] == "LMS6-123456" and d["sondes"][0]["phase"] == "descending"


def test_next_launch():
    base = 1_700_000_000 - (1_700_000_000 % 86400)     # 00:00 UTC
    assert B.next_launch(base) == 11 * 3600
    assert B.next_launch(base + 12 * 3600) == 11 * 3600
    assert B.next_launch(base + 23 * 3600 + 1) == 12 * 3600 - 1
