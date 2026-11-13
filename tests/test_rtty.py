"""Tests for the RTTY/Baudot-ITA2 encoder (Phase 5 #6). Codes verified vs the standard table."""
import rtty


def test_letter_codes_match_table():
    assert rtty.LETTERS["R"] == 0b01010 and rtty.LETTERS["Y"] == 0b10101
    assert rtty.LETTERS["A"] == 0b11000 and rtty.LETTERS["E"] == 0b10000


def test_encode_codes_starts_in_letters():
    codes = rtty.encode_codes("RY")
    assert codes == [rtty.LTRS, 0b01010, 0b10101]        # LTRS, R, Y


def test_figures_shift_inserted_for_digits():
    codes = rtty.encode_codes("A5")
    # LTRS, A, FIGS, 5
    assert codes == [rtty.LTRS, rtty.LETTERS["A"], rtty.FIGS, rtty.FIGURES["5"]]


def test_shift_back_to_letters():
    codes = rtty.encode_codes("5A")
    assert codes == [rtty.LTRS, rtty.FIGS, rtty.FIGURES["5"], rtty.LTRS, rtty.LETTERS["A"]]


def test_space_is_shift_neutral():
    codes = rtty.encode_codes("A B")
    assert rtty.CONTROLS[" "] in codes
    # no spurious shift inserted around the space (still letters throughout)
    assert codes.count(rtty.FIGS) == 0


def test_decode_roundtrip():
    for text in ("RYRY", "CQ CQ DE KD0ABC", "QRL 599", "TEST 123"):
        assert rtty.decode_codes(rtty.encode_codes(text)) == text


def test_encode_bits_frame_structure():
    bits = rtty.encode_bits("E", stop_bits=2)      # LTRS then E
    # each char = 1 start(0) + 5 data + 2 stop(1) = 8 bits; two codes (LTRS, E) = 16 bits
    assert len(bits) == 16
    assert bits[0] == "0" and bits[6:8] == "11"    # start bit low, stop bits high
    # E data bits = 10000
    assert bits[8:16] == "0" + "10000" + "11"


def test_duration_scales_with_baud():
    d = rtty.duration_s("TEST", stop_bits=2, baud=45.45)
    assert d > 0 and abs(d - len(rtty.encode_bits("TEST")) / 45.45) < 1e-9
