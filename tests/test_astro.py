"""Tests for the consolidated astro/look-angle engine (Phase 1a)."""
import astro


def test_azel_straight_up():
    # A point directly overhead the home position reads ~90 deg elevation.
    home = (40.0, -75.0, 0.0)
    az, el, rng = astro.azel(home, 40.0, -75.0, 10000.0)
    assert el > 89.0
    assert rng > 0


def test_azel_same_point_is_zenith():
    home = (40.0, -75.0, 100.0)
    az, el, rng = astro.azel(home, 40.0, -75.0, 100.0)
    assert (az, el, rng) == (0.0, 90.0, 0.0)


def test_sun_azel_ranges():
    t = 1_700_000_000.0  # arbitrary fixed epoch
    az, el = astro.sun_azel(51.5, -0.1, t)
    assert 0 <= az < 360
    assert -90 <= el <= 90


def test_moon_lit_fraction_bounded():
    t = 1_700_000_000.0
    az, el, lit = astro.moon_azel(51.5, -0.1, t)
    assert 0 <= az < 360
    assert 0.0 <= lit <= 1.0


def test_daylight_thresholds():
    assert astro.daylight(10) == "day"
    assert astro.daylight(-3) == "civil twilight"
    assert astro.daylight(-9) == "nautical twilight"
    assert astro.daylight(-15) == "astronomical twilight"
    assert astro.daylight(-20) == "night"


def test_overwatch_reexports_astro():
    # fieldcomp reaches these through `overwatch`; keep that surface intact.
    import overwatch
    assert overwatch.sun_azel is astro.sun_azel
    assert overwatch.moon_azel is astro.moon_azel
    assert overwatch.azel is astro.azel
    assert overwatch.daylight is astro.daylight
