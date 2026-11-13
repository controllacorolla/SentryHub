"""Tests for the operator profile."""
import opprofile as O


def test_valid_grid():
    assert O.valid_grid("DM79") and O.valid_grid("DM79lw")
    assert not O.valid_grid("ZZ99") and not O.valid_grid("") and not O.valid_grid("DM7")


def test_aprs_passcode_deterministic_and_ranged():
    a = O.aprs_passcode("N0CALL")
    assert a == O.aprs_passcode("N0CALL")          # deterministic
    assert 0 <= a <= 0x7FFF
    assert O.aprs_passcode("N0CALL") == 13023       # canonical APRS-IS passcode for N0CALL
    assert O.aprs_passcode("W1AW-5") == O.aprs_passcode("W1AW")   # SSID stripped
    assert O.aprs_passcode("") == -1


def test_validate_and_can_tx():
    assert O.validate({"callsign": "KD0ABC"}) == []
    assert O.can_tx({"callsign": "KD0ABC"}) is True
    probs = O.validate({"callsign": "", "grid": "nope"})
    assert any("callsign" in p for p in probs) and any("grid" in p for p in probs)
    assert O.can_tx({"callsign": ""}) is False


def test_tx_settings():
    ts = O.tx_settings({"callsign": "KD0ABC"})
    assert ts["callsign"] == "KD0ABC" and ts["tx_enabled"] is True
    assert O.tx_settings({"callsign": ""})["tx_enabled"] is False
