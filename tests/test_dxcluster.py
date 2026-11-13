"""Tests for the DX cluster parser (Phase 7 #4)."""
import dxcluster as DX


def test_band_from_khz():
    assert DX.band_from_khz(14074) == "20m"
    assert DX.band_from_khz(7030) == "40m"
    assert DX.band_from_khz(1) is None


def test_mode_from_comment():
    assert DX.mode_from_comment("FT8 -15 dB") == "FT8"
    assert DX.mode_from_comment("CQ CW") == "CW"
    assert DX.mode_from_comment("calling USB") == "SSB"
    assert DX.mode_from_comment("nothing here") is None


def test_parse_dx_spot():
    s = DX.parse_dx_spot("DX de W1ABC:     14074.0  JA1XYZ       FT8 -15 dB          1230Z")
    assert s["spotter"] == "W1ABC" and s["freq_khz"] == 14074.0 and s["dx_call"] == "JA1XYZ"
    assert s["band"] == "20m" and s["mode"] == "FT8" and s["time"] == "1230Z"


def test_parse_rejects_junk():
    assert DX.parse_dx_spot("not a spot line") is None


def test_spots_filter_by_band_and_mode():
    sp = DX.Spots()
    sp.add(DX.parse_dx_spot("DX de A: 14074.0 JA1X FT8 1200Z"))
    sp.add(DX.parse_dx_spot("DX de B: 7030.0 EA1Y CW 1201Z"))
    sp.add(DX.parse_dx_spot("DX de C: 14250.0 VK3Z SSB 1202Z"))
    assert len(sp.recent(band="20m")) == 2
    assert len(sp.recent(mode="CW")) == 1
    assert sp.recent()[0]["dx_call"] == "VK3Z"          # most recent first


def test_active_bands():
    sp = DX.Spots()
    sp.add(DX.parse_dx_spot("DX de A: 14074.0 JA1X FT8 1200Z"))
    sp.add(DX.parse_dx_spot("DX de B: 14030.0 EA1Y CW 1201Z"))
    sp.add(DX.parse_dx_spot("DX de C: 7030.0 VK3Z CW 1202Z"))
    assert DX.active_bands if False else sp.active_bands()["20m"] == 2
