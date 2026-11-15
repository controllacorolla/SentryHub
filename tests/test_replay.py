"""Tests for the IQ replay analyzer gating (Phase 6 #6)."""
import pytest

import replay
import txguard


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    txguard.reset_session()
    yield
    txguard.reset_session()


_ISM = 915_000_000       # US 902-928 ISM. (433.92 is licence-free only outside the US — CL2/G10)
_SET = {"tx_enabled": True}


def test_replay_requires_confirmation():
    txguard.arm(True)
    txguard.unlock_session(True)
    ok, why, _ = replay.authorize_replay(_ISM, confirmed=False, settings=_SET)
    assert not ok and "confirmation" in why.lower()


def test_replay_blocked_until_armed_and_unlocked():
    ok, why, _ = replay.authorize_replay(_ISM, confirmed=True, settings=_SET)
    assert not ok and "kill switch" in why.lower()


def test_replay_authorized_on_ism_when_gated():
    txguard.arm(True)
    txguard.unlock_session(True)
    ok, why, power = replay.authorize_replay(_ISM, confirmed=True, settings=_SET)
    assert ok and power == 10


def test_replay_433_is_amateur_in_us_ism_in_eu():
    txguard.arm(True)
    txguard.unlock_session(True)
    assert replay.authorize_replay(433_920_000, confirmed=True, settings=_SET)[0] is False
    assert replay.authorize_replay(433_920_000, confirmed=True,
                                   settings={"tx_enabled": True, "tx_region": "EU"})[0] is True


def test_replay_refused_on_protected_band():
    txguard.arm(True)
    txguard.unlock_session(True)
    ok, why, _ = replay.authorize_replay(1_090_000_000, confirmed=True, settings=_SET)  # ADS-B
    assert not ok and "protected" in why.lower()


def test_prepare_replay_builds_argv_only_when_authorized():
    txguard.arm(True)
    txguard.unlock_session(True)
    ok, why, t = replay.prepare_replay("/tmp/b.cu8", _ISM, 2_000_000, confirmed=True,
                                       settings=_SET, tx_gain=20)
    argv = t.argv
    assert ok and argv[0] == "hackrf_transfer" and "-t" in argv and "/tmp/b.cu8" in argv
    assert argv[argv.index("-x") + 1] == "20"              # within the 10 dBm-derived cap
    # blocked -> no argv
    txguard.arm(False)
    ok2, _, argv2 = replay.prepare_replay("/tmp/b.cu8", _ISM, 2_000_000, confirmed=True,
                                          settings=_SET)
    assert not ok2 and argv2 is None
