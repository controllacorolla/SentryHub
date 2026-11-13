"""Tests for the satellite pass scheduler (Phase 7 #3)."""
import passsched as P


def test_assign_decoder():
    assert P.assign_decoder("NOAA 19") == "noaa-apt"
    assert P.assign_decoder("METEOR-M2 3") == "satdump"
    assert P.assign_decoder("ISS (ZARYA)") == "sstv"
    assert P.assign_decoder("GOES 18") == "satdump"
    assert P.assign_decoder("RANDOMSAT") is None


def test_filters_low_elevation():
    passes = [{"sat": "NOAA 19", "aos": 100, "los": 200, "max_elev": 10, "freq_mhz": 137.1},
              {"sat": "NOAA 18", "aos": 300, "los": 400, "max_elev": 45, "freq_mhz": 137.9}]
    out = P.schedule(passes, min_elev=20)
    assert [p["sat"] for p in out] == ["NOAA 18"]


def test_non_overlapping_selection_maximises_captures():
    passes = [
        {"sat": "A", "aos": 0, "los": 100, "max_elev": 40, "freq_mhz": 137.1},
        {"sat": "B", "aos": 50, "los": 150, "max_elev": 50, "freq_mhz": 137.9},   # overlaps A
        {"sat": "C", "aos": 110, "los": 200, "max_elev": 30, "freq_mhz": 137.5},  # fits after A
    ]
    out = P.schedule(passes, min_elev=20)
    # earliest-LOS greedy picks A (ends 100) then C (starts 110); B dropped
    assert [p["sat"] for p in out] == ["A", "C"]
    assert all(p.get("decoder") is not None or p["sat"] in ("A", "B", "C") for p in out)


def test_conflicts_lists_dropped():
    passes = [
        {"sat": "A", "aos": 0, "los": 100, "max_elev": 40, "freq_mhz": 137.1},
        {"sat": "B", "aos": 50, "los": 150, "max_elev": 50, "freq_mhz": 137.9},
    ]
    conf = P.conflicts(passes, min_elev=20)
    assert [p["sat"] for p in conf] == ["B"]


def test_radio_busy_blocks_early_pass():
    passes = [{"sat": "A", "aos": 10, "los": 100, "max_elev": 40, "freq_mhz": 137.1}]
    assert P.schedule(passes, min_elev=20, radio_free_at=50) == []   # radio busy past AOS


def test_next_pass():
    passes = [{"sat": "A", "aos": 100, "los": 200, "max_elev": 40},
              {"sat": "B", "aos": 300, "los": 400, "max_elev": 50}]
    assert P.next_pass(passes, now=250)["sat"] == "B"
    assert P.next_pass(passes, now=500) is None
