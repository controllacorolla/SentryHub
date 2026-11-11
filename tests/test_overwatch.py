"""Overwatch: sky geometry, the radio director, and spoken call-outs (all pure logic)."""
import calendar
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import overwatch as W   # noqa: E402

HOME = (39.6, -104.9, 1700.0)


def test_azel_overhead_north_and_below_horizon():
    az, el, km = W.azel(HOME, 39.6, -104.9, 11700)
    assert el > 89.9 and abs(km - 10.0) < 0.01
    az, el, km = W.azel(HOME, 40.6, -104.9, 11000)          # ~111 km north at cruise height
    assert (az < 1 or az > 359) and 3.5 < el < 5 and 110 < km < 113
    az, el, _ = W.azel(HOME, 39.6, -103.9, 1700)            # same height, 86 km east
    assert 89 < az < 91 and el < 0                          # earth curvature hides it


def test_sun_and_moon_against_known_events():
    t = calendar.timegm((2026, 6, 21, 19, 2, 0))            # Denver solar noon, solstice
    az, el = W.sun_azel(39.74, -104.99, t)
    assert abs(az - 180) < 1.5 and abs(el - 73.7) < 0.5
    t = calendar.timegm((2024, 4, 8, 18, 42, 0))            # total eclipse over Dallas
    saz, sel = W.sun_azel(32.78, -96.8, t)
    maz, mel, lit = W.moon_azel(32.78, -96.8, t)
    assert abs(saz - maz) < 1.5 and abs(sel - mel) < 1.5 and lit < 0.01
    assert W.moon_azel(0, 0, calendar.timegm((2026, 11, 24, 14, 53, 0)))[2] > 0.99   # full moon
    assert W.daylight(10) == "day" and W.daylight(-3) == "civil twilight"
    assert W.daylight(-30) == "night"


def test_projection_and_compass():
    assert W.project(0, 90, 100, 100, 50) == (100, 100)                  # zenith at the centre
    x, y = W.project(90, 0, 100, 100, 50)
    assert abs(x - 150) < 1e-6 and abs(y - 100) < 1e-6                   # east horizon, right rim
    assert W.dome_r(30, 100) < 100 * 60 / 90      # the 0-30 degree band gets more of the dome
    assert W.dome_r(10, 100) > W.dome_r(30, 100) > W.dome_r(60, 100) > W.dome_r(90, 100) == 0
    assert [W.compass(a) for a in (0, 44, 90, 181, 359)] == ["N", "NE", "E", "S", "N"]
    assert W.compass(100, 8) == "E"


def test_sky_objects_sorted_and_ground_on_the_horizon():
    ents = [{"id": "air:1", "kind": "air", "label": "UAL1", "lat": 39.6, "lon": -104.9,
             "alt_ft": 36000, "course": 90, "speed_kt": 450},
            {"id": "aprs:K", "kind": "aprs", "label": "KD0ABC", "lat": 39.7, "lon": -104.9,
             "alt_ft": None},
            {"id": "bad", "kind": "air", "label": "x", "lat": "nope", "lon": 0, "alt_ft": 1}]
    objs = W.sky_objects(ents, HOME, 0)
    assert [o["id"] for o in objs] == ["air:1", "aprs:K"]
    assert objs[0]["el"] > 85 and objs[1]["ground"] and abs(objs[1]["el"]) < 1


def test_gps_sats_tolerate_junk():
    sky = {"satellites": [{"PRN": 5, "az": 370, "el": 40, "ss": 30, "used": True, "gnssid": 0},
                          {"PRN": 9, "el": 10}, None, {"PRN": 3, "az": "x", "el": 1}]}
    g = W.gps_sats(sky)
    assert len(g) == 1 and g[0]["az"] == 10 and g[0]["used"] and g[0]["sys"] == "G"
    assert W.gps_sats(None) == []


def test_rotation_is_stateless_and_covers_the_cycle():
    plan = [["air", 8], ["aprs", 4], ["sensors", 2]]
    seen = []
    for m in range(14):
        mode, a, b = W.rotation(plan, m * 60 + 1)
        assert a <= m * 60 + 1 < b
        seen.append(mode)
    assert seen == ["air"] * 8 + ["aprs"] * 4 + ["sensors"] * 2
    assert W.rotation(plan, 14 * 60 + 1)[0] == "air"                     # wraps
    assert W.rotation([], 5)[0] == "air"
    assert W.rotation([["bogus", 3], ["aprs", 0]], 5)[0] == "aprs"       # unknown skipped, min 1


def test_director_priorities():
    cfg = W.plans(W.DEFAULTS)
    t = calendar.timegm((2026, 11, 11, 17, 0, 30))                       # no launch window
    on = {"on": True, "can": {"air", "aprs", "sensors", "sonde"}}
    assert W.direct(t, cfg, {})[0] == "off"
    assert W.direct(t, cfg, dict(on, hot=True))[0] == "rest"
    assert W.direct(t, cfg, dict(on, low_batt=True))[0] == "rest"
    assert W.direct(t, cfg, dict(on, holder="FM"))[0] == "yield"         # you are on the radio
    mode, until, why = W.direct(t, cfg, dict(on, holder="APRS", mine=True))
    assert mode in W.MODES and until > t
    assert W.direct(t, cfg, {"on": True, "can": {"air"}})[0] == "air"    # nothing else set up
    tl = calendar.timegm((2026, 11, 11, 11, 20, 0))                      # 20 min after launch
    modes = {W.direct(tl + k * 60, cfg, on)[0] for k in range(17)}
    assert "sonde" in modes and "sensors" not in modes                   # balloon plan in force
    assert "sonde" not in {W.direct(tl + k * 60, cfg, {"on": True, "can": {"air", "aprs"}})[0]
                           for k in range(17)}                           # not installed: never


def test_sonde_window():
    assert W.in_sonde_window(calendar.timegm((2026, 1, 1, 10, 55, 0)))
    assert W.in_sonde_window(calendar.timegm((2026, 1, 1, 12, 30, 0)))
    assert not W.in_sonde_window(calendar.timegm((2026, 1, 1, 13, 0, 0)))
    assert W.in_sonde_window(calendar.timegm((2026, 1, 1, 23, 30, 0)))
    assert W.in_sonde_window(calendar.timegm((2026, 1, 2, 0, 30, 0)))    # across midnight
    assert not W.in_sonde_window(calendar.timegm((2026, 1, 1, 5, 0, 0)))


def test_schedule_is_contiguous():
    t = calendar.timegm((2026, 11, 11, 17, 3, 0))
    sch = W.schedule(t, W.plans(W.DEFAULTS), {"air", "aprs", "sensors"}, 30)
    assert sch[0][1] == t and sch[-1][2] >= t + 30 * 60
    for (m1, a1, b1), (m2, a2, b2) in zip(sch, sch[1:]):
        assert abs(a2 - b1) < 2 and m1 != m2


def test_callouts_once_and_rate_limited():
    c = W.Caller(overhead_deg=60, repeat_s=900, gap_s=20)
    over = {"id": "air:1", "kind": "air", "label": "UAL1234", "az": 10, "el": 75, "km": 11,
            "alt_ft": 36000, "ground": False}
    low = dict(over, id="air:2", el=10)
    said = c.calls([over, low], 1000)
    assert len(said) == 1 and "overhead" in said[0] and "36 thousand" in said[0]
    assert c.calls([over, low], 1005) == []                              # not again
    mil = {"id": "mil:1", "kind": "mil", "label": "RCH471", "az": 90, "el": 8, "km": 37.4,
           "alt_ft": 24000, "ground": False}
    assert c.calls([mil], 1010) == []                                    # too soon after the last
    assert c.calls([mil], 1100) == []                                    # and it stays marked said
    sonde = {"id": "sonde:1", "kind": "sonde", "label": "LMS6-1", "az": 200, "el": 30, "km": 40,
             "ground": False}
    assert "Weather balloon" in c.calls([sonde], 1200)[0]
    gnd = {"id": "aprs:1", "kind": "aprs", "label": "K", "az": 0, "el": 0, "km": 5, "ground": True}
    assert c.calls([gnd], 5000) == []
    assert c.calls([over], 1000 + 901)                                   # after the repeat window
    assert W.spoken_name("UAL1234") == "U A L 1 2 3 4"
    assert W.spoken_name("") == "unknown"


def test_plans_from_settings():
    p = W.plans(W.DEFAULTS)
    assert p["plan"] == [["air", 8], ["aprs", 4], ["sensors", 2]]
    assert p["sonde_plan"][0] == ["sonde", 10] and ["sensors", 2] not in p["sonde_plan"]
    p = W.plans({"air_min": 0, "aprs_min": 5, "sensors_min": "x", "sonde_min": 0})
    assert p["plan"] == [["aprs", 5]] and p["sonde_plan"] == p["plan"]      # balloons left out
    assert W.plans({})["plan"] == [["air", 10]]                             # never an empty plan
    t = calendar.timegm((2026, 11, 11, 11, 20, 0))
    on = {"on": True, "can": {"air", "aprs", "sensors", "sonde"}}
    assert W.direct(t, p, on)[0] == "aprs"                                  # no sonde slot at all


def test_doctor_reports_what_autopilot_can_use():
    import doctor
    ok, detail, fix = doctor.chk_autopilot(which=lambda n: "/usr/bin/" + n, sonde=True)
    assert ok is True and "APRS" in detail and "Balloons" in detail and fix == ""
    ok, detail, fix = doctor.chk_autopilot(which=lambda n: None, sonde=False)
    assert ok is None and detail == "rotates: plane map" and "rtl-433" in fix
