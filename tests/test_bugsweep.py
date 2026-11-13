"""Tests for the bug/camera sweep (defensive TSCM)."""
import bugsweep as B


def test_in_suspect_band():
    assert B.in_suspect_band(2_450_000_000) == "2.4 GHz camera / Wi-Fi cam"
    assert B.in_suspect_band(1_200_000_000) == "1.2 GHz video"
    assert B.in_suspect_band(14_000_000) is None       # 20 m ham, not a suspect band


def test_find_suspects_filters_and_ranks():
    new = [
        {"freq_hz": 2_450_000_000, "over_db": 25},     # 2.4 GHz camera — suspect, strong
        {"freq_hz": 14_074_000, "over_db": 40},        # ham FT8 — NOT a suspect band
        {"freq_hz": 1_250_000_000, "over_db": 15},     # 1.2 GHz video — suspect, weaker
    ]
    out = B.find_suspects(new)
    assert [s["freq_hz"] for s in out] == [2_450_000_000, 1_250_000_000]   # filtered + ranked
    assert out[0]["band"] == "2.4 GHz camera / Wi-Fi cam"


def test_proximity():
    assert B.proximity(35) == "very close" and B.proximity(22) == "close"
    assert B.proximity(14) == "nearby" and B.proximity(5) == "faint"


def test_sweeper_learns_then_flags():
    sw = B.Sweeper(threshold_db=12)
    quiet = [(2_450_000_000, -100), (2_451_000_000, -100)]
    for _ in range(3):
        sw.learn(quiet)
    hits = sw.sweep([(2_450_000_000, -70), (2_451_000_000, -100)])   # one bin lifts 30 dB
    assert len(hits) == 1 and hits[0]["freq_hz"] == 2_450_000_000
    assert hits[0]["band"].startswith("2.4 GHz")
