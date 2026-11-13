"""Tests for the CW/Morse keyer (Phase 5 #13)."""
import cw
import radio
import txguard


def test_encode_morse_sos():
    assert cw.encode_morse("SOS") == "... --- ..."


def test_encode_words_separated_by_slash():
    assert cw.encode_morse("HI BYE") == ".... .. / -... -.-- ."


def test_decode_roundtrip():
    for text in ("SOS", "HELLO WORLD", "CQ CQ DE KD0ABC", "73"):
        assert cw.decode_morse(cw.encode_morse(text)) == text


def test_unknown_chars_dropped():
    assert cw.encode_morse("A~B") == ".- -..."     # ~ not in table


def test_dot_ms_paris_standard():
    assert cw.dot_ms(20) == 60.0
    assert cw.dot_ms(1200) == 1.0


def test_key_timing_structure():
    seq = cw.key_timing("E E", wpm=20)   # two 'E' (single dot) separated by a letter gap... actually word gap
    ons = [ms for on, ms in seq if on]
    assert all(abs(ms - 60.0) < 1e-6 for ms in ons)     # each dot = 1 unit = 60 ms at 20 wpm
    assert len(ons) == 2


def test_key_timing_dash_is_three_units():
    seq = cw.key_timing("T", wpm=20)     # 'T' = single dash
    ons = [ms for on, ms in seq if on]
    assert ons == [180.0]                # 3 units


def test_timing_decode_roundtrip():
    seq = cw.key_timing("SOS", wpm=20)
    assert cw.decode_timing(seq, wpm=20) == "SOS"


def test_tx_is_gated_by_txguard(monkeypatch):
    # Even with hardware, authorize fails while the kill switch is OFF.
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    txguard.reset_session()
    hackrf = dict(radio.TX_HARDWARE["hackrf"], id="hackrf")
    req = radio.TxRequest("cw", 7_030_000, callsign="KD0ABC",
                          settings={"tx_enabled": True, "callsign": "KD0ABC"})
    ok, why, _ = req.authorize(devices=[hackrf])
    assert not ok and "kill switch" in why.lower()
    txguard.arm(True)
    txguard.unlock_session(True)
    ok, why, power = req.authorize(devices=[hackrf])
    assert ok and power == 15        # HackRF-limited
    txguard.reset_session()
