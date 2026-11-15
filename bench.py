#!/usr/bin/env python3
"""
Conducted-mode RF bench: replay a baseband IQ file through the HackRF for testing your own
receivers over a cable. This is NOT an over-the-air transmitter and ships no spoofing or
jamming waveforms - you supply the signal, it goes into a dummy load / attenuator / the
receiver's antenna port, and every key-up is gated by txguard and logged.

Gate (audit G1 / G8): txguard.authorize("bench") - the ONE chain: env lock, master kill switch
armed, session unlocked, the SAVED tx_enabled setting (default off, must be exactly True), the
conducted-only acknowledgment, and the band check. Conducted does not lift protected bands
(txguard.CONDUCTED_PROTECTED_ALLOWED = False, owner decision). The key-up runs through the executor
with a registered process group (stoppable; disarm / PANIC kill it) and reports the real exit code.

Pure helpers (gain clamp, logging record) are separate so they can be tested without a radio.
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


def saved_settings():
    """The saved bench settings (fail closed: tx_enabled defaults to False)."""
    s, _path = S.settings("bench", DEFAULTS)
    return s


def clamp_gain(g):
    """TX VGA gain into hackrf_transfer's 0..47 dB, defaulting to the floor on bad input."""
    try:
        g = int(g)
    except (TypeError, ValueError):
        return TX_GAIN_DEFAULT
    return max(0, min(TX_GAIN_MAX, g))


def _tx_argv(iq_file, freq_hz, sample_rate=2_000_000, tx_gain=TX_GAIN_DEFAULT, repeat=False,
             exe="hackrf_transfer"):
    """The hackrf_transfer command to replay an IQ file as TX. Private: only start_transmit builds
    one, after the gate. Raises on bad input."""
    if not iq_file:
        raise ValueError("no IQ file to transmit")
    f, sr = txguard.as_hz(freq_hz), txguard.as_hz(sample_rate)
    if f is None or f <= 0:
        raise ValueError("frequency must be a positive number")
    if sr is None:
        raise ValueError("sample rate is not a finite number")
    argv = [exe, "-t", iq_file, "-f", str(f), "-s", str(sr),
            "-x", str(clamp_gain(tx_gain))]
    if repeat:
        argv.append("-R")
    return argv


def log_record(settings, iq_file, freq_hz, tx_gain, repeat):
    """One JSON line describing a key-up, for the audit log."""
    return {"t": time.time(), "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "freq_hz": txguard.as_hz(freq_hz), "freq_mhz": round(float(freq_hz) / 1e6, 4),
            "sample_rate": txguard.as_hz(settings.get("sample_rate", 2_000_000)),
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
    """(ok, reason): may this transmit proceed? The one txguard chain, bench mode."""
    ok, why, _p = txguard.authorize("bench", freq_hz, power_dbm=(settings or {}).get("power_dbm"),
                                    settings=settings,
                                    sample_rate=(settings or {}).get("sample_rate", 2_000_000))
    return ok, why


def start_transmit(settings, spawner=None, on_line=None, opt_in=None):
    """Gate + start the conducted key-up in a registered process group. Returns
    (ok, reason, handle); the handle can be stopped and reports the real exit code."""
    import executor
    iq = settings.get("iq_file", "")
    freq = settings.get("freq_hz", 0)
    sr = settings.get("sample_rate", 2_000_000)
    repeat = settings.get("repeat", False)
    ok, why, power = txguard.authorize("bench", freq, power_dbm=settings.get("power_dbm"),
                                       settings=settings, sample_rate=sr)
    if not ok:
        return False, "TX blocked: " + why, None
    if not iq or not os.path.exists(iq):
        return False, "IQ file not found: %r" % iq, None
    gok, gwhy, gain = txguard.check_gain(settings.get("tx_gain", TX_GAIN_DEFAULT), power)
    if not gok:
        return False, "TX blocked: " + gwhy, None
    try:
        argv = _tx_argv(iq, freq, sr, gain, repeat)
    except ValueError as e:
        return False, str(e), None
    # CL2-fix N8: re-checks read the LIVE settings — this same dict (not a copy) and, when the
    # caller passes opt_in() (the Qt bench app: the SAVED tx_enabled), that too. Both must stay
    # True: clearing either during a transmission stops it, like a disarm does.
    def live():
        s = dict(settings)
        ok = settings.get("tx_enabled") is True
        if opt_in is not None:
            ok = ok and opt_in() is True
        s["tx_enabled"] = ok
        return s
    ok, why, ticket, _p = txguard.issue_ticket("bench", argv, freq, settings.get("power_dbm"),
                                               settings=settings, sample_rate=sr,
                                               label="tx:bench", live=live)
    if not ok:
        return False, "TX blocked: " + why, None
    append_log(log_record(settings, iq, freq, gain, repeat))
    try:
        h = executor.start(ticket, spawner=spawner, on_line=on_line)
    except executor.TicketRefused as e:
        return False, "TX blocked: %s" % e, None
    except OSError as e:
        return False, "could not start hackrf_transfer: %s" % e, None
    return True, "%s -> %.4f MHz (conducted): %s" % (os.path.basename(iq), float(freq) / 1e6,
                                                     shlex.join(argv)), h


def transmit(settings, spawner=None, timeout=None, on_line=None):
    """start_transmit() and wait for it. Returns (ok, message, exit_code): ok only when the
    transmitter actually ran and exited 0 — the runner's real result, never a synthetic success."""
    ok, why, h = start_transmit(settings, spawner=spawner, on_line=on_line)
    if not ok:
        return False, why, None
    code = h.wait(timeout)
    if code is None and h.running():
        h.stop("timeout")
        code = h.exit_code
    tail = (" — " + h.lines[-1]) if h.lines else ""
    if h.stopped:
        return False, "stopped (%s), exit %s%s" % (h.stopped, code, tail), code
    if code == 0:
        return True, "transmitted: %s (exit 0)" % why, 0
    return False, "hackrf_transfer failed: exit %s%s" % (code, tail), code


if __name__ == "__main__":
    s = dict(DEFAULTS)
    print("Conducted bench TX. This is for a CABLED setup (dummy load / attenuator / receiver")
    print("antenna port), never an antenna. Edit settings and set bench_conducted_ack=True.")
    ok, why = preflight(s, s["freq_hz"])
    print(("READY: " if ok else "BLOCKED: ") + why)
