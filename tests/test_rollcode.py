"""Tests for the rolling-code analyzer (Phase 6 #7). Analysis only."""
import rollcode as R


def test_to_bits_accepts_formats():
    assert R.to_bits("1010") == "1010"
    assert R.to_bits("0xa") == "1010"
    assert R.to_bits([1, 0, 1, 0]) == "1010"


def test_fixed_code_detected_and_replayable():
    label, d = R.classify_sequence(["0x1a3c", "0x1a3c", "0x1a3c"])
    assert label == "fixed" and "replayable" in d["note"]
    assert R.replay_risk(["0x1a3c", "0x1a3c"]) == [R.to_bits("0x1a3c")]


def test_rolling_code_structure_found():
    # 8-bit: top nibble fixed serial (1010), bottom nibble rolls
    caps = ["10100001", "10100010", "10100100", "10101000"]
    label, d = R.classify_sequence(caps)
    assert label == "rolling"
    assert d["unique"] == 4
    assert R.fixed_positions(caps) == [0, 1, 2, 3]       # fixed serial nibble
    assert set(R.rolling_positions(caps)) == {4, 5, 6, 7}


def test_bit_stability_fractions():
    stab = R.bit_stability(["1100", "1010"])
    assert stab[0] == 1.0 and stab[3] == 0.0          # bit0 always 1, bit3 always 0
    assert stab[1] == 0.5 and stab[2] == 0.5          # change


def test_single_and_empty():
    assert R.classify_sequence([])[0] == "empty"
    assert R.classify_sequence(["0xff"])[0] == "single"


def test_mismatched_lengths_raise():
    import pytest
    with pytest.raises(ValueError):
        R.bit_stability(["1010", "101"])


def test_no_replay_when_all_unique():
    assert R.replay_risk(["0001", "0010", "0100"]) == []
