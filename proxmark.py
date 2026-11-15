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


def _norm_uid(u):
    import re
    s = str(u or "").strip()
    if s.lower().startswith("uid:"):
        s = s[4:]
    s = re.sub(r"[\s:]", "", s).upper()
    return s if re.fullmatch(r"(?:[0-9A-F]{2}){4,10}", s) else None


def parse_uid(text):
    """The card UID / ID from pm3 `hf 14a info` / `lf search` output, or None."""
    import re
    m = re.search(r"UID\s*:\s*((?:[0-9A-Fa-f]{2}\s?){4,10})", str(text or ""))
    if not m:
        m = re.search(r"\bID\s*:?\s*([0-9A-Fa-f]{8,20})\b", str(text or ""))
    return _norm_uid(m.group(1)) if m else None


def prepare(op, target=None, evidence_chain=None, read_uid=None, port="/dev/ttyACM0", **params):
    """Build a Proxmark3 command. Read ops: (ok, reason, command_string), ungated.
    Active ops (write / clone / sim): the scope is bound to the card (audit G5) — `target` must be a
    uid:… entry in scope, and read_uid() (a fresh read of the card on the antenna) must return the
    same UID, else refused (no read-back = refused). Returns (ok, reason, ticket)."""
    if op not in OPS:
        return False, "unknown op %r" % (op,), None
    try:
        cmd = pm3_command(op, **params)
    except KeyError as e:
        return False, "missing parameter %s for %s" % (e, op), None
    if not is_active(op):
        return True, "read op (ungated)", cmd
    ok, why = engagement.require_active()
    if not ok:
        return False, why, None
    want = _norm_uid(target)
    if want is None:
        return False, "active op needs the target card UID (scope entry uid:…)", None
    if read_uid is None:
        return False, "no UID read-back available — refusing to write a card that was not read", None
    try:
        got = _norm_uid(read_uid())
    except Exception as e:
        got, err = None, str(e)
    else:
        err = ""
    if got is None:
        return False, "UID read-back failed%s — refusing" % ((": " + err) if err else ""), None
    if got != want:
        return False, "UID mismatch: card on the antenna is %s, authorized %s — refusing" % (
            got, want), None
    return engagement.issue("proxmark:" + op, "uid:" + want, argv=client_argv(cmd, port),
                            kind="uid", evidence_chain=evidence_chain, label="proxmark:" + op)


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
