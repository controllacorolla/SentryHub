"""Tests for active BLE assessment (authorized, engagement-gated)."""
import pytest

import blepent as B
import engagement as E
import txguard


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    txguard.reset_session()
    yield
    E.reset()
    txguard.reset_session()


def test_enum_denied_without_engagement():
    ok, why, argv = B.prepare("enum", "AA:BB:CC:DD:EE:FF")
    assert not ok and argv is None and "engagement" in why.lower()


def test_enum_in_scope():
    E.start("iot audit", "self-owned", ["AA:BB:CC:DD:EE:FF"], "KD0ABC")
    txguard.arm(True)    # CL2-fix N2: an RF emitter also needs the TX kill switch armed
    ok, why, t = B.prepare("enum", "AA:BB:CC:DD:EE:FF")
    argv = t.argv
    assert ok and argv[0] == "gatttool" and "--primary" in argv and "AA:BB:CC:DD:EE:FF" in argv


def test_read_requires_handle():
    E.start("j", "roe", ["AA:BB:CC:DD:EE:FF"], "KD0ABC")
    txguard.arm(True)    # CL2-fix N2: an RF emitter also needs the TX kill switch armed
    assert B.prepare("read", "AA:BB:CC:DD:EE:FF")[0] is False       # no handle
    ok, _, t = B.prepare("read", "AA:BB:CC:DD:EE:FF", handle="0x0025")
    argv = t.argv
    assert ok and "--char-read" in argv and "0x0025" in argv


def test_write_requires_handle_and_value():
    E.start("j", "roe", ["AA:BB:CC:DD:EE:FF"], "KD0ABC")
    txguard.arm(True)    # CL2-fix N2: an RF emitter also needs the TX kill switch armed
    assert B.prepare("write", "AA:BB:CC:DD:EE:FF", handle="0x0025")[0] is False   # no value
    ok, _, t = B.prepare("write", "AA:BB:CC:DD:EE:FF", handle="0x0025", value="01")
    argv = t.argv
    assert ok and "--char-write-req" in argv and "01" in argv


def test_out_of_scope_blocked():
    assert E.start("j", "roe", ["AA:BB:CC:DD:EE:FF"], "KD0ABC")[0]
    txguard.arm(True)    # CL2-fix2 R2: armed + unlocked, so only SCOPE can refuse (not the RF gate)
    txguard.unlock_session(True)
    ok, why, t = B.prepare("write", "11:22:33:44:55:66", handle="0x1", value="ff")
    assert not ok and t is None and "not in the engagement scope" in why, why
    assert B.prepare("write", "AA:BB:CC:DD:EE:FF", handle="0x1", value="ff")[0] is True
