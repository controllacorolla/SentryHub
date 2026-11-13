"""Tests for the spectrum analyzer (trace math, peaks, markers, channel power). Receive-only."""
import math

import specan as A


def _bins(dbm, lo=100_000_000, step=1_000_000):
    return [(lo + i * step, d) for i, d in enumerate(dbm)]


def test_rbw():
    assert A.rbw_hz(430_000_000, 470_000_000, 160) == 250_000.0
    assert A.rbw_hz(0, 1, 0) is None


def test_maxhold_and_average():
    sp = A.Spectrum(avg_alpha=0.5)
    sp.add(_bins([-100, -50, -100]))
    sp.add(_bins([-100, -90, -40]))      # bin1 dropped, bin2 rose
    assert sp.maxhold == [-100, -50, -40]        # per-bin max across both sweeps
    assert sp.cur == [-100, -90, -40]
    # exponential avg of bin1: start -50, then 0.5*-90 + 0.5*-50 = -70
    assert abs(sp.avg[1] - (-70.0)) < 1e-9


def test_reset_hold():
    sp = A.Spectrum()
    sp.add(_bins([-100, -40, -100]))
    sp.add(_bins([-100, -100, -100]))
    assert sp.maxhold[1] == -40
    sp.reset_hold()
    assert sp.maxhold == sp.cur == [-100, -100, -100]


def test_find_peaks():
    dbm = [-100, -100, -45, -100, -100, -55, -100]
    bins = _bins(dbm)
    pk = A.find_peaks([f for f, _ in bins], dbm, n=5, above_floor_db=10)
    freqs = [p["freq_hz"] for p in pk]
    assert bins[2][0] in freqs and bins[5][0] in freqs and len(pk) == 2


def test_nearest_marker_and_delta():
    sp = A.Spectrum()
    sp.add(_bins([-90, -50, -70], lo=100_000_000, step=1_000_000))
    m = sp.nearest(100_400_000)           # closest to bin 0 (100.0) vs bin1(101.0) -> bin0
    assert m["bin"] == 0 and m["dbm"] == -90
    m1 = sp.nearest(100_000_000)
    m2 = sp.nearest(102_000_000)
    d = A.marker_delta(m1, m2)
    assert d["dfreq_hz"] == 2_000_000 and d["ddbm"] == -70 - (-90)
    assert A.marker_delta(None, m2) is None


def test_channel_power():
    # two equal -40 dBm bins integrate to -40 + 10log10(2) ≈ -36.99 dBm
    freqs = [100e6, 101e6, 102e6]
    dbm = [-100, -40, -40]
    cp = A.channel_power(freqs, dbm, 100.5e6, 102.5e6)
    assert abs(cp - (-40 + 10 * math.log10(2))) < 0.01
    assert A.channel_power(freqs, [-200, -200, -200], 0, 0) is None   # nothing in band


def test_db_to_y():
    # ref -20 at top (y=0), range 90 -> -110 at bottom (y=h)
    assert A.db_to_y(-20, -20, 90, 100) == 0
    assert A.db_to_y(-110, -20, 90, 100) == 100
    assert A.db_to_y(-65, -20, 90, 100) == 50
    assert A.db_to_y(10, -20, 90, 100) == 0        # above ref clamps to top


def test_demo_has_signals():
    sp = A.Spectrum()
    sp.add(A.Demo().sweep())
    pk = sp.peaks(n=5, above_floor_db=12)
    assert len(pk) >= 2        # the two steady carriers at least
