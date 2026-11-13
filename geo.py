"""Shared pure geometry helpers (Phase 1a consolidation).

Great-circle distance and initial bearing, extracted from the copies that had
accreted in skyintel.py, aprs.py and sky_app.py. Pure stdlib, no Tk, no I/O,
unit-testable. Callers import from here; skyintel re-exports for back-compat.
"""
import math

# Mean Earth radius in nautical miles (matches the value every prior copy used).
EARTH_NM = 3440.065


def dist_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360
