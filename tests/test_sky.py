"""Sky pure helpers: geo math, altitude/ground, settings merge."""
import sky_app


def test_dist_nm_known_distance():
    # KAPA (39.5701,-104.849) to KDEN (39.8617,-104.6731) is ~22 nm
    d = sky_app.dist_nm(39.5701, -104.849, 39.8617, -104.6731)
    assert 18 < d < 26


def test_dist_nm_zero_for_same_point():
    assert sky_app.dist_nm(39.0, -104.0, 39.0, -104.0) == 0


def test_on_ground():
    assert sky_app.on_ground({"alt_baro": "ground"}) is True
    assert sky_app.on_ground({"alt_baro": 3500}) is False
    assert sky_app.on_ground({}) is False


def test_alt_ft_variants():
    assert sky_app.alt_ft({"alt_baro": "ground"}) is None
    assert sky_app.alt_ft({"alt_baro": 37000}) == 37000
    # falls back to geometric altitude when baro is missing/invalid
    assert sky_app.alt_ft({"alt_geom": 12000}) == 12000
    assert sky_app.alt_ft({}) is None


def test_load_settings_merges_defaults(tmp_path, monkeypatch):
    # a settings file missing newer keys still comes back with them filled from DEFAULT_SETTINGS
    import json
    p = tmp_path / "sky.json"
    p.write_text(json.dumps({"map_center": "KAPA-KDEN"}))
    monkeypatch.setattr(sky_app, "SETTINGS_PATH", str(p))
    s = sky_app.load_settings()
    assert "tfr_states" in s        # a key we added this session
    assert "adsb_sources" in s
    assert s["map_center"] == "KAPA-KDEN"


def test_default_settings_has_tfr_states():
    assert isinstance(sky_app.DEFAULT_SETTINGS.get("tfr_states"), list)


def test_sky_mode_default_is_both():
    assert sky_app.DEFAULT_SETTINGS.get("sky_mode") == "both"


def test_load_settings_fills_sky_mode(tmp_path, monkeypatch):
    import json
    p = tmp_path / "sky.json"
    p.write_text(json.dumps({"map_center": "KAPA-KDEN"}))   # old file, no sky_mode
    monkeypatch.setattr(sky_app, "SETTINGS_PATH", str(p))
    assert sky_app.load_settings().get("sky_mode") == "both"


# ---- DemoFeed: synthetic traffic for the display without an antenna ----------

def _demo():
    return sky_app.DemoFeed()


def test_demo_snapshot_shape_matches_adsbfeed():
    acs, trails, status, rcv = _demo().snapshot()
    assert status == "live" and rcv == sky_app.DemoFeed.CTR
    assert len(acs) == 11
    for a in acs:
        assert a["seen"] == 0 and a["seen_pos"] == 0
        assert "_turn" not in a          # internal field never leaks
        assert {"hex", "flight", "lat", "lon", "track", "gs"} <= set(a)


def test_demo_has_one_military_and_one_ground():
    acs, _, _, _ = _demo().snapshot()
    mil = [a for a in acs if 0xADF7C8 <= int(a["hex"], 16) <= 0xAFFFFF]
    assert [a["flight"] for a in mil] == ["RCH471"]
    assert sum(1 for a in acs if a["alt_baro"] == "ground") == 1


def test_demo_aircraft_move_at_groundspeed():
    d = _demo()
    acs, _, _, _ = d.snapshot()
    p0 = {a["hex"]: (a["lat"], a["lon"]) for a in acs}
    for _ in range(60):
        d._step(1.0)
    ual = next(a for a in d.aircraft if a["flight"] == "UAL1234")
    nm = sky_app.dist_nm(*p0[ual["hex"]], ual["lat"], ual["lon"])
    assert 6.5 < nm < 8.5                # 452 kt over one minute
    swa = next(a for a in d.aircraft if a["flight"] == "SWA2311")
    assert swa["alt_baro"] > 13400       # climber climbs


def test_demo_stays_bounded_over_hours():
    d = _demo()
    for _ in range(240):
        d._step(30.0)                    # two hours, coarse
    far = max(sky_app.dist_nm(a["lat"], a["lon"], *d.CTR) for a in d.aircraft)
    assert far < 90
    for a in d.aircraft:
        if a["alt_baro"] != "ground":
            assert 6000 < a["alt_baro"] < 42000


def test_demo_trails_capped():
    d = _demo()
    for _ in range(80):
        d._step(1.0)
    assert d.trails and all(len(t) <= 30 for t in d.trails.values())


def test_clean_aircraft_coerces_and_drops():
    a = {"hex": "AA0001", "lat": 91.0, "lon": -104.8, "track": "north", "gs": "fast",
         "alt_baro": {"x": 1}, "flight": "EV{IL}\x1b[31m\nNL" + "A" * 300, "seen": "3"}
    c = sky_app.clean_aircraft(a)
    assert c["hex"] == "aa0001"
    assert "lat" not in c and "lon" not in c          # impossible coords dropped
    assert "track" not in c and "gs" not in c          # unparseable numerics dropped
    assert "alt_baro" not in c
    assert c["seen"] == 3.0
    assert "\x1b" not in c["flight"] and "\n" not in c["flight"] and len(c["flight"]) <= 48


def test_clean_aircraft_keeps_good_values():
    a = {"hex": "ae01ce", "lat": 39.6, "lon": -104.8, "track": 405.0, "gs": -5,
         "alt_baro": "ground", "flight": "RCH471", "squawk": 1200}
    c = sky_app.clean_aircraft(a)
    assert c["lat"] == 39.6 and c["track"] == 45.0 and c["gs"] == 0
    assert c["alt_baro"] == "ground" and c["squawk"] == "1200"


def test_clean_aircraft_numeric_strings_coerced():
    c = sky_app.clean_aircraft({"hex": "abc", "lat": "39.6", "lon": "-104.8", "gs": "250"})
    assert c["lat"] == 39.6 and c["gs"] == 250.0


def test_clean_aircraft_none_values_removed():
    c = sky_app.clean_aircraft({"hex": "x1", "lat": None, "lon": None, "track": None,
                                "gs": None, "alt_baro": None})
    for k in ("lat", "lon", "track", "gs", "alt_baro"):
        assert k not in c
