"""Tests for active BLE assessment (authorized, engagement-gated)."""
import pytest

import blepent as B
import engagement as E


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_enum_denied_without_engagement():
    ok, why, argv = B.prepare("enum", "AA:BB:CC:DD:EE:FF")
    assert not ok and argv is None and "engagement" in why.lower()


def test_enum_in_scope():
    E.start("iot audit", "self-owned", ["AA:BB:CC:DD:EE:FF"], "KD0ABC")
    ok, why, argv = B.prepare("enum", "AA:BB:CC:DD:EE:FF")
    assert ok and argv[0] == "gatttool" and "--primary" in argv and "AA:BB:CC:DD:EE:FF" in argv


def test_read_requires_handle():
    E.start("j", "roe", ["AA:BB:CC:DD:EE:FF"], "op")
    assert B.prepare("read", "AA:BB:CC:DD:EE:FF")[0] is False       # no handle
    ok, _, argv = B.prepare("read", "AA:BB:CC:DD:EE:FF", handle="0x0025")
    assert ok and "--char-read" in argv and "0x0025" in argv


def test_write_requires_handle_and_value():
    E.start("j", "roe", ["AA:BB:CC:DD:EE:FF"], "op")
    assert B.prepare("write", "AA:BB:CC:DD:EE:FF", handle="0x0025")[0] is False   # no value
    ok, _, argv = B.prepare("write", "AA:BB:CC:DD:EE:FF", handle="0x0025", value="01")
    assert ok and "--char-write-req" in argv and "01" in argv


def test_out_of_scope_blocked():
    E.start("j", "roe", ["AA:BB:CC:DD:EE:FF"], "op")
    assert B.prepare("write", "11:22:33:44:55:66", handle="0x1", value="ff")[0] is False
