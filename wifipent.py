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


def monitor_argv(iface, enable=True):
    return ["airmon-ng", "start" if enable else "stop", iface]


def set_channel_argv(iface, channel):
    return ["iw", "dev", iface, "set", "channel", str(int(channel))]


def handshake_capture_argv(iface, bssid, channel, out_prefix):
    """airodump-ng targeted at one BSSID to capture its WPA handshake."""
    return ["airodump-ng", "--bssid", bssid, "--channel", str(int(channel)),
            "--write", out_prefix, "--output-format", "pcap", iface]


def pmkid_capture_argv(iface, out_file):
    """hcxdumptool PMKID/EAPOL capture (clientless where supported)."""
    return ["hcxdumptool", "-i", iface, "-o", out_file, "--enable_status=1"]


def deauth_argv(iface, bssid, client=None, count=3):
    """A SMALL, targeted deauth to trigger a re-handshake. count is clamped to DEAUTH_MAX; no
    broadcast flood is offered (a client is targeted when given)."""
    n = max(1, min(DEAUTH_MAX, int(count)))
    argv = ["aireplay-ng", "--deauth", str(n), "-a", bssid]
    if client:
        argv += ["-c", client]
    return argv


def prepare(action, bssid, client=None, evidence_chain=None, iface="wlan0mon", channel=1,
            out="cap", count=3):
    """Gate + build an active Wi-Fi action. Returns (ok, reason, argv). 'scan' is passive/ungated;
    capture/deauth require an engagement with `bssid` in scope."""
    if action == "handshake":
        argv = handshake_capture_argv(iface, bssid, channel, out)
    elif action == "pmkid":
        argv = pmkid_capture_argv(iface, out)
    elif action == "deauth":
        argv = deauth_argv(iface, bssid, client, count)
    else:
        return False, "unknown action %r" % (action,), None
    ok, why = engagement.authorize_action("wifi:" + action, bssid, evidence_chain)
    if not ok:
        return False, why, None
    return True, why, argv


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
