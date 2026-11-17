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


# CL2-fix2 R1: the only programs this module may run through the engagement gate (argv[0],
# a bare name). engagement.issue refuses anything else.
ALLOWED_PROGRAMS = frozenset(("nmap", "arp-scan"))


def _ping_sweep_argv(cidr):
    return ["nmap", "-sn", cidr]


def _port_scan_argv(target, ports="1-1024", syn=True):
    return ["nmap", "-sS" if syn else "-sT", "-p", str(ports), target]


def _service_enum_argv(target, ports="1-1024"):
    return ["nmap", "-sV", "-p", str(ports), target]


def _os_fingerprint_argv(target):
    return ["nmap", "-O", target]


def _survey_argv(target):
    """Scout's "Scan my network": connect scan with light version detection, greppable output."""
    return ["nmap", "-sV", "--version-light", "-T4", "--open", "-oG", "-", target]


def _arp_scan_argv(iface):
    """arp-scan of the local net: ACTIVE. Private and not wired to any gate action yet."""
    return ["arp-scan", "--interface", iface, "--localnet"]


_ACTIONS = {"discover": _ping_sweep_argv, "portscan": _port_scan_argv,
            "services": _service_enum_argv, "osfp": _os_fingerprint_argv,
            "survey": _survey_argv}
_PORTS_RE = __import__("re").compile(r"^[0-9]{1,5}(-[0-9]{1,5})?(,[0-9]{1,5}(-[0-9]{1,5})?)*$")


def _is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def prepare(action, target, evidence_chain=None, ports="1-1024", syn=None):
    """Gate + build a network scan. Every action is active (touches the target), so all require an
    open engagement with `target` inside the typed IP scope (address / network / range; a hostname
    is resolved and every address must be in scope). Returns (ok, reason, ticket) — the ticket is
    single-use and runs only through executor.run()/start().

    RX: `syn=None` picks the port-scan type that can actually run: a SYN scan (-sS) needs raw
    sockets (root), so an unprivileged operator gets a connect scan (-sT) instead of an nmap that
    quits with "requires root privileges". The scope check is the same either way."""
    if action not in _ACTIONS:
        return False, "unknown action %r" % (action,), None
    if not _PORTS_RE.match(str(ports)):
        return False, "ports must look like 1-1024 or 22,80,443", None
    t = str(target).strip()
    if t.startswith("-"):
        return False, "target %r looks like an option" % (target,), None
    # CL2-fix N5: a hostname is resolved ONCE here; nmap gets the checked addresses (every one in
    # scope, re-checked at spawn), never the name — no second, unchecked lookup by nmap.
    try:
        pinned = engagement.pin_host(t)
    except ValueError as e:
        return False, "refused: %s" % e, None
    addrs = pinned or [t]
    if action == "portscan":
        argv = _port_scan_argv(addrs[0], ports, syn=_is_root() if syn is None else bool(syn))
    elif action == "services":
        argv = _service_enum_argv(addrs[0], ports)
    else:
        argv = _ACTIONS[action](addrs[0])
    argv = argv[:-1] + addrs                        # every builder ends with its target
    label = "net:" + action + ((":" + t) if pinned else "")
    return engagement.issue("net:" + action, addrs[0], argv=argv, kind="ip",
                            evidence_chain=evidence_chain, label=label,
                            also=tuple((a, "ip") for a in addrs[1:]))


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
