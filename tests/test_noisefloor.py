"""Tests for the noise-floor survey (Phase 7 #1)."""
import noisefloor as NF


def test_parse_rtl_power_row():
    row = "2026-11-12, 12:00:00, 24000000, 24003000, 1000.00, 100, -40.5, -41.2, -39.8"
    r = NF.parse_rtl_power_row(row)
    assert r["f_low"] == 24_000_000 and r["step"] == 1000
    assert r["bins"][0] == (24_000_000, -40.5)
    assert r["bins"][2] == (24_002_000, -39.8)


def test_parse_rejects_short_row():
    assert NF.parse_rtl_power_row("too, few, fields") is None


def test_band_floor_median():
    bins = [(1e6, -100), (2e6, -98), (3e6, -102), (4e6, -40)]   # one emitter at 4 MHz
    assert NF.band_floor(bins, 1e6, 3e6) == -100.0              # ignores the 4 MHz spike


def test_baseline_learns_minimum_and_finds_new_signal():
    nf = NF.NoiseFloor(bin_key_hz=1_000)
    # three quiet sweeps establish the floor near -100
    for _ in range(3):
        nf.update([(100_000, -100), (101_000, -99), (102_000, -101)])
    # a new emitter appears at 101 kHz, 30 dB over floor
    new = nf.new_signals([(100_000, -100), (101_000, -69), (102_000, -101)], threshold_db=10)
    assert len(new) == 1 and new[0]["freq_hz"] == 101_000
    assert abs(new[0]["over_db"] - 30) < 1e-6


def test_no_new_signal_when_at_floor():
    nf = NF.NoiseFloor(bin_key_hz=1_000)
    nf.update([(100_000, -100), (101_000, -100)])
    assert nf.new_signals([(100_000, -99), (101_000, -98)], threshold_db=10) == []


def test_summary():
    nf = NF.NoiseFloor(bin_key_hz=1_000)
    nf.update([(1e6, -100), (2e6, -90)])
    s = nf.summary()
    assert s["bins"] == 2 and s["floor_min"] == -100 and s["sweeps"] == 1
