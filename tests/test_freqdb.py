"""Tests for the frequency allocation database (Phase 6 #3)."""
import freqdb


def test_lookup_fm_broadcast():
    hits = freqdb.lookup(100.3e6)
    assert any(a[2] == "FM broadcast" for a in hits)
    assert "FM broadcast" in freqdb.describe(100.3e6)


def test_lookup_amateur_20m():
    assert "Amateur" in freqdb.describe(14.074e6)


def test_lookup_gps_l1():
    assert "GNSS" in freqdb.describe(1575.42e6)


def test_lookup_unallocated_gap():
    assert freqdb.describe(70e6) == "unallocated / unknown"     # between 6 m and FM


def test_lookup_returns_narrowest_first():
    # 162.45 MHz is inside both Marine VHF (wide) and NWR (narrow) -> NWR first
    hits = freqdb.lookup(162.45e6)
    assert hits[0][2] == "NOAA Weather Radio"


def test_search_by_service_and_notes():
    assert any(a[2] == "Marine VHF" for a in freqdb.search("marine"))
    assert any("AIS" in a[3] for a in freqdb.search("ais"))
    assert any(a[2] == "Iridium" for a in freqdb.search("iridium"))


def test_cross_reference_annotates_signals():
    sigs = [{"freq_hz": 14.074e6, "power": -40}, {"freq_hz": 1090e6}, {"freq_hz": None}]
    out = freqdb.cross_reference(sigs)
    assert "Amateur" in out[0]["allocation"]
    assert "radionav" in out[1]["allocation"].lower()
    assert out[2]["allocation"] == "?"


def test_allocations_are_well_formed():
    for lo, hi, svc, note in freqdb.ALLOCATIONS:
        assert lo <= hi and isinstance(svc, str) and isinstance(note, str)
