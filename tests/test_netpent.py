"""Tests for network assessment (authorized, engagement-gated)."""
import pytest

import engagement as E
import netpent as N


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_all_scans_gated():
    for action in ("discover", "portscan", "services", "osfp"):
        ok, why, argv = N.prepare(action, "192.168.1.10")
        assert not ok and argv is None and "engagement" in why.lower()


def test_in_scope_scans_build_argv():
    E.start("home-net audit", "self-owned", ["192.168.1.*"], "KD0ABC")
    ok, _, argv = N.prepare("discover", "192.168.1.0/24")
    assert ok and argv == ["nmap", "-sn", "192.168.1.0/24"]
    ok, _, argv = N.prepare("portscan", "192.168.1.10", ports="1-1000")
    assert ok and "-sS" in argv and "1-1000" in argv and "192.168.1.10" in argv


def test_out_of_scope_blocked():
    E.start("home-net audit", "self-owned", ["192.168.1.*"], "KD0ABC")
    assert N.prepare("portscan", "8.8.8.8")[0] is False     # not my network


def test_unknown_action():
    E.start("j", "roe", ["x"], "op")
    assert N.prepare("exploit", "x")[0] is False
