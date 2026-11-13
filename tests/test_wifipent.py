"""Tests for active Wi-Fi assessment (authorized, engagement-gated)."""
import pytest

import engagement as E
import wifipent as W


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_active_actions_denied_without_engagement():
    for action in ("handshake", "pmkid", "deauth"):
        ok, why, argv = W.prepare(action, "AA:BB:CC:DD:EE:FF")
        assert not ok and argv is None and "engagement" in why.lower()


def test_handshake_capture_in_scope():
    E.start("own-net audit", "self-owned", ["AA:BB:CC:*"], "KD0ABC")
    ok, why, argv = W.prepare("handshake", "AA:BB:CC:11:22:33", iface="wlan0mon", channel=6, out="h")
    assert ok and argv[0] == "airodump-ng" and "AA:BB:CC:11:22:33" in argv and "6" in argv


def test_out_of_scope_blocked():
    E.start("own-net audit", "self-owned", ["AA:BB:CC:*"], "KD0ABC")
    ok, why, argv = W.prepare("deauth", "99:99:99:99:99:99")
    assert not ok and argv is None


def test_deauth_is_capped_not_a_flood():
    assert W.deauth_argv("w", "AA:BB", count=99999)[2] == str(W.DEAUTH_MAX)   # clamped
    assert W.deauth_argv("w", "AA:BB", count=0)[2] == "1"                     # floored
    E.start("j", "roe", ["AA:BB"], "op")
    ok, _, argv = W.prepare("deauth", "AA:BB", client="CC:DD", count=500)
    assert ok and argv[2] == str(W.DEAUTH_MAX) and "-c" in argv              # targeted + capped


def test_unknown_action():
    E.start("j", "roe", ["X"], "op")
    assert W.prepare("nuke", "X")[0] is False
