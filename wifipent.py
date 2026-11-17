#!/usr/bin/env python3
"""wifipent.py — active 802.11 assessment (Phase 6, authorized engagements only).

Beyond the passive survey (wifisurvey.py): monitor-mode capture, WPA handshake / PMKID capture for
password-strength assessment, and a SMALL, targeted deauth to force a client to re-handshake so the
capture completes. Every active action is gated by an open, scoped engagement (in-scope BSSID) and
logged to the evidence chain.

Deliberate limits — this is an assessment tool, not a weapon:
  * deauth is targeted at one in-scope BSSID (+ optionally one client) and HARD-CAPPED to a few
    frames (enough to trigger a re-handshake); there is no broadcast/continuous/flood mode.
  * it will not touch a BSSID that is not in the engagement scope.
Pure command-building + gating is unit-testable; the capture tools run only with the right hardware.
"""
import os
import sys

import engagement

DEAUTH_MAX = 10          # hard cap: enough to force a re-handshake, never a denial-of-service


# CL2-fix2 R1: the only programs this module may run through the engagement gate (argv[0],
# a bare name). engagement.issue refuses anything else.
ALLOWED_PROGRAMS = frozenset(("airodump-ng", "hcxdumptool", "aireplay-ng"))


def monitor_argv(iface, enable=True):
    return ["airmon-ng", "start" if enable else "stop", iface]


def set_channel_argv(iface, channel):
    return ["iw", "dev", iface, "set", "channel", str(int(channel))]


def _handshake_capture_argv(iface, bssid, channel, out_prefix):
    """airodump-ng targeted at one BSSID to capture its WPA handshake."""
    return ["airodump-ng", "--bssid", bssid, "--channel", str(int(channel)),
            "--write", out_prefix, "--output-format", "pcap", iface]


def _pmkid_capture_argv(iface, out_file, filter_file):
    """hcxdumptool PMKID/EAPOL capture, restricted to the in-scope AP by a filter list
    (--filtermode=2: attack only the listed APs) — audit G5."""
    return ["hcxdumptool", "-i", iface, "-o", out_file, "--enable_status=1",
            "--filterlist_ap=" + filter_file, "--filtermode=2"]


def _deauth_argv(iface, bssid, client, count=3):
    """A SMALL, targeted deauth to trigger a re-handshake: one AP, one client, count clamped to
    DEAUTH_MAX. There is no broadcast form."""
    n = max(1, min(DEAUTH_MAX, int(count)))
    return ["aireplay-ng", "--deauth", str(n), "-a", bssid, "-c", client, iface]


def _mac(x):
    import re
    s = re.sub(r"[:-]", "", str(x or "").strip()).upper()
    if not re.fullmatch(r"[0-9A-F]{12}", s):
        return None
    return ":".join(s[i:i + 2] for i in range(0, 12, 2))


def prepare(action, bssid, client=None, evidence_chain=None, iface="wlan0mon", channel=1,
            out="cap", count=3):
    """Gate + build an active Wi-Fi action. Returns (ok, reason, ticket). The scope is bound to the
    command (audit G5): handshake and PMKID capture filter on the in-scope BSSID; a deauth needs a
    client, and both the AP and the client must be in scope (no client = refused, never a
    broadcast)."""
    if action not in ("handshake", "pmkid", "deauth"):
        return False, "unknown action %r" % (action,), None
    ok, why = engagement.require_active()
    if not ok:
        return False, why, None
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", str(iface or "")):
        # RX: the interface is an argv token of a tool run through the executor; a value that
        # starts with "-" (or carries a path) would be read as an option, so it is refused here
        return False, "interface %r is not a network interface name" % (iface,), None
    if not str(out or "") or str(out).startswith("-"):
        return False, "capture path %r is not a file path" % (out,), None
    ap = _mac(bssid)
    if ap is None:
        return False, "BSSID %r is not a MAC address" % (bssid,), None
    try:
        ch = int(channel)
    except (TypeError, ValueError):
        return False, "channel must be a number", None
    files = None
    if action == "handshake":
        argv = _handshake_capture_argv(iface, ap, ch, out)
    elif action == "pmkid":
        ffile = str(out) + ".bssid"
        argv = _pmkid_capture_argv(iface, str(out) + ".pcapng", ffile)
        files = {ffile: ap.replace(":", "") + "\n"}
    else:
        cl = _mac(client)
        if cl is None:
            return False, ("deauth needs a target client MAC (no broadcast deauth) — "
                           "refusing"), None
        ok, why, _b = engagement.check("wifi:deauth", cl, kind="mac")
        if not ok:
            return False, "client: " + why, None
        argv = _deauth_argv(iface, ap, cl, count)
    return engagement.issue("wifi:" + action, ap, argv=argv, kind="mac",
                            evidence_chain=evidence_chain, label="wifi:" + action, files=files)


def main(parent=None):
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("WiFiPent")
    S.settings("wifipent", {"iface": "wlan0"})
    root, F = S.make_root("Wi-Fi Assessment", parent=parent)
    import tkinter as tk
    T = S.T
    have = bool(shutil.which("airodump-ng") or shutil.which("hcxdumptool"))
    S.top_bar(root, F, "Wi-Fi Assessment", "Authorized · engagement-gated · no flood")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text=("WPA handshake / PMKID capture for password-strength assessment, with a small "
                   "targeted deauth (capped — not a flood) to complete the capture. Every action "
                   "needs an open engagement with the target AP in scope, and is logged. "
                   + ("Capture tools present." if have else "Install aircrack-ng / hcxdumptool."))).pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
