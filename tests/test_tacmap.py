"""Tests for the unified tactical map aggregation."""
import tacmap as M


def test_normalize_unifies_ids_and_glyph():
    r = M.normalize({"source": "ais", "mmsi": 123, "type": "vessel", "lat": 39, "lon": -104})
    assert r["id"] == 123 and r["type"] == "vessel" and r["glyph"] == "▸"
    r2 = M.normalize({"uas_id": "UAS-1", "type": "drone", "lat": 1, "lon": 2}, source="dronewatch")
    assert r2["id"] == "UAS-1" and r2["source"] == "dronewatch" and r2["prio"] == 3


def test_collect_drops_positionless():
    sources = {
        "sky": [{"type": "aircraft", "id": "UAL1", "lat": 39.6, "lon": -104.9}],
        "ais": [{"type": "vessel", "mmsi": 1, "lat": None, "lon": None}],    # no fix -> dropped
    }
    out = M.collect(sources)
    assert len(out) == 1 and out[0]["type"] == "aircraft" and out[0]["source"] == "sky"


def test_filter_by_type_source_age():
    cs = [
        {"id": "a", "type": "drone", "source": "dronewatch", "lat": 1, "lon": 1, "ts": 100},
        {"id": "b", "type": "vessel", "source": "ais", "lat": 2, "lon": 2, "ts": 50},
    ]
    assert len(M.filter_contacts(cs, types=["drone"])) == 1
    assert len(M.filter_contacts(cs, sources=["ais"])) == 1
    assert len(M.filter_contacts(cs, max_age_s=30, now=110)) == 1       # only 'a' is fresh


def test_bounds_and_nearest_and_counts():
    cs = M.collect({"m": [
        {"type": "aircraft", "id": "x", "lat": 39.5, "lon": -105.0},
        {"type": "drone", "id": "y", "lat": 39.7, "lon": -104.8},
    ]})
    assert M.bounds(cs) == (39.5, -105.0, 39.7, -104.8)
    assert M.nearest(cs, 39.69, -104.81)["id"] == "y"
    assert M.counts_by_type(cs) == {"aircraft": 1, "drone": 1}


def test_bounds_empty():
    assert M.bounds([]) is None and M.nearest([], 0, 0) is None
