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
# Scope catalogue (owner decision 2026-11-17, "all tools in scope"): active network + web
# enumeration tools. Each is engagement-gated by catalog_prepare() exactly like nmap/arp-scan;
# this is a GATE CATALOG, not execution wiring — no attack-specific flags are baked in here, and a
# tool returns no runnable ticket without an open, in-scope engagement.
_NET_CATALOG = frozenset((
    "nbtscan", "netdiscover", "masscan", "smbmap", "enum4linux-ng", "netexec", "nxc",
    "hydra", "bettercap", "mitmproxy",
    "impacket-secretsdump", "impacket-wmiexec", "impacket-samrdump", "impacket-rpcdump",
    "impacket-netview",
))
_WEB_CATALOG = frozenset((
    "nikto", "sqlmap", "whatweb", "gobuster", "ffuf", "feroxbuster", "nuclei", "testssl", "cewl",
))
CATALOG_PROGRAMS = _NET_CATALOG | _WEB_CATALOG
ALLOWED_PROGRAMS = frozenset(("nmap", "arp-scan")) | CATALOG_PROGRAMS


def _ping_sweep_argv(cidr):
    return ["nmap", "-n", "-sn", cidr]


def _port_scan_argv(target, ports="1-1024", syn=True):
    return ["nmap", "-n", "-sS" if syn else "-sT", "-p", str(ports), target]


def _service_enum_argv(target, ports="1-1024"):
    return ["nmap", "-n", "-sV", "-p", str(ports), target]


def _os_fingerprint_argv(target):
    return ["nmap", "-n", "-O", target]


def _survey_argv(target):
    """Scout's "Scan my network": connect scan with light version detection, greppable output."""
    return ["nmap", "-n", "-sV", "--version-light", "-T4", "--open", "-oG", "-", target]


def _arp_scan_argv(iface):
    """arp-scan of the local net: ACTIVE. Private and not wired to any gate action yet."""
    return ["arp-scan", "--interface", iface, "--localnet"]


_ACTIONS = {"discover": _ping_sweep_argv, "portscan": _port_scan_argv,
            "services": _service_enum_argv, "osfp": _os_fingerprint_argv,
            "survey": _survey_argv}
_PORTS_RE = __import__("re").compile(r"^[0-9]{1,5}(-[0-9]{1,5})?(,[0-9]{1,5}(-[0-9]{1,5})?)*$")


def _literal_targets(t):
    """RA-RX H1: what nmap is given for a non-hostname target — address / network literals only.
    A scope prefix (ip: / host:) is stripped and an a-b range becomes the CIDR blocks that cover
    exactly it, because nmap reads neither form as an address and would hand the text to the
    system resolver (a search domain or hostile DNS would then choose the scanned host). Passing
    literals only is what stops forward lookups; -n additionally stops nmap's reverse lookups.
    None if t is no literal."""
    import ipaddress
    s = t
    for pre in ("ip:", "host:"):
        if s.lower().startswith(pre):
            s = s[len(pre):]
    try:
        if "-" in s and "/" not in s:
            a, _, b = s.partition("-")
            lo, hi = ipaddress.ip_address(a), ipaddress.ip_address(b)
            return [str(n) for n in ipaddress.summarize_address_range(lo, hi)]
        if "/" in s:
            return [str(ipaddress.ip_network(s, strict=True))]
        return [str(ipaddress.ip_address(s))]
    except (ValueError, TypeError):
        return None


def _is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def prepare(action, target, evidence_chain=None, ports="1-1024", syn=None, out=None):
    """Gate + build a network scan. Every action is active (touches the target), so all require an
    open engagement with `target` inside the typed IP scope (address / network / range; a hostname
    is resolved and every address must be in scope). Returns (ok, reason, ticket) — the ticket is
    single-use and runs only through executor.run()/start().

    RX: `syn=None` picks the port-scan type that can actually run: a SYN scan (-sS) needs raw
    sockets (root), so an unprivileged operator gets a connect scan (-sT) instead of an nmap that
    quits with "requires root privileges". The scope check is the same either way.

    RX-fix2: `out` (a file path) adds `-oN out`, so the scan's results are kept as evidence (the
    path is in the argv the chain records at issue and spawn). IPv6 targets get `-6` (without it
    nmap scans nothing and still exits 0); a target whose addresses mix IPv4 and IPv6 is refused
    with the addresses to scan separately."""
    if action not in _ACTIONS:
        return False, "unknown action %r" % (action,), None
    if not _PORTS_RE.match(str(ports)):
        return False, "ports must look like 1-1024 or 22,80,443", None
    t = str(target).strip()
    if t.startswith("-"):
        return False, "target %r looks like an option" % (target,), None
    if out is not None:
        # RA-RXc N5: results go only under <DATA>/captures (no option, no other path)
        import suite
        cap = os.path.realpath(os.path.join(suite.DATA, "captures"))
        o = str(out)
        if not o or o.startswith("-") or os.path.dirname(os.path.realpath(o)) != cap:
            return False, "output path %r is not a file in the captures folder" % (out,), None
    # CL2-fix N5: a hostname is resolved ONCE here; nmap gets the checked addresses (every one in
    # scope, re-checked at spawn), never the name — no second, unchecked lookup by nmap.
    try:
        pinned = engagement.pin_host(t)
    except ValueError as e:
        return False, "refused: %s" % e, None
    if pinned:
        addrs = pinned
    else:
        addrs = _literal_targets(t)
        if addrs is None:
            import re
            if re.fullmatch(r"(host:)?[A-Za-z0-9][A-Za-z0-9-]{0,62}", t, re.I):
                return False, ("refused: %r is a single-word name — it is not looked up (the "
                               "answer would depend on the search domain); use its IP address "
                               "or a full name like %s.lan" % (target, t.split(":")[-1])), None
            return False, ("refused: %r is not an IP address, network, range or hostname"
                           % (target,)), None
    import ipaddress
    fams = {ipaddress.ip_network(a, strict=False).version for a in addrs}
    if len(fams) > 1:
        return False, ("refused: %r mixes IPv4 and IPv6 addresses (%s) — scan each address "
                       "separately" % (target, ", ".join(addrs))), None
    if action == "portscan":
        argv = _port_scan_argv(addrs[0], ports, syn=_is_root() if syn is None else bool(syn))
    elif action == "services":
        argv = _service_enum_argv(addrs[0], ports)
    else:
        argv = _ACTIONS[action](addrs[0])
    opts = (["-6"] if fams == {6} else []) + (["-oN", str(out)] if out is not None else [])
    argv = argv[:-1] + opts + addrs                 # every builder ends with its target
    label = "net:" + action + ((":" + t) if pinned else "")
    return engagement.issue("net:" + action, addrs[0], argv=argv, kind="ip",
                            evidence_chain=evidence_chain, label=label,
                            also=tuple((a, "ip") for a in addrs[1:]))


def catalog_prepare(tool, target, args=(), evidence_chain=None):
    """Gate + build a catalogued active RECON tool (CATALOG_PROGRAMS) against an in-scope host/IP.
    Returns (ok, reason, ticket). Same gate as prepare(): the target must sit inside the open
    engagement's typed IP scope (a hostname is pinned to its resolved addresses, every one
    re-checked at spawn). `args` are extra, already-plain tokens the caller supplies; no
    attack-specific flags are baked in here. Out of scope — or with no engagement — the gate
    returns (False, reason, None) and no ticket."""
    if tool not in CATALOG_PROGRAMS:
        return False, "%r is not a catalogued RECON tool" % (tool,), None
    toks = [str(a) for a in (args or ())]
    if any((not a) or a != a.strip() for a in toks):
        return False, "extra arguments must be plain, non-empty tokens", None
    t = str(target).strip()
    if t.startswith("-"):
        return False, "target %r looks like an option" % (target,), None
    try:
        pinned = engagement.pin_host(t)
    except ValueError as e:
        return False, "refused: %s" % e, None
    addrs = pinned or [t]
    argv = [tool] + toks + addrs
    label = "recon:" + tool + ((":" + t) if pinned else "")
    return engagement.issue("recon:" + tool, addrs[0], argv=argv, kind="ip",
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
