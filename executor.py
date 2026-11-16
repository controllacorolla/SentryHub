#!/usr/bin/env python3
"""executor.py — the ONE place a gated action is carried out (audit G11).

A gate (txguard.issue_ticket, engagement-gated prepare() functions, flipper.prepare_command) does
not hand out a command string that is valid forever. It hands out a Ticket: single-use, expiring,
and bound to a hash of the exact argv (or the exact bytes for a device write). This module is the
only consumer of tickets, and the only gated-path code that spawns a process or writes to a
serial / HID device:

  * run() / start()  — redeem the ticket (exists, issued here, unused, unexpired, argv hash equal),
                       RE-RUN THE GATE at spawn, spawn in its own process group, register it,
                       stream its output, and return / record the real exit code.
  * write()          — the same redemption for a device write (serial line, HID report); every
                       line written is logged (audit G2).
  * kill_all()       — END engagement, disarm, PANIC: every registered process group is killed.

While a process runs, its ticket's gate is re-checked whenever txguard or engagement change and on
a short timer (expiry, a hub's shared state in another process): the moment the gate stops
passing, the process group is killed.

Evidence is CL3's job: record(event, ...) below is the single hook this module calls on issue,
spawn, write, kill and exit; every record after `issue` goes to the chain the ticket was issued
under (RA-CL3b B3/N14).
"""
import hashlib
import json
import os
import signal
import subprocess
import threading
import time
import uuid

TICKET_TTL_S = 120.0              # a ticket must be used within two minutes of the gate passing
MONITOR_INTERVAL_S = 0.25
SERIAL_LOG = os.path.join(os.path.expanduser("~"), ".local", "share", "uconsole-suite",
                          "serial_tx.jsonl")


def record(event, chain_id=None, **fields):
    """The single evidence hook (CL3): issue / spawn / write / exit (with the real exit code) /
    kill go to an evidence chain. Returns the id of the chain written to (None if dropped).

    RA-CL3b B3/N14: a ticket is BOUND to the chain it was issued under. `issue` goes to the chain
    in force now (the open engagement's, else this process's session chain) and the ticket's entry
    keeps that chain's id; every later record for the ticket (refuse_ticket, spawn, write, kill,
    exit) passes `chain_id` and goes to THAT chain by id, never to whatever engagement is in force
    at record time. So a bound child killed after the hub ENDs still records its kill + exit in the
    engagement chain (not a fresh session chain), and a bench ticket from before START never writes
    its exit into the new engagement's chain.

    A failure to record an ISSUE refuses the ticket (fail closed: no durable record, no
    capability); the other records are best-effort because by then the process exists and must
    still be tracked and killable. A bound chain that cannot be opened is never swapped for another
    chain (that would misfile the record)."""
    import chain
    try:
        ch = chain.for_id(chain_id) if chain_id else chain.current()
        ch.record(event, **fields)
        return ch.id
    except Exception as e:
        if event == "issue":
            raise TicketRefused("evidence chain write failed (%s) — no ticket" % e)
        return None


def _mono():
    return time.monotonic()


class TicketRefused(Exception):
    """The executor refused a ticket (unknown, forged, reused, expired, altered, or the gate no
    longer passes). Nothing was spawned or written."""


class Ticket:
    """An opaque, immutable capability. Holders can read what it authorizes (argv / payload / files,
    the gate's reason and whether the authorization is scope-bound or label-only) but cannot alter
    it: the executor keeps its own digest and compares on redemption."""
    __slots__ = ("_id", "_kind", "_argv", "_payload", "_files", "_label", "_binding", "_reason",
                 "_meta", "_sealed")

    def __init__(self, kind, argv, payload, files, label, binding, reason, meta):
        object.__setattr__(self, "_id", uuid.uuid4().hex)
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_argv", tuple(str(a) for a in argv) if argv is not None else None)
        object.__setattr__(self, "_payload", bytes(payload) if payload is not None else None)
        object.__setattr__(self, "_files", dict(files or {}))
        object.__setattr__(self, "_label", label)
        object.__setattr__(self, "_binding", binding)
        object.__setattr__(self, "_reason", reason)
        object.__setattr__(self, "_meta", dict(meta or {}))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        raise AttributeError("tickets are immutable")

    def __delattr__(self, name):
        raise AttributeError("tickets are immutable")

    id = property(lambda self: getattr(self, "_id", None))
    kind = property(lambda self: getattr(self, "_kind", None))
    argv = property(lambda self: getattr(self, "_argv", None))
    payload = property(lambda self: getattr(self, "_payload", None))
    files = property(lambda self: dict(getattr(self, "_files", {}) or {}))
    label = property(lambda self: getattr(self, "_label", None))
    binding = property(lambda self: getattr(self, "_binding", None))
    reason = property(lambda self: getattr(self, "_reason", None))
    meta = property(lambda self: dict(getattr(self, "_meta", {}) or {}))

    def display(self):
        """The command as text, for a UI to show (never to run)."""
        if self.argv is not None:
            return " ".join(self.argv)
        return (self.payload or b"").decode("utf-8", "replace").rstrip("\r\n")

    def __repr__(self):
        return "<Ticket %s %s %s>" % (self.kind, self.label, (self.id or "")[:8])


_LOCK = threading.RLock()
_ISSUED = {}          # id -> entry dict (the executor's own copy of what the ticket authorizes)
_RUNNING = []         # Handle objects whose process may still be alive
_MON = {"thread": None, "subscribed": False}


def _digest(kind, argv, payload, files):
    h = hashlib.sha256()
    h.update(json.dumps({"kind": kind, "argv": list(argv) if argv is not None else None,
                         "payload": payload.hex() if payload is not None else None,
                         "files": sorted((files or {}).items())}, sort_keys=True).encode())
    return h.hexdigest()


# The only modules allowed to mint tickets: the two gates, and the serial-line classifier (which
# issues ungated tickets only for allowlisted Flipper reads / the synthetic demo device and sends
# everything else through engagement.issue). Checked on every issue() and statically in
# tests/test_cl2_gates.py. Not a security boundary against hostile in-process code — a guard
# against a well-meaning caller minting its own "authorization".
ISSUERS = ("txguard", "engagement", "flipper")
# Owner decision 1 (CL2-fix N1): only these issuers may mint a ticket for an SDR transmitter
# (rfemit.SDR_TX). The engagement gate knows scope, not band plans or power caps.
TX_ISSUERS = ("txguard",)


def _with_rf_gate(recheck):
    """Compose the RF-silence gate (env hard lock + TX kill switch, owner decision 2) in front of
    a ticket's own re-check. Runs at issue, at spawn and on every sweep: disarm kills the process."""
    def rf_recheck():
        import txguard
        ok, why = txguard.emit_allowed()
        if not ok:
            return False, why
        return recheck()
    return rf_recheck


def issue(argv=None, recheck=None, label="", binding="scoped", reason="", files=None,
          payload=None, meta=None, ttl=None):
    """Called ONLY by a gate that has just passed. recheck() -> (ok, reason) re-runs that gate."""
    import sys
    caller = sys._getframe(1).f_globals.get("__name__", "")
    if caller not in ISSUERS:
        raise TicketRefused("only a gate (%s) may issue tickets, not %r" % (", ".join(ISSUERS),
                                                                             caller))
    if recheck is None or not callable(recheck):
        raise ValueError("a ticket needs the gate's recheck()")
    if (argv is None) == (payload is None):
        raise ValueError("a ticket authorizes exactly one argv or one payload")
    kind = "proc" if argv is not None else "write"
    # CL2-fix N1/N2: what the command radiates decides which gates must keep passing.
    import rfemit
    emitter = rfemit.classify(argv=argv, payload=payload, meta=meta)
    if emitter == rfemit.SDR_TX and caller not in TX_ISSUERS:
        raise TicketRefused("an SDR transmitter (%s) can only be authorized by txguard (band, "
                            "power and protected-range checks), not by %r"
                            % (" ".join(str(a) for a in argv)[:80], caller))
    if emitter is not None:
        recheck = _with_rf_gate(recheck)
        ok, why = recheck()
        if not ok:
            raise TicketRefused(why)
    t = Ticket(kind, argv, payload, files, label, binding, reason, meta)
    # CL3 (G6): the durable record comes BEFORE the capability exists; a failed record raises
    # TicketRefused and nothing is minted.
    # RA-CL3b B3/N14: the ticket is bound to the chain this record went to (see record()).
    cid = record("issue", ticket=t.id, label=label, binding=binding, reason=reason,
                 argv=list(t.argv) if t.argv else None, issuer=caller, emitter=emitter,
                 target=str((meta or {}).get("target", "")))
    with _LOCK:
        _ISSUED[t.id] = {"ticket": t, "digest": _digest(kind, t.argv, t.payload, t.files),
                         "expires": _mono() + float(TICKET_TTL_S if ttl is None else ttl),
                         "recheck": recheck, "used": False, "emitter": emitter, "chain": cid}
    return t


def _redeem(ticket, argv=None, payload=None, kind="proc"):
    """Validate and consume. Raises TicketRefused; on success returns the executor's entry."""
    if not isinstance(ticket, Ticket) or not getattr(ticket, "_sealed", False):
        raise TicketRefused("not a ticket issued by a gate")
    with _LOCK:
        entry = _ISSUED.get(ticket.id)
        if entry is None or entry["ticket"] is not ticket:
            raise TicketRefused("unknown ticket (not issued here, or already discarded)")
        if entry["used"]:
            raise TicketRefused("ticket already used — tickets are single-use")
        if _mono() > entry["expires"]:
            entry["used"] = True
            raise TicketRefused("ticket expired — authorize again")
        if ticket.kind != kind:
            raise TicketRefused("ticket is for a %s, not a %s" % (ticket.kind, kind))
        want_argv = ticket.argv if argv is None else tuple(str(a) for a in argv)
        want_payload = ticket.payload if payload is None else bytes(payload)
        if _digest(kind, want_argv, want_payload, ticket.files) != entry["digest"]:
            raise TicketRefused("command differs from what was authorized")
        entry["used"] = True                    # consumed even if the re-check below fails
    try:
        ok, why = entry["recheck"]()
    except Exception as e:                      # a gate that cannot answer is a no
        ok, why = False, "gate re-check failed: %s" % e
    if not ok:
        record("refuse_ticket", chain_id=entry.get("chain"), ticket=ticket.id,
               label=ticket.label, reason=why,
               target=str(ticket.meta.get("target", "")))          # RA-CL3 N10: visible in the trail
        raise TicketRefused("gate no longer passes: %s" % why)
    return entry


def _default_spawner(argv, **kw):
    return subprocess.Popen(list(argv), start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1)


def _kill_group(proc, grace=1.0):
    if proc is None or proc.poll() is not None:
        return
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill() if sig == signal.SIGKILL else proc.terminate()
            except Exception:
                return
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue
        except Exception:
            return


class Handle:
    """A registered, running (or finished) gated process."""

    def __init__(self, ticket, proc, argv, entry, on_line=None):
        self.ticket = ticket
        self.proc = proc
        self.argv = tuple(argv)
        self.exit_code = None
        self.stopped = None               # reason, when the executor (not the tool) ended it
        self.lines = []
        self._entry = entry
        self.chain_id = (entry or {}).get("chain")    # RA-CL3b B3: the chain issued under
        self._on_line = on_line
        self._done = threading.Event()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self):
        try:
            out = getattr(self.proc, "stdout", None)
            if out is not None:
                for line in out:
                    line = line.rstrip("\r\n") if isinstance(line, str) else \
                        line.decode("utf-8", "replace").rstrip("\r\n")
                    self.lines.append(line)
                    if len(self.lines) > 2000:
                        del self.lines[:-2000]
                    if self._on_line is not None:
                        try:
                            self._on_line(line)
                        except Exception:
                            pass
        except Exception:
            pass
        try:
            code = self.proc.wait()
        except Exception:
            code = None
        self.exit_code = code
        with _LOCK:
            if self in _RUNNING:
                _RUNNING.remove(self)
        record("exit", chain_id=self.chain_id, ticket=self.ticket.id, label=self.ticket.label,
               exit_code=code, stopped=self.stopped)
        self._done.set()

    def running(self):
        return not self._done.is_set()

    def wait(self, timeout=None):
        self._done.wait(timeout)
        return self.exit_code

    def stop(self, reason="stopped"):
        if self.stopped is None:
            self.stopped = reason
            record("kill", chain_id=self.chain_id, ticket=self.ticket.id,
                   label=self.ticket.label, reason=reason, pid=getattr(self.proc, "pid", None))
        _kill_group(self.proc)
        self._done.wait(3.0)


def start(ticket, argv=None, spawner=None, on_line=None):
    """Redeem a process ticket and spawn it in its own process group. Returns a Handle."""
    entry = _redeem(ticket, argv=argv, kind="proc")
    for path, content in ticket.files.items():          # e.g. a BSSID filter list (audit G5)
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)
    run_argv = ticket.argv
    proc = (spawner or _default_spawner)(run_argv)
    h = Handle(ticket, proc, run_argv, entry, on_line)
    with _LOCK:
        if not h._done.is_set():
            _RUNNING.append(h)
    _ensure_monitor()
    record("spawn", chain_id=h.chain_id, ticket=ticket.id, label=ticket.label,
           argv=list(run_argv), pid=proc.pid)
    _sweep()                     # the gate could have flipped between redeem and register
    return h


class Result:
    def __init__(self, exit_code, lines, stopped):
        self.exit_code = exit_code
        self.lines = list(lines)
        self.stopped = stopped


def run(ticket, argv=None, spawner=None, on_line=None, timeout=None):
    """start() and wait. Returns Result(exit_code, lines, stopped). On timeout the process group is
    killed (stopped='timeout')."""
    h = start(ticket, argv=argv, spawner=spawner, on_line=on_line)
    if h.wait(timeout) is None and h.running():
        h.stop("timeout")
    return Result(h.exit_code, h.lines, h.stopped)


def write(ticket, port, port_name="", chunk=None):
    """Redeem a device-write ticket and write its exact bytes to `port` (an object with .write),
    whole or in `chunk`-byte pieces (one HID report per write). Every line is logged. Returns the
    number of bytes the port reports written."""
    if ticket.binding == "demo" and getattr(type(port), "SYNTHETIC", False) is not True:
        # CL2-fix N9a: an ungated demo-device ticket is only ever written to the synthetic port
        raise TicketRefused("a demo-device ticket can only be written to the synthetic demo port")
    entry = _redeem(ticket, kind="write")
    data = ticket.payload
    pieces = [data] if not chunk else [data[i:i + chunk] for i in range(0, len(data), chunk)]
    n = 0
    for piece in pieces:
        w = port.write(piece)
        n += len(piece) if w is None else int(w)
    if hasattr(port, "flush"):
        try:
            port.flush()
        except Exception:
            pass
    meta = ticket.meta
    rec = {"t": time.time(), "port": port_name, "device": meta.get("device", ""),
           "line": data.decode("utf-8", "replace").rstrip("\r\n"), "bytes": n,
           "binding": ticket.binding, "ticket": ticket.id}
    try:
        os.makedirs(os.path.dirname(SERIAL_LOG), exist_ok=True)
        with open(SERIAL_LOG, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass
    record("write", chain_id=entry.get("chain"), **rec)
    return n


def running():
    with _LOCK:
        return [h for h in _RUNNING if h.running()]


def kill_all(reason="kill_all"):
    """Kill every registered process group (END engagement, disarm, PANIC). Returns how many."""
    hs = running()
    for h in hs:
        h.stop(reason)
    return len(hs)


def _sweep():
    """Re-check the gate of every running process; kill those whose gate no longer passes."""
    for h in running():
        try:
            ok, why = h._entry["recheck"]()
        except Exception as e:
            ok, why = False, str(e)
        if not ok:
            h.stop("gate closed: %s" % why)


def _ensure_monitor():
    with _LOCK:
        if not _MON["subscribed"]:
            import engagement
            import txguard
            txguard.subscribe(_sweep)
            engagement.subscribe(_sweep)
            _MON["subscribed"] = True
        t = _MON["thread"]
        if t is None or not t.is_alive():
            t = threading.Thread(target=_monitor, daemon=True)
            _MON["thread"] = t
            t.start()


def _monitor():
    while True:
        time.sleep(MONITOR_INTERVAL_S)
        if not running():
            with _LOCK:
                if not _RUNNING:
                    _MON["thread"] = None
                    return
            continue
        _sweep()


def reset():
    """Forget every issued ticket (tests / startup). Running processes are not touched."""
    with _LOCK:
        _ISSUED.clear()
