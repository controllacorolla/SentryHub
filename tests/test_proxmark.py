"""Tests for the Proxmark3 module (Phase 6 #13)."""
import pytest

import engagement as E
import proxmark as P


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_read_ops_are_ungated():
    ok, why, cmd = P.prepare("lf_search")
    assert ok and cmd == "lf search" and "ungated" in why
    assert P.prepare("hf_mf_info")[2] == "hf mf info"


def test_active_op_denied_without_engagement():
    ok, why, cmd = P.prepare("lf_hid_clone", target="BADGE-1", id="2006f623ae")
    assert not ok and cmd is None and "engagement" in why.lower()


def test_active_op_allowed_in_scope():
    E.start("badge audit", "ROE-7", ["BADGE-*"], "KD0ABC")
    ok, why, cmd = P.prepare("lf_hid_clone", target="BADGE-1", id="2006f623ae")
    assert ok and cmd == "lf hid clone -r 2006f623ae"


def test_active_op_blocked_out_of_scope():
    E.start("badge audit", "ROE-7", ["BADGE-*"], "KD0ABC")
    ok, why, cmd = P.prepare("hf_mf_sim", target="VIP-CARD", uid="DEADBEEF")
    assert not ok and cmd is None


def test_command_formatting_and_missing_param():
    assert P.pm3_command("lf_t55_write", block=0, data="12345678") == "lf t55xx write -b 0 -d 12345678"
    ok, why, cmd = P.prepare("lf_t55_write")      # missing params
    # missing params surface before the gate (it's a build error)
    assert not ok and cmd is None


def test_client_argv():
    argv = P.client_argv("lf search", port="/dev/ttyACM1", which=lambda n: "/usr/bin/pm3" if n == "pm3" else None)
    assert argv == ["pm3", "-p", "/dev/ttyACM1", "-c", "lf search"]


def test_detect_injected():
    assert P.detect(which=lambda n: "/usr/bin/pm3" if n == "pm3" else None) is True
    assert P.detect(which=lambda n: None) is False
