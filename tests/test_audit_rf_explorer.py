"""Regression tests for bugs fixed in rf_explorer.py during the code audit."""
import math

import rf_explorer as R


def test_parse_row_replaces_nan_and_inf_keeping_alignment():
    ln = "2026-11-08, 21:50:01, 88000000, 90000000, 50000.0, 32, nan, -29.5, -inf, -8.2, inf"
    hz_lo, step, dbs = R.parse_row(ln)
    assert len(dbs) == 5, "bins dropped: frequency mapping would shift"
    assert all(math.isfinite(v) for v in dbs)
    assert dbs[1] == -29.5 and dbs[3] == -8.2


def test_parse_row_all_nonfinite_is_none():
    assert R.parse_row("d, t, 88000000, 90000000, 50000.0, 32, nan, -inf") is None


def test_assembler_output_safe_for_median_and_scale():
    a = R.SweepAssembler()
    r1 = "d, t, 88000000, 90000000, 1000000.0, 32, nan, -20"
    r2 = "d, t, 90000000, 92000000, 1000000.0, 32, -25, -inf"
    a.feed(r1), a.feed(r2)
    freqs, dbs = a.feed(r1)
    assert len(freqs) == len(dbs) == 4
    assert all(math.isfinite(v) for v in dbs)
