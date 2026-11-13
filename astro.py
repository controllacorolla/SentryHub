"""Shared astronomy / look-angle engine (Phase 1a consolidation).

Az/el geometry and low-precision sun/moon ephemeris, extracted verbatim from
overwatch.py so there is a single authoritative owner. Pure stdlib, no Tk, no
I/O, unit-testable. overwatch re-exports these names, so its own code and
fieldcomp (which calls them via `overwatch`) are unchanged.

Satellite/pass prediction itself is NOT here: wxsat.py owns the skyfield SGP4
propagator and is already the single owner, so it is left in place.
"""
import math


def _ecef(lat, lon, alt_m):
    a, e2 = 6378137.0, 6.69437999014e-3
    la, lo = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return ((n + alt_m) * math.cos(la) * math.cos(lo), (n + alt_m) * math.cos(la) * math.sin(lo),
            (n * (1 - e2) + alt_m) * math.sin(la))


def azel(home, lat, lon, alt_m):
    """Where to look from home=(lat, lon, alt_m): (azimuth deg from north, elevation deg above
    the horizon, slant range km). Earth curvature included, so far-off aircraft sit low."""
    hlat, hlon, halt = home
    x0, y0, z0 = _ecef(hlat, hlon, halt)
    x, y, z = _ecef(lat, lon, alt_m)
    dx, dy, dz = x - x0, y - y0, z - z0
    la, lo = math.radians(hlat), math.radians(hlon)
    e = -math.sin(lo) * dx + math.cos(lo) * dy
    n = -math.sin(la) * math.cos(lo) * dx - math.sin(la) * math.sin(lo) * dy + math.cos(la) * dz
    u = math.cos(la) * math.cos(lo) * dx + math.cos(la) * math.sin(lo) * dy + math.sin(la) * dz
    rng = math.sqrt(e * e + n * n + u * u)
    if rng < 1.0:
        return 0.0, 90.0, 0.0
    return math.degrees(math.atan2(e, n)) % 360.0, math.degrees(math.asin(u / rng)), rng / 1000.0


def _jd(t):
    return t / 86400.0 + 2440587.5


def _radec_to_azel(ra, dec, lat, lon, t):
    d = _jd(t) - 2451545.0
    gmst = (280.46061837 + 360.98564736629 * d) % 360.0
    ha = math.radians((gmst + lon - ra) % 360.0)
    la, de = math.radians(lat), math.radians(dec)
    el = math.asin(math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(ha))
    az = math.atan2(-math.sin(ha) * math.cos(de),
                    math.cos(la) * math.sin(de) - math.sin(la) * math.cos(de) * math.cos(ha))
    return math.degrees(az) % 360.0, math.degrees(el)


def _ecl_to_radec(lam, beta, d):
    eps = math.radians(23.439 - 0.0000004 * d)
    l_, b = math.radians(lam), math.radians(beta)
    ra = math.atan2(math.sin(l_) * math.cos(eps) - math.tan(b) * math.sin(eps), math.cos(l_))
    dec = math.asin(math.sin(b) * math.cos(eps) + math.cos(b) * math.sin(eps) * math.sin(l_))
    return math.degrees(ra) % 360.0, math.degrees(dec)


def _sun_lon(d):
    g = math.radians((357.529 + 0.98560028 * d) % 360.0)
    return (280.459 + 0.98564736 * d + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360.0


def sun_azel(lat, lon, t):
    """Sun position, good to a fraction of a degree (Astronomical Almanac low-precision)."""
    d = _jd(t) - 2451545.0
    ra, dec = _ecl_to_radec(_sun_lon(d), 0.0, d)
    return _radec_to_azel(ra, dec, lat, lon, t)


def moon_azel(lat, lon, t):
    """Moon position (within about a degree: no parallax) and the lit fraction 0..1."""
    d = _jd(t) - 2451545.0
    T_ = d / 36525.0

    def s(a, b):
        return math.sin(math.radians(a + b * T_))
    lam = (218.32 + 481267.881 * T_ + 6.29 * s(135.0, 477198.87) - 1.27 * s(259.3, -413335.36)
           + 0.66 * s(235.7, 890534.22) + 0.21 * s(269.9, 954397.74) - 0.19 * s(357.5, 35999.05)
           - 0.11 * s(186.5, 966404.03)) % 360.0
    beta = (5.13 * s(93.3, 483202.02) + 0.28 * s(228.2, 960400.89) - 0.28 * s(318.3, 6003.15)
            - 0.17 * s(217.6, -407332.21))
    ra, dec = _ecl_to_radec(lam, beta, d)
    az, el = _radec_to_azel(ra, dec, lat, lon, t)
    elong = math.radians((lam - _sun_lon(d)) % 360.0)
    return az, el, (1 - math.cos(elong)) / 2.0


def daylight(sun_el):
    if sun_el > 0:
        return "day"
    if sun_el > -6:
        return "civil twilight"
    if sun_el > -12:
        return "nautical twilight"
    if sun_el > -18:
        return "astronomical twilight"
    return "night"
