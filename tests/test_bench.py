"""Conducted bench TX: gating, gain clamp, argv, logging. No radio is ever touched - the executor's
spawner is injected and must stay un-called whenever the guard says no.

CL2 (G1/G8): the bench goes through the one txguard chain — armed + unlocked + the saved
tx_enabled (exactly True) + the conducted acknowledgment — and protected bands stay denied even
conducted (strict owner-decision default). The key-up runs in the executor and reports the real
exit code."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bench as B  # noqa: E402
import txguard  # noqa: E402

ACK = {"tx_enabled": True, "bench_conducted_ack": True}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    txguard.reset_session()
    yield
    txguard.reset_session()


def _armed():
    txguard.arm(True)
    txguard.unlock_session(True)


def _spawner(calls, code=0):
    def spawn(argv, **kw):
        calls.append(list(argv))
        return subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(%d)" % code],
                                start_new_session=True, stdout=subprocess.PIPE, text=True)
    return spawn


def test_gain_is_clamped_to_the_hackrf_range_and_floors_on_bad_input():
    assert B.clamp_gain(-5) == 0
    assert B.clamp_gain(99) == B.TX_GAIN_MAX == 47
    assert B.clamp_gain("x") == B.TX_GAIN_DEFAULT == 0
    assert B.clamp_gain(20) == 20


def test_tx_argv_shape():
    argv = B._tx_argv("sig.iq", 915_000_000, 2_000_000, 10, repeat=True)
    assert argv[:2] == ["hackrf_transfer", "-t"] and "sig.iq" in argv
    assert "-f" in argv and "915000000" in argv and "-x" in argv and "10" in argv and "-R" in argv


def test_tx_argv_rejects_bad_input():
    for bad in [("", 915e6), ("s.iq", 0), ("s.iq", -1)]:
        with pytest.raises(ValueError):
            B._tx_argv(*bad)


def test_transmit_is_blocked_without_the_conducted_acknowledgment(tmp_path):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00\x01" * 16)
    calls = []
    _armed()
    s = {"tx_enabled": True, "bench_conducted_ack": False, "freq_hz": 915_000_000, "iq_file": str(iq)}
    ok, msg, code = B.transmit(s, spawner=_spawner(calls))
    assert ok is False and "acknowledgment" in msg and calls == []     # radio never keyed


def test_transmit_is_blocked_when_tx_is_disabled(tmp_path):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 8)
    calls = []
    _armed()
    for v in (False, "yes", 1):
        s = {"tx_enabled": v, "bench_conducted_ack": True, "freq_hz": 915_000_000,
             "iq_file": str(iq)}
        ok, msg, code = B.transmit(s, spawner=_spawner(calls))
        assert ok is False and calls == [], v


def test_transmit_is_blocked_until_armed_and_unlocked(tmp_path):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 8)
    calls = []
    s = dict(ACK, freq_hz=915_000_000, iq_file=str(iq))
    assert B.transmit(s, spawner=_spawner(calls))[0] is False
    txguard.arm(True)
    assert B.transmit(s, spawner=_spawner(calls))[0] is False
    assert calls == []


def test_hard_env_lock_blocks_even_an_acknowledged_bench(tmp_path, monkeypatch):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 8)
    calls = []
    _armed()
    monkeypatch.setenv("SUITE_TX_LOCK", "1")
    s = dict(ACK, freq_hz=915_000_000, iq_file=str(iq))
    ok, msg, code = B.transmit(s, spawner=_spawner(calls))
    assert ok is False and "SUITE_TX_LOCK" in msg and calls == []


def test_protected_band_denied_even_conducted(tmp_path):
    """Owner decision 1, strict default: the old test asserted a conducted 1090 MHz key-up with only
    the settings flag; now it is refused (txguard.CONDUCTED_PROTECTED_ALLOWED is False)."""
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 8)
    calls = []
    _armed()
    ok, msg, code = B.transmit(dict(ACK, freq_hz=1_090_000_000, iq_file=str(iq)),
                               spawner=_spawner(calls))
    assert ok is False and "protected" in msg and calls == []


def test_transmit_runs_and_logs_when_acknowledged(tmp_path, monkeypatch):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00\x01" * 32)
    log = tmp_path / "tx.log"
    monkeypatch.setattr(B, "TX_LOG", str(log))
    calls = []
    _armed()
    s = dict(ACK, freq_hz=915_000_000, sample_rate=2_000_000, tx_gain=200, iq_file=str(iq),
             repeat=False)
    ok, msg, code = B.transmit(s, spawner=_spawner(calls, 0))
    assert ok is True and code == 0 and len(calls) == 1          # keyed exactly once, exit 0
    argv = calls[0]
    assert argv[0] == "hackrf_transfer" and "915000000" in argv
    assert argv[argv.index("-x") + 1] == "47"                     # 200 clamped to the 15 dBm cap
    import json
    rec = json.loads(log.read_text().strip())
    assert rec["freq_hz"] == 915_000_000 and rec["mode"] == "conducted-bench" and rec["tx_gain"] == 47


def test_transmit_reports_the_real_exit_code(tmp_path, monkeypatch):
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 8)
    monkeypatch.setattr(B, "TX_LOG", str(tmp_path / "tx.log"))
    _armed()
    ok, msg, code = B.transmit(dict(ACK, freq_hz=915_000_000, iq_file=str(iq)),
                               spawner=_spawner([], 1))
    assert ok is False and code == 1 and "exit 1" in msg


def test_transmit_refuses_a_missing_iq_file():
    calls = []
    _armed()
    ok, msg, code = B.transmit(dict(ACK, freq_hz=915_000_000, iq_file="/nope/none.iq"),
                               spawner=_spawner(calls))
    assert ok is False and "not found" in msg and calls == []
