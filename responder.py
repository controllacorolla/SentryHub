#!/usr/bin/env python3
"""responder.py — LLMNR / NBT-NS / mDNS responder, two modes.

Responder is the single biggest win on an internal engagement, and it has two very different modes:

  * ANALYZE  (`-A`): passive. It LISTENS for LLMNR / NBT-NS / mDNS name queries and logs who is
    asking for what — it never answers, so it poisons nothing. Ungated by design (like any passive
    listen), but still LOGGED to the evidence chain. Built here, run by the UI's passive runner.

  * POISON  (no `-A`): active. It ANSWERS those name queries to capture authentication, so it is a
    gated capability exactly like targeted Wi-Fi deauth (owner decision, 2026-11-17: a gated tool,
    scope-bound and logged, is not a ban). It runs ONLY inside an open, authorized engagement whose
    IP scope covers the local segment the operator names, and the issue / spawn / exit are recorded
    in that engagement's evidence chain. The gate is engagement.issue (engagement.py + the operator
    identity from opprofile.py); this module never spawns the process itself — the single-use ticket
    runs only through executor.start().

Responder needs root. The installer grants it through a dedicated NOPASSWD launcher (owner decision
2026-11-18, "Capabilities + Responder rule"): a bare `responder` shim on PATH that escalates only
itself, so the gated argv stays a bare program name (never `sudo …`, which the engagement gate
refuses). If the shim is absent the UI shows an install hint.

NOTE ON SCOPE: Responder answers for the local broadcast/multicast segment it listens on; it cannot
be aimed at one host. The engagement scope is therefore the authorization boundary — poisoning is
refused unless the segment the operator names is in scope. Narrowing which names/hosts Responder
answers (its RespondTo list) is a documented follow-up; the gate already refuses an unauthorized
segment outright.
"""
import shutil

import engagement

# CL2-fix2 R1: the only program this module's gate may mint a ticket for — a bare launcher name,
# never an interpreter or `sudo` (both of which the engagement gate refuses anyway).
ALLOWED_PROGRAMS = frozenset(("responder",))


def program():
    """The bare launcher name to run, or None if it is not installed. The installer puts a
    `responder` shim on PATH (it points at the Responder checkout and escalates via the NOPASSWD
    rule); a distro `responder`/`Responder` package would also satisfy this."""
    for name in ("responder", "Responder"):
        if shutil.which(name):
            return "responder" if name == "responder" else name
    return None


def _iface_ok(iface):
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", str(iface or "").strip()))


def analyze_argv(iface):
    """(argv, error) for ANALYZE mode (passive, ungated, logged). Run by the UI passive runner."""
    prog = program()
    if prog is None:
        return None, "Responder is not installed"
    if not _iface_ok(iface):
        return None, "interface %r is not a plain interface name" % (iface,)
    return [prog, "-I", str(iface).strip(), "-A"], None


def poison_prepare(iface, segment, evidence_chain=None):
    """Gate + build POISON mode. `segment` is the local network the operator is authorized to
    poison (an IP network / range / address); it must be inside the open engagement's scope, or the
    gate refuses with no ticket. Returns (ok, reason, ticket) — the ticket runs only through
    executor.start(). argv carries no secret and no attack-specific flag beyond the interface."""
    prog = program()
    if prog is None:
        return False, "Responder is not installed (see the installer's source-tools note)", None
    if not _iface_ok(iface):
        return False, "interface %r is not a plain interface name" % (iface,), None
    t = str(segment).strip()
    if t.startswith("-"):
        return False, "segment %r looks like an option" % (segment,), None
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
            if "-" in s and "/" not in s:
                a, _, b = s.partition("-")
                addrs = [str(n) for n in ipaddress.summarize_address_range(
                    ipaddress.ip_address(a), ipaddress.ip_address(b))]
            elif "/" in s:
                addrs = [str(ipaddress.ip_network(s, strict=True))]
            else:
                addrs = [str(ipaddress.ip_address(s))]
        except (ValueError, TypeError):
            return False, ("refused: %r is not an IP address, network or range — name the segment "
                           "you are authorized to poison" % (segment,)), None
    argv = [prog, "-I", str(iface).strip()]
    return engagement.issue("responder:poison", addrs[0], argv=argv, kind="ip",
                            evidence_chain=evidence_chain, label="responder:poison",
                            also=tuple((a, "ip") for a in addrs[1:]))
