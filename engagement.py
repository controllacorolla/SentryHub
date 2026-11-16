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
        "operator": None, "started": None, "expires": None, "expiry_notified": False,
        "chain": None}
_CHAIN = {"obj": None}             # the open engagement's evidence chain (chain.Chain), CL3
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


def pin_host(target):
    """CL2-fix N5: the addresses a HOSTNAME target resolves to right now (sorted strings), so a
    command can be given the checked addresses instead of the name (no second, unchecked lookup by
    the tool — DNS rebinding). None when target is not a hostname (an address / network / range
    is already literal). Raises ValueError when the name does not resolve."""
    t = str(target).strip()
    if t.lower().startswith("host:"):
        t = t[5:]
    if not t or _GLOB & set(t) or any(c.isspace() for c in t):
        return None
    try:
        if _parse_ip_text(t, False) is not None:
            return None
    except ValueError:
        return None
    if not _HOST.match(t):
        return None
    try:
        addrs = sorted({str(ipaddress.ip_address(a)) for a in _resolve(t)})
    except (OSError, ValueError) as e:
        raise ValueError("%r does not resolve (%s)" % (t, e))
    if not addrs:
        raise ValueError("%r does not resolve" % t)
    return addrs


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
                   "expires": float(e.get("expires")), "chain": e.get("chain")}
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
            "operator": _ENG["operator"], "started": _ENG["started"], "expires": _ENG["expires"],
            "chain": _ENG.get("chain")}


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
    # CL3 (G6/G7): the durable evidence chain is opened FIRST; no chain, no engagement.
    import chain as _chain
    try:
        ch = _chain.Chain.create(name=name.strip())
        ch.record("engagement.open", name=name.strip(), authorization=str(authorization).strip(),
                  scope=[e.text for e in entries], operator=str(prof).strip(), started=t,
                  expires=t + float(h) * 3600.0, hours=float(h))
    except Exception as e:                     # RA-CL3 N7: never raise out of start()
        return False, "cannot open the evidence chain (%s) — refusing to start (fail closed)" % e
    _ENG.update(active=True, name=name.strip(), authorization=str(authorization).strip(),
                scope=[e.text for e in entries], entries=entries, operator=str(prof).strip(),
                started=t, expires=t + float(h) * 3600.0, expiry_notified=False, chain=ch.id)
    _CHAIN["obj"] = ch
    _chain.set_open(ch)
    _ACTIONS.clear()
    _notify()
    return True, "engagement '%s' active (%d targets in scope, expires in %g h)" % (
        name, len(entries), h)


END_DRAIN_S = 2.0                   # how long END waits for bound children to record kill/exit


def _open_tickets(ch):
    """{ticket: info} for every ENGAGEMENT-issued ticket of `ch` (the ones END voids and kills; a
    txguard bench ticket is not ended by END and keeps its own outcome) without a final outcome
    yet, re-read from disk so a
    bound child's records are seen. info["spawned"]: it has a spawn record (a process exists);
    info["killed"]: a kill is recorded but its exit is not (yet). Outcome = exit (process), write
    (device), or refuse_ticket (void). None if the chain does not verify."""
    ok, _why = ch.verify()
    if not ok:
        return None
    out = {}
    for r in ch.records:
        tid, ev = r.get("ticket"), r.get("event")
        if not tid:
            continue
        if ev == "issue":
            if r.get("issuer") != "engagement":
                continue                # txguard / ungated tickets do not end with the engagement
            out.setdefault(tid, {"label": r.get("label", ""), "target": str(r.get("target", "")),
                                 "spawned": False, "killed": False})
        elif tid not in out:
            continue
        elif ev == "spawn":
            out[tid]["spawned"] = True
            out[tid]["pid"], out[tid]["pstart"] = r.get("pid"), r.get("pstart")
        elif ev == "kill":
            out[tid]["killed"] = True
        elif ev in ("exit", "write", "refuse_ticket", "unconfirmed"):
            out[tid]["done"] = True
    return {t: i for t, i in out.items() if not i.get("done")}


def _ticket_events(records, tid):
    return [r.get("event") for r in records if r.get("ticket") == tid]


def _identity(pid, pstart):
    """Is `pid` still the process logged at launch (gatestate.proc_start identity check — a
    recycled pid never matches; unknown is no)? One of:
      "match"    — alive, and its start time equals the one logged at spawn
      "zombie"   — it IS that process, but it has exited and only its reap is pending (N22/N25)
      "gone"     — no such process any more
      "mismatch" — another process holds the pid now, or identity cannot be proven
    RA-CL3d N23: never the hub itself, its parent, or the leader of the hub's own process group,
    whatever a (keyed, forged) record says."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1 or not pstart:
        return "mismatch"
    if pid in (os.getpid(), os.getppid(), os.getpgrp()):
        return "mismatch"
    import gatestate
    start = gatestate.proc_start(pid)
    if start is None:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return "gone"
        except OSError:
            pass
        return "mismatch"
    if start != pstart:
        return "mismatch"
    z = gatestate.is_zombie(pid)
    if z:
        return "zombie"
    if z is None:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return "gone"                   # exited and reaped between the two reads
        except OSError:
            pass
    return "match"


def _same_process(pid, pstart):
    """True only if `pid` is alive AND is the process logged at launch (see _identity)."""
    return _identity(pid, pstart) == "match"


def _orphan_group(pid):
    """The process group END may signal for this orphan: its own group when it leads one (gated
    processes are spawned with start_new_session), never the hub's own group. None -> pid only."""
    try:
        pg = os.getpgid(pid)
    except OSError:
        return None
    return pg if pg == pid and pg != os.getpgrp() else None


def _orphan_gone(pid, pstart, pg):
    """Verified gone (RA-CL3d N20): the launched process is no longer running AND, when it led its
    own group, no live process is left in that group (a pgid with live members cannot be reused as
    a new pid, so the probe is safe)."""
    if _identity(pid, pstart) == "match":
        return False
    if pg is None:
        return True
    import gatestate
    return not gatestate.group_alive(pg)


def _kill_orphans(orphans, grace=1.0, kill_wait=1.0):
    """END's kill of every matching orphan AT ONCE (RA-CL3d N24): SIGTERM each one's group, wait
    once for all of them, SIGKILL whatever is left (the leader while it still proves to be the
    launched process, or the group when the leader exited but a member did not — N20), wait once.
    `orphans` = {key: (pid, pstart)}. Returns {key: (verified_gone, why)}; why is "" when gone,
    "leader" when the launched process is still alive, "group" when it exited but a process in its
    group survived. A signal is only ever sent while the pid still proves to be the launched
    process, or to a group that still has live members."""
    import signal
    import gatestate
    state = {}
    for key, (pid, pstart) in orphans.items():
        if _identity(pid, pstart) != "match":
            state[key] = [pid, pstart, None, False]          # nothing to signal: gone already
            continue
        pg = _orphan_group(pid)
        try:
            if pg is not None:
                os.killpg(pg, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            pass
        state[key] = [pid, pstart, pg, True]

    def wait(t):
        end_t = time.monotonic() + t
        while time.monotonic() < end_t:
            if all(_orphan_gone(pid, ps, pg) for pid, ps, pg, sig in state.values() if sig):
                return
            time.sleep(0.05)

    if any(v[3] for v in state.values()):
        wait(grace)
        killed = False
        for key, (pid, pstart, pg, sig) in state.items():
            if not sig or _orphan_gone(pid, pstart, pg):
                continue
            try:
                if _identity(pid, pstart) == "match":
                    if pg is not None:
                        os.killpg(pg, signal.SIGKILL)
                    else:
                        os.kill(pid, signal.SIGKILL)
                    killed = True
                elif pg is not None and gatestate.group_alive(pg):
                    os.killpg(pg, signal.SIGKILL)          # leader gone, a member is not (N20)
                    killed = True
            except OSError:
                pass
        if killed:
            wait(kill_wait)
    out = {}
    for key, (pid, pstart, pg, sig) in state.items():
        if _identity(pid, pstart) == "match":
            out[key] = (False, "leader")
        elif pg is not None and gatestate.group_alive(pg, grace_s=0.2):
            out[key] = (False, "group")
        else:
            out[key] = (True, "")
    return out


def _kill_orphan(pid, pstart, grace=1.0):
    """One orphan (kept for callers of the old API). True when verified gone."""
    return _kill_orphans({0: (pid, pstart)}, grace=grace)[0][0]


_UNSEEN_REASON = {
    "mismatch": ("engagement ended — exit not confirmed; pid %s does not match the process logged "
                 "at launch, END sent no signal"),
    "zombie": ("engagement ended — pid %s is the process logged at launch but it had already "
               "exited (zombie, not yet reaped by its parent); exit code not observed, END sent "
               "no signal"),
    "gone": ("engagement ended — pid %s is no longer running and its exit was never reported; "
             "END sent no signal"),
}
_ORPHAN_FAIL = {
    "error": "orphan at END: the kill could not be completed (error) — state not confirmed",
    "leader": "orphan at END: signalled, still alive",
    "group": ("orphan at END: the launched process exited, but a process in its group survived "
              "SIGKILL"),
}


def _settle_tickets(ch):
    """RA-CL3b B3 / RA-CL3c N16 N17 N18: before engagement.close, every ticket of this engagement
    has an outcome in THIS chain, so no row stays RUNNING / ISSUED after END — and END never
    writes an outcome it has not observed.

    The engagement has just been marked expired and published (the caller's _notify): this
    process's executor has already killed its own processes (kill + exit recorded), and every bound
    child's executor sees the expired engagement on its next sweep, kills its process and records
    kill + exit — in this chain, because a ticket is bound to the chain it was issued under. Wait up
    to END_DRAIN_S for every spawned ticket's exit. Then, for any ticket still open, each record is
    appended under the chain's EXCLUSIVE lock and only if, at that instant, it is still true (N17):
      spawned, no kill/exit  -> an orphan (its child died without reporting). Owner decision N16:
                                if its pid AND the start time logged at spawn still match, END
                                kills its process group and, once verified gone (leader AND every
                                group member — RA-CL3d N20), records `kill` "orphan at END". All
                                matching orphans are signalled together (N24). Otherwise (no match,
                                exited-unreaped, gone, or it survived) `unconfirmed` with the reason
                                that is true (N22) — never KILLED. A later exit from it overrides.
      no spawn/write/outcome -> `refuse_ticket`: END saw no use of the ticket; from now on its
                                re-check fails. If a use that had already passed its gate lands
                                after this (N18), its spawn/kill/exit follow and the row shows them."""
    deadline = time.monotonic() + END_DRAIN_S
    open_ = _open_tickets(ch)
    while open_ and any(i["spawned"] for i in open_.values()) and time.monotonic() < deadline:
        time.sleep(0.05)
        open_ = _open_tickets(ch)

    def unreported(t):
        return lambda recs: not ({"kill", "exit"} & set(_ticket_events(recs, t)))
    to_kill = {}
    for tid, i in (open_ or {}).items():
        common = dict(ticket=tid, label=i["label"], target=i["target"], by="end")
        try:
            if i["spawned"]:
                pid, pstart = i.get("pid"), i.get("pstart")
                fresh = _open_tickets(ch) or {}
                if tid not in fresh or fresh[tid].get("killed"):
                    continue                    # the process reported (or its child killed it)
                ident = _identity(pid, pstart)
                if ident == "match":
                    to_kill[tid] = (pid, pstart, common)
                else:
                    ch.record("unconfirmed", _only_if=unreported(tid),
                              reason=_UNSEEN_REASON[ident] % pid, pid=pid, **common)
            else:
                ch.record("refuse_ticket", _only_if=lambda recs, t=tid: not (
                    {"spawn", "write", "exit", "kill", "refuse_ticket"}
                    & set(_ticket_events(recs, t))),
                    reason="engagement ended — no use of this ticket recorded by then; it can no "
                           "longer pass its gate", **common)
        except Exception:
            pass                        # END is the kill path; never block it on a record
    if not to_kill:
        return
    try:
        res = _kill_orphans({t: (p, ps) for t, (p, ps, _c) in to_kill.items()})
    except Exception:
        res = {}                        # the kill itself failed: say so, never KILLED
    for tid, (pid, pstart, common) in to_kill.items():
        gone, why = res.get(tid, (False, "error"))
        try:
            if gone:
                ch.record("kill", _only_if=unreported(tid), reason="orphan at END",
                          pid=pid, pstart=pstart, verified_gone=True, **common)
            else:
                ch.record("unconfirmed", _only_if=unreported(tid), reason=_ORPHAN_FAIL[why],
                          pid=pid, **common)
        except Exception:
            pass


def end():
    if _shared() is not None:
        return None
    was = _ENG["name"]
    changed = _ENG["active"]
    ch = _active_chain() if changed else None
    if changed:
        # the executor kills registered processes on _notify() (here, and in every bound child via
        # the published state); their kill/exit records must land in THIS chain, so the engagement
        # stays routable (active, expired) until every ticket has an outcome (RA-CL3b B3)
        _ENG["expires"] = _now()
        _notify()
        if ch is not None:
            try:
                _settle_tickets(ch)
            except Exception:
                pass
    _ENG.update(active=False, name=None, authorization=None, scope=[], entries=[], operator=None,
                started=None, expires=None, expiry_notified=False, chain=None)
    if ch is not None:
        try:
            ch.record("engagement.close", name=was, actions=len(_ACTIONS))
        except Exception:
            pass                        # closing never blocks END (it is the kill path)
    _CHAIN["obj"] = None
    if changed:
        _notify()                       # listeners now see NONE
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


def authorize_action(action, target, evidence_chain=None, kind=None, binding=None):
    """Gate one active action against `target`. Returns (ok, reason). On success, records the action
    to the in-session trail and, if given, to the evidence chain. `binding` overrides the recorded
    binding when the caller knows the command is less bound than the target (e.g. "label-only"
    for written content the scope cannot bind — CL2-fix2 R5)."""
    ok, why, _seq = _authorize(action, target, kind, binding)
    return ok, why


def _authorize(action, target, kind=None, binding=None):
    """authorize_action() returning also the seq of its `authorize` record (RA-CL3 N15: the ticket
    issued from it carries that seq, so the trail folds the ticket into exactly this row)."""
    ok, why, chk_binding = check(action, target, kind)
    e = _eng()
    if not ok:
        _record_soft("refuse", action=action, target=str(target), reason=why,
                     engagement=e.get("name"))
        return False, why, None
    binding = binding or chk_binding
    rec = {"t": _now(), "action": action, "target": str(target), "engagement": e["name"],
           "operator": e["operator"], "binding": binding}
    # CL3 (G6): the record is written durably BEFORE the authorization exists. If it cannot be
    # written, there is no authorization. A legacy per-page EvidenceChain is no longer consulted.
    ch = _active_chain()
    if ch is None:
        return False, ("no evidence chain is open for this engagement — refusing (no durable "
                       "record, no authorization)"), None
    try:
        arec = ch.record("authorize", action=action, target=str(target), binding=binding,
                         engagement=e["name"], operator=e["operator"],
                         authorization=e["authorization"])
    except Exception as ex:
        return False, "evidence chain write failed (%s) — refusing (no durable record, no " \
                      "authorization)" % ex, None
    seq = arec.get("seq") if isinstance(arec, dict) else None
    rec["seq"] = seq
    _ACTIONS.append(rec)
    return True, why, seq


def current_chain_id():
    """The chain id of the engagement in force RIGHT NOW — this process's own engagement, or the
    hub's as published to a bound child — or None. Always re-derived; never a cached object, so an
    engagement rollover (END alpha, START bravo) can never route a record to alpha (RA-CL3 B2)."""
    e = _eng()
    if not isinstance(e, dict) or not e.get("active"):
        return None
    cid = e.get("chain")
    return cid if cid else None


def _active_chain():
    """The open engagement's chain, by its CURRENT id (RA-CL3 B1/B2), or None."""
    cid = current_chain_id()
    if not cid:
        return None
    import chain as _chain
    try:
        return _chain.for_id(cid)
    except Exception:            # RA-CL3b N12: any failure to open the chain fails closed
        return None


def _record_soft(event, **fields):
    """Record something that must never block (a refusal, a close). With no engagement the record
    goes to the session chain (RA-CL3 N9). Errors are dropped."""
    try:
        import chain as _chain
        _chain.record(event, **fields)
    except Exception:
        pass


def chain_states():
    """H9 view: rows with AUTHORIZED / ISSUED / RUNNING / EXECUTED / KILLED / REFUSED / FAILED."""
    ch = _active_chain()
    if ch is None:
        return []
    try:
        ch.verify()
    except Exception:
        return []
    return ch.states()


def chain_info():
    """(id, path, records, verified) for the open chain, or None."""
    ch = _active_chain()
    if ch is None:
        return None
    ok, why = ch.verify()
    return {"id": ch.id, "path": ch.path, "records": len(ch.records), "verified": ok, "why": why}


# CL2-fix2 R1: argv[0] basenames the engagement gate never runs, whatever a module declares —
# each can execute an arbitrary second program the allowlist would never see.
NEVER_PROGRAMS = frozenset((
    "sh", "bash", "zsh", "dash", "ash", "ksh", "csh", "tcsh", "fish", "busybox", "env", "sudo",
    "doas", "su", "pkexec", "runuser", "xargs", "nohup", "timeout", "stdbuf", "nice", "ionice",
    "setsid", "chrt", "taskset", "exec", "command", "perl", "ruby", "node", "nodejs", "php",
    "lua", "tclsh", "wish", "osascript", "awk", "gawk", "mawk", "find", "script", "watch",
))
_INTERP = re.compile(r"^(python|pypy|perl|ruby|node|php|lua)[0-9.]*$", re.I)


def program_allowed(argv, allowed, module="?"):
    """(ok, reason): may the engagement gate run argv? argv[0]'s basename must be in `allowed`
    (the calling module's ALLOWED_PROGRAMS) and must not be a shell / interpreter / wrapper."""
    toks = [str(a) for a in (argv or ())]
    if not toks or not toks[0].strip():
        return False, "refused: empty command"
    prog = toks[0]
    if os.sep in prog or "/" in prog or not prog or prog != prog.strip():
        # a bare name only: a path (or a renamed / symlinked binary) is never what a module declared
        return False, "refused: program %r is not a bare declared tool name" % (toks[0],)
    if prog.lower() in NEVER_PROGRAMS or _INTERP.match(prog):
        return False, ("refused: %s is a shell, interpreter or wrapper — the engagement gate runs "
                       "only a module's declared tools, never a program that runs another" % prog)
    if not isinstance(allowed, (frozenset, set, tuple, list)) or prog not in allowed:
        return False, ("refused: %s is not a program %s may run (ALLOWED_PROGRAMS) — the "
                       "engagement gate runs declared tools only" % (prog, module))
    return True, ""


def issue(action, target, argv=None, payload=None, kind=None, evidence_chain=None, label=None,
          files=None, meta=None, also=(), binding=None):
    """authorize_action() and, on success, a single-use executor ticket for exactly this argv (or
    device payload), re-checked against this gate at spawn. Returns (ok, reason, ticket).

    `also` lists further (target, kind) pairs that must ALSO be in scope, at issue and on every
    re-check (e.g. the identity a Proxmark emulates — CL2-fix N4, or the pinned addresses of a
    hostname — N5).

    Before anything is recorded (CL2-fix, owner decisions 1 and 2): a command that keys an SDR
    transmitter is refused outright — only txguard may authorize those — and a command that
    radiates (rfemit) is refused while the env hard lock or the TX kill switch silences RF.

    CL2-fix2 R1 (owner decision): a process ticket is minted only for a program the CALLING module
    declares in its ALLOWED_PROGRAMS (basename of argv[0]), and never for a shell, interpreter or
    wrapper — an allowlist, so quoting / globbing / renamed binaries / unknown transmitters cannot
    reach the executor through this gate. rfemit stays as defence in depth (checked first, so a
    named transmitter gets the clearer txguard reason)."""
    import rfemit
    emitter = rfemit.classify(argv=argv, payload=payload, meta=meta)
    if emitter == rfemit.SDR_TX:
        return False, ("refused: %s keys an SDR transmitter — only the TX gate (txguard: band "
                       "plan, protected ranges, power cap) may authorize it, never an engagement"
                       % (str((argv or ["?"])[0]),)), None
    if argv is not None:
        caller = sys._getframe(1).f_globals
        ok_prog, why_prog = program_allowed(argv, caller.get("ALLOWED_PROGRAMS"),
                                            caller.get("__name__", "?"))
        if not ok_prog:
            return False, why_prog, None
    pre_ok, pre_why, _b = check(action, target, kind)        # scope first: the clearer reason
    if not pre_ok:
        return False, pre_why, None
    if emitter is not None:
        import txguard
        rf_ok, rf_why = txguard.emit_allowed()
        if not rf_ok:
            return False, rf_why, None
    extra = [(t, k) for t, k in (also or ())]
    for xt, xk in extra:
        xok, xwhy, _b = check(action, xt, xk)
        if not xok:
            return False, xwhy, None
    ok, why, auth_seq = _authorize(action, target, kind, binding=binding)
    if not ok:
        return False, why, None
    import executor
    binding = _ACTIONS[-1]["binding"] if _ACTIONS else None

    issued_under = current_chain_id()

    def recheck():
        # RA-CL3b B3: the ticket belongs to the engagement it was issued under. After END + START
        # (even within the ticket TTL, even if the new scope covers the target) it is void, and a
        # process it started is killed — its evidence lives in the old engagement's chain.
        if current_chain_id() != issued_under:
            return False, ("engagement changed since this ticket was issued — authorize again "
                           "under the current engagement")
        r = check(action, target, kind)
        if not r[0]:
            return r[0], r[1]
        for xt, xk in extra:
            x = check(action, xt, xk)
            if not x[0]:
                return x[0], x[1]
        return r[0], r[1]
    m = dict(meta or {})
    m.setdefault("target", str(target))
    m["auth_seq"] = auth_seq
    try:
        t = executor.issue(argv=argv, payload=payload, recheck=recheck, label=label or action,
                           binding=binding, reason=why, files=files, meta=m)
    except executor.TicketRefused as e:
        return False, "refused: %s" % e, None
    return True, why, t


def actions():
    return list(_ACTIONS)


def reset():
    """Drop any engagement + trail (startup and tests)."""
    if _shared() is None:
        end()
    _ACTIONS.clear()
    _CHAIN["obj"] = None
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
