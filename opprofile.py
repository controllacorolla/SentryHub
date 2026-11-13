#!/usr/bin/env python3
"""opprofile.py — operator profile: one place for the operator's identity + authorization.

TX gating, the QSO/ADIF logger, beacons, and the evidence-chain engagement record all read the
operator's callsign, grid, license class and pen-test authorization from here, instead of each
module keeping its own copy. Credentials are NEVER invented or hardcoded — the operator enters
them, and outbound services (WSPRnet, APRS-IS, LoTW) are opt-in and separately configured.

Pure helpers (validation, the deterministic APRS-IS passcode) are unit-testable.
"""
import os
import re
import sys

DEFAULTS = {"callsign": "", "grid": "", "license_class": "", "name": "",
            "authorization": "", "wsprnet_opt_in": False, "aprsis_opt_in": False}

_GRID = re.compile(r"^[A-R]{2}[0-9]{2}([a-x]{2})?$", re.I)


def valid_callsign(call):
    """Delegates to txguard's amateur-callsign check (the single source of truth)."""
    import txguard
    return txguard.valid_callsign(call)


def valid_grid(grid):
    """Maidenhead locator, 4 or 6 characters."""
    return bool(grid) and bool(_GRID.match(str(grid).strip()))


def aprs_passcode(callsign):
    """The standard deterministic APRS-IS passcode for a callsign (derived from the call, not a
    secret the operator types). Base callsign only (SSID stripped)."""
    call = str(callsign or "").split("-")[0].upper()
    if not call:
        return -1
    h = 0x73E2
    for i, c in enumerate(call):
        h ^= ord(c) << (8 if i % 2 == 0 else 0)
    return h & 0x7FFF


def validate(profile):
    """Return a list of problems with the profile (empty = OK to transmit)."""
    problems = []
    if not valid_callsign(profile.get("callsign")):
        problems.append("callsign missing or malformed")
    if profile.get("grid") and not valid_grid(profile["grid"]):
        problems.append("grid is not a valid Maidenhead locator")
    return problems


def can_tx(profile):
    """May this operator transmit on ham bands? (A valid callsign is the legal minimum.)"""
    return valid_callsign(profile.get("callsign"))


def load(settings_fn, name="operator"):
    """Load the operator profile via a suite-style settings function; returns the profile dict."""
    s, _ = settings_fn(name, DEFAULTS)
    return s


def tx_settings(profile):
    """A settings dict TX modules can hand to txguard (callsign + tx_enabled gate)."""
    return {"callsign": profile.get("callsign", ""),
            "tx_enabled": bool(profile.get("callsign")) and profile.get("tx_enabled", True)}


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Operator")
    s, spath = S.settings("operator", DEFAULTS)
    root, F = S.make_root("Operator Profile", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Operator Profile", "Callsign · grid · authorization")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True, padx=T.px(12), pady=T.px(8))
    entries = {}
    for key in ("callsign", "grid", "license_class", "name", "authorization"):
        row = tk.Frame(body, bg=S.BG)
        row.pack(fill="x", pady=T.px(3))
        tk.Label(row, text=key, width=14, anchor="w", bg=S.BG, fg=T.TXT_3,
                 font=F["sm"]).pack(side="left")
        e = tk.Entry(row, font=F["mono"])
        e.insert(0, str(s.get(key, "")))
        e.pack(side="left", fill="x", expand=True)
        entries[key] = e
    status = tk.Label(body, text="", font=F["sm"], fg=T.TXT_3, bg=S.BG, anchor="w")
    status.pack(fill="x", pady=T.px(8))

    def save():
        for k, e in entries.items():
            s[k] = e.get().strip()
        probs = validate(s)
        if probs:
            status.config(text="⚠ " + "; ".join(probs), fg=S.AMBER)
        else:
            pc = aprs_passcode(s["callsign"])
            status.config(text="OK — TX enabled. APRS-IS passcode: %d" % pc, fg=S.GREEN)
        try:
            S.save_json(spath, s)
        except Exception:
            pass
    S.btn(body, "Save", save, F, padx=14, pady=5, kind="primary").pack(anchor="w", pady=T.px(6))
    save()
    S.bind_quit(root, lambda: (S.save_json(spath, s), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
