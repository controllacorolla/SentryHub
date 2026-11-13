"""Tests for the hardware bus lab (UART / JTAG / SPI-flash).

JEDEC manufacturer codes (JEP106) and the IDCODE bitfield layout (IEEE 1149.1) are standard; probing
is ungated, flashing is engagement-gated.
"""
import pytest

import buslab as B
import engagement as E


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_printable_ratio_and_autobaud():
    good = b"Linux version 5.10\r\nboot> "
    junk = bytes([0x00, 0xFF, 0x80, 0x13, 0xC2, 0x91])
    assert B.printable_ratio(good) > 0.9
    assert B.printable_ratio(junk) < 0.3
    baud, score = B.guess_baud({9600: junk, 115200: good, 57600: junk})
    assert baud == 115200 and score > 0.6


def test_autobaud_none_when_all_garbage():
    baud, score = B.guess_baud({9600: bytes([0xFF, 0x00, 0x80]), 115200: bytes([0x81, 0x13])})
    assert baud is None


def test_decode_idcode_cortex_m():
    # ARM Cortex-M JTAG-DP IDCODE 0x4BA00477
    d = B.decode_idcode(0x4BA00477)
    assert d["valid"] and d["version"] == 0x4 and d["part"] == 0xBA00 and d["manufacturer"] == 0x23B


def test_decode_idcode_invalid_lsb():
    assert B.decode_idcode(0x4BA00476)["valid"] is False   # bit0 == 0


def test_decode_jedec_winbond_16mib():
    # EF 40 18 -> Winbond, 2**0x18 = 16 MiB = 128 Mbit
    d = B.decode_jedec_id([0xEF, 0x40, 0x18])
    assert d["mfr"] == "Winbond" and d["capacity_bytes"] == 16 * 1024 * 1024
    assert d["capacity_mbit"] == 128


def test_decode_jedec_macronix_and_unknown():
    assert B.decode_jedec_id([0xC2, 0x20, 0x17])["mfr"] == "Macronix"
    assert B.decode_jedec_id([0x55, 0x00, 0x00])["mfr"] == "0x55"       # unknown -> hex
    with pytest.raises(ValueError):
        B.decode_jedec_id([0xEF, 0x40])                                  # needs 3 bytes


def test_read_argv_are_ungated():
    assert B.flashrom_read_argv("linux_spi:dev=/dev/spidev0.0", "/tmp/dump.bin") == \
        ["flashrom", "-p", "linux_spi:dev=/dev/spidev0.0", "-r", "/tmp/dump.bin"]
    assert B.openocd_scan_argv("interface/jlink.cfg")[-1].startswith("init; scan_chain")
    assert B.picocom_argv("/dev/ttyUSB0", 115200) == ["picocom", "-b", "115200", "/dev/ttyUSB0"]


def test_flash_write_is_gated():
    ok, why, argv = B.prepare_flash_write("ch341a_spi", "fw.bin", target="ROUTER-1")
    assert not ok and argv is None and "engagement" in why.lower()
    E.start("fw audit", "ROE-11", ["ROUTER-1"], "KD0ABC")
    ok, why, argv = B.prepare_flash_write("ch341a_spi", "fw.bin", target="ROUTER-1")
    assert ok and argv == ["flashrom", "-p", "ch341a_spi", "-w", "fw.bin"]
    ok, why, argv = B.prepare_flash_write("ch341a_spi", "fw.bin", target="OTHER-DEV")
    assert not ok and argv is None


def test_jtag_write_is_gated():
    ok, why, argv = B.prepare_jtag_write("interface/stlink.cfg", "reset halt", target="MCU-1")
    assert not ok and argv is None
    E.start("mcu", "ROE-12", ["MCU-1"], "KD0ABC")
    ok, why, argv = B.prepare_jtag_write("interface/stlink.cfg", "reset halt", target="MCU-1")
    assert ok and "init; reset halt; shutdown" in argv[-1]


def test_detect_injected():
    have = B.detect(which=lambda n: "/usr/bin/" + n if n in ("openocd", "flashrom", "picocom") else None)
    assert have == {"uart": True, "jtag": True, "spi": True}
    assert B.detect(which=lambda n: None) == {"uart": False, "jtag": False, "spi": False}
