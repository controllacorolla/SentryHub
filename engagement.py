#!/usr/bin/env python3
"""engagement.py — engagement authorization gate for active assessment.

Active pen-test actions (RFID write/clone, Zigbee/Z-Wave enumeration & injection assessment, IQ
replay, network scans, anything that touches a target rather than just listening) are gated here,
the way TX is gated by txguard. An action is allowed only inside an AUTHORIZED ENGAGEMENT: a named
engagement with a written-authorization reference, an explicit TYPED target scope, the operator
from the operator profile, and an expiry.

Scope entries are typed, never globs (audit G4):
  ip      192.168.1.10 · 192.168.1.0/24 (strict, prefix >= /8) · 192.168.1.10-192.168.1.20
  host    nas.example.lan — resolved when the engagement opens; its addresses are pinned
  mac     AA:BB:CC:DD:EE:FF, or an OUI AA:BB:CC:* (the only wildcard accepted)
  can     can0:0x700-0x7FF (interface + arbitration-ID range) or can0:0x7DF
  zigbee  pan:0x1A2B@15 (PAN id @ channel)
  uid     uid:04A22B3C (an RFID/NFC card UID)
  device  usb:0483:5740 (USB VID:PID) · port:ttyS0 — a serial device, label-only
  label   BADGE-7 — an exact name, label-only
A target is checked by kind: IP targets (address, network, range or hostname — every resolved
address) must sit inside one ip/host entry; nothing matches by string prefix.

Where the command cannot be bound to the scope (USB-HID, flash, Flipper, Z-Wave, serial), the
authorization is reported as "label-only authorization" in the reason and the trail (audit G5).

One engagement at a time: start() while one is open is refused (audit G13); it expires after
ENGAGEMENT_HOURS_DEFAULT hours, enforced by the gate. issue() returns a single-use executor ticket
(audit G11) whose re-check is this gate. subscribe(fn) for change listeners (audit G12). A child
process bound to a hub session (gatestate) reads the hub's engagement and cannot open its own.

The evidence chain is CL3's; authorize_action() still hands its record to an evidence_chain when
one is passed, unchanged.
"""
import ipaddress
import math
import os
import re
import sys
import time

ENGAGEMENT_HOURS_DEFAULT = 8
ENGAGEMENT_HOURS_MAX = 24
MIN_PREFIX = {4: 8, 6: 32}          # a scope network wider than this is refused
MAX_RANGE = 1 << 24                 # an a-b range wider than a /8 is refused
BOUND_KINDS = ("ip", "host", "mac", "oui", "can", "zigbee", "uid")
LABEL_ONLY = "label-only"

_ENG = {"active": False, "name": None, "authorization": None, "scope": [], "entries": [],
        "operator": None, "started": None, "expires": None, "expiry_notified": False}
_ACTIONS = []                      # in-session audit trail (also mirrored to the evidence chain)
_LISTENERS = []

_MAC = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")
_OUI = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){2}[:-]\*$")
_CAN = re.compile(r"^((?:v|sl)?can\d{1,2}):(0x[0-9A-Fa-f]{1,8}|\d{1,10})(?:-(0x[0-9A-Fa-f]{1,8}|\d{1,10}))?$")
_PAN = re.compile(r"^(?:pan|zigbee):(0x[0-9A-Fa-f]{1,4}|\d{1,5})@(\d{2})$", re.I)
_UID = re.compile(r"^(?:[0-9A-Fa-f]{2}){4,10}$")
_USB = re.compile(r"^usb:([0-9a-fA-F]{4}):([0-9a-fA-F]{4})$")
_PORT = re.compile(r"^port:[A-Za-z0-9_.-]{1,40}$")
_HOST = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_GLOB = set("*?[]{}!")


def _now():
    return time.time()


def _resolve(host):
    """Every address `host` resolves to (A and AAAA). Raises OSError when it does not resolve."""
    import socket
    infos = socket.getaddrinfo(host, None)
    return sorted({i[4][0] for i in infos})


def _profile_operator():
    """The operator identity from the saved operator profile (callsign, else name), or None."""
    try:
        import opprofile
        import suite
        return opprofile.operator_identity(opprofile.load(suite.settings)) or None
    except Exception:
        return None


# ------------------------------------------------------------------ typed scope
class Entry:
    __slots__ = ("kind", "text", "data")

    def __init__(self, kind, text, data):
        self.kind, self.text, self.data = kind, text, data

    def to_json(self):
        d = self.data
        if self.kind == "host":
            d = {"name": d["name"], "addrs": [str(a) for a in d["addrs"]]}
        elif self.kind == "ip":
            d = {"lo": str(d["lo"]), "hi": str(d["hi"])}
        return {"kind": self.kind, "text": self.text, "data": d}

    @classmethod
    def from_json(cls, obj):
        k, d = obj["kind"], obj["data"]
        if k == "host":
            d = {"name": d["name"], "addrs": [ipaddress.ip_address(a) for a in d["addrs"]]}
        elif k == "ip":
            d = {"lo": ipaddress.ip_address(d["lo"]), "hi": ipaddress.ip_address(d["hi"])}
        elif k == "can":
            d = tuple(d)
        elif k == "zigbee":
            d = tuple(d)
        return cls(k, obj["text"], d)


def _int(s):
    return int(s, 16) if str(s).lower().startswith("0x") else int(s)


def _parse_ip_text(s, for_scope):
    """(lo, hi) addresses for an address, strict network or a-b range; None if s is not IP-shaped;
    raises ValueError when it is IP-shaped but malformed / too wide."""
    if "-" in s and "/" not in s:
        a, _, b = s.partition("-")
        try:
            lo, hi = ipaddress.ip_address(a), ipaddress.ip_address(b)
        except ValueError:
            if re.fullmatch(r"[0-9.\-]+|[0-9a-fA-F:\-]+", s):
                raise ValueError("%r is not a valid address range (use a.b.c.d-a.b.c.e)" % s)
            return None
        if lo.version != hi.version or int(lo) > int(hi):
            raise ValueError("%r is not a valid address range" % s)
        if for_scope and int(hi) - int(lo) + 1 > MAX_RANGE:
            raise ValueError("%r is wider than a /8" % s)
        return lo, hi
    if "/" in s:
        try:
            net = ipaddress.ip_network(s, strict=True)
        except ValueError:
            raise ValueError("%r is not a valid network (host bits set, or bad mask)" % s)
        if for_scope and net.prefixlen < MIN_PREFIX[net.version]:
            raise ValueError("%r is wider than /%d" % (s, MIN_PREFIX[net.version]))
        return net.network_address, net.broadcast_address
    try:
        a = ipaddress.ip_address(s)
        return a, a
    except ValueError:
        if re.fullmatch(r"[0-9.]+", s):
            raise ValueError("%r is not a valid IP address" % s)
        return None


def parse_entry(raw, resolver=None):
    """One typed scope entry. Raises ValueError with the reason when the entry is not accepted."""
    if not isinstance(raw, str):
        raise ValueError("scope entries must be text, got %r" % (raw,))
    s = raw.strip()
    if not s:
        raise ValueError("empty scope entry")
    if any(c.isspace() for c in s):
        raise ValueError("%r contains whitespace" % s)
    if _GLOB & set(s):
        if _OUI.match(s):
            oui = re.sub(r"[:-]", "", s[:-1]).upper()
            return Entry("oui", ":".join(oui[i:i + 2] for i in range(0, 6, 2)) + ":*", oui)
        raise ValueError("%r: wildcards / glob syntax are not scope (list targets explicitly; "
                         "only a MAC OUI 'AA:BB:CC:*' may end in *)" % s)
    low = s.lower()
    for pre in ("label:", "host:", "ip:", "mac:", "uid:"):
        if low.startswith(pre):
            body = s[len(pre):]
            kind = pre[:-1]
            if kind == "label":
                if not _LABEL.match(body):
                    raise ValueError("%r is not a valid label" % s)
                return Entry("label", body, body)
            if kind == "uid":
                u = body.replace(":", "").upper()
                if not _UID.match(u):
                    raise ValueError("%r is not a card UID (4-10 hex bytes)" % s)
                return Entry("uid", "uid:" + u, u)
            if kind == "mac" and not _MAC.match(body):
                raise ValueError("%r is not a MAC address" % s)
            if kind == "ip" and _parse_ip_text(body, True) is None:
                raise ValueError("%r is not an IP address / network / range" % s)
            if kind == "host" and not _HOST.match(body):
                raise ValueError("%r is not a hostname" % s)
            s, low = body, body.lower()
            break
    if _MAC.match(s):
        mac = re.sub(r"[:-]", "", s).upper()
        return Entry("mac", ":".join(mac[i:i + 2] for i in range(0, 12, 2)), mac)
    m = _CAN.match(s)
    if m:
        lo = _int(m.group(2))
        hi = _int(m.group(3)) if m.group(3) else lo
        if not (0 <= lo <= hi <= 0x1FFFFFFF):
            raise ValueError("%r: CAN ID range must be within 0..0x1FFFFFFF, low <= high" % s)
        return Entry("can", "%s:0x%X-0x%X" % (m.group(1), lo, hi), (m.group(1), lo, hi))
    m = _PAN.match(s)
    if m:
        pan, ch = _int(m.group(1)), int(m.group(2))
        if not (0 <= pan <= 0xFFFF) or not (11 <= ch <= 26):
            raise ValueError("%r: PAN 0..0xFFFF, channel 11..26" % s)
        return Entry("zigbee", "pan:0x%04X@%d" % (pan, ch), (pan, ch))
    m = _USB.match(s)
    if m:
        return Entry("device", "usb:%s:%s" % (m.group(1).lower(), m.group(2).lower()),
                     "usb:%s:%s" % (m.group(1).lower(), m.group(2).lower()))
    if _PORT.match(s):
        return Entry("device", s, s)
    rng = _parse_ip_text(s, True)
    if rng is not None:
        lo, hi = rng
        return Entry("ip", s, {"lo": lo, "hi": hi})
    if _HOST.match(s) and re.search(r"[A-Za-z]", s.rsplit(".", 1)[-1]):
        try:
            addrs = [ipaddress.ip_address(a) for a in (resolver or _resolve)(s)]
        except (OSError, ValueError) as e:
            raise ValueError("%r does not resolve (%s) — list its address instead" % (s, e))
        if not addrs:
            raise ValueError("%r does not resolve" % s)
        return Entry("host", low, {"name": low, "addrs": addrs})
    if _LABEL.match(s):
        return Entry("label", s, s)
    raise ValueError("%r is not a recognised scope entry (ip / host / mac / can / pan / uid / "
                     "usb / label)" % s)


def parse_scope(scope, resolver=None):
    """(ok, reason, entries). scope must be a list/tuple of entries — a string is refused, never
    split into characters."""
    if isinstance(scope, (str, bytes)) or not isinstance(scope, (list, tuple)):
        return False, "scope must be a list of typed entries, not %s" % type(scope).__name__, []
    if not scope:
        return False, "engagement needs an explicit target scope (no open-ended testing)", []
    entries, errs = [], []
    for raw in scope:
        try:
            entries.append(parse_entry(raw, resolver))
        except ValueError as e:
            errs.append(str(e))
    if errs:
        return False, "scope refused: " + "; ".join(errs), []
    return True, "", entries


# ------------------------------------------------------------------ target checks
def _ip_targets(target):
    """List of (lo, hi) intervals the target covers, or None if it is not an IP target. Hostnames
    are resolved and every address is returned. Raises ValueError for malformed IP-ish input."""
    t = str(target).strip()
    if not t or _GLOB & set(t) or any(c.isspace() for c in t):
        raise ValueError("malformed target %r" % (target,))
    if t.lower().startswith("ip:"):
        t = t[3:]
    rng = _parse_ip_text(t, False)
    if rng is not None:
        return [rng]
    if t.lower().startswith("host:"):
        t = t[5:]
    if _HOST.match(t):
        try:
            addrs = [ipaddress.ip_address(a) for a in _resolve(t)]
        except (OSError, ValueError) as e:
            raise ValueError("%r does not resolve (%s)" % (t, e))
        if not addrs:
            raise ValueError("%r does not resolve" % t)
        return [(a, a) for a in addrs]
    return None


def _ip_ok(intervals, entries):
    for lo, hi in intervals:
        hit = False
        for e in entries:
            if e.kind == "ip":
                elo, ehi = e.data["lo"], e.data["hi"]
                if elo.version == lo.version and int(elo) <= int(lo) and int(hi) <= int(ehi):
                    hit = True
            elif e.kind == "host" and lo == hi:
                if any(a == lo for a in e.data["addrs"]):
                    hit = True
            if hit:
                break
        if not hit:
            return False
    return True


def _norm_mac(t):
    s = re.sub(r"[:-]", "", str(t).strip()).upper()
    return s if re.fullmatch(r"[0-9A-F]{12}", s) else None


def _infer_kind(target):
    if isinstance(target, tuple):
        return None
    t = str(target).strip()
    if _MAC.match(t):
        return "mac"
    low = t.lower()
    if low.startswith("uid:"):
        return "uid"
    if low.startswith(("usb:", "port:")):
        return "device"
    if _CAN.match(t):
        return "can"
    if _PAN.match(t):
        return "zigbee"
    if low.startswith(("ip:", "host:")) or re.fullmatch(r"[0-9a-fA-F.:/\-]+", t) or \
            ("." in t and not _LABEL.match(t)):
        return "ip"
    return "label"


def _match(target, kind, entries):
    """(ok, binding, detail) — is target inside the typed scope for this kind?"""
    kind = kind or _infer_kind(target)
    if kind is None:
        return False, None, "cannot tell what kind of target %r is" % (target,)
    if kind == "ip":
        try:
            iv = _ip_targets(target)
        except ValueError as e:
            return False, "scoped", str(e)
        if iv is None:
            return False, "scoped", "%r is not an IP address, network, range or hostname" % (target,)
        return _ip_ok(iv, entries), "scoped", ""
    if kind == "mac":
        m = _norm_mac(target)
        if m is None:
            return False, "scoped", "%r is not a MAC address" % (target,)
        ok = any((e.kind == "mac" and e.data == m) or (e.kind == "oui" and m.startswith(e.data))
                 for e in entries)
        return ok, "scoped", ""
    if kind == "can":
        if isinstance(target, tuple):
            iface, cid = target
        else:
            mm = _CAN.match(str(target))
            if not mm or mm.group(3):
                return False, "scoped", "CAN target must be iface:id"
            iface, cid = mm.group(1), _int(mm.group(2))
        ok = any(e.kind == "can" and e.data[0] == iface and e.data[1] <= int(cid) <= e.data[2]
                 for e in entries)
        return ok, "scoped", ""
    if kind == "zigbee":
        pan, ch = target if isinstance(target, tuple) else (None, None)
        ok = any(e.kind == "zigbee" and e.data[1] == ch and (pan is None or e.data[0] == pan)
                 for e in entries)
        return ok, "scoped", ""
    if kind == "uid":
        u = str(target).strip()
        u = (u[4:] if u.lower().startswith("uid:") else u).replace(":", "").replace(" ", "").upper()
        return any(e.kind == "uid" and e.data == u for e in entries), "scoped", ""
    if kind == "device":
        t = str(target).strip().lower()
        return any(e.kind == "device" and e.data.lower() == t for e in entries), LABEL_ONLY, ""
    t = str(target).strip()
    if t.lower().startswith("label:"):
        t = t[6:]
    return any(e.kind == "label" and e.data == t for e in entries), LABEL_ONLY, ""


# ------------------------------------------------------------------ state
def subscribe(fn):
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)


def unsubscribe(fn):
    try:
        _LISTENERS.remove(fn)
    except ValueError:
        pass


def _notify():
    for fn in list(_LISTENERS):
        try:
            fn()
        except Exception:
            pass


_SHARED_CACHE = {"key": None, "eng": None}


def _shared():
    try:
        import gatestate
    except ImportError:
        return None
    return gatestate.shared_state()


def _eng():
    """The effective engagement record: the hub's when bound to one, else this process's own."""
    sh = _shared()
    if sh is None:
        return _ENG
    e = sh.get("engagement")
    if sh.get("stale") or not e:
        return {"active": False, "name": None, "authorization": None, "scope": [], "entries": [],
                "operator": None, "started": None, "expires": None, "stale": sh.get("stale")}
    key = (sh.get("pid"), sh.get("t"))
    if _SHARED_CACHE["key"] != key:
        try:
            entries = [Entry.from_json(x) for x in e.get("entries", [])]
            rec = {"active": True, "name": e.get("name"), "authorization": e.get("authorization"),
                   "scope": list(e.get("scope", [])), "entries": entries,
                   "operator": e.get("operator"), "started": float(e.get("started")),
                   "expires": float(e.get("expires"))}
        except Exception:
            rec = {"active": False, "name": None, "authorization": None, "scope": [],
                   "entries": [], "operator": None, "started": None, "expires": None}
        _SHARED_CACHE.update(key=key, eng=rec)
    return _SHARED_CACHE["eng"]


def export_state():
    """The local engagement for gatestate to publish (None when none is open)."""
    if not _ENG["active"]:
        return None
    return {"name": _ENG["name"], "authorization": _ENG["authorization"],
            "scope": list(_ENG["scope"]), "entries": [e.to_json() for e in _ENG["entries"]],
            "operator": _ENG["operator"], "started": _ENG["started"], "expires": _ENG["expires"]}


def _expired(e):
    return bool(e["active"]) and (e["expires"] is None or _now() >= e["expires"])


def start(name, authorization, scope, operator=None, hours=ENGAGEMENT_HOURS_DEFAULT,
          resolver=None):
    """Open an engagement. Requires a name, a non-empty authorization reference (ticket/ROE/owner
    consent), a typed target scope, the operator from the operator profile, and an expiry
    (hours, 0 < hours <= ENGAGEMENT_HOURS_MAX). Refused while another is open. Returns (ok, reason)."""
    if _shared() is not None:
        return False, "this process is bound to the hub session — open the engagement in the hub"
    if _ENG["active"]:
        return False, ("engagement '%s' is already open — END it first (a second start never "
                       "replaces it)" % _ENG["name"])
    if not name or not isinstance(name, str) or not name.strip():
        return False, "engagement needs a name"
    if not authorization or not str(authorization).strip():
        return False, "engagement needs an authorization reference (scope/ROE/owner consent)"
    prof = _profile_operator()
    if not prof:
        return False, ("no operator profile — set your callsign or name in the operator profile "
                       "first (the operator is never free text)")
    if operator is not None and str(operator).strip().upper() != str(prof).strip().upper():
        return False, "operator %r does not match the operator profile (%s)" % (operator, prof)
    h = hours
    if isinstance(h, bool) or not isinstance(h, (int, float)) or not math.isfinite(h) or \
            not (0 < h <= ENGAGEMENT_HOURS_MAX):
        return False, "engagement length must be 0-%d hours" % ENGAGEMENT_HOURS_MAX
    ok, why, entries = parse_scope(scope, resolver)
    if not ok:
        return False, why
    t = _now()
    _ENG.update(active=True, name=name.strip(), authorization=str(authorization).strip(),
                scope=[e.text for e in entries], entries=entries, operator=str(prof).strip(),
                started=t, expires=t + float(h) * 3600.0, expiry_notified=False)
    _ACTIONS.clear()
    _notify()
    return True, "engagement '%s' active (%d targets in scope, expires in %g h)" % (
        name, len(entries), h)


def end():
    if _shared() is not None:
        return None
    was = _ENG["name"]
    changed = _ENG["active"]
    _ENG.update(active=False, name=None, authorization=None, scope=[], entries=[], operator=None,
                started=None, expires=None, expiry_notified=False)
    if changed:
        _notify()
    return was


def is_active():
    """An engagement is open AND not expired."""
    e = _eng()
    if not e["active"]:
        return False
    if _expired(e):
        if e is _ENG and not _ENG["expiry_notified"]:
            _ENG["expiry_notified"] = True
            _notify()
        return False
    return True


def expired():
    e = _eng()
    return _expired(e)


def info():
    e = _eng()
    return {"active": is_active(), "open": bool(e["active"]), "expired": _expired(e),
            "name": e["name"], "authorization": e["authorization"], "scope": list(e["scope"]),
            "operator": e["operator"], "started": e["started"], "expires": e["expires"],
            "stale": bool(e.get("stale"))}


def require_active():
    """(ok, reason) — is an unexpired engagement open? For tools that validate their own inputs
    after this but must report the missing engagement first."""
    ok, why, _b = check("-", "-", kind="label")
    if not ok and ("no active engagement" in why or "expired" in why or "stale" in why):
        return False, why
    return True, ""


def in_scope(target, kind=None):
    """Is target within the engagement scope (typed match, see module doc)?"""
    e = _eng()
    return _match(target, kind, e["entries"])[0]


def check(action, target, kind=None):
    """(ok, reason, binding) without recording anything — the gate itself, also the executor's
    re-check for tickets this gate issued."""
    e = _eng()
    if not e["active"]:
        if e.get("stale"):
            return False, "hub session state is missing or stale — refusing (fail closed)", None
        return False, "no active engagement — open an authorized engagement first", None
    if _expired(e):
        return False, "engagement '%s' has expired — END it and open a new one" % e["name"], None
    ok, binding, detail = _match(target, kind, e["entries"])
    if not ok:
        return False, ("%r is not in the engagement scope — refusing (out of authorization)%s"
                       % (target, (": " + detail) if detail else "")), binding
    note = " — label-only authorization (the command is not bound to the scope)" \
        if binding == LABEL_ONLY else ""
    return True, "authorized: %s on %s (engagement '%s')%s" % (action, target, e["name"], note), \
        binding


def authorize_action(action, target, evidence_chain=None, kind=None):
    """Gate one active action against `target`. Returns (ok, reason). On success, records the action
    to the in-session trail and, if given, to the evidence chain."""
    ok, why, binding = check(action, target, kind)
    if not ok:
        return False, why
    e = _eng()
    rec = {"t": _now(), "action": action, "target": str(target), "engagement": e["name"],
           "operator": e["operator"], "binding": binding}
    _ACTIONS.append(rec)
    if evidence_chain is not None:
        try:
            evidence_chain.add("%s:%s" % (action, target),
                               data=("%s|%s|%s" % (action, target, e["authorization"])).encode(),
                               meta=rec)
        except Exception:
            pass
    return True, why


def issue(action, target, argv=None, payload=None, kind=None, evidence_chain=None, label=None,
          files=None, meta=None):
    """authorize_action() and, on success, a single-use executor ticket for exactly this argv (or
    device payload), re-checked against this gate at spawn. Returns (ok, reason, ticket)."""
    ok, why = authorize_action(action, target, evidence_chain, kind)
    if not ok:
        return False, why, None
    import executor
    binding = _ACTIONS[-1]["binding"] if _ACTIONS else None

    def recheck():
        r = check(action, target, kind)
        return r[0], r[1]
    t = executor.issue(argv=argv, payload=payload, recheck=recheck, label=label or action,
                       binding=binding, reason=why, files=files, meta=meta)
    return True, why, t


def actions():
    return list(_ACTIONS)


def reset():
    """Drop any engagement + trail (startup and tests)."""
    if _shared() is None:
        end()
    _ACTIONS.clear()
    _SHARED_CACHE.update(key=None, eng=None)


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Engagement")
    S.settings("engagement", {})
    root, F = S.make_root("Engagement", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Engagement", "Scoped authorization for active assessment")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Open a scoped, authorized engagement before any active test. Every action is "
                  "checked against the typed target scope and logged. Passive monitoring does not "
                  "need this. (Opening an engagement from the Tk suite is not available: use the "
                  "PALISADE Qt shell's ENGAGEMENT panel.)").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
