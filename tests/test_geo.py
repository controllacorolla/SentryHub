"""Tests for the consolidated geo helpers (Phase 1a)."""
import math

import geo


def test_dist_nm_zero():
    assert geo.dist_nm(40.0, -75.0, 40.0, -75.0) == 0.0


def test_dist_nm_one_degree_latitude():
    # 1 degree of latitude is ~60 nm.
    d = geo.dist_nm(40.0, -75.0, 41.0, -75.0)
    assert 59.9 < d < 60.1


def test_dist_nm_symmetric():
    a = geo.dist_nm(51.5, -0.1, 48.85, 2.35)
    b = geo.dist_nm(48.85, 2.35, 51.5, -0.1)
    assert abs(a - b) < 1e-9


def test_bearing_cardinals():
    assert abs(geo.bearing_deg(0, 0, 1, 0) - 0) < 1e-6      # due north
    assert abs(geo.bearing_deg(0, 0, 0, 1) - 90) < 1e-6     # due east
    assert abs(geo.bearing_deg(0, 0, -1, 0) - 180) < 1e-6   # due south
    assert abs(geo.bearing_deg(0, 0, 0, -1) - 270) < 1e-6   # due west


def test_bearing_in_range():
    b = geo.bearing_deg(51.5, -0.1, 48.85, 2.35)
    assert 0 <= b < 360


def test_matches_legacy_skyintel_values():
    # The canonical impl must reproduce the old skyintel formula exactly.
    def legacy(lat1, lon1, lat2, lon2):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        a = (math.sin((p2 - p1) / 2) ** 2
             + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
        return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))
    for args in [(40, -75, 41, -74), (0, 0, 10, 10), (-33, 151, 35, 139)]:
        assert abs(geo.dist_nm(*args) - legacy(*args)) < 1e-9
