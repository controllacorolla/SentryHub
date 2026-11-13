"""Tests for RF fingerprinting (Phase 6 #5)."""
import rffinger as R


def _fp(**kw):
    base = {"freq_offset_hz": 300, "clock_ppm": 0.5, "ramp_us": 12, "power_dbm": -50,
            "bandwidth_hz": 20000}
    base.update(kw)
    return base


def test_distance_identical_is_zero():
    assert R.distance(_fp(), _fp()) == 0.0


def test_distance_symmetric_and_positive():
    a, b = _fp(), _fp(freq_offset_hz=800)
    assert R.distance(a, b) == R.distance(b, a) > 0


def test_match_recognizes_same_device():
    db = R.FingerprintDB()
    db.add("fob-A", _fp(freq_offset_hz=300))
    db.add("fob-B", _fp(freq_offset_hz=2000, clock_ppm=5))
    did, d = db.match(_fp(freq_offset_hz=320, clock_ppm=0.6))     # close to A
    assert did == "fob-A"


def test_match_rejects_unknown_device():
    db = R.FingerprintDB()
    db.add("fob-A", _fp(freq_offset_hz=300))
    did, d = db.match(_fp(freq_offset_hz=9000, clock_ppm=20, power_dbm=-10), threshold=1.0)
    assert did is None


def test_identify_or_enroll():
    db = R.FingerprintDB()
    id1, new1 = db.identify_or_enroll(_fp())
    assert new1 is True and id1.startswith("DEV")
    id2, new2 = db.identify_or_enroll(_fp(freq_offset_hz=310))    # same device-ish
    assert new2 is False and id2 == id1
    id3, new3 = db.identify_or_enroll(_fp(freq_offset_hz=9000, clock_ppm=50, power_dbm=0))
    assert new3 is True and id3 != id1
