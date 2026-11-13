#!/usr/bin/env python3
"""
Conducted-mode RF bench: replay a baseband IQ file through the HackRF for testing your own
receivers over a cable. This is NOT an over-the-air transmitter and ships no spoofing or
jamming waveforms - you supply the signal, it goes into a dummy load / attenuator / the
receiver's antenna port, and every key-up is gated by txguard and logged.

Legitimate use: feed a known signal into a receiver you own to verify it decodes, measure
sensitivity, or reproduce a bug - all conducted, nothing radiating. That is why the band
restriction is lifted for service="bench": the signal never leaves the coax.

Pure helpers (argv building, gain clamp, logging record) are separate from the subprocess
call so they can be tested without a radio.
"""
import json
import os
import shlex
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402
import txguard  # noqa: E402

TX_GAIN_MAX = 47          # hackrf_transfer -x range is 0..47 dB
TX_GAIN_DEFAULT = 0       # floored: conducted paths use external attenuation, not chip gain
TX_LOG = os.path.join(S.DATA, "bench_tx.log")

DEFAULTS = {"tx_enabled": False, "bench_conducted_ack": False,
            "freq_hz": 915_000_000, "sample_rate": 2_000_000,
            "tx_gain": TX_GAIN_DEFAULT, "iq_file": "", "repeat": False}


def clamp_gain(g):
    """TX VGA gain into hackrf_transfer's 0..47 dB, defaulting to the floor on bad input."""
    try:
        g = int(g)
    except (TypeError, ValueError):
        return TX_GAIN_DEFAULT
    return max(0, min(TX_GAIN_MAX, g))


def tx_argv(iq_file, freq_hz, sample_rate=2_000_000, tx_gain=TX_GAIN_DEFAULT, repeat=False,
            exe="hackrf_transfer"):
    """The hackrf_transfer command to replay an IQ file as TX. -t transmits the file; -a 1
    enables the amp only if asked for elsewhere (we never do here). Raises on bad input."""
    if not iq_file:
        raise ValueError("no IQ file to transmit")
    f = int(freq_hz)
    if f <= 0:
        raise ValueError("frequency must be positive")
    argv = [exe, "-t", iq_file, "-f", str(f), "-s", str(int(sample_rate)),
            "-x", str(clamp_gain(tx_gain))]
    if repeat:
        argv.append("-R")
    return argv


def log_record(settings, iq_file, freq_hz, tx_gain, repeat):
    """One JSON line describing a key-up, for the audit log."""
    return {"t": time.time(), "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "freq_hz": int(freq_hz), "freq_mhz": round(float(freq_hz) / 1e6, 4),
            "sample_rate": int(settings.get("sample_rate", 2_000_000)),
            "tx_gain": clamp_gain(tx_gain), "iq_file": iq_file, "repeat": bool(repeat),
            "mode": "conducted-bench"}


def append_log(rec, path=None):
    path = path or TX_LOG
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def preflight(settings, freq_hz=None):
    """(ok, reason): may this transmit proceed? Routes through txguard's bench policy."""
    return txguard.decide(freq_hz=freq_hz, service="bench", settings=settings)


def transmit(settings, run=None):
    """Replay settings['iq_file'] once (or repeating). Returns (ok, message). Honours txguard;
    floors/clamps gain; logs the key-up. run(argv) is injectable for tests - it is NOT called
    unless preflight passes."""
    iq = settings.get("iq_file", "")
    freq = settings.get("freq_hz", 0)
    gain = settings.get("tx_gain", TX_GAIN_DEFAULT)
    repeat = settings.get("repeat", False)
    ok, why = preflight(settings, freq)
    if not ok:
        return False, "TX blocked: " + why
    if not iq or not os.path.exists(iq):
        return False, "IQ file not found: %r" % iq
    try:
        argv = tx_argv(iq, freq, settings.get("sample_rate", 2_000_000), gain, repeat)
    except ValueError as e:
        return False, str(e)
    append_log(log_record(settings, iq, freq, gain, repeat))
    runner = run or (lambda a: S.run(a, timeout=0))
    runner(argv)
    return True, "transmitting %s -> %.4f MHz (conducted): %s" % (
        os.path.basename(iq), float(freq) / 1e6, shlex.join(argv))


if __name__ == "__main__":
    s = dict(DEFAULTS)
    print("Conducted bench TX. This is for a CABLED setup (dummy load / attenuator / receiver")
    print("antenna port), never an antenna. Edit settings and set bench_conducted_ack=True.")
    ok, why = preflight(s, s["freq_hz"])
    print(("READY: " if ok else "BLOCKED: ") + why)
