"""Field computer: geo math, track stats, GPX, rise/set (all pure)."""
import calendar
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fieldcomp as FC   # noqa: E402


def test_haversine_and_bearing():
    # one degree of latitude is ~111 km
    assert abs(FC.haversine(0, 0, 1, 0) - 111195) < 200
    assert abs(FC.haversine(39.74, -104.99, 39.74, -104.99)) < 0.01
    assert abs(FC.bearing(0, 0, 1, 0) - 0) < 0.1       # due north
    assert abs(FC.bearing(0, 0, 0, 1) - 90) < 0.1      # due east


def test_track_stats():
    pts = [(0, 39.7400, -104.99, 1600, None),
           (10, 39.7410, -104.99, 1610, 2.0),
           (20, 39.7420, -104.99, 1605, 3.0),
           (300, 39.7420, -104.99, 1605, 0.0)]         # a 280 s stop at the end
    st = FC.track_stats(pts)
    assert st["points"] == 4
    assert st["duration_s"] == 300
    assert 200 < st["distance_m"] < 260               # ~2 x 111 m
    assert st["moving_s"] == 20                        # the stop doesn't count
    assert st["max_speed"] == 3.0
    assert round(st["gain_m"]) == 10 and round(st["loss_m"]) == 5
    assert FC.track_stats([]) == {"points": 0, "distance_m": 0.0, "duration_s": 0.0,
                                  "moving_s": 0.0, "max_speed": 0.0, "gain_m": 0.0, "loss_m": 0.0}
    assert FC.track_stats([(0, 1, 2, 3, None)])["points"] == 1


def test_formatters():
    assert FC.fmt_dist(450) == "450 m" and FC.fmt_dist(1500) == "1.50 km"
    assert FC.fmt_dur(65) == "1:05" and FC.fmt_dur(3661) == "1:01:01"
    assert FC.fmt_latlon(39.74267, -104.9912) == "39.74267, -104.99120"


def test_gpx_is_valid_xml_with_track_and_waypoints():
    import xml.dom.minidom as md
    pts = [(1731000000, 39.74, -104.99, 1600.0, None),
           (1731000010, 39.741, -104.99, 1610.0, 2.0)]
    wpts = [{"lat": 39.742, "lon": -104.991, "alt": 1620.0, "name": "camp & rest"}]
    gpx = FC.to_gpx(pts, wpts, name="hike")
    doc = md.parseString(gpx)                           # raises if malformed
    assert doc.getElementsByTagName("trkpt").length == 2
    assert doc.getElementsByTagName("wpt").length == 1
    assert "camp &amp; rest" in gpx                     # name is XML-escaped
    assert '<ele>1600.0</ele>' in gpx


def test_moon_phase_name():
    assert FC.moon_phase_name(0.01, True) == "new"
    assert FC.moon_phase_name(0.99, False) == "full"
    assert FC.moon_phase_name(0.5, True) == "first quarter"
    assert FC.moon_phase_name(0.5, False) == "last quarter"
    assert FC.moon_phase_name(0.2, True) == "waxing crescent"
    assert FC.moon_phase_name(0.8, False) == "waning gibbous"


def test_rise_set_on_a_synthetic_sine_day():
    # elevation = 40*sin(2*pi*(t)/86400) peaks at 6h, crosses 0 up at t=0, down at 12h
    def elev(lat, lon, t):
        return 40 * math.sin(2 * math.pi * (t % 86400) / 86400)
    rise, set_, up, down = FC.rise_set(elev, 0, 0, 0, horizon=0.0, step=60)
    assert rise is not None and set_ is not None
    assert abs(set_ - 43200) < 120                      # sets at ~12h
    assert not up and not down


def test_rise_set_against_the_sun_for_denver():
    import overwatch as OW
    midnight = calendar.timegm((2026, 6, 21, 7, 0, 0))   # ~local midnight MDT on the solstice
    rise, set_, _, _ = FC.rise_set(lambda la, lo, t: OW.sun_azel(la, lo, t)[1],
                                   39.74, -104.99, midnight, horizon=-0.833)
    # Denver solstice: sunrise ~05:32 MDT (11:32 UTC), sunset ~20:32 MDT (02:32 UTC next day)
    assert rise is not None and set_ is not None
    rise_h = (rise % 86400) / 3600
    assert 11 < rise_h < 12                              # ~11:32 UTC


def test_doctor_fieldcomp_check():
    import doctor
    ok, detail, fix = doctor.chk_fieldcomp()
    assert ok is True and "map" in detail and "track" in detail
