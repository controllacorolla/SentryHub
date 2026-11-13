#!/usr/bin/env python3
"""passaudit.py — password-strength audit (authorized engagements only).

Offline assessment of a WPA handshake / PMKID YOU captured under an engagement: convert it to the
cracking format and run a wordlist/mask audit to see whether the network's passphrase is weak. This
is how you prove 'our Wi-Fi password is strong enough' (or isn't). Gated on the engagement that
owns the capture (target in scope) so the audit is part of the logged assessment. The keyspace/time
estimates are pure and unit-testable; hashcat/aircrack run with the tools + a wordlist.
"""
import math
import os
import sys

import engagement

HASHCAT_MODES = {"wpa_eapol": 22000, "pmkid": 22000, "wpa_pmk": 2500}


def hcx_convert_argv(pcapng, out_hc22000):
    """Convert a capture to the hashcat 22000 format."""
    return ["hcxpcapngtool", "-o", out_hc22000, pcapng]


def hashcat_argv(hash_file, wordlist, mode=22000, mask=None):
    if mask:
        return ["hashcat", "-m", str(mode), "-a", "3", hash_file, mask]
    return ["hashcat", "-m", str(mode), "-a", "0", hash_file, wordlist]


def aircrack_argv(cap_file, wordlist, bssid=None):
    argv = ["aircrack-ng", "-w", wordlist]
    if bssid:
        argv += ["-b", bssid]
    return argv + [cap_file]


def keyspace(charset_size, length):
    """Number of candidate passwords for a brute-force of given charset/length."""
    return int(charset_size) ** int(length)


def crack_seconds(keyspace_size, hashes_per_sec):
    """Expected time to exhaust half the keyspace at a given hashrate (seconds)."""
    if hashes_per_sec <= 0:
        return math.inf
    return (keyspace_size / 2) / hashes_per_sec


def strength_verdict(seconds):
    """Human verdict from expected crack time."""
    if seconds < 3600:
        return "weak", "cracked in under an hour — change it"
    if seconds < 86400 * 30:
        return "marginal", "cracked within a month — strengthen it"
    if seconds < 86400 * 365 * 100:
        return "ok", "would take years"
    return "strong", "infeasible to brute-force"


def prepare(action, target, hash_file="cap.hc22000", wordlist="rockyou.txt", mode=22000,
            mask=None, pcapng="cap.pcapng", evidence_chain=None):
    """Gate + build a password-audit command for an in-scope capture. Returns (ok, reason, argv)."""
    if action == "convert":
        argv = hcx_convert_argv(pcapng, hash_file)
    elif action == "hashcat":
        argv = hashcat_argv(hash_file, wordlist, mode, mask)
    elif action == "aircrack":
        argv = aircrack_argv(pcapng, wordlist, target)
    else:
        return False, "unknown action %r" % (action,), None
    ok, why = engagement.authorize_action("passaudit:" + action, target, evidence_chain)
    if not ok:
        return False, why, None
    return True, why, argv


def main(parent=None):
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    import engagement as E
    if parent is None:
        S.single_instance("PassAudit")
    s, spath = S.settings("passaudit", {"target": "", "capture": "cap.pcapng",
                                        "wordlist": "/usr/share/wordlists/rockyou.txt"})
    root, F = S.make_root("Password Audit", parent=parent)
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("passaudit")
    have = bool(shutil.which("hashcat") or shutil.which("aircrack-ng"))

    S.top_bar(root, F, "Password Audit", "Audit your own handshake · engagement-gated")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True, padx=T.px(12), pady=T.px(8))
    fields = {}
    for key, label in (("target", "target BSSID"), ("capture", "capture file"),
                       ("wordlist", "wordlist")):
        row = tk.Frame(body, bg=S.BG)
        row.pack(fill="x", pady=T.px(3))
        tk.Label(row, text=label, width=13, anchor="w", bg=S.BG, fg=T.TXT_3,
                 font=F["sm"]).pack(side="left")
        e = tk.Entry(row, font=F["mono"])
        e.insert(0, str(s.get(key, "")))
        e.pack(side="left", fill="x", expand=True)
        fields[key] = e

    # quick offline strength estimate (what a brute-force would cost)
    est = tk.Label(body, text="", font=F["mono"], fg=S.AMBER, bg=S.BG, anchor="w", justify="left")
    est.pack(fill="x", pady=T.px(6))
    status = tk.Label(body, text="", font=F["sm"], fg=T.TXT_3, bg=S.BG, anchor="w",
                      justify="left", wraplength=T.px(700))
    status.pack(fill="x")

    def estimate():
        # typical GPU ~ 1e6 WPA2 H/s; show time for charset=95, lengths 8/10/12
        lines = []
        for length in (8, 10, 12):
            ks = keyspace(95, length)
            secs = crack_seconds(ks, 1_000_000)
            level, note = strength_verdict(secs)
            yrs = secs / (86400 * 365)
            lines.append("%2d-char (full ASCII): %-9s %s" % (
                length, level, ("%.1e yr" % yrs if yrs >= 1 else "%.0f s" % secs)))
        est.config(text="Brute-force cost @ 1 MH/s:\n  " + "\n  ".join(lines))
    estimate()

    def audit():
        tgt = fields["target"].get().strip()
        if not tgt:
            status.config(text="set the target BSSID (the capture you own)", fg=S.AMBER)
            return
        ok, why, argv = prepare("hashcat", tgt, hash_file=fields["capture"].get().strip(),
                                wordlist=fields["wordlist"].get().strip())
        if not ok:
            status.config(text="BLOCKED: " + why, fg=S.RED)
            return
        slog.event("passaudit", "audit %s" % tgt, id=tgt)
        status.config(text="Authorized: %s\n  %s" % (why, " ".join(argv)), fg=S.GREEN)

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Audit (gated)", audit, F, padx=14, pady=5, kind="primary").pack(
        side="left", padx=(10, 6), pady=6)
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))

    def on_close():
        for k, e in fields.items():
            s[k] = e.get().strip()
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()
    S.bind_quit(root, on_close)
    msg = "Cracking tools present." if have else "Install hashcat / aircrack-ng to run."
    if not E.is_active():
        msg += " No engagement open — Audit is gated."
    status.config(text=msg)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
