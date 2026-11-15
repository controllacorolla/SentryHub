#!/usr/bin/env python3
"""replay.py — IQ replay analyzer (Phase 6 #6). Build-and-gate, MANUAL replay only.

Records an IQ burst (via the IQ Recorder), lets you inspect it, and — for an authorized physical-
security assessment of ISM remotes/keyfobs/gate openers (433/315/915 MHz) — replay it through a
HackRF. Replay is NOT automatic: it requires an explicit per-burst confirmation AND passes txguard
(armed kill switch + session unlock + an ISM/allowed band; protected bands are refused). The
module builds the command and authorizes it; it does not auto-key. Pure gating is unit-testable.
"""
import os
import sys


def _replay_argv(iq_file, freq_hz, sample_rate, tx_gain):
    """The hackrf_transfer command to replay an IQ file as TX. Private: built only by
    prepare_replay after authorization, with a gain derived from the authorized power."""
    import txguard
    f, sr = txguard.as_hz(freq_hz), txguard.as_hz(sample_rate)
    if f is None or sr is None:
        raise ValueError("frequency / sample rate is not a finite number")
    return ["hackrf_transfer", "-t", iq_file, "-f", str(f), "-s", str(sr), "-x", str(int(tx_gain))]


def authorize_replay(freq_hz, confirmed, settings=None, power_dbm=None, sample_rate=None):
    """Gate a replay. Returns (ok, reason, power_allowed). Requires an explicit per-burst
    confirmation AND the full txguard replay-mode policy (armed + unlocked + tx_enabled + ISM band
    for the region + finite power / sample rate)."""
    import txguard
    if confirmed is not True:
        return False, "replay requires an explicit per-burst confirmation (manual trigger only)", 0
    return txguard.authorize("replay", freq_hz, power_dbm=power_dbm, settings=settings or {},
                             sample_rate=sample_rate)


def prepare_replay(iq_file, freq_hz, sample_rate, confirmed, settings=None, tx_gain=None,
                   power_dbm=None):
    """Authorize + build the replay command. Returns (ok, reason, ticket). The -x gain is derived
    from the authorized power (audit G9): a requested gain above that is clamped down, a
    non-integer / non-finite / negative one is refused."""
    import txguard
    ok, reason, power = authorize_replay(freq_hz, confirmed, settings, power_dbm, sample_rate)
    if not ok:
        return False, reason, None
    gok, gwhy, gain = txguard.check_gain(tx_gain, power)
    if not gok:
        return False, gwhy, None
    try:
        argv = _replay_argv(iq_file, freq_hz, sample_rate, gain)
    except ValueError as e:
        return False, "refused: %s" % e, None
    ok, why, ticket, _p = txguard.issue_ticket("replay", argv, freq_hz, power_dbm,
                                               settings=settings or {}, sample_rate=sample_rate,
                                               label="tx:replay")
    if not ok:
        return False, why, None
    return True, "%s; %s" % (reason, gwhy), ticket


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    import radio
    if parent is None:
        S.single_instance("Replay")
    s, spath = S.settings("replay", {"tx_enabled": False, "tx_gain": 0})
    root, F = S.make_root("Replay Analyzer", parent=parent)
    import tkinter as tk
    T = S.T
    tx_ok = bool(radio.tx_hardware_available())
    S.top_bar(root, F, "Replay Analyzer", "Record → inspect → MANUAL replay (gated)")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text=("Record an IQ burst, inspect it, then manually replay it on an ISM band for an "
                   "authorized assessment. Replay needs a per-burst confirmation + txguard armed + "
                   "unlocked; protected bands are refused and nothing auto-keys."
                   + ("" if tx_ok else "  (No TX hardware — inspect only.)"))).pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
