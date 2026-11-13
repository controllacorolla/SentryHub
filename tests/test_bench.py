"""Conducted bench TX: gating, gain clamp, argv, logging. No radio is ever touched - the
subprocess runner is injected and must stay un-called whenever the guard says no."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bench as B  # noqa: E402

ACK = {"tx_enabled": True, "bench_conducted_ack": True}


def test_gain_is_clamped_to_the_hackrf_range_and_floors_on_bad_input():
    assert B.clamp_gain(-5) == 0
    assert B.clamp_gain(99) == B.TX_GAIN_MAX == 47
    assert B.clamp_gain("x") == B.TX_GAIN_DEFAULT == 0
    assert B.clamp_gain(20) == 20


def test_tx_argv_shape():
    argv = B.tx_argv("sig.iq", 915_000_000, 2_000_000, 10, repeat=True)
    assert argv[:2] == ["hackrf_transfer", "-t"] and "sig.iq" in argv
    assert "-f" in argv and "915000000" in argv and "-x" in argv and "10" in argv and "-R" in argv


def test_tx_argv_rejects_bad_input():
    for bad in [("", 915e6), ("s.iq", 0), ("s.iq", -1)]:
        try:
            B.tx_argv(*bad)
            assert False, bad
        except ValueError:
            pass


def test_transmit_is_blocked_without_the_conducted_acknowledgment(tmp_path):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00\x01" * 16)
    calls = []
    s = {"tx_enabled": True, "bench_conducted_ack": False, "freq_hz": 915_000_000, "iq_file": str(iq)}
    ok, msg = B.transmit(s, run=calls.append)
    assert ok is False and "acknowledgment" in msg and calls == []     # radio never keyed


def test_transmit_is_blocked_when_tx_is_disabled(tmp_path):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 8)
    calls = []
    s = {"tx_enabled": False, "bench_conducted_ack": True, "freq_hz": 915_000_000, "iq_file": str(iq)}
    ok, msg = B.transmit(s, run=calls.append)
    assert ok is False and calls == []


def test_hard_env_lock_blocks_even_an_acknowledged_bench(tmp_path, monkeypatch):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 8)
    calls = []
    monkeypatch.setenv("SUITE_TX_LOCK", "1")
    s = dict(ACK, freq_hz=915_000_000, iq_file=str(iq))
    ok, msg = B.transmit(s, run=calls.append)
    assert ok is False and "SUITE_TX_LOCK" in msg and calls == []


def test_transmit_runs_and_logs_when_acknowledged(tmp_path, monkeypatch):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00\x01" * 32)
    log = tmp_path / "tx.log"
    monkeypatch.setattr(B, "TX_LOG", str(log))
    calls = []
    s = dict(ACK, freq_hz=1_090_000_000, sample_rate=2_000_000, tx_gain=200, iq_file=str(iq), repeat=False)
    ok, msg = B.transmit(s, run=calls.append)
    assert ok is True and len(calls) == 1              # keyed exactly once
    argv = calls[0]
    assert argv[0] == "hackrf_transfer" and "1090000000" in argv
    assert "47" in argv                                # gain 200 clamped to max
    # the key-up is recorded, including the protected-band freq (allowed because conducted)
    import json
    rec = json.loads(log.read_text().strip())
    assert rec["freq_hz"] == 1_090_000_000 and rec["mode"] == "conducted-bench" and rec["tx_gain"] == 47


def test_transmit_refuses_a_missing_iq_file():
    calls = []
    ok, msg = B.transmit(dict(ACK, freq_hz=915_000_000, iq_file="/nope/none.iq"), run=calls.append)
    assert ok is False and "not found" in msg and calls == []
