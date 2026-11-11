"""Regression tests for bugs fixed in wxsat.py during the code audit."""
import wxsat as W


def test_armed_pass_survives_repredict_jitter():
    armed = W.PassSet()
    armed.add({"sat": "METEOR-M2 3", "aos": 1_800_000_000.0})
    # hourly re-prediction moves the rise time by a few seconds
    assert {"sat": "METEOR-M2 3", "aos": 1_800_000_004.7} in armed
    assert {"sat": "METEOR-M2 4", "aos": 1_800_000_000.0} not in armed      # other sat
    assert {"sat": "METEOR-M2 3", "aos": 1_800_006_000.0} not in armed      # next orbit


def test_passset_discard_and_no_duplicates():
    ps = W.PassSet()
    p = {"sat": "METEOR-M2 3", "aos": 1000.0}
    ps.add(p)
    ps.add({"sat": "METEOR-M2 3", "aos": 1003.0})
    assert len(ps.keys) == 1
    ps.discard({"sat": "METEOR-M2 3", "aos": 998.0})
    assert p not in ps
