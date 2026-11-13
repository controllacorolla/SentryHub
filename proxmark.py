#!/usr/bin/env python3
"""proxmark.py — Proxmark3 RFID/NFC assessment (Phase 6 #13).

Drives a USB-connected Proxmark3 for LF (125 kHz: EM4x / HID / T55xx) and HF (13.56 MHz: MIFARE /
iCLASS) work. Reading a card you are holding is passive and ungated; WRITE / CLONE / SIM are active
impersonation and go through the engagement gate (scoped, authorized, evidence-logged) — even on
your own cards, so the assessment is auditable. Degrades gracefully with no Proxmark3 attached.
Pure command-building + gating is unit-testable.
"""
import os
import shutil
import sys

import engagement

# op -> (is_active, pm3 client command template, band). Active ops require an engagement.
OPS = {
    "lf_search":      (False, "lf search", "LF"),
    "hf_search":      (False, "hf search", "HF"),
    "hf_mf_info":     (False, "hf mf info", "HF"),
    "lf_hid_read":    (False, "lf hid read", "LF"),
    "hf_14a_info":    (False, "hf 14a info", "HF"),
    "lf_hid_clone":   (True, "lf hid clone -r {id}", "LF"),
    "lf_t55_write":   (True, "lf t55xx write -b {block} -d {data}", "LF"),
    "hf_mf_restore":  (True, "hf mf restore --1k", "HF"),
    "hf_mf_sim":      (True, "hf mf sim --1k -u {uid}", "HF"),
    "hf_iclass_clone": (True, "hf iclass clone", "HF"),
}


def is_active(op):
    return bool(OPS.get(op, (False,))[0])


def pm3_command(op, **params):
    if op not in OPS:
        raise ValueError("unknown proxmark op: %r" % (op,))
    return OPS[op][1].format(**params)


def prepare(op, target=None, evidence_chain=None, **params):
    """Build a Proxmark3 command. For active ops, gate through the engagement authorization first.
    Returns (ok, reason, command_string)."""
    if op not in OPS:
        return False, "unknown op %r" % (op,), None
    try:
        cmd = pm3_command(op, **params)
    except KeyError as e:
        return False, "missing parameter %s for %s" % (e, op), None
    if is_active(op):
        ok, why = engagement.authorize_action("proxmark:" + op, target, evidence_chain)
        if not ok:
            return False, why, None
        return True, why, cmd
    return True, "read op (ungated)", cmd


def detect(which=shutil.which):
    """Is a Proxmark3 client installed?"""
    return bool(which("pm3") or which("proxmark3"))


def client_argv(command, port="/dev/ttyACM0", which=shutil.which):
    """Full pm3 client invocation for a single command."""
    binary = "pm3" if which("pm3") else "proxmark3"
    return [binary, "-p", port, "-c", command]


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Proxmark")
    S.settings("proxmark", {})
    root, F = S.make_root("Proxmark3", parent=parent)
    import tkinter as tk
    T = S.T
    present = detect()
    S.top_bar(root, F, "Proxmark3", "RFID / NFC · read ungated · clone/sim gated")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text=("LF (EM4x/HID/T55xx) + HF (MIFARE/iCLASS). Reading a card is ungated; "
                   "write/clone/sim require an open, scoped engagement and are logged to the "
                   "evidence chain. " + ("Proxmark3 detected." if present
                                         else "No Proxmark3 found — attach one over USB."))).pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
