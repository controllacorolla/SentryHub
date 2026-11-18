#!/usr/bin/env python3
"""webtriage.py — fast web / TLS triage (authorized engagements only).

Quick first-look at a web service you are authorized to test: what it is (whatweb), its TLS posture
(testssl), and known-vulnerability templates (nuclei). Each reaches the target, so each is gated on
an open engagement with the target host/IP in scope and logged — the same gate as nmap
(engagement.issue). Pure command-building + gating is unit-testable.

The operator supplies a host / IP (checked against the scope) and, optionally, a scheme and port;
the URL is formed from the PINNED address, so no second, unchecked DNS lookup is handed to the tool
(DNS rebinding). nuclei is run with its update check disabled (-duc) so it never phones home mid-run.
"""
import shutil

import engagement

ALLOWED_PROGRAMS = frozenset(("testssl.sh", "testssl", "whatweb", "nuclei"))

_SCHEMES = ("https", "http")


def _testssl_name():
    return "testssl.sh" if shutil.which("testssl.sh") or not shutil.which("testssl") else "testssl"


def _url(addr, scheme, port):
    default = {"http": 80, "https": 443}.get(scheme)
    hostport = addr if port in (None, "", default) else "%s:%s" % (addr, port)
    return "%s://%s" % (scheme, hostport)


def _build(action, addr, scheme, port):
    if action == "testssl":
        host = addr if port in (None, "") else "%s:%s" % (addr, port)
        return [_testssl_name(), "--quiet", "--color", "0", host]
    if action == "whatweb":
        return ["whatweb", "--no-errors", "--color", "never", _url(addr, scheme, port)]
    if action == "nuclei":
        return ["nuclei", "-duc", "-silent", "-u", _url(addr, scheme, port)]
    return None


def prepare(action, target, scheme="https", port=None, evidence_chain=None):
    """Gate + build one web/TLS triage action against `target` (a host or IP). Returns
    (ok, reason, ticket) — the ticket runs only through executor.start()."""
    if action not in ("testssl", "whatweb", "nuclei"):
        return False, "unknown action %r" % (action,), None
    if scheme not in _SCHEMES:
        return False, "scheme must be http or https", None
    if port not in (None, ""):
        try:
            p = int(port)
            if not 1 <= p <= 65535:
                raise ValueError
            port = p
        except (TypeError, ValueError):
            return False, "port must be 1-65535", None
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
    argv = _build(action, addrs[0], scheme, port)
    label = "web:" + action + ((":" + t) if pinned else "")
    return engagement.issue("web:" + action, addrs[0], argv=argv, kind="ip",
                            evidence_chain=evidence_chain, label=label,
                            also=tuple((a, "ip") for a in addrs[1:]))
