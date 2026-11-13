"""Tests for the digital-mode TX launcher (Phase 5 #2-5/#7)."""
import digimodes
import txguard
import pytest


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    txguard.reset_session()
    yield
    txguard.reset_session()


def _which(present):
    return lambda n: ("/usr/bin/" + n) if n in present else None


def test_availability_tracks_installed_tools():
    assert digimodes.available("ft8", which=_which({"wsjtx"})) is True
    assert digimodes.available("psk31", which=_which({"wsjtx"})) is False   # needs fldigi
    assert digimodes.installed_modes(which=_which({"wsjtx", "fldigi"})) == \
        ["ft8", "ft4", "wspr", "psk31", "olivia"]                          # not js8 (js8call)


def test_prepare_blocked_when_tool_missing():
    txguard.arm(True)
    txguard.unlock_session(True)
    ok, why, argv = digimodes.prepare("ft8", callsign="KD0ABC",
                                      settings={"tx_enabled": True, "callsign": "KD0ABC"},
                                      which=_which(set()))
    assert not ok and "not installed" in why and argv is None


def test_prepare_blocked_until_armed_and_unlocked():
    ok, why, argv = digimodes.prepare("ft8", callsign="KD0ABC",
                                      settings={"tx_enabled": True, "callsign": "KD0ABC"},
                                      which=_which({"wsjtx"}))
    assert not ok and "kill switch" in why.lower() and argv is None


def test_prepare_authorizes_with_gate_and_tool():
    txguard.arm(True)
    txguard.unlock_session(True)
    ok, why, argv = digimodes.prepare("wspr", callsign="KD0ABC",
                                      settings={"tx_enabled": True, "callsign": "KD0ABC"},
                                      which=_which({"wsjtx"}))
    assert ok and argv == ["wsjtx"] and "WSPR" in why


def test_prepare_rejects_unknown_mode():
    ok, why, argv = digimodes.prepare("nonsense", which=_which({"wsjtx"}))
    assert not ok and argv is None
