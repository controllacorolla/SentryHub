import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rf_explorer as R


def test_parse_row_valid():
    ln = "2026-11-08, 21:50:01, 88000000, 90000000, 50000.0, 32, -30.1, -29.5, -8.2"
    hz_lo, step, dbs = R.parse_row(ln)
    assert hz_lo == 88000000 and step == 50000.0 and dbs == [-30.1, -29.5, -8.2]


def test_parse_row_junk():
    assert R.parse_row("garbage") is None
    assert R.parse_row("a, b, c, d, e, f, g, h") is None
    assert R.parse_row("") is None


def test_assembler_emits_on_wrap():
    a = R.SweepAssembler()
    r1 = "d, t, 88000000, 90000000, 1000000.0, 32, -30, -20"
    r2 = "d, t, 90000000, 92000000, 1000000.0, 32, -25, -15"
    assert a.feed(r1) is None and a.feed(r2) is None
    out = a.feed(r1)   # wrap: previous sweep comes out
    assert out is not None
    freqs, dbs = out
    assert freqs == [88.0, 89.0, 90.0, 91.0] and dbs == [-30, -20, -25, -15]


def test_find_peaks_orders_by_power():
    freqs = [100 + i * 0.1 for i in range(50)]
    dbs = [-35.0] * 50
    dbs[10], dbs[30] = -5.0, -12.0
    pk = R.find_peaks(freqs, dbs)
    assert [p[0] for p in pk] == [10, 30]


def test_find_peaks_ignores_flat_noise():
    freqs = list(range(30))
    assert R.find_peaks(freqs, [-35.0] * 30) == []


def test_demo_sweep_has_carriers_above_floor():
    freqs, dbs = R.demo_sweep(88.0, 108.0, 50.0, t=1.0)
    assert len(freqs) == len(dbs) > 100
    assert max(dbs) > -20 and sorted(dbs)[len(dbs) // 2] < -30


def test_tune_cmd_modes():
    assert "wbfm" in R.tune_cmd(98.5, "wbfm", 32)
    assert "am" in R.tune_cmd(121.5, "am", 32)
    c = R.tune_cmd(146.52, "nfm", 32)
    assert "fm" in c and "146.5200M" in c


def test_bands_sane():
    for name, lo, hi, step, mode in R.BANDS:
        assert 24.0 <= lo < hi <= 1766.0
        assert mode in ("am", "nfm", "wbfm")
        assert 5.0 <= step <= 100.0
