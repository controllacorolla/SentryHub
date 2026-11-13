"""Tests for the loopback self-test harness."""
import pytest

import loopback
import txguard


def test_all_software_selftests_pass():
    results = loopback.software_selftests()
    names = [n for n, _, _ in results]
    assert "CW keyer round-trip" in names and "RTTY/Baudot round-trip" in names
    assert "OpenDroneID pack round-trip" in names and "AIS decode reference" in names
    for name, ok, detail in results:
        assert ok, "%s failed: %s" % (name, detail)
    assert loopback.all_pass(results) is True


@pytest.fixture
def _reset(monkeypatch):
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    txguard.reset_session()
    yield
    txguard.reset_session()


def test_hardware_loopback_gated(_reset, monkeypatch):
    # blocked until armed/unlocked
    ok, why, plan = loopback.hardware_loopback_plan("replay", 433_920_000,
                                                    {"tx_enabled": True})
    assert not ok and plan is None
    # mock a TX device so the gate's hardware check is exercised without a real HackRF
    # (the production path fails closed when no TX hardware is present — see radio.pick_tx_device)
    import radio
    monkeypatch.setattr(radio, "pick_tx_device", lambda *a, **k: {
        "id": "hackrf", "name": "HackRF One",
        "freq_hz": (1_000_000, 6_000_000_000), "power_dbm_max": 15})
    txguard.arm(True)
    txguard.unlock_session(True)
    ok, why, plan = loopback.hardware_loopback_plan("replay", 433_920_000,
                                                    {"tx_enabled": True})
    assert ok and plan["tx_argv"][0] == "hackrf_transfer" and "rx_argv" in plan
