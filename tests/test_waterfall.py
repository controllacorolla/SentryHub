"""Tests for the spectrum waterfall (Phase 6 #1)."""
import waterfall as W


def _bins(vals, f0=400_000_000, step=100_000):
    return [(f0 + i * step, v) for i, v in enumerate(vals)]


def test_add_sweep_caps_rows_and_sets_freqs():
    wf = W.Waterfall(max_rows=3)
    for _ in range(5):
        wf.add_sweep(_bins([-100, -98, -99]))
    assert len(wf.rows) == 3 and len(wf.freqs) == 3


def test_peak_hold_tracks_max():
    wf = W.Waterfall()
    wf.add_sweep(_bins([-100, -60, -100]))
    wf.add_sweep(_bins([-100, -100, -70]))
    assert wf.peak_hold[400_100_000] == -60       # held the earlier strong value
    assert wf.peak_hold[400_200_000] == -70


def test_noise_floor_median():
    wf = W.Waterfall()
    wf.add_sweep(_bins([-100, -100, -40, -100, -100]))
    assert wf.noise_floor() == -100               # the one spike doesn't move the median


def test_peaks_detection():
    wf = W.Waterfall()
    # floor ~-100, two peaks at idx 2 (-50) and idx 6 (-60)
    wf.add_sweep(_bins([-100, -100, -50, -100, -100, -100, -60, -100]))
    pk = wf.peaks(above_floor_db=8, n=5)
    freqs = [p["freq_hz"] for p in pk]
    assert 400_200_000 in freqs and 400_600_000 in freqs
    assert pk[0]["over_db"] > 8


def test_sweep_argv():
    argv = W.rtl_power_sweep_argv(400e6, 500e6, 100_000, "wf.csv", gain=20)
    assert argv[0] == "rtl_power" and "400000000:500000000:100000" in argv


def test_parse_sweep_delegates():
    bins = W.parse_sweep("d, t, 24000000, 24000200, 100.0, 50, -40.0, -41.0, -39.0")
    assert bins[0] == (24_000_000, -40.0)


def test_heat_color_floor_vs_strong():
    floor = W.heat_color(-110)
    strong = W.heat_color(-20)
    assert floor.startswith("#") and len(floor) == 7
    # floor is blue-dominant, strong is red-dominant
    assert int(floor[5:7], 16) > int(floor[1:3], 16)      # blue > red near the floor
    assert int(strong[1:3], 16) > int(strong[5:7], 16)    # red > blue when strong


def test_demo_sweep_has_signal_above_floor():
    dm = W.Demo(bins=120)
    bins = dm.sweep()
    assert len(bins) == 120
    dbs = [db for _, db in bins]
    assert max(dbs) > -70 and min(dbs) < -100            # a signal and a floor
