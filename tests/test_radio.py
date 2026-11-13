"""Tests for radio.py — TX hardware detection and the gated TxRequest (Phase 3a).

Detection probes are injected, so these run with no SDR/TX hardware attached.
"""
import pytest

import radio
import txguard


@pytest.fixture(autouse=True)
def _reset_tx(monkeypatch):
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    txguard.reset_session()
    yield
    txguard.reset_session()


def _which(present):
    return lambda name: ("/usr/bin/" + name) if name in present else None


def test_detect_none_when_nothing_present():
    assert radio.detect_tx_hardware(runner=lambda *a, **k: (None, ""),
                                    which=_which(set()), soapy_devices=[]) == []
    assert radio.tx_hardware_available(runner=lambda *a, **k: (None, ""),
                                       which=_which(set()), soapy_devices=[]) is False


def test_detect_hackrf_when_info_succeeds():
    devs = radio.detect_tx_hardware(
        runner=lambda argv, **k: (0, "Found HackRF\nSerial: 123"),
        which=_which({"hackrf_info"}), soapy_devices=[])
    assert [d["id"] for d in devs] == ["hackrf"]
    assert devs[0]["duplex"] == "half" and devs[0]["power_dbm_max"] == 15


def test_detect_hackrf_absent_when_info_fails():
    devs = radio.detect_tx_hardware(
        runner=lambda argv, **k: (1, "hackrf_info: no HackRF boards found"),
        which=_which({"hackrf_info"}), soapy_devices=[])
    assert devs == []


def test_detect_soapy_lime_and_pluto():
    devs = radio.detect_tx_hardware(
        runner=lambda *a, **k: (None, ""), which=_which({"SoapySDRUtil"}),
        soapy_devices=["driver=lime, label=limesdr mini", "driver=plutosdr"])
    ids = {d["id"] for d in devs}
    assert ids == {"limesdr", "pluto"}


def test_detect_rigctld_and_direwolf_tools():
    devs = radio.detect_tx_hardware(runner=lambda *a, **k: (None, ""),
                                    which=_which({"rigctld", "direwolf"}), soapy_devices=[])
    assert {d["id"] for d in devs} == {"rigctld", "direwolf"}


def test_pick_prefers_requested_device():
    hackrf = dict(radio.TX_HARDWARE["hackrf"], id="hackrf")
    pluto = dict(radio.TX_HARDWARE["pluto"], id="pluto")
    assert radio.pick_tx_device(devices=[hackrf, pluto], prefer="pluto")["id"] == "pluto"
    assert radio.pick_tx_device(devices=[hackrf, pluto])["id"] == "hackrf"
    assert radio.pick_tx_device(devices=[]) is None


def test_txrequest_refused_without_hardware_even_if_authorized():
    txguard.arm(True)
    txguard.unlock_session(True)
    req = radio.TxRequest("aprs", 144_390_000, callsign="KD0ABC",
                          settings={"tx_enabled": True, "callsign": "KD0ABC"})
    ok, why, _ = req.authorize(devices=[])      # txguard passes, but no hardware
    assert not ok and "hardware" in why.lower()


def test_txrequest_refused_when_txguard_denies():
    # Not armed -> refused regardless of hardware.
    hackrf = dict(radio.TX_HARDWARE["hackrf"], id="hackrf")
    req = radio.TxRequest("aprs", 144_390_000, callsign="KD0ABC",
                          settings={"tx_enabled": True, "callsign": "KD0ABC"})
    ok, why, _ = req.authorize(devices=[hackrf])
    assert not ok and "kill switch" in why.lower()


def test_txrequest_authorized_with_hardware_and_power_is_device_limited():
    txguard.arm(True)
    txguard.unlock_session(True)
    hackrf = dict(radio.TX_HARDWARE["hackrf"], id="hackrf")       # 15 dBm cap
    req = radio.TxRequest("aprs", 144_390_000, power_dbm=37, callsign="KD0ABC",
                          settings={"tx_enabled": True, "callsign": "KD0ABC"})
    ok, why, power = req.authorize(devices=[hackrf])
    assert ok and power == 15        # min(mode 37, HackRF 15)


def test_txrequest_refused_when_frequency_out_of_device_range():
    txguard.arm(True)
    txguard.unlock_session(True)
    pluto = dict(radio.TX_HARDWARE["pluto"], id="pluto")          # 70 MHz - 6 GHz
    req = radio.TxRequest("ft8", 7_030_000, callsign="KD0ABC",   # 40 m, below Pluto's range
                          settings={"tx_enabled": True, "callsign": "KD0ABC"})
    ok, why, _ = req.authorize(devices=[pluto])
    assert not ok and "cannot reach" in why.lower()


def test_builtin_sdr_is_not_tx_hardware():
    assert radio.BUILTIN_RTL_IS_RX_ONLY is True
    for d in radio.TX_HARDWARE.values():
        assert "rtl" not in d["name"].lower()


# ---- Phase 3b: SoapySDR device layer + remote sharing -------------------------------------
_SOAPY_OUT = """Found device 0
  driver = rtlsdr
  label = Generic RTL2832U OEM
  serial = 00000001
Found device 1
  driver = airspy
  label = Airspy MINI
  serial = abcd1234
"""


def test_parse_soapy_find_annotates():
    devs = radio.parse_soapy_find(_SOAPY_OUT)
    assert [d["driver"] for d in devs] == ["rtlsdr", "airspy"]
    assert devs[0]["name"] == "Generic RTL2832U OEM" and devs[0]["tx_capable"] is False
    assert devs[1]["serial"] == "abcd1234"


def test_list_soapy_devices_uses_tool():
    devs = radio.list_soapy_devices(runner=lambda *a, **k: (0, _SOAPY_OUT),
                                    which=lambda n: "/usr/bin/" + n if n == "SoapySDRUtil" else None)
    assert len(devs) == 2
    assert radio.list_soapy_devices(runner=lambda *a, **k: (0, _SOAPY_OUT),
                                    which=lambda n: None) == []        # no tool -> none


def test_devices_changed_detects_hotplug():
    a = radio.parse_soapy_find(_SOAPY_OUT)
    assert radio.devices_changed(a, a) is False
    assert radio.devices_changed(a, a[:1]) is True                     # one unplugged


def test_tx_capable_flag_by_driver():
    assert radio.SOAPY_DRIVERS["hackrf"]["tx"] is True
    assert radio.SOAPY_DRIVERS["rtlsdr"]["tx"] is False


def test_remote_sharing_commands():
    assert radio.rtl_tcp_server_argv(port=1234, sample_rate=2_048_000)[:3] == ["rtl_tcp", "-a", "0.0.0.0"]
    assert radio.soapy_remote_server_argv(port=55132) == ["SoapySDRServer", "--bind=0.0.0.0:55132"]
    assert radio.rtl_tcp_client_device("10.0.0.5", 1234) == "rtl_tcp=10.0.0.5:1234"
    assert "remote=10.0.0.5:55132" in radio.soapy_remote_client_device("10.0.0.5")
