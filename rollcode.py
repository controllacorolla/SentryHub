#!/usr/bin/env python3
"""rollcode.py — rolling-code / keyfob analyzer (Phase 6 #7). ANALYSIS ONLY.

For authorized physical-security assessments of remotes, keyfobs and gate openers (315/433/915
MHz). Given a set of captured transmissions from one device, it determines empirically whether the
device uses a FIXED code (replayable — insecure) or a ROLLING code, and which bit positions are
constant (the fixed serial/button field) versus changing (the hopping/encrypted field) — WITHOUT
assuming any specific protocol's bit layout. It also flags replay risk (a repeated code).

It performs NO brute-force, NO key recovery, and NO transmission. Pure + unit-testable.
"""
import os
import sys


def to_bits(payload):
    """Accept a bit string ('0101'), a hex string ('0x1a3' or '1a3'), or an int-list; return a
    canonical bit string."""
    if isinstance(payload, (list, tuple)):
        return "".join("1" if b else "0" for b in payload)
    s = str(payload).strip().lower()
    if set(s) <= {"0", "1"} and s:
        return s
    if s.startswith("0x"):
        s = s[2:]
    width = len(s) * 4
    return bin(int(s, 16))[2:].zfill(width)


def bit_stability(payloads):
    """For equal-length captures, the fraction of captures in which each bit position is 1.
    Positions at 0.0 or 1.0 are FIXED; anything in between changes (rolling/encrypted)."""
    bits = [to_bits(p) for p in payloads]
    if not bits:
        return []
    width = len(bits[0])
    if any(len(b) != width for b in bits):
        raise ValueError("captures differ in length; align them first")
    n = len(bits)
    return [sum(b[i] == "1" for b in bits) / n for i in range(width)]


def fixed_positions(payloads):
    stab = bit_stability(payloads)
    return [i for i, p in enumerate(stab) if p in (0.0, 1.0)]


def rolling_positions(payloads):
    stab = bit_stability(payloads)
    return [i for i, p in enumerate(stab) if 0.0 < p < 1.0]


def classify_sequence(payloads):
    """'fixed' (every capture identical -> replayable), 'rolling' (changes), or 'empty'/'single'.
    Returns (label, detail dict)."""
    bits = [to_bits(p) for p in payloads]
    if not bits:
        return "empty", {}
    uniq = set(bits)
    if len(bits) == 1:
        return "single", {"captures": 1}
    if len(uniq) == 1:
        return "fixed", {"captures": len(bits), "unique": 1, "note": "same code every time — replayable"}
    try:
        roll = rolling_positions(payloads)
        fixed = fixed_positions(payloads)
    except ValueError:
        roll, fixed = [], []
    return "rolling", {"captures": len(bits), "unique": len(uniq),
                       "rolling_bits": len(roll), "fixed_bits": len(fixed),
                       "rolling_positions": roll, "fixed_positions": fixed}


def replay_risk(payloads):
    """Any code seen more than once is replay-able. Returns the list of repeated codes."""
    bits = [to_bits(p) for p in payloads]
    seen, repeats = set(), set()
    for b in bits:
        if b in seen:
            repeats.add(b)
        seen.add(b)
    return sorted(repeats)


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("RollCode")
    S.settings("rollcode", {})
    root, F = S.make_root("Rolling Code", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Rolling Code", "Keyfob analysis · no brute-force · no TX")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Capture several presses of a remote (via the IQ Recorder / rtl_433), then "
                  "analyze: fixed vs rolling code, which bits are the fixed serial vs the hopping "
                  "field, and replay risk. Analysis only — nothing is transmitted.").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
