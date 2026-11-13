"""Tests for KrakenSDR triangulation / geolocation."""
import geo
import kraken as K


def test_triangulate_recovers_known_emitter():
    emitter = (39.70, -104.80)
    obs = [(39.60, -104.90), (39.60, -104.70)]      # two observers flanking it
    fixes = [(lat, lon, geo.bearing_deg(lat, lon, *emitter)) for lat, lon in obs]
    est = K.triangulate(fixes)
    assert est is not None
    assert geo.dist_nm(est[0], est[1], *emitter) < 0.1       # within ~0.1 nm


def test_triangulate_three_fixes():
    emitter = (40.00, -105.00)
    obs = [(39.9, -105.1), (39.9, -104.9), (40.1, -105.0)]
    fixes = [(lat, lon, geo.bearing_deg(lat, lon, *emitter)) for lat, lon in obs]
    est = K.triangulate(fixes)
    assert geo.dist_nm(est[0], est[1], *emitter) < 0.1


def test_parallel_bearings_return_none():
    # both pointing due north from different points -> never intersect
    assert K.triangulate([(39.6, -104.9, 0.0), (39.7, -104.9, 0.0)]) is None


def test_too_few_fixes():
    assert K.triangulate([(39.6, -104.9, 45.0)]) is None


def test_confidence_high_for_consistent_bearings():
    emitter = (39.70, -104.80)
    obs = [(39.60, -104.90), (39.60, -104.70), (39.80, -104.80)]
    fixes = [(lat, lon, geo.bearing_deg(lat, lon, *emitter)) for lat, lon in obs]
    est = K.triangulate(fixes)
    assert K.confidence(fixes, est) > 0.8
    assert K.residual_nm(fixes, est) < 1.0        # bearings all agree (degrees)


def test_confidence_low_for_inconsistent():
    fixes = [(39.6, -104.9, 45.0), (39.6, -104.7, 200.0)]   # contradictory
    est = K.triangulate(fixes)
    assert est is None or K.confidence(fixes, est) < 0.6


def test_kraken_available_injected():
    assert K.kraken_available(opener=lambda url, t: True) is True

    def boom(url, t):
        raise OSError("refused")
    assert K.kraken_available(opener=boom) is False
