"""Tests for the password-strength audit (authorized, engagement-gated)."""
import math

import pytest

import engagement as E
import passaudit as P


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_keyspace_and_crack_time():
    assert P.keyspace(10, 4) == 10000
    assert P.crack_seconds(10000, 1000) == 5.0        # half of 10000 at 1000/s
    assert P.crack_seconds(1000, 0) == math.inf


def test_strength_verdict_tiers():
    assert P.strength_verdict(60)[0] == "weak"
    assert P.strength_verdict(86400 * 5)[0] == "marginal"
    assert P.strength_verdict(86400 * 365 * 5)[0] == "ok"
    assert P.strength_verdict(86400 * 365 * 1000)[0] == "strong"


def test_commands_build():
    assert P.hcx_convert_argv("c.pcapng", "c.hc22000")[0] == "hcxpcapngtool"
    assert "-m" in P.hashcat_argv("h", "w", 22000) and "22000" in P.hashcat_argv("h", "w", 22000)
    assert P.hashcat_argv("h", None, 22000, mask="?d?d?d?d")[4] == "3"       # -a 3 = mask attack
    assert "-b" in P.aircrack_argv("c.cap", "w", bssid="AA:BB")


def test_audit_gated():
    assert P.prepare("hashcat", "AA:BB:CC:DD:EE:FF")[0] is False     # no engagement
    E.start("wifi audit", "self-owned", ["AA:BB:CC:*"], "KD0ABC")
    ok, _, argv = P.prepare("hashcat", "AA:BB:CC:DD:EE:FF", hash_file="h", wordlist="w")
    assert ok and argv[0] == "hashcat"
    assert P.prepare("hashcat", "99:99:99:99:99:99")[0] is False     # out of scope
