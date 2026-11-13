"""Tests for the GNSS jamming/spoofing monitor (Phase 6 #16)."""
import gnss


def _sats(cn0s):
    return [{"prn": i, "cn0": c, "elev": 45, "used": True} for i, c in enumerate(cn0s)]


def test_nominal_no_jamming():
    jammed, score, _ = gnss.jamming_check(_sats([40, 42, 38, 44, 39, 41]))
    assert not jammed and score == 0.0


def test_total_loss_is_jamming():
    jammed, score, why = gnss.jamming_check(_sats([0, 0]))
    assert jammed and score == 1.0 and "no satellites" in why


def test_cn0_collapse_is_jamming():
    jammed, _, why = gnss.jamming_check(_sats([20, 22, 19, 21]))   # ~18 below nominal 38
    assert jammed and "depressed" in why or "collapsed" in why


def test_position_jump_flags_spoof():
    prev = {"lat": 39.60, "lon": -104.90, "t": 100}
    cur = {"lat": 39.90, "lon": -104.90, "t": 101}     # ~18 nm in 1 s = impossible
    flags = gnss.spoofing_check(prev, cur, 1.0, _sats([40, 41, 39, 42]))
    assert any("jumped" in f for f in flags)


def test_backward_time_flags_spoof():
    prev = {"lat": 39.6, "lon": -104.9, "t": 100}
    cur = {"lat": 39.6, "lon": -104.9, "t": 95}
    flags = gnss.spoofing_check(prev, cur, 5.0, _sats([40, 41, 39, 42]))
    assert any("backward" in f for f in flags)


def test_uniform_strong_cn0_flags_spoof():
    flags = gnss.spoofing_check(None, None, None, _sats([48, 48, 49, 48, 48, 49]))
    assert any("uniform" in f for f in flags)


def test_monitor_emits_alerts():
    got = []
    m = gnss.GnssMonitor()
    m.on_alert = got.append
    m.ingest({"lat": 39.6, "lon": -104.9, "t": 100}, _sats([40, 41, 39, 42]))      # nominal
    m.ingest({"lat": 40.6, "lon": -104.9, "t": 101}, _sats([40, 41, 39, 42]))      # big jump
    assert any("spoofing" in a for a in got)
