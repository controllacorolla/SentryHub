import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import skyintel as I  # noqa: E402


# ---- N-number <-> ICAO hex --------------------------------------------------------------
def test_n_number_block_edges_and_known_pair():
    assert I.n_number("a00001") == "N1"
    assert I.n_number("adf7c7") == "N99999"
    assert I.n_number("a835af") == "N628TS"        # publicly documented pairing


def test_n_number_rejects_non_us_and_military():
    assert I.n_number("ae01ce") is None             # US military block
    assert I.n_number("c0ffee") is None             # Canada
    assert I.n_number("zzzzzz") is None


def test_n_number_round_trips_across_whole_block():
    seen = set()
    for v in range(I.US_FIRST, I.US_LAST + 1, 97):   # ~9.4k samples across the range
        h = "%06x" % v
        n = I.n_number(h)
        assert n not in seen and I.n_to_hex(n) == h
        seen.add(n)
    assert I.n_to_hex("N628TS") == "a835af"


def test_n_to_hex_rejects_impossible_tails():
    for bad in ("N0", "NI", "N1O", "N1ABC", "X123", "N123456", "N12A3"):
        assert I.n_to_hex(bad) is None, bad


# ---- tables -----------------------------------------------------------------------------
def test_country_blocks():
    assert I.icao_country("a12345") == "United States"
    assert I.icao_country("c01234") == "Canada"
    assert I.icao_country("0d0abc") == "Mexico"
    assert I.icao_country("4cc123") == "Iceland"
    assert I.icao_country("000001") == ""


def test_relayed_sources_dont_count_as_heard():
    for t in ("tisb_icao", "adsr_icao", "mlat", "tisb_trackfile"):
        assert I.relayed(t)
    assert not I.relayed("adsb_icao") and not I.relayed(None)


def test_fl_formatting():
    assert I.fl(36000) == "FL360" and I.fl(18000) == "FL180"
    assert I.fl(9500) == "9,500" and I.fl(None) == ""


# ---- flight phase (Denver: the field is 5,400 ft, so sea-level rules lie) ----------------
DEN = ("KDEN", 8.0, 5434)


def test_phase_approach_judged_against_field_elevation():
    # 8,500 ft MSL is only ~3,000 ft AGL at Denver: that's an approach, not "descending"
    assert I.flight_phase(8500, -800, 160, False, DEN) == ("approach", "KDEN")


def test_phase_departure_climb_cruise():
    assert I.flight_phase(7200, 2500, 180, False, DEN)[0] == "departure"
    assert I.flight_phase(24000, 1800, 420, False, None)[0] == "climbing"
    assert I.flight_phase(37000, 0, 460, False, None)[0] == "cruise"
    assert I.flight_phase(12000, 0, 250, False, None)[0] == "level"


def test_phase_on_ground():
    assert I.flight_phase(None, 0, 12, True)[0] == "taxiing"
    assert I.flight_phase(None, 0, 120, True)[0] == "rolling"
    assert I.flight_phase(None, 0, 0, True)[0] == "on ground"


# ---- closest point of approach ----------------------------------------------------------
HOME = (39.57, -104.85)


def test_cpa_head_on_overhead():
    # 10 nm due west, heading east at 120 kt -> passes overhead in 5 minutes
    lat, lon = HOME[0], HOME[1] - 10 / (60 * 0.7705)
    miss, t = I.cpa(HOME[0], HOME[1], lat, lon, 90, 120)
    assert miss < 0.1 and abs(t - 300) < 5


def test_cpa_receding_and_offset_track():
    lat, lon = HOME[0], HOME[1] - 10 / (60 * 0.7705)
    assert I.cpa(HOME[0], HOME[1], lat, lon, 270, 120)[1] == 0      # flying away
    lat2 = HOME[0] + 3 / 60.0                                        # 3 nm north offset
    miss, t = I.cpa(HOME[0], HOME[1], lat2, lon, 90, 120)
    assert abs(miss - 3.0) < 0.1 and t > 0


def test_overhead_window():
    lat, lon = HOME[0], HOME[1] - 10 / (60 * 0.7705)
    a = {"lat": lat, "lon": lon, "track": 90, "gs": 120, "alt_baro": 7500}
    assert I.overhead(HOME[0], HOME[1], a) is not None
    assert I.overhead(HOME[0], HOME[1], a, within_s=120) is None     # too far out yet
    assert I.overhead(HOME[0], HOME[1], dict(a, alt_baro="ground")) is None


# ---- coverage ---------------------------------------------------------------------------
def test_coverage_bins_by_direction_and_keeps_max():
    c = I.Coverage(today="2026-11-09")
    north = {"lat": HOME[0] + 50 / 60.0, "lon": HOME[1], "type": "adsb_icao"}
    east_near = {"lat": HOME[0], "lon": HOME[1] + 20 / (60 * 0.7705), "type": "adsb_icao"}
    east_far = dict(east_near, lon=HOME[1] + 90 / (60 * 0.7705))
    for a in (north, east_near, east_far, east_near):
        c.add(HOME[0], HOME[1], a)
    out = dict((round(b), round(d)) for b, d in c.outline("all"))
    assert out[5] == 50                       # 0-10 deg sector
    # great-circle bearing to a point "due east" on the same parallel starts just north
    # of 090, so compute the sector rather than assume it
    sec = int(I.bearing_deg(HOME[0], HOME[1], east_far["lat"], east_far["lon"]) // 10) * 10 + 5
    assert out[sec] == 90                     # farthest kept, the nearer one ignored
    assert c.dirty


def test_coverage_ignores_relayed_and_bogus_positions():
    c = I.Coverage(today="2026-11-09")
    tisb = {"lat": HOME[0] + 1.0, "lon": HOME[1], "type": "tisb_icao"}
    bogus = {"lat": HOME[0] + 10.0, "lon": HOME[1], "type": "adsb_icao"}   # 600 nm
    assert not c.add(HOME[0], HOME[1], tisb)
    assert not c.add(HOME[0], HOME[1], bogus)
    assert c.outline("all") == []


def test_coverage_today_resets_on_new_day_but_all_time_persists():
    c = I.Coverage(today="2026-11-08")
    c.add(HOME[0], HOME[1], {"lat": HOME[0] + 1.0, "lon": HOME[1]})
    saved = c.to_json()
    c2 = I.Coverage(saved, today=time.strftime("%Y-%m-%d"))
    assert c2.outline("all") and (c2.outline("today") == [] or saved["date"] ==
                                  time.strftime("%Y-%m-%d"))


def test_coverage_survives_corrupt_file():
    c = I.Coverage({"all": "junk", "today": [1, 2], "date": 5})
    assert c.outline("all") == [] and c.summary() == ""


def test_demo_tails_match_their_transponder_addresses():
    # a plane-spotter would notice instantly if a demo N-number disagreed with its hex
    import sky_app
    for a in sky_app.DemoFeed().aircraft:
        cs = a["flight"]
        if cs.startswith("N") and cs[1:2].isdigit():
            assert I.n_number(a["hex"]) == cs, cs


# ---- routes -----------------------------------------------------------------------------
SFO = {"icao": "KSFO", "iata": "SFO", "city": "San Francisco", "name": "SFO",
       "lat": 37.619, "lon": -122.375}
ORD = {"icao": "KORD", "iata": "ORD", "city": "Chicago", "name": "ORD",
       "lat": 41.978, "lon": -87.904}
ROUTE = {"orig": SFO, "mid": None, "dest": ORD, "airline": "United"}

ADSBDB = {"response": {"flightroute": {
    "callsign": "UAL1234", "callsign_icao": "UAL1234", "callsign_iata": "UA1234",
    "airline": {"name": "United Airlines", "icao": "UAL", "iata": "UA", "country": "US",
                "country_iso": "US", "callsign": "UNITED"},
    "origin": {"country_iso_name": "US", "country_name": "United States", "elevation": 13,
               "iata_code": "SFO", "icao_code": "KSFO", "latitude": 37.619,
               "longitude": -122.375, "municipality": "San Francisco",
               "name": "San Francisco International Airport"},
    "midpoint": None,
    "destination": {"country_iso_name": "US", "country_name": "United States",
                    "elevation": 672, "iata_code": "ORD", "icao_code": "KORD",
                    "latitude": 41.978, "longitude": -87.904, "municipality": "Chicago",
                    "name": "Chicago O'Hare International Airport"}}}}


def test_parse_adsbdb_documented_shape():
    rt = I.parse_adsbdb(ADSBDB)
    assert I.route_short(rt) == "SFO → ORD"
    assert I.route_cities(rt) == "San Francisco → Chicago"
    assert rt["airline"] == "United Airlines"


def test_parse_adsbdb_unknown_and_junk():
    assert I.parse_adsbdb({"response": "unknown callsign"}) is None
    assert I.parse_adsbdb(None) is None
    bad = {"response": {"flightroute": {"origin": {"latitude": "x"}, "destination": {}}}}
    assert I.parse_adsbdb(bad) is None


def test_route_check_progress_on_track():
    mid_lat, mid_lon = 40.2, -105.0          # over Colorado, near the SFO-ORD great circle
    chk = I.route_check(mid_lat, mid_lon, ROUTE)
    assert chk["plausible"]
    assert 0.3 < chk["flown"] / chk["total"] < 0.65
    assert abs(chk["flown"] + chk["to_go"] - chk["total"]) < 1


def test_route_check_flags_stale_listing():
    # a "UAL1234 SFO-ORD" listing for a plane actually over Miami is a stale route
    assert not I.route_check(25.8, -80.3, ROUTE)["plausible"]


def test_route_eligibility_and_airline():
    assert I.route_eligible("UAL1234") and I.route_eligible("SWA2311")
    assert not I.route_eligible("N425CP") and not I.route_eligible("")
    assert I.airline_of("SKW4123") == "SkyWest" and I.airline_of("N425CP") == ""


def test_infer_route_offline():
    assert I.infer_route("approach", "KDEN") == "→ KDEN (on approach)"
    assert I.infer_route("departure", "KAPA") == "KAPA → (departing)"
    assert I.infer_route("cruise", "") == ""


def test_route_cache_ttls():
    c = I.RouteCache()
    c.put("UAL1", ROUTE, now=1000)
    c.put("XYZ9", None, now=1000)
    assert c.get("ual1", now=2000)[1] == "hit"
    assert c.get("XYZ9", now=2000)[1] == "miss"
    assert c.get("XYZ9", now=1000 + 13 * 3600)[1] == "unknown"     # miss expired, re-ask
    assert c.get("UAL1", now=1000 + 4 * 86400)[1] == "unknown"


def test_route_feed_worker_with_fixture(tmp_path, monkeypatch):
    import json, sky_app
    fx = tmp_path / "routes.json"
    fx.write_text(json.dumps({"UAL1234": ADSBDB}))
    monkeypatch.setenv("UCS_ROUTES_FILE", str(fx))
    rf = sky_app.RouteFeed(path=str(tmp_path / "cache.json"))
    rf.want("UAL1234")
    rf.want("ZZZ999")                      # not in the fixture -> miss
    rf.want("N425CP")                      # GA: never looked up
    end = time.time() + 6
    while time.time() < end and (rf.get("UAL1234")[1] != "hit" or rf.get("ZZZ999")[1] != "miss"):
        time.sleep(0.1)
    rt, st = rf.get("UAL1234")
    assert st == "hit" and I.route_short(rt) == "SFO → ORD"
    assert rf.get("ZZZ999")[1] == "miss"
    assert rf.get("N425CP")[1] == "unknown"


def test_demo_routes_fit_demo_planes():
    import sky_app
    d = sky_app.DemoFeed()
    for a in d.aircraft:
        rt = sky_app.DEMO_ROUTES.get(a["flight"])
        if rt:
            assert I.route_check(a["lat"], a["lon"], rt)["plausible"], a["flight"]


# ---- runways in use ---------------------------------------------------------------------
def _den():
    import sky_app
    return sky_app.RWY_ENDS["KDEN"], sky_app.AIRPORTS["KDEN"]["elev"]


def _on_line(end, back_nm, alt, track, vr):
    lat, lon = I.offset(end["lat"], end["lon"], (end["hdg"] + 180) % 360, back_nm) \
        if back_nm > 0 else I.offset(end["lat"], end["lon"], end["hdg"], -back_nm)
    return {"lat": lat, "lon": lon, "alt_baro": alt, "track": track, "baro_rate": vr}


def test_arrival_on_16R_not_its_parallel():
    ends, elev = _den()
    e = {x["id"]: x for x in ends}["16R"]
    a = _on_line(e, 5.0, elev + 1600, e["hdg"], -750)
    assert I.runway_use(a, ends, elev) == ("arr", "16R")


def test_departure_climbing_out_on_25():
    ends, elev = _den()
    e = {x["id"]: x for x in ends}["25"]
    a = _on_line(e, -(e["len"] + 2.5), elev + 2000, e["hdg"], 2200)
    assert I.runway_use(a, ends, elev) == ("dep", "25")


def test_not_runway_traffic():
    ends, elev = _den()
    e = {x["id"]: x for x in ends}["16R"]
    level = _on_line(e, 5.0, elev + 1600, e["hdg"], 0)              # level overflight
    wrong = _on_line(e, 5.0, elev + 1600, (e["hdg"] + 90) % 360, -750)  # crossing the final
    high = _on_line(e, 5.0, elev + 9000, e["hdg"], -750)             # descending, far too high
    gnd = dict(_on_line(e, 5.0, elev, e["hdg"], 0), alt_baro="ground")
    for a in (level, wrong, high, gnd):
        assert I.runway_use(a, ends, elev) is None


def test_runway_watch_counts_unique_aircraft_in_window():
    w = I.RunwayWatch()
    w.note("KDEN", "arr", "16R", "a1", now=1000)
    w.note("KDEN", "arr", "16R", "a1", now=1005)     # same plane twice: one vote
    w.note("KDEN", "arr", "16R", "a2", now=1010)
    w.note("KDEN", "dep", "25", "a3", now=1010)
    assert w.active("KDEN", now=1100) == {"arr": [("16R", 2)], "dep": [("25", 1)]}
    assert w.label("KDEN", now=1100) == "ARR 16R  DEP 25"
    assert w.label("KDEN", now=1010 + 1201) == ""     # aged out
    assert w.label("KAPA", now=1100) == ""


# ---- logbook ----------------------------------------------------------------------------
def _ac(hx, cs, lat_off, alt, t="B738", mil=False):
    return {"hex": hx, "flight": cs, "lat": HOME[0] + lat_off / 60.0, "lon": HOME[1],
            "alt_baro": alt, "t": t, "_mil": mil}


def test_logbook_one_entry_per_airframe_keeps_extremes():
    lb = I.Logbook(today="2026-11-09")
    lb.see(_ac("a835af", "N628TS", 20, 9000, "GLF6"), HOME, now=100)
    lb.see(_ac("a835af", "N628TS", 3, 12000, "GLF6"), HOME, now=200)
    lb.see(_ac("a835af", "EJA628", 8, 4000, "GLF6"), HOME, now=300)
    e = lb.ent["a835af"]
    assert len(lb.ent) == 1 and e["calls"] == ["N628TS", "EJA628"]
    assert e["closest"] == 3.0 and e["closest_alt"] == 12000 and e["max_alt"] == 12000
    assert e["first"] == 100 and e["last"] == 300 and e["reg"] == "N628TS"


def test_logbook_flags_new_types_against_lifetime():
    lb = I.Logbook(today="2026-11-09", life={"types": {"B738": "2026-11-01"}, "frames": {}})
    lb.see(_ac("a00001", "UAL1", 10, 30000, "B738"), HOME)
    lb.see(_ac("ae01ce", "RCH471", 10, 24000, "C17", mil=True), HOME)
    s = lb.summary()
    assert s["new_types"] == ["C17"] and s["mil"] == 1 and s["new_frames"] == 2
    assert not lb.ent["a00001"]["new_type"] and lb.ent["ae01ce"]["new_type"]
    # tomorrow, C17 is no longer new
    lb2 = I.Logbook(None, lb.life_json(), today="2026-11-10")
    lb2.see(_ac("ae01cf", "RCH472", 10, 24000, "C17", mil=True), HOME)
    assert not lb2.ent["ae01cf"]["new_type"]


def test_logbook_new_day_starts_clean_and_survives_junk():
    lb = I.Logbook(today="2026-11-09")
    lb.see(_ac("a00001", "UAL1", 10, 30000), HOME)
    assert I.Logbook(lb.day_json(), lb.life_json(), today="2026-11-10").ent == {}
    assert I.Logbook(lb.day_json(), lb.life_json(), today="2026-11-09").ent
    junk = I.Logbook({"date": "2026-11-09", "ent": "x"}, {"types": 5}, today="2026-11-09")
    assert junk.ent == {} and junk.types == {}


def test_logbook_sorting_and_csv():
    lb = I.Logbook(today="2026-11-09")
    lb.see(_ac("a00002", "B2", 30, 9000, "A320"), HOME, now=200)
    lb.see(_ac("a00001", "A1", 5, 9000, "B738"), HOME, now=100)
    assert [e["hex"] for e in lb.entries("first")] == ["a00001", "a00002"]
    assert [e["hex"] for e in lb.entries("closest")] == ["a00001", "a00002"]
    assert [e["hex"] for e in lb.entries("last")] == ["a00002", "a00001"]
    rows = lb.csv().strip().splitlines()
    assert rows[0].startswith("first_seen,") and len(rows) == 3
