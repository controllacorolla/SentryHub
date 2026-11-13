"""Tests for the alert engine (Phase 3c)."""
import alerts


def _engine():
    got = []
    e = alerts.AlertEngine(deliver=got.append)
    return e, got


def test_threshold_fires_and_reports():
    e, got = _engine()
    e.add_rule({"id": "low", "name": "Low altitude", "type": "threshold",
                "params": {"field": "alt_m", "op": "<", "value": 120}})
    assert e.feed({"id": "d1", "alt_m": 200}) == []
    fired = e.feed({"id": "d1", "alt_m": 90})
    assert len(fired) == 1 and got[-1]["rule_id"] == "low" and "alt_m < 120" in got[-1]["text"]


def test_threshold_missing_field_is_safe():
    e, _ = _engine()
    e.add_rule({"id": "r", "type": "threshold", "params": {"field": "x", "op": ">", "value": 1}})
    assert e.feed({"id": "d"}) == []


def test_presence_fires_once_per_entity_with_filter():
    e, _ = _engine()
    e.add_rule({"id": "newdrone", "type": "presence", "params": {"match": {"type": "drone"}}})
    assert len(e.feed({"id": "uasA", "type": "drone"})) == 1
    assert e.feed({"id": "uasA", "type": "drone"}) == []        # already seen
    assert e.feed({"id": "planeB", "type": "aircraft"}) == []   # filtered out
    assert len(e.feed({"id": "uasB", "type": "drone"})) == 1


def test_geofence_enter_and_exit_transitions():
    e, _ = _engine()
    e.add_rule({"id": "enter", "type": "geofence",
                "params": {"lat": 39.0, "lon": -104.0, "radius_nm": 1.0, "mode": "enter"}})
    e.add_rule({"id": "exit", "type": "geofence",
                "params": {"lat": 39.0, "lon": -104.0, "radius_nm": 1.0, "mode": "exit"}})
    assert e.feed({"id": "d", "lat": 40.0, "lon": -104.0}) == []           # far, outside
    fired = [a["rule_id"] for a in e.feed({"id": "d", "lat": 39.001, "lon": -104.0})]
    assert "enter" in fired                                                # moved inside
    assert e.feed({"id": "d", "lat": 39.001, "lon": -104.0}) == []         # still inside, no re-enter
    fired = [a["rule_id"] for a in e.feed({"id": "d", "lat": 40.0, "lon": -104.0})]
    assert "exit" in fired                                                 # moved out


def test_anomaly_fires_on_deviation_after_baseline():
    e, _ = _engine()
    e.add_rule({"id": "noise", "type": "anomaly",
                "params": {"field": "floor_db", "k": 3.0, "min_samples": 5}})
    for i in range(12):
        # a realistic noise floor jitters a little, so std > 0
        assert e.feed({"id": "band", "floor_db": -100.0 + (0.5 if i % 2 else -0.5)}) == []
    fired = e.feed({"id": "band", "floor_db": -60.0})               # big jump off baseline
    assert len(fired) == 1 and "deviates" in fired[0]["detail"] and "σ" in fired[0]["detail"]


def test_compound_fires_when_both_within_window():
    e, got = _engine()
    e.add_rule({"id": "a", "type": "threshold", "params": {"field": "alt_m", "op": "<", "value": 120}})
    e.add_rule({"id": "b", "type": "presence", "params": {"match": {"type": "drone"}}})
    e.add_rule({"id": "both", "name": "Low new drone", "type": "compound",
                "params": {"rules": ["a", "b"], "window_s": 10}})
    fired = {a["rule_id"] for a in e.feed({"id": "uas1", "type": "drone", "alt_m": 90}, now=100.0)}
    assert fired == {"a", "b", "both"}


def test_disabled_rule_does_not_fire():
    e, _ = _engine()
    e.add_rule({"id": "r", "type": "threshold", "params": {"field": "v", "op": ">", "value": 0}})
    e.set_enabled("r", False)
    assert e.feed({"id": "x", "v": 5}) == []


def test_delivery_paths_preserved():
    e, got = _engine()
    e.add_rule({"id": "r", "type": "threshold", "delivery": ["banner", "speak"],
                "params": {"field": "v", "op": ">", "value": 0}})
    e.feed({"id": "x", "v": 1})
    assert got[-1]["delivery"] == ["banner", "speak"]


def test_export_import_roundtrip(tmp_path):
    e, _ = _engine()
    e.add_rule({"id": "low", "type": "threshold", "params": {"field": "alt_m", "op": "<", "value": 120}})
    p = tmp_path / "rules.json"
    assert e.save(str(p))
    e2, got2 = _engine()
    assert e2.load(str(p))
    assert e2.rules[0]["id"] == "low"
    assert len(e2.feed({"id": "d", "alt_m": 50})) == 1
