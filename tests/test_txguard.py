"""The transmit policy gate. These tests ARE the safety contract: protected bands stay denied,
ham needs a callsign, ISM/LoRa are free, and a hard lock stops everything."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import txguard as G  # noqa: E402

ENABLED = {"tx_enabled": True, "callsign": "KD0ABC"}

# CL2/G8: decide() was a public, arm-less gate (and let service="lora" through at any frequency). It
# is now the private band classifier; these band-policy tests run through the ONE public chain,
# authorize(), with the kill switch armed and the session unlocked so only the band policy decides.


def _open():
    G.arm(True)
    G.unlock_session(True)


def _band(f, mode="aprs", callsign="", settings=None):
    _open()
    ok, why, _p = G.authorize(mode, f, callsign=callsign, settings=settings)
    return ok, why


def test_protected_bands_are_always_denied_even_with_a_callsign():
    for f, _name in [(1_575_420_000, "GPS L1"), (1_090_000_000, "ADS-B"), (978_000_000, "UAT"),
                     (121_500_000, "emergency"), (124_000_000, "aviation"), (156_800_000, "marine"),
                     (835_000_000, "cellular"), (1_750_000_000, "AWS uplink")]:
        for mode in ("aprs", "replay", "lora", "bench"):
            ok, why = _band(f, mode, callsign="KD0ABC",
                            settings=dict(ENABLED, bench_conducted_ack=True))
            assert ok is False, (f, mode, why)
            assert "protected" in why or "illegal" in why


def test_ham_band_requires_a_valid_callsign():
    f = 144_200_000  # 2m
    assert _band(f, settings=ENABLED)[0] is True                       # callsign from settings
    assert _band(f, callsign="KD0ABC", settings={"tx_enabled": True})[0] is True
    ok, why = _band(f, callsign="", settings={"tx_enabled": True})
    assert ok is False and "callsign" in why
    assert _band(f, callsign="NOT A CALL", settings={"tx_enabled": True})[0] is False


def test_ism_bands_need_no_callsign_but_still_need_tx_enabled():
    assert _band(915_000_000, "replay", settings={"tx_enabled": True})[0] is True
    assert _band(2_450_000_000, "replay", settings={"tx_enabled": True})[0] is True
    # 433.92 MHz is licence-free only outside the US (CL2/G10)
    assert _band(433_920_000, "replay", settings={"tx_enabled": True})[0] is False
    assert _band(433_920_000, "replay", settings={"tx_enabled": True, "tx_region": "EU"})[0] is True
    ok, why = _band(915_000_000, "replay", settings={"tx_enabled": False})
    assert ok is False and "disabled" in why


def test_lora_goes_through_the_same_chain_and_the_hard_env_lock_stops_everything(monkeypatch):
    # owner decision 2, strict default: no service is exempt from arm / unlock / tx_enabled / band
    assert G.EXEMPT_SERVICES == ()
    assert G.authorize("lora", 915_000_000, settings={"tx_enabled": True})[0] is False  # disarmed
    assert _band(915_000_000, "lora", settings={"tx_enabled": False})[0] is False
    assert _band(915_000_000, "lora", settings={"tx_enabled": True})[0] is True
    monkeypatch.setenv("SUITE_TX_LOCK", "1")
    assert _band(915_000_000, "lora", settings=ENABLED)[0] is False                # lora too
    assert _band(144_200_000, settings=ENABLED)[0] is False                        # ham too
    assert _band(915_000_000, "replay", settings=ENABLED)[0] is False              # ism too


def test_unknown_or_bad_frequency_is_denied_by_default():
    assert _band(5_000_000, settings=ENABLED)[0] is False        # 5 MHz: not ham, not ISM
    assert _band(None, settings=ENABLED)[0] is False
    assert _band("abc", settings=ENABLED)[0] is False
    assert _band(-1, settings=ENABLED)[0] is False
    assert _band(0, settings=ENABLED)[0] is False


def test_tx_defaults_closed_when_settings_do_not_enable_it():
    assert _band(144_200_000, callsign="KD0ABC", settings={})[0] is False      # no tx_enabled
    assert _band(144_200_000, callsign="KD0ABC", settings=None)[0] is False
    assert _band(915_000_000, "replay", settings=None)[0] is False


def test_classify_puts_protected_over_overlapping_allocations():
    # 902-928 is both 33cm ham and 915 ISM; neither overlaps a protected range here
    assert G.classify(915_000_000) in ("ism", "ham")
    # 1240-1300 is 23cm ham but 1215-1240 is protected radiolocation
    assert G.classify(1_220_000_000) == "protected"
    assert G.classify(1_270_000_000) == "ham"
    assert G.classify(146_000_000) == "ham"
    assert G.classify(100_000_000) == "other"      # FM broadcast: not a suite TX band


def test_valid_callsign():
    for good in ("KD0ABC", "W1AW", "N0CALL", "KD0ABC-9", "VE3XYZ", "2E0ABC"):
        assert G.valid_callsign(good), good
    for bad in ("", "HELLO", "123", "ABCDEF", "K", "KD0ABC-123"):
        assert not G.valid_callsign(bad), bad


def test_mesh_send_is_off_by_default_and_needs_the_chain():
    import mesh_dash
    assert mesh_dash.DEFAULTS["tx_enabled"] is False             # strict default (CL2)
    _open()
    assert mesh_dash.authorize_send(mesh_dash.DEFAULTS)[0] is False
    assert mesh_dash.authorize_send(dict(mesh_dash.DEFAULTS, tx_enabled=True))[0] is True


# ---- Phase 3a: authorize() gate (kill switch, session unlock, per-mode caps) --------------
import pytest  # noqa: E402

TXS = {"tx_enabled": True, "callsign": "KD0ABC", "bench_conducted_ack": True}


@pytest.fixture(autouse=True)
def _reset_tx(monkeypatch):
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    G.reset_session()
    yield
    G.reset_session()


def test_authorize_denied_until_kill_switch_armed():
    ok, why, _ = G.authorize("aprs", 144_390_000, callsign="KD0ABC", settings=TXS)
    assert not ok and "kill switch" in why.lower()


def test_authorize_denied_when_armed_but_not_unlocked():
    G.arm(True)
    ok, why, _ = G.authorize("aprs", 144_390_000, callsign="KD0ABC", settings=TXS)
    assert not ok and "unlock" in why.lower()


def test_authorize_allows_ham_when_armed_unlocked_and_valid():
    G.arm(True)
    G.unlock_session(True)
    ok, why, power = G.authorize("aprs", 144_390_000, callsign="KD0ABC", settings=TXS)
    assert ok and power == 37


def test_authorize_still_denies_protected_band_even_when_unlocked():
    G.arm(True)
    G.unlock_session(True)
    ok, why, _ = G.authorize("ft8", 1_090_000_000, callsign="KD0ABC", settings=TXS)
    assert not ok and "protected" in why.lower()


def test_authorize_ham_mode_rejects_non_ham_frequency():
    G.arm(True)
    G.unlock_session(True)
    ok, why, _ = G.authorize("ft8", 27_000_000, callsign="KD0ABC", settings=TXS)   # CB, not ham
    assert not ok


def test_authorize_power_capped_to_mode_max():
    G.arm(True)
    G.unlock_session(True)
    ok, _, power = G.authorize("wspr", 14_097_000, power_dbm=50, callsign="KD0ABC", settings=TXS)
    assert ok and power == 30            # WSPR cap, not the requested 50


def test_authorize_ham_requires_callsign():
    G.arm(True)
    G.unlock_session(True)
    ok, why, _ = G.authorize("cw", 7_030_000, callsign="", settings={"tx_enabled": True})
    assert not ok and "callsign" in why.lower()


def test_authorize_ism_mode_needs_no_callsign():
    G.arm(True)
    G.unlock_session(True)
    ok, _, power = G.authorize("lora", 915_000_000, settings={"tx_enabled": True})
    assert ok and power == 20


def test_disarm_drops_session_unlock():
    G.arm(True)
    G.unlock_session(True)
    assert G.session_unlocked() is True
    G.arm(False)
    assert G.session_unlocked() is False


def test_env_hard_lock_overrides_everything(monkeypatch):
    monkeypatch.setenv("SUITE_TX_LOCK", "1")
    G.arm(True)
    G.unlock_session(True)
    ok, why, _ = G.authorize("aprs", 144_390_000, callsign="KD0ABC", settings=TXS)
    assert not ok and "SUITE_TX_LOCK" in why


def test_log_tx_appends_jsonl(tmp_path):
    import json
    p = tmp_path / "tx_log.jsonl"
    G.log_tx(144_390_000, "aprs", 30, 2.5, "KD0ABC", path=str(p))
    G.log_tx(14_097_000, "wspr", 30, 110.0, "KD0ABC", path=str(p))
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["freq_hz"] == 144_390_000 and rec["mode"] == "aprs" and rec["callsign"] == "KD0ABC"
    assert rec["power_dbm"] == 30 and rec["duration_s"] == 2.5
