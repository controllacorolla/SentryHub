"""Tests for the contact fusion engine (Phase 3d)."""
import fusion


def test_shared_callsign_merges_to_one_card_with_badges():
    e = fusion.FusionEngine()
    e.submit({"source": "adsb", "callsign": "UAL123", "lat": 39.6, "lon": -104.9, "alt_m": 9000}, now=100)
    e.submit({"source": "acars", "callsign": "UAL123", "msg": "OOOI"}, now=101)
    cards = e.contacts(now=101)
    assert len(cards) == 1
    assert cards[0]["badges"] == ["acars", "adsb"]
    assert cards[0]["label"] == "UAL123" and cards[0]["alt_m"] == 9000


def test_position_time_proximity_merges():
    e = fusion.FusionEngine(pos_tol_nm=0.5, time_tol_s=30)
    e.submit({"source": "adsb", "hex": "ae01", "lat": 39.600, "lon": -104.900}, now=100)
    e.submit({"source": "modeac", "lat": 39.6005, "lon": -104.9003}, now=110)   # ~0.03 nm away
    assert len(e.contacts(now=110)) == 1


def test_far_apart_stay_separate():
    e = fusion.FusionEngine(pos_tol_nm=0.5)
    e.submit({"source": "adsb", "lat": 39.6, "lon": -104.9}, now=100)
    e.submit({"source": "adsb", "lat": 40.6, "lon": -104.9}, now=100)      # ~60 nm away
    assert len(e.contacts(now=100)) == 2


def test_dronewatch_and_ble_scanner_merge_by_addr():
    e = fusion.FusionEngine()
    e.submit({"source": "dronewatch", "uas_id": "UAS-1", "ble_addr": "AA:01",
              "lat": 39.7, "lon": -104.8}, now=50)
    e.submit({"source": "ble", "ble_addr": "AA:01", "name": "DJI-xyz"}, now=51)
    cards = e.contacts(now=51)
    assert len(cards) == 1 and set(cards[0]["badges"]) == {"ble", "dronewatch"}
    assert cards[0]["label"] == "UAS-1"


def test_conflicting_ids_block_proximity_merge():
    e = fusion.FusionEngine(pos_tol_nm=1.0)
    e.submit({"source": "adsb", "hex": "aaa", "lat": 39.6, "lon": -104.9}, now=100)
    # same spot, different strong id -> must NOT merge
    e.submit({"source": "adsb", "hex": "bbb", "lat": 39.6001, "lon": -104.9001}, now=101)
    assert len(e.contacts(now=101)) == 2


def test_latest_position_wins_and_stale_pruned():
    e = fusion.FusionEngine(stale_s=60)
    e.submit({"source": "adsb", "icao": "x1", "lat": 39.6, "lon": -104.9}, now=100)
    e.submit({"source": "adsb", "icao": "x1", "lat": 39.7, "lon": -104.8}, now=140)
    card = e.contacts(now=140)[0]
    assert card["lat"] == 39.7 and card["lon"] == -104.8
    assert e.contacts(now=250) == []       # stale
    e.prune(now=250)
    assert e.cards == []
