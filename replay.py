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


def replay_argv(iq_file, freq_hz, sample_rate, tx_gain=0):
    """The hackrf_transfer command to replay an IQ file as TX (built only after authorization)."""
    return ["hackrf_transfer", "-t", iq_file, "-f", str(int(freq_hz)),
            "-s", str(int(sample_rate)), "-x", str(int(tx_gain))]


def authorize_replay(freq_hz, confirmed, settings=None, power_dbm=None):
    """Gate a replay. Returns (ok, reason, argv_power). Requires an explicit per-burst confirmation
    AND the full txguard replay-mode policy (armed + unlocked + ISM/allowed band)."""
    import txguard
    if not confirmed:
        return False, "replay requires an explicit per-burst confirmation (manual trigger only)", 0
    return txguard.authorize("replay", freq_hz, power_dbm=power_dbm, settings=settings or {})


def prepare_replay(iq_file, freq_hz, sample_rate, confirmed, settings=None, tx_gain=0):
    """Authorize + build the replay command. Returns (ok, reason, argv). argv is None unless fully
    authorized (confirmed + txguard pass)."""
    ok, reason, _power = authorize_replay(freq_hz, confirmed, settings)
    if not ok:
        return False, reason, None
    return True, reason, replay_argv(iq_file, freq_hz, sample_rate, tx_gain)


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
