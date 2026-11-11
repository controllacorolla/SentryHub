"""Scanner: preset banks, channel assembly, custom parsing, and RMS squelch math."""
import scanner


def test_all_banks_nonempty_and_valid_mode():
    for name in scanner.BANK_ORDER:
        b = scanner.BANKS[name]
        assert b["mode"] in ("am", "nfm")
        assert len(b["channels"]) >= 1
        for fr, lb in b["channels"]:
            assert 20.0 < fr < 500.0      # sane VHF/UHF/CB range, MHz
            assert isinstance(lb, str)


def test_cb_has_40_channels():
    assert len(scanner.BANKS["CB"]["channels"]) == 40


def test_gmrs_has_22_channels():
    assert len(scanner.BANKS["GMRS/FRS"]["channels"]) == 22


def test_bank_channels_carries_mode():
    chans = scanner.bank_channels("Airband", [])
    assert all(m == "am" for _, _, m in chans)
    assert all(m == "nfm" for _, _, m in scanner.bank_channels("Marine VHF", []))


def test_parse_custom_valid_and_junk():
    out = scanner.parse_custom(["462.5500 Repeater nfm", "121.5 Guard am", "garbage", ""])
    assert out == [(462.55, "Repeater", "nfm"), (121.5, "Guard", "am")]


def test_parse_custom_defaults_mode_nfm():
    assert scanner.parse_custom(["155.160 SAR"]) == [(155.160, "SAR", "nfm")]


def test_rtl_cmd_maps_nfm_to_fm_and_am():
    assert "fm" in scanner.rtl_cmd(146.52, "nfm", 40)
    assert "am" in scanner.rtl_cmd(27.185, "am", 20)


def test_rms_silence_and_signal():
    import numpy as np
    assert scanner.rms_of(np.zeros(1024, dtype=np.int16).tobytes()) == 0.0
    assert scanner.rms_of((np.ones(1024, dtype=np.int16) * 2500).tobytes()) > 2000
    assert scanner.rms_of(b"") == 0.0


def test_custom_bank_in_channels_when_present():
    assert scanner.bank_channels("Custom", ["462.55 Test nfm"]) == [(462.55, "Test", "nfm")]


def test_parse_custom_rejects_out_of_range():
    assert scanner.parse_custom(["999999 zz", "-50 fm", "5.0 shortwave"]) == []


def test_parse_custom_bare_mode_token_is_mode():
    assert scanner.parse_custom(["121.5 am"]) == [(121.5, "custom", "am")]
    assert scanner.parse_custom(["462.55 My Repeater nfm"]) == [(462.55, "My Repeater", "nfm")]
