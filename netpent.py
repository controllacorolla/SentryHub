#!/usr/bin/env python3
"""netpent.py — network assessment (authorized engagements only).

Host discovery, port scanning and service enumeration for a network you are authorized to test.
Scanning reaches out to targets, so every scan is gated on an open engagement with the target
host/subnet in scope, and logged to the evidence chain. Pure command-building + gating is
unit-testable; nmap/arp-scan run with the right tools installed.
"""
import os
import sys

import engagement


def ping_sweep_argv(cidr):
    return ["nmap", "-sn", cidr]


def port_scan_argv(target, ports="1-1024", syn=True):
    return ["nmap", "-sS" if syn else "-sT", "-p", str(ports), target]


def service_enum_argv(target, ports="1-1024"):
    return ["nmap", "-sV", "-p", str(ports), target]


def os_fingerprint_argv(target):
    return ["nmap", "-O", target]


def arp_scan_argv(iface):
    return ["arp-scan", "--interface", iface, "--localnet"]


_ACTIONS = {"discover": ping_sweep_argv, "portscan": port_scan_argv,
            "services": service_enum_argv, "osfp": os_fingerprint_argv}


def prepare(action, target, evidence_chain=None, ports="1-1024"):
    """Gate + build a network scan. Every action is active (touches the target), so all require an
    open engagement with `target` (IP/host/CIDR) in scope. Returns (ok, reason, argv)."""
    if action not in _ACTIONS:
        return False, "unknown action %r" % (action,), None
    ok, why = engagement.authorize_action("net:" + action, target, evidence_chain)
    if not ok:
        return False, why, None
    if action in ("portscan", "services"):
        argv = _ACTIONS[action](target, ports)
    else:
        argv = _ACTIONS[action](target)
    return True, why, argv


def main(parent=None):
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("NetPent")
    S.settings("netpent", {})
    root, F = S.make_root("Network Assessment", parent=parent)
    import tkinter as tk
    T = S.T
    have = bool(shutil.which("nmap"))
    S.top_bar(root, F, "Network Assessment", "Host/port/service scan · engagement-gated")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text=("Discover hosts, scan ports and enumerate services on a network you are "
                   "authorized to test. Every scan needs an open engagement with the target in "
                   "scope, and is logged. " + ("nmap present." if have else "Install nmap."))).pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
