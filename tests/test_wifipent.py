"""Tests for active Wi-Fi assessment (authorized, engagement-gated)."""
import pytest

import engagement as E
import txguard
import wifipent as W


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    txguard.reset_session()
    yield
    E.reset()
    txguard.reset_session()


def test_active_actions_denied_without_engagement():
    for action in ("handshake", "pmkid", "deauth"):
        ok, why, argv = W.prepare(action, "AA:BB:CC:DD:EE:FF")
        assert not ok and argv is None and "engagement" in why.lower()


def test_handshake_capture_in_scope():
    E.start("own-net audit", "self-owned", ["AA:BB:CC:*"], "KD0ABC")      # an OUI entry is typed
    ok, why, t = W.prepare("handshake", "AA:BB:CC:11:22:33", iface="wlan0mon", channel=6, out="h")
    argv = t.argv
    assert ok and argv[0] == "airodump-ng" and "AA:BB:CC:11:22:33" in argv and "6" in argv


def test_out_of_scope_blocked():
    E.start("own-net audit", "self-owned", ["AA:BB:CC:*"], "KD0ABC")
    ok, why, argv = W.prepare("deauth", "99:99:99:99:99:99", client="AA:BB:CC:00:00:01")
    assert not ok and argv is None


def test_deauth_is_capped_not_a_flood():
    E.start("j", "roe", ["AA:BB:CC:DD:EE:01", "CC:DD:EE:FF:00:02"], "KD0ABC")
    txguard.arm(True)    # CL2-fix N2: an RF emitter also needs the TX kill switch armed
    ok, _, t = W.prepare("deauth", "AA:BB:CC:DD:EE:01", client="CC:DD:EE:FF:00:02", count=500)
    assert ok and t.argv[2] == str(W.DEAUTH_MAX) and "-c" in t.argv          # targeted + capped
    ok, _, t = W.prepare("deauth", "AA:BB:CC:DD:EE:01", client="CC:DD:EE:FF:00:02", count=0)
    assert ok and t.argv[2] == "1"                                            # floored


def test_unknown_action():
    E.start("j", "roe", ["LAB-X"], "KD0ABC")
    assert W.prepare("nuke", "X")[0] is False
