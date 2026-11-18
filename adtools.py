#!/usr/bin/env python3
"""adtools.py — Active Directory / SMB enumeration (authorized engagements only).

The core internal-pentest job: enumerate SMB shares, sessions, users and RPC endpoints on a Windows
/ Samba host you are authorized to test. Every action reaches out to the target, so each is gated on
an open engagement with the target host/IP in scope and logged to the evidence chain — the same gate
as nmap (engagement.issue). Pure command-building + gating is unit-testable; the tools run with the
right packages installed.

This first pass is UNAUTHENTICATED (null / guest session) — the highest-value first step on an
internal test and, importantly, one that puts NO credential on the command line (argv is recorded in
the tamper-evident chain, so a password must never be built into it). Credentialed enumeration is a
documented follow-up that will carry the secret out of band, not through argv.
"""
import shutil

import engagement

_NXC = None


def _nxc_name():
    """netexec's binary is `nxc` (new) or `netexec` (older). Pick the installed one; default to
    nxc so the command is stable when neither is installed (the pane then says 'not installed')."""
    global _NXC
    if _NXC is None:
        _NXC = "nxc" if shutil.which("nxc") or not shutil.which("netexec") else "netexec"
    return _NXC


ALLOWED_PROGRAMS = frozenset((
    "smbmap", "nxc", "netexec", "enum4linux-ng",
    "impacket-samrdump", "impacket-rpcdump", "impacket-netview",
))


def _smbmap_argv(addr):
    return ["smbmap", "-H", addr]                         # null session: list shares + access


def _netexec_argv(addr):
    return [_nxc_name(), "smb", addr]                     # null session: host info, shares, users


def _enum4linux_argv(addr):
    return ["enum4linux-ng", "-A", addr]                  # all simple enumeration


def _samrdump_argv(addr):
    return ["impacket-samrdump", addr]                    # users/groups via SAMR (null)


def _rpcdump_argv(addr):
    return ["impacket-rpcdump", addr]                     # RPC endpoint map


_ACTIONS = {"shares": _smbmap_argv, "netexec": _netexec_argv, "enum": _enum4linux_argv,
            "samr": _samrdump_argv, "rpc": _rpcdump_argv}


def prepare(action, target, evidence_chain=None):
    """Gate + build one SMB/AD enumeration action against `target` (a host or IP). The target must
    be inside the open engagement's IP scope (a hostname is resolved and every address re-checked at
    spawn). Returns (ok, reason, ticket) — the ticket runs only through executor.start()."""
    if action not in _ACTIONS:
        return False, "unknown action %r" % (action,), None
    t = str(target).strip()
    if t.startswith("-"):
        return False, "target %r looks like an option" % (target,), None
    try:
        pinned = engagement.pin_host(t)
    except ValueError as e:
        return False, "refused: %s" % e, None
    if pinned:
        addrs = pinned
    else:
        import ipaddress
        s = t[3:] if t.lower().startswith("ip:") else t
        try:
            ipaddress.ip_address(s)
            addrs = [s]
        except ValueError:
            import re
            if re.fullmatch(r"(host:)?[A-Za-z0-9][A-Za-z0-9-]{0,62}", t, re.I):
                return False, ("refused: %r is a single-word name — use its IP address or a full "
                               "name like %s.lan" % (target, t.split(':')[-1])), None
            return False, "refused: %r is not an IP address or hostname" % (target,), None
    argv = _ACTIONS[action](addrs[0])
    label = "ad:" + action + ((":" + t) if pinned else "")
    return engagement.issue("ad:" + action, addrs[0], argv=argv, kind="ip",
                            evidence_chain=evidence_chain, label=label,
                            also=tuple((a, "ip") for a in addrs[1:]))
