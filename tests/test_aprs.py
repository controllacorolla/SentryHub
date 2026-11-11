import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import aprs as A  # noqa: E402


def rep(line):
    f = A.parse_frame(line)
    assert f, line
    return A.decode(f)


def mic_e_encode(lat, lon, speed, course, code=">", table="/"):
    """Test-only Mic-E encoder (north, west) so decoding is checked against geometry."""
    la = abs(lat)
    d = int(la)
    m = (la - d) * 60
    digits = "%02d%02d%02d" % (d, int(m), round((m - int(m)) * 100))
    dst = ""
    for i, ch in enumerate(digits):
        flag = (i == 3) or (i == 5) or (i == 4 and abs(lon) >= 100)
        dst += chr(ord("P") + int(ch)) if flag else ch
    lo = abs(lon)
    ld = int(lo)
    lm = (lo - ld) * 60
    lh = round((lm - int(lm)) * 100)
    dd = ld - 100 if ld >= 100 else ld
    if ld >= 110:
        dd = ld - 100
    b1 = dd + 28 if not (100 <= ld <= 109) else ld - 100 + 80 + 28 + 100 - 100
    if 100 <= ld <= 109:
        b1 = (ld - 100 + 180 - 100) + 28 + 0
    sp = speed // 10
    dc = (speed % 10) * 10 + course // 100
    se = course % 100
    info = "`" + chr(b1) + chr(int(lm) + 28) + chr(lh + 28) + chr(sp + 28) + chr(dc + 28) + \
        chr(se + 28) + code + table
    return dst, info


def test_uncompressed_position_with_course_alt():
    r = rep("APRS: KD0ABC-9>APDR16,WIDE1-1,KQ0ABC-1*,WIDE2-1:=3937.20N/10452.20W>090/045/A=005712 commute")
    assert r["kind"] == "position" and r["symbol"] == "car"
    assert r["lat"] == pytest.approx(39.62) and r["lon"] == pytest.approx(-104.87)
    assert r["course"] == 90 and r["speed_kt"] == 45 and r["alt_ft"] == 5712
    assert r["comment"] == "commute" and r["via"] == "KQ0ABC-1"


def test_timestamped_and_direct():
    r = rep("N0CALL>APRS:@092345z3937.20N/10452.20W-PHG2360 home")
    assert r["lat"] == pytest.approx(39.62) and r["symbol"] == "house" and r["via"] is None


def test_compressed_spec_example():
    r = rep("N0CALL>APRS:=/5L!!<*e7>7P[")
    assert r["lat"] == pytest.approx(49.5, abs=1e-4)
    assert r["lon"] == pytest.approx(-72.75, abs=1e-4)
    assert r["symbol"] == "car"


def test_mic_e_spec_destination():
    # APRS spec: destination S32U6T = 33 25.64 N, longitude offset 0, West
    f = A.parse_frame("N0CALL>S32U6T:`" + chr(112 + 28 - 100 + 0) + "  " + "    >/")
    r = A.decode(f)
    assert r["lat"] == pytest.approx(33 + 25.64 / 60)


@pytest.mark.parametrize("lat,lon,spd,crs", [(39.62, -104.87, 55, 270), (39.75, -105.0, 0, 0),
                                             (40.01, -99.5, 120, 45), (39.5, -105.25, 7, 359)])
def test_mic_e_roundtrip(lat, lon, spd, crs):
    dst, info = mic_e_encode(lat, lon, spd, crs)
    r = A.decode(A.parse_frame("KD0XYZ-7>%s,WIDE1-1:%s" % (dst, info)))
    assert r["kind"] == "position"
    assert r["lat"] == pytest.approx(lat, abs=2e-4)
    assert r["lon"] == pytest.approx(lon, abs=2e-4)
    assert r["speed_kt"] == spd
    assert r.get("course", 0) == crs % 360


def test_weather_station():
    r = rep("KC0WX>APRS:!3937.20N/10452.20W_220/004g010t045r000p000P000h65b10132")
    assert r["kind"] == "weather"
    assert r["wx"]["wind_dir"] == 220 and r["wx"]["wind_mph"] == 4
    assert r["wx"]["temp_f"] == 45 and r["wx"]["humidity"] == 65
    assert r["wx"]["pressure_mb"] == pytest.approx(1013.2)


def test_object_and_message_and_status():
    r = rep("W0DEN>APRS:;145.340-R*111111z3944.50N/10459.00Wr Denver rptr")
    assert r["kind"] == "object" and r["src"] == "145.340-R" and r["object_of"] == "W0DEN"
    m = rep("KD0ABC>APRS::KD0XYZ-7 :see you at the field{12")
    assert m["kind"] == "message" and m["to"] == "KD0XYZ-7" and m["text"] == "see you at the field"
    s = rep("KD0ABC>APRS:>On the way")
    assert s["kind"] == "status" and s["comment"] == "On the way"


@pytest.mark.parametrize("bad", ["", "garbage", "APRS: >:x", "toolongcall>APRS:!x",
                                 "N0CALL>APRS:", "N0CALL>APRS:!9999.99N/99999.99W>",
                                 "N0CALL>APRS:=/!!!!!!!!", None, "N0CALL>AB:`\x00\x00"])
def test_garbage_never_raises(bad):
    f = A.parse_frame(bad)
    if f:
        r = A.decode(f)
        assert "lat" not in r or -90 <= r["lat"] <= 90


def test_fuzz_never_raises():
    import random
    rnd = random.Random(7)
    base = "KD0ABC-9>S32U6T,WIDE1-1*:"
    for _ in range(3000):
        p = "".join(chr(rnd.randint(0, 255)) for _ in range(rnd.randint(0, 40)))
        f = A.parse_frame(base + rnd.choice("!=/@;)`'>:_") + p)
        if f:
            A.decode(f)


def test_stations_tracks_and_digis():
    st = A.Stations(cap=3)
    for i in range(5):
        st.add(rep("KD0ABC-9>APRS,KQ0ABC-1*:=39%02d.00N/10452.00W>090/030" % (37 + i)), now=i)
    s = st.s["KD0ABC-9"]
    assert s["n"] == 5 and len(s["track"]) == 5 and st.moving(s)
    assert st.digis == {"KQ0ABC-1": 5}
    for c in ("A1", "B2", "C3"):
        st.add(rep("%s>APRS:>hi" % c), now=10)
    assert len(st.s) == 3 and "KD0ABC-9" not in st.s


def test_save_load_roundtrip_and_expiry(tmp_path):
    st = A.Stations()
    st.add(rep("KD0ABC-9>APRS,KQ0ABC-1*:=3937.20N/10452.20W>090/030"), now=1000)
    st.add(rep("KD0ABC-9>APRS:=3938.20N/10452.20W>090/030"), now=1010)
    st.add(rep("KD0ABC>APRS::KD0XYZ-7 :hi{1"), now=1020)
    st.add(rep("OLD>APRS:=3937.20N/10452.20W-"), now=-90000)
    p = tmp_path / "s.json"
    A.save_stations(st, str(p), now=1030)
    back = A.load_stations(str(p), now=1100)
    assert set(back.s) == {"KD0ABC-9", "KD0ABC"}
    assert len(back.s["KD0ABC-9"]["track"]) == 2 and back.s["KD0ABC-9"]["lat"] == pytest.approx(39.6367, abs=1e-3)
    assert back.digis == {"KQ0ABC-1": 1}
    back.add(rep("KD0ABC-9>APRS:=3939.20N/10452.20W>"), now=1200)   # usable after load
    assert back.s["KD0ABC-9"]["n"] == 3
    assert A.load_stations(str(p), now=1030 + 90000).s == {}


@pytest.mark.parametrize("content", ["", "{", "[]", '{"stations": []}',
                                     '{"stations": {"X": {"last": "nan?"}}}',
                                     '{"stations": {"X": {"last": 1, "lat": 999, "lon": 0}}}',
                                     '{"stations": {"X": {"last": 1, "track": [[1]]}}}'])
def test_load_corrupt_never_raises(tmp_path, content):
    p = tmp_path / "s.json"
    p.write_text(content)
    s = A.load_stations(str(p), now=2)
    for v in s.s.values():
        assert "lat" not in v or -90 <= v["lat"] <= 90


def test_sitrep_mentions_balloon_and_aprs():
    import sitrep
    t = sitrep.template({"time": "01:00", "sonde": {"id": "LMS6-1", "alt_m": 12000,
                                                     "phase": "ascending"}, "aprs_24h": 14})
    assert "LMS6-1 ascending at 12,000 metres" in t and "14 APRS stations" in t
    assert "launch in 40 minutes" in sitrep.template({"time": "x", "next_launch_min": 40})
    assert "launch" not in sitrep.template({"time": "x", "next_launch_min": 400})
