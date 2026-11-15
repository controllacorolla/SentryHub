"""entity_graph — multi-radio identity resolution engine (pure).

Covers the brief's acceptance list at the engine level: temporal + spatial co-occurrence, the
confirmation threshold, thresholds frozen at promotion time, persistence + stable UUIDs, deterministic
match-on-return, flapping, temporal-only (no GNSS), demo flagging, the full evidence paper-trail, and
evidence export. No Qt, no hardware.
"""
import json
import os
import sys

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

import entity_graph as eg


def obs(source, kind, raw, t, lat=None, lon=None, rssi=None, demo=False):
    return {"source": source, "identifier": "%s:%s" % (kind, raw), "kind": kind, "t": t,
            "lat": lat, "lon": lon, "rssi": rssi, "demo": demo}


def cfg(**over):
    c = {"temporal_window_s": 90, "spatial_window_m": 50, "promotion_n": 3, "promotion_m": 3,
         "window_bucket_s": 600, "ttl_s": 3600}
    c.update(over)
    return c


def _confirm_two_sources(g, s1, s2, base=1_000_000, pos=(47.61, -122.33)):
    """Drive 3 co-located co-occurrences across 3 distinct 10-min windows -> confirmation."""
    events = []
    for w in range(3):
        t = base + w * 700
        events += g.ingest(obs(*s1, t=t, lat=pos[0], lon=pos[1]))
        events += g.ingest(obs(*s2, t=t, lat=pos[0], lon=pos[1]))
    return events


# ---- temporal + spatial co-occurrence ----
def test_temporal_cooccurrence_links_across_sources():
    g = eg.EntityGraph(config=cfg())
    events = _confirm_two_sources(g, ("WiFi", "wifi", "AA:01"), ("BLE", "ble", "d0:02"))
    assert any(e["change"] == "confirmed" for e in events)
    ents = g.entities()
    assert len(ents) == 1
    e = ents[0]
    assert e["status"] == "confirmed"
    assert set(e["identifiers"]) == {"wifi:AA:01", "ble:d0:02"}
    assert e["source_breakdown"] == {"WiFi": 3, "BLE": 3}


def test_spatial_requires_both_positions_and_proximity():
    # both positioned but 500m apart -> never co-occur -> two separate candidates
    g = eg.EntityGraph(config=cfg())
    for w in range(3):
        t = 1000 + w * 700
        g.ingest(obs("WiFi", "wifi", "A", t=t, lat=47.60, lon=-122.33))
        g.ingest(obs("BLE", "ble", "B", t=t, lat=47.61, lon=-122.33))   # ~1.1 km north
    assert all(e["status"] == "candidate" for e in g.entities())
    assert len(g.entities()) == 2
    # within 50 m -> links and confirms
    g2 = eg.EntityGraph(config=cfg())
    _confirm_two_sources(g2, ("WiFi", "wifi", "A"), ("BLE", "ble", "B"), pos=(47.6000, -122.3300))
    assert any(e["status"] == "confirmed" for e in g2.entities())


def test_no_gnss_runs_temporal_only():
    g = eg.EntityGraph(config=cfg())
    # neither side has a position -> temporal-only co-occurrence still links
    events = []
    for w in range(3):
        t = 2000 + w * 700
        events += g.ingest(obs("WiFi", "wifi", "A", t=t))
        events += g.ingest(obs("TPMS", "tpms", "T", t=t))
    conf = [e for e in g.entities() if e["status"] == "confirmed"]
    assert conf and conf[0]["resolver_thresholds_at_promotion"]["spatial_used"] is False


# ---- confirmation threshold ----
def test_below_threshold_is_candidate_at_threshold_is_confirmed():
    g = eg.EntityGraph(config=cfg(promotion_n=3, promotion_m=3))
    # two windows only -> below M -> candidate
    for w in range(2):
        t = 5000 + w * 700
        g.ingest(obs("WiFi", "wifi", "A", t=t, lat=1.0, lon=1.0))
        g.ingest(obs("BLE", "ble", "B", t=t, lat=1.0, lon=1.0))
    assert all(e["status"] == "candidate" for e in g.entities())
    cooc, win, n, m = g.candidate_progress(g.lookup("wifi:A")["entity_uuid"])
    assert cooc == 2 and win == 2 and n == 3 and m == 3
    # third window -> confirmed
    t = 5000 + 2 * 700
    g.ingest(obs("WiFi", "wifi", "A", t=t, lat=1.0, lon=1.0))
    g.ingest(obs("BLE", "ble", "B", t=t, lat=1.0, lon=1.0))
    assert any(e["status"] == "confirmed" for e in g.entities())


def test_thresholds_are_frozen_at_promotion_not_rewritten():
    g = eg.EntityGraph(config=cfg(promotion_n=3, promotion_m=3))
    _confirm_two_sources(g, ("WiFi", "wifi", "A"), ("BLE", "ble", "B"))
    frozen = g.entities()[0]["resolver_thresholds_at_promotion"]
    assert frozen["promotion_n"] == 3 and frozen["promotion_m"] == 3
    assert frozen["temporal_window_s"] == 90 and frozen["spatial_window_m"] == 50
    # later threshold change must NOT rewrite the recorded history
    g.cfg["promotion_n"] = 99
    g.cfg["temporal_window_s"] = 5
    assert g.entities()[0]["resolver_thresholds_at_promotion"]["promotion_n"] == 3
    assert g.entities()[0]["resolver_thresholds_at_promotion"]["temporal_window_s"] == 90


def test_same_source_does_not_link():
    g = eg.EntityGraph(config=cfg())
    for w in range(3):                                  # two aircraft, same source -> never one entity
        t = 7000 + w * 700
        g.ingest(obs("ADS-B", "aircraft", "DAL1", t=t, lat=1.0, lon=1.0))
        g.ingest(obs("ADS-B", "aircraft", "UAL2", t=t, lat=1.0, lon=1.0))
    assert len(g.entities()) == 2 and all(e["status"] == "candidate" for e in g.entities())


# ---- persistence + match-on-return ----
def test_persistence_roundtrip_and_stable_uuid(tmp_path):
    g = eg.EntityGraph(config=cfg(), session="20260101")
    _confirm_two_sources(g, ("WiFi", "wifi", "MAC1"), ("BLE", "ble", "B1"))
    uuid0 = g.entities()[0]["entity_uuid"]
    path = g.save(str(tmp_path / "eg.json"))
    assert os.path.exists(path)
    loaded = eg.EntityGraph.load(path)
    assert loaded.lookup("wifi:MAC1")["entity_uuid"] == uuid0        # UUID stable across save/load


def test_match_on_return_is_deterministic(tmp_path):
    g = eg.EntityGraph(config=cfg(), session="day1")
    _confirm_two_sources(g, ("WiFi", "wifi", "MACX"), ("BLE", "ble", "BY"))
    uuid0 = g.entities()[0]["entity_uuid"]
    prior = g.to_dict()
    # new session: same MAC reappears -> links to the historical UUID via the deterministic path
    index = eg.historical_index([prior])
    g2 = eg.EntityGraph(config=cfg(), session="day4", historical=index)
    events = g2.ingest(obs("WiFi", "wifi", "MACX", t=9_000_000, lat=1.0, lon=1.0))
    assert any(e["change"] == "recognized" for e in events)
    ent = g2.lookup("wifi:MACX")
    assert ent["entity_uuid"] == uuid0                              # recognised = same identity
    assert ent["recognition_links"] and ent["recognition_links"][0]["identifier"] == "wifi:MACX"


def test_flapping_identifier_decays_then_reappears():
    g = eg.EntityGraph(config=cfg(ttl_s=300))
    g.ingest(obs("WiFi", "wifi", "FLAP", t=0.0, lat=1.0, lon=1.0))
    assert g.lookup("wifi:FLAP") is not None
    gone = g.decay(now=400.0)                                        # past TTL -> dropped
    assert any(e["change"] == "disappeared" for e in gone)
    assert g.lookup("wifi:FLAP") is None
    g.ingest(obs("WiFi", "wifi", "FLAP", t=500.0, lat=1.0, lon=1.0))  # reappears -> fresh candidate
    assert g.lookup("wifi:FLAP") is not None


# ---- honesty / evidence ----
def test_demo_flagged_throughout():
    g = eg.EntityGraph(config=cfg())
    _confirm_two_sources(g, ("WiFi", "wifi", "A"), ("BLE", "ble", "B"))
    # re-run tagging demo
    g2 = eg.EntityGraph(config=cfg())
    for w in range(3):
        t = w * 700
        g2.ingest(obs("WiFi", "wifi", "A", t=t, lat=1.0, lon=1.0, demo=True))
        g2.ingest(obs("BLE", "ble", "B", t=t, lat=1.0, lon=1.0, demo=True))
    assert g2.entities()[0]["demo"] is True


def test_confirmed_entity_carries_every_evidence_field():
    g = eg.EntityGraph(config=cfg())
    _confirm_two_sources(g, ("WiFi", "wifi", "A"), ("BLE", "ble", "B"))
    e = g.entities()[0]
    for field in ("entity_uuid", "status", "confirmation_score", "first_seen", "last_seen",
                  "identifiers", "source_breakdown", "link_history", "recognition_links",
                  "resolver_thresholds_at_promotion", "positions"):
        assert field in e, "missing evidence field %s" % field
    assert e["confirmation_score"] >= 3
    assert e["link_history"] and "co_with" in e["link_history"][0]


def test_export_entity_is_valid_json_with_evidence_and_engagement():
    g = eg.EntityGraph(config=cfg())
    _confirm_two_sources(g, ("WiFi", "wifi", "A"), ("BLE", "ble", "B"))
    export = eg.export_entity(g.entities()[0], engagement_uuid="ENG-123", now=1000.0)
    blob = json.dumps(export)                                        # must serialise cleanly
    back = json.loads(blob)
    assert back["engagement_uuid"] == "ENG-123"
    assert back["entity"]["resolver_thresholds_at_promotion"]["promotion_n"] == 3
    assert set(back["entity"]["identifiers"]) == {"wifi:A", "ble:B"}


def test_observation_from_contact_normalises_and_namespaces():
    ev = {"type": "contact", "source": "AIS", "ts": 10.0,
          "payload": {"id": "366123456", "kind": "vessel", "lat": 47.6, "lon": -122.3}}
    o = eg.observation_from_contact(ev, demo=False)
    assert o["identifier"] == "vessel:366123456" and o["source"] == "AIS" and o["lat"] == 47.6
    assert eg.observation_from_contact({"type": "alert"}) is None    # non-contact ignored
