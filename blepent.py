#!/usr/bin/env python3
"""blepent.py — active BLE assessment (Phase 6, authorized engagements only).

Beyond the passive BLE scanner (blescan.py): connect to a target, enumerate its GATT services and
characteristics, and read/write characteristics to assess a device's security (e.g. an unauthenticated
write that controls something it shouldn't). Connecting to and interrogating a target is an active
action, so enum/read/write all go through the engagement gate (target BLE address in scope) and are
logged to the evidence chain. Pure command-building + gating is unit-testable.
"""
import os
import sys

import engagement


def gatt_argv(address, op, handle=None, value=None, adapter="hci0"):
    """Build a gatttool command for one GATT operation against a device."""
    base = ["gatttool", "-i", adapter, "-b", address]
    if op == "enum":
        return base + ["--primary"]
    if op == "characteristics":
        return base + ["--characteristics"]
    if op == "read":
        if handle is None:
            raise KeyError("handle")
        return base + ["--char-read", "--handle", str(handle)]
    if op == "write":
        if handle is None:
            raise KeyError("handle")
        if value is None:
            raise KeyError("value")
        return base + ["--char-write-req", "--handle", str(handle), "--value", str(value)]
    raise ValueError("unknown op %r" % (op,))


OPS = ("enum", "characteristics", "read", "write")


def prepare(action, address, handle=None, value=None, evidence_chain=None, adapter="hci0"):
    """Gate + build an active BLE action. Returns (ok, reason, argv). Every op connects to the
    target, so all are gated on an in-scope engagement."""
    if action not in OPS:
        return False, "unknown action %r" % (action,), None
    try:
        argv = gatt_argv(address, action, handle, value, adapter)
    except KeyError as e:
        return False, "missing parameter %s for %s" % (e, action), None
    ok, why = engagement.authorize_action("ble:" + action, address, evidence_chain)
    if not ok:
        return False, why, None
    return True, why, argv


def main(parent=None):
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("BLEPent")
    S.settings("blepent", {})
    root, F = S.make_root("BLE Assessment", parent=parent)
    import tkinter as tk
    T = S.T
    have = bool(shutil.which("gatttool") or shutil.which("bluetoothctl"))
    S.top_bar(root, F, "BLE Assessment", "GATT enum / read / write · engagement-gated")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text=("Connect to an in-scope BLE device, enumerate its services/characteristics and "
                   "read/write them to assess security (e.g. an unauthenticated write). All actions "
                   "need an open engagement with the device in scope, and are logged. "
                   + ("BLE tools present." if have else "Install bluez (gatttool)."))).pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
