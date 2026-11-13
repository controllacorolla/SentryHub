"""Tests for the MLAT feed config (Phase 7 #8)."""
import pytest

import mlat


def test_valid_station():
    assert mlat.valid_station(39.62, -104.87, 1600)[0] is True
    assert mlat.valid_station(0, 0, 100)[0] is False            # null island
    assert mlat.valid_station(95, 0, 100)[0] is False           # lat out of range
    assert mlat.valid_station(39, -104, 50000)[0] is False      # absurd altitude
    assert mlat.valid_station("x", 0, 0)[0] is False


def test_mlat_client_argv():
    argv = mlat.mlat_client_argv("adsbexchange", 39.62, -104.87, 1600, "kd0abc")
    assert argv[0] == "mlat-client" and "--user" in argv and "kd0abc" in argv
    assert "feed.adsbexchange.com:31090" in argv
    assert "39.620000" in argv and "-104.870000" in argv


def test_mlat_opensky_server():
    argv = mlat.mlat_client_argv("opensky", 39.62, -104.87, 1600, "u")
    assert "feed.opensky-network.org:10004" in argv


def test_unknown_server_raises():
    with pytest.raises(ValueError):
        mlat.mlat_client_argv("nonsense", 39.62, -104.87, 1600, "u")


def test_invalid_station_raises():
    with pytest.raises(ValueError):
        mlat.mlat_client_argv("adsbexchange", 0, 0, 100, "u")
