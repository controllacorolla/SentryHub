"""Hardware workbench: serial line framing, hex dump, I2C parsing, GPIO parsing (all pure)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hwlab as H   # noqa: E402


def test_line_framer_holds_partial_lines():
    f = H.LineFramer()
    assert f.feed(b"hello wor") == []                         # no newline yet: held
    assert f.feed(b"ld\nsecond line\npa") == ["hello world", "second line"]
    assert f.feed(b"rt") == []
    assert f.feed(b"ial\n") == ["partial"]
    assert f.flush() is None


def test_line_framer_normalises_newlines():
    f = H.LineFramer()
    assert f.feed(b"a\r\nb\rc\nd") == ["a", "b", "c"]         # CRLF, CR, LF all split
    assert f.flush() == "d"                                   # trailing with no newline


def test_control_bytes_are_escaped_not_raw():
    f = H.LineFramer()
    # a stray NUL and a bell must never reach the Tk widget as raw control chars
    out = f.feed(b"ok\x00\x07bye\n")
    assert out == ["ok^@^Gbye"]
    assert H.clean_text("tab\there") == "tab\there"           # tab is kept
    assert H.clean_text("\x1b[0m") == "^[[0m"                 # ANSI escape shown literally
    assert H.clean_text("café") == "café"                     # real text survives


def test_hexdump_format():
    lines = H.hexdump(b"Hello, world!", base=0)
    assert lines[0].startswith("00000000  48 65 6c 6c 6f")
    assert lines[0].endswith("  Hello, world!")
    two = H.hexdump(bytes(range(20)))
    assert len(two) == 2 and two[1].startswith("00000010  10 11 12 13")


def test_parse_i2cdetect():
    sample = (
        "     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f\n"
        "00:                         -- -- -- -- -- -- -- --\n"
        "10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --\n"
        "20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --\n"
        "30: -- -- -- -- -- -- -- -- -- -- -- -- 3c -- -- --\n"
        "40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --\n"
        "50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --\n"
        "60: -- -- -- -- -- -- -- -- 68 -- -- -- -- -- -- --\n"
        "70: -- -- -- -- -- -- 76 -- UU -- -- -- -- -- -- --\n")
    assert H.parse_i2cdetect(sample) == [0x3c, 0x68, 0x76]    # UU (busy driver) is skipped


def test_i2c_label_names_common_chips():
    assert "SSD1306" in H.i2c_label(0x3c)
    assert "BME280" in H.i2c_label(0x76)
    assert H.i2c_label(0x11) == ""                            # unknown address


def test_parse_raspi_gpio():
    sample = ("GPIO 2: level=1 fsel=0 func=INPUT pull=UP\n"
              "GPIO 4: level=0 fsel=1 func=OUTPUT pull=NONE\n"
              "BANK0 (GPIO 0..27):\n"
              "GPIO 14: level=1 fsel=4 func=ALT0 pull=NONE\n")
    rows = H.parse_raspi_gpio(sample)
    assert rows == [(2, "INPUT", "0", "1"), (4, "OUTPUT", "1", "0"), (14, "ALT0", "4", "1")]


def test_scan_i2c_without_the_bus(monkeypatch):
    # pretend /dev/i2c-1 is absent, so this also holds on a real uConsole that has the bus
    real_exists = H.os.path.exists
    monkeypatch.setattr(H.os.path, "exists",
                        lambda p: False if p == "/dev/i2c-1" else real_exists(p))
    addrs, err = H.scan_i2c(1, run=lambda *a, **k: (1, ""))
    # no /dev/i2c-1: a clear, actionable message, no crash
    assert addrs == [] and err and "i2c" in err.lower()


def test_demo_serial_boots_and_answers():
    d = H.DemoSerial()
    first = d.read_lines()
    assert any("RF Reaper" in ln for ln in first)             # boot banner
    d.write(b"help\n")
    assert any("commands:" in ln for ln in d.read_lines())
    d.write(b"bogus\n")
    assert any("unknown cmd" in ln for ln in d.read_lines())
    d.close()
    assert d.open is False


def test_doctor_hwbench_check():
    import doctor
    ok, detail, fix = doctor.chk_hwbench(which=lambda n: "/usr/bin/" + n)
    assert ok is True and "serial" in detail and fix == ""
    ok, detail, fix = doctor.chk_hwbench(which=lambda n: None)
    assert "i2c-tools" in fix and "raspi-gpio" in fix


def test_parse_values_key_value():
    assert H.parse_values("temp=21.3C hum=41% pres=1012.2hPa rssi=-61dBm") == {
        "temp": 21.3, "hum": 41.0, "pres": 1012.2, "rssi": -61.0}
    # a leading millis counter is stripped, not plotted
    assert H.parse_values("[  1000] temp=22.0 hum=40") == {"temp": 22.0, "hum": 40.0}
    assert H.parse_values("x:1 y:2.5 z:-3") == {"x": 1.0, "y": 2.5, "z": -3.0}


def test_parse_values_csv_and_single():
    assert H.parse_values("1, 2, 3, 4") == {"ch0": 1.0, "ch1": 2.0, "ch2": 3.0, "ch3": 4.0}
    assert H.parse_values("12.5 -0.3 100") == {"ch0": 12.5, "ch1": -0.3, "ch2": 100.0}
    assert H.parse_values("battery 87 percent") == {"value": 87.0}   # one number in prose
    assert H.parse_values("ready >") == {}                            # no numbers
    assert H.parse_values("[rf] CC1101 init ok, 433.92 MHz") == {}   # 2 numbers: ambiguous
    assert H.parse_values("") == {}


def test_parse_values_ignores_noise_lines():
    # a boot line with several numbers but no key=value and not pure-CSV: don't invent series
    assert H.parse_values("load:0x3fff0030,len:1184") == {"len": 1184.0}
    assert H.parse_values("mode:DIO, clock div:1") == {"div": 1.0}
