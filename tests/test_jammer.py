"""Tests for the jamming detector (Phase 6 #17)."""
import jammer


def _bins(vals, f0=100_000, step=1_000):
    return [(f0 + i * step, v) for i, v in enumerate(vals)]


def test_classify_wideband():
    new = [{"freq_hz": i, "over_db": 15} for i in range(60)]
    kind, sev = jammer.classify_interference(new, total_bins=100, wideband_frac=0.3)
    assert kind == "wideband" and sev >= 0.6


def test_classify_narrowband():
    new = [{"freq_hz": 1, "over_db": 30}]
    kind, sev = jammer.classify_interference(new, total_bins=100)
    assert kind == "narrowband" and sev > 0


def test_classify_none_when_quiet():
    assert jammer.classify_interference([], total_bins=100) == (None, 0.0)


def test_sustained_wideband_alerts_after_streak():
    d = jammer.JammingDetector(sustained_sweeps=3)
    quiet = _bins([-100] * 20)
    for _ in range(3):
        d.learn(quiet)
    jam = _bins([-50] * 20)                      # whole band lifts 50 dB
    assert d.feed(jam) is None                   # sweep 1 — not yet sustained
    assert d.feed(jam) is None                   # sweep 2
    alert = d.feed(jam)                          # sweep 3 — sustained
    assert alert and "wideband" in alert


def test_transient_does_not_alert():
    d = jammer.JammingDetector(sustained_sweeps=3)
    quiet = _bins([-100] * 20)
    for _ in range(3):
        d.learn(quiet)
    d.feed(_bins([-50] * 20))                    # one noisy sweep
    assert d.feed(quiet) is None                 # back to quiet resets the streak
    assert d.streak == 0


def test_narrowband_sustained_alerts():
    d = jammer.JammingDetector(sustained_sweeps=2)
    quiet = _bins([-100] * 20)
    for _ in range(2):
        d.learn(quiet)
    spike = _bins([-100] * 10 + [-60] + [-100] * 9)    # one strong bin
    d.feed(spike)
    alert = d.feed(spike)
    assert alert and "narrowband" in alert
