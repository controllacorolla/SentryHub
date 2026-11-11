import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ops as O  # noqa: E402
import aprs as A  # noqa: E402

HOME = (39.62, -104.87)


def ents(now=1000.0):
    acs = [{"hex": "a835af", "flight": "UAL1234 ", "lat": 39.7, "lon": -104.8, "alt_baro": 36000,
            "gs": 452, "track": 270, "seen": 1},
           {"hex": "ae01ce", "flight": "RCH471", "lat": 39.6, "lon": -104.6, "alt_baro": 24000,
            "gs": 410, "squawk": "7700"},
           {"hex": "abc123", "flight": "NOPOS"},
           {"hex": "abc124", "lat": "junk", "lon": None}]
    st = A.Stations()
    st.add(A.decode(A.parse_frame("KD0ABC-9>APRS:=3937.20N/10452.20W>090/030")), now - 30)
    st.add(A.decode(A.parse_frame("KC0WX>APRS:!3940.00N/10450.00W_220/004t045h65")), now - 9000)
    sondes = [{"id": "LMS6-1", "lat": 39.9, "lon": -104.5, "alt": 12000, "phase": "ascending",
               "t": now, "track": [[39.8, -104.6], [39.9, -104.5]]}, {"id": "bad", "lat": None}]
    mesh = [{"id": "!a1", "short": "KAPA", "lat": 39.57, "lon": -104.85, "last": now - 10},
            {"id": "!me", "lat": 39.6, "lon": -104.8, "me": True}]
    return O.build_entities(acs, st.s, sondes, mesh, HOME, now,
                            mil=lambda a: a["hex"].startswith("ae"))


def test_fusion_shapes_and_counts():
    e = {x["id"]: x for x in ents()}
    assert set(e) == {"air:a835af", "air:ae01ce", "aprs:KD0ABC-9", "aprs:KC0WX",
                      "sonde:LMS6-1", "mesh:!a1"}
    assert e["air:ae01ce"]["kind"] == "mil" and e["air:ae01ce"]["alert"]
    assert e["air:a835af"]["label"] == "UAL1234" and e["air:a835af"]["dist_nm"] > 0
    assert e["aprs:KC0WX"]["stale"] is False            # 2.5 h < 3 h APRS window
    assert e["sonde:LMS6-1"]["alt_ft"] == pytest.approx(39370, rel=1e-3)
    for x in e.values():
        assert {"id", "kind", "label", "lat", "lon", "props", "t", "key"} <= set(x)


@pytest.mark.parametrize("q,want", [("", 6), ("mil", 1), ("air", 2), ("aprs", 2), ("sonde", 1),
                                    ("high", 2), ("fast", 2), ("alert", 1), ("ual", 1),
                                    ("air high", 1), ("kapa", 1), ("zzz", 0), ("near", None)])
def test_search(q, want):
    got = [x for x in ents() if O.match(x, q)]
    if want is not None:
        assert len(got) == want, (q, [x["id"] for x in got])


def test_timeline_and_links():
    now = 10000.0
    rows = [{"t": now - 10, "app": "sky", "kind": "contact", "text": "x", "id": "a835af"},
            {"t": now - 7200, "app": "sky", "text": "old"}, {"t": "bad"}, "notadict",
            {"t": now - 5, "app": "aprs", "kind": "aprs", "text": "y", "id": "KD0ABC-9"}]
    tl = O.timeline(rows, now)
    assert [r[1] for r in tl] == ["sky", "aprs"]
    e = ents()
    assert O.link_id("sky", "a835af", e) == "air:a835af"
    assert O.link_id("aprs", "KD0ABC-9", e) == "aprs:KD0ABC-9"
    assert O.link_id("aprs", "nope", e) is None and O.link_id("sky", "", e) is None


def test_board_persistence(tmp_path):
    p = str(tmp_path / "b.json")
    O.save_board(p, {"air:a": "watching", "aprs:b": "logged", "x": "bogus"})
    assert O.load_board(p) == {"air:a": "watching", "aprs:b": "logged"}
    open(p, "w").write("[1,2]")
    assert O.load_board(p) == {}


def test_demo_extras_are_valid():
    st, sondes, mesh = O.demo_extras(HOME, time.time())
    e = O.build_entities([], st, sondes, mesh, HOME, time.time())
    kinds = {x["kind"] for x in e}
    assert kinds == {"aprs", "sonde", "mesh"}
    assert all(x["label"].startswith(("DEMO", "LMS6", "KAPA", "GLDN")) for x in e)


@pytest.mark.parametrize("q,want", [("within:5", {"mesh:!a1", "aprs:KD0ABC-9"}), ("above:30000", {"air:a835af", "sonde:LMS6-1"}),
                                    ("air below:30000", {"air:ae01ce"}), ("within:abc", set()),
                                    ("mil within:25", {"air:ae01ce"})])
def test_search_ranges(q, want):
    got = {x["id"] for x in ents() if O.match(x, q)}
    if q == "within:5":
        assert want <= got and "air:ae01ce" not in got
    else:
        assert got == want


def test_watcher_fires_once_and_rearms():
    w = O.Watcher([{"name": "Mil", "q": "mil within:25", "on": True},
                   {"name": "off", "q": "air", "on": False},
                   {"name": "empty", "q": "  ", "on": True}, "junk"], rearm=300)
    assert [r["name"] for r in w.rules] == ["Mil"]
    e = ents()
    a = w.check(e, 1000)
    assert len(a) == 1 and a[0]["id"] == "air:ae01ce" and "RCH471" in a[0]["text"]
    assert w.check(e, 1010) == []                      # still matching: no repeat
    assert w.check([], 1100) == [] and w.check(e, 1200) == []   # brief dropout: no repeat
    assert w.check([], 1600) == []                     # gone > rearm
    assert len(w.check(e, 1700)) == 1                  # comes back: alerts again
    stale = [dict(x, stale=True) for x in e]
    assert O.Watcher([{"q": "alert"}]).check(stale, 1) == []


def test_history_rewind_and_trail():
    h = O.History(span=100, step=10)
    mk = lambda lat: [{"id": "air:x", "lat": lat, "lon": -104.0}]
    assert h.at(5) == [] and h.first() is None
    for i in range(0, 200, 5):
        h.add(1000 + i, mk(39 + i / 1000))
    assert len(h.snaps) == 11 and h.first() == 1090    # 10 s steps, 100 s kept
    assert h.at(1125)[0]["lat"] == pytest.approx(39.12)
    assert h.at(0)[0]["lat"] == pytest.approx(39.09)   # before the window: oldest
    assert h.at(9999)[0]["lat"] == pytest.approx(39.19)
    tr = h.trail("air:x", 1150, 30)
    assert [round(p[0], 2) for p in tr] == [39.12, 39.13, 39.14, 39.15]
    assert h.trail("nope", 1150, 30) == []


def test_fusion_survives_malformed_records():
    import random
    rnd = random.Random(3)
    good = {"hex": "a835af", "lat": 39.7, "lon": -104.8, "flight": "UAL1 ", "alt_baro": 36000}
    junk = [None, 1, "x", [], {}, {"lat": "a"}, {"lat": 1e400}, {"lat": float("nan"), "lon": 0},
            {"hex": None, "lat": 1, "lon": 2}, {"hex": "zz", "lat": 39, "lon": -104, "flight": 5},
            {"hex": "abc", "lat": 999, "lon": 0}, good]
    for _ in range(200):
        e = O.build_entities([rnd.choice(junk) for _ in range(5)] + [good],
                             {rnd.choice(["A", 5, None]): rnd.choice(junk) for _ in range(3)},
                             [rnd.choice(junk) for _ in range(3)], [rnd.choice(junk) for _ in range(3)],
                             HOME, 1000.0)
        assert any(x["id"] == "air:a835af" for x in e)          # the good record always survives
        assert all(-85 <= x["lat"] <= 85 and -180 <= x["lon"] <= 180 for x in e)
        for x in e:
            O.match(x, "mil near high within:50 ual")
