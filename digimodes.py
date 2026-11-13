#!/usr/bin/env python3
"""digimodes.py — digital-mode TX launcher (Phase 5 #2/#3/#4/#5/#7). Build-and-gate.

FT8, WSPR, JS8Call, PSK31 and Olivia are complex FEC/varicode protocols already implemented
correctly by WSJT-X (FT8/WSPR/JS8) and fldigi (PSK31/RTTY/Olivia/CW), both installable on this
box. Rather than reimplement their encoders from memory (error-prone, and against the suite's
"verify, don't guess" rule), this module is a txguard-GATED launcher: it refuses to even open the
TX application until the master kill switch is armed, the session is unlocked, a callsign is set,
and the band/power pass policy — then it hands off to the real tool. CW and RTTY, being simple and
universally specified, have their own in-tree encoders (cw.py / rtty.py).

Pure helpers (availability, gated prepare) are unit-testable; the Tk workspace is a mode picker.
"""
import os
import shutil
import sys

# mode -> backend tool + the txguard mode used for policy. Default dial frequencies are the common
# calling frequencies (MHz); the operator sets the real frequency in the tool.
MODES = {
    "ft8":   {"tool": "wsjtx", "guard": "ft8", "default_mhz": 14.074, "label": "FT8"},
    "ft4":   {"tool": "wsjtx", "guard": "ft4", "default_mhz": 7.0475, "label": "FT4"},
    "wspr":  {"tool": "wsjtx", "guard": "wspr", "default_mhz": 14.0956, "label": "WSPR"},
    "js8":   {"tool": "js8call", "guard": "js8", "default_mhz": 14.078, "label": "JS8Call"},
    "psk31": {"tool": "fldigi", "guard": "psk31", "default_mhz": 14.070, "label": "PSK31"},
    "olivia": {"tool": "fldigi", "guard": "olivia", "default_mhz": 14.0735, "label": "Olivia"},
}


def available(mode, which=shutil.which):
    m = MODES.get(mode)
    return bool(m and which(m["tool"]))


def installed_modes(which=shutil.which):
    return [k for k in MODES if available(k, which)]


def prepare(mode, freq_mhz=None, callsign="", settings=None, which=shutil.which):
    """Gate opening the TX tool for `mode`. Returns (ok, reason, argv).

    argv is the command to launch the backend, returned ONLY when txguard authorizes the band +
    callsign + armed kill switch + session unlock, and the backend tool is installed."""
    import txguard
    m = MODES.get(mode)
    if not m:
        return False, "unknown mode %r" % (mode,), None
    if not which(m["tool"]):
        return False, "%s is not installed (backend for %s)" % (m["tool"], m["label"]), None
    freq_hz = float(freq_mhz if freq_mhz is not None else m["default_mhz"]) * 1e6
    ok, reason, _power = txguard.authorize(m["guard"], freq_hz, callsign=callsign,
                                           settings=settings or {})
    if not ok:
        return False, reason, None
    return True, "%s via %s authorized" % (m["label"], m["tool"]), [m["tool"]]


DEFAULTS = {"mode": "ft8", "freq_mhz": 14.074, "callsign": "", "tx_enabled": False}


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("DigiModes")
    s, spath = S.settings("digimodes", DEFAULTS)
    root, F = S.make_root("Digital Modes", parent=parent)
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("digimodes")

    S.top_bar(root, F, "Digital Modes", "FT8 · WSPR · JS8 · PSK31 · Olivia · TX gated")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    inst = installed_modes()
    info = tk.Label(body, font=F["mono"], fg=T.TXT_3, bg=S.BG, anchor="w", justify="left",
                    wraplength=T.px(700),
                    text="Backends: " + (", ".join("%s(%s)" % (MODES[m]["label"], MODES[m]["tool"])
                                                   for m in inst) or "none installed"))
    info.pack(fill="x", padx=T.px(12), pady=T.px(8))
    status = tk.Label(body, text="", font=F["sm"], fg=T.TXT_3, bg=S.BG, anchor="w",
                      justify="left", wraplength=T.px(700))
    status.pack(fill="x", padx=T.px(12), pady=T.px(6))

    def launch(mode):
        ok, reason, argv = prepare(mode, s.get("freq_mhz"), s.get("callsign", ""),
                                   {"tx_enabled": s.get("tx_enabled", False),
                                    "callsign": s.get("callsign", "")})
        if not ok:
            status.config(text="Blocked: " + reason, fg=S.RED)
            return
        slog.event("digimodes", "launch %s" % mode, id=mode)
        status.config(text="Authorized: %s — launch %s manually (gate passed)" % (reason, argv[0]),
                      fg=S.GREEN)

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    for m in MODES:
        S.btn(bar, MODES[m]["label"], (lambda mm=m: launch(mm)), F, padx=10, pady=5,
              kind="primary" if available(m) else "ghost").pack(side="left", padx=2, pady=6)
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))

    def on_close():
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()
    S.bind_quit(root, on_close)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
