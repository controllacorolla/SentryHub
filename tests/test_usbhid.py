"""Tests for USB-HID keystroke-injection assessment (authorized, engagement-gated)."""
import pytest

import engagement as E
import usbhid as U


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_parse_ducky():
    acts = U.parse_ducky("REM a comment\nGUI r\nDELAY 500\nSTRING notepad\nENTER")
    assert acts[0] == {"type": "key", "mods": ["GUI"], "keys": ["r"]}
    assert acts[1] == {"type": "delay", "ms": 500}
    assert acts[2] == {"type": "string", "text": "notepad"}
    assert acts[3]["keys"] == ["ENTER"]


def test_hid_report_modifiers_and_keys():
    rep = U.hid_report(mods=["CTRL", "ALT"], keys=["DELETE"])
    assert len(rep) == 8 and rep[0] == (0x01 | 0x04)         # ctrl+alt
    assert rep[2] == 0x4C                                     # delete usage id
    assert U.hid_report(keys=["a"])[2] == 0x04


def test_keycode():
    assert U.keycode("a") == 0x04 and U.keycode("ENTER") == 0x28 and U.keycode("1") == 0x1E


def test_injection_gated():
    assert U.prepare("STRING hi", "LAPTOP-7")[0] is False     # no engagement
    E.start("usb audit", "self-owned", ["LAPTOP-*"], "KD0ABC")
    ok, why, actions = U.prepare("GUI r\nSTRING cmd\nENTER", "LAPTOP-7")
    assert ok and actions[1]["text"] == "cmd"
    assert U.prepare("STRING hi", "SERVER-1")[0] is False     # out of scope
