"""Tests for the Flipper Zero bridge + NFC relay detector.

Read/receive commands are ungated; emit commands (tx/emulate/write/badusb/gpio set) are
engagement-gated. The relay detector flags inflated APDU latency.
"""
import pytest

import engagement as E
import flipper as FL


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_classify_read_vs_emit():
    assert FL.classify_command("device_info") == "read"
    assert FL.classify_command("nfc detect") == "read"
    assert FL.classify_command("subghz rx 433920000") == "read"
    assert FL.classify_command("storage list /ext") == "read"
    assert FL.classify_command("subghz tx_from_file /ext/x.sub") == "emit"
    assert FL.classify_command("nfc emulate") == "emit"
    assert FL.classify_command("rfid write") == "emit"
    assert FL.classify_command("ir tx NEC 0x04 0x08") == "emit"
    assert FL.classify_command("badusb /ext/payload.txt") == "emit"
    assert FL.classify_command("gpio set pa7 1") == "emit"


def test_read_command_ungated():
    ok, why, cmd = FL.prepare_command("nfc detect")
    assert ok and cmd == "nfc detect" and "ungated" in why


def test_emit_command_gated():
    ok, why, cmd = FL.prepare_command("subghz tx_from_file /ext/g.sub", target="GARAGE-1")
    assert not ok and cmd is None and "engagement" in why.lower()
    E.start("rf audit", "ROE-14", ["GARAGE-1"], "KD0ABC")
    ok, why, cmd = FL.prepare_command("subghz tx_from_file /ext/g.sub", target="GARAGE-1")
    assert ok and cmd == "subghz tx_from_file /ext/g.sub"
    ok, why, cmd = FL.prepare_command("subghz tx_from_file /ext/g.sub", target="NOT-IN-SCOPE")
    assert not ok and cmd is None


def test_parse_device_info():
    info = FL.parse_device_info(FL.Demo().device_info())
    assert info["hardware_model"] == "Flipper Zero" and info["firmware_version"] == "0.98.3"
    assert info["battery_level"] == "87"


def test_find_port():
    ports = ["/dev/serial/by-id/usb-Nordic_x", "/dev/serial/by-id/usb-Flipper_Yosemite_abcd"]
    assert "Flipper" in FL.find_port(ports)
    assert FL.find_port([]) is None


def test_relay_detector():
    dm = FL.Demo()
    clean = FL.relay_latency_suspect(dm.normal_timings())
    assert clean["suspect"] is False and clean["n"] == 5
    relayed = FL.relay_latency_suspect(dm.relay_timings())
    assert relayed["suspect"] is True and relayed["excess_ms"] > 8.0
    assert FL.relay_latency_suspect([])["suspect"] is False
