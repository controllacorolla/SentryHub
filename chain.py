#!/usr/bin/env python3
"""chain.py — THE evidence chain (audit G6, G7, H9; cluster CL3, hardened by RA-CL3).

One chain per engagement, on disk, shared by every process of the session:

    DATA/engagements/<id>.jsonl   append-only records, one JSON object per line
    DATA/engagements/<id>.key     32 random bytes, mode 0600 — the per-engagement HMAC key
    DATA/engagements/<id>.head    "<n> <h> <mac>": record count, last hash, HMAC(key, id|n|h)

Every record is hashed as a WHOLE: `h = HMAC-SHA256(key, id || prev || canonical_json(record - h))`.
Rewriting any field breaks the chain; dropping records fails against the keyed head (RA-CL3 N1);
a chain's files cannot be swapped under another id (N2); without the key a record cannot be
re-forged. Opening an existing chain loads it under a shared lock, verifies it and CONTINUES it (no
second genesis). Every append is `flock`ed, fsynced and raises on failure — and an append that
fails half-way is rolled back to the previous length, so one ENOSPC never bricks the chain (N3).
A record that could not be made durable was not made, and the gate that asked for it refuses
(G6: no durable record, no authorization).

Which chain receives a record (RA-CL3 B1/B2): `current()` asks the engagement engine for the
chain id of the engagement in force RIGHT NOW (the hub's own, or the hub's as published to a
bound child) and opens/caches by that id — never a process-global that only the hub sets. With no
engagement open, records go to a per-process session chain (a conducted bench run is still
evidence). An executor ticket is bound to the chain it was ISSUED under: its refuse_ticket / spawn
/ write / kill / exit go to that chain by id (`for_id`), never to `current()` at record time
(RA-CL3b B3/N14), so END and START never misfile a running ticket's outcome.

Limits, stated plainly: the HMAC key is a 0600 file of the same user. The chain is tamper-evident
against anything that cannot read that file. A same-user attacker WITH the key can rewrite
everything; only an off-device anchor (a signed head shipped elsewhere; `sign_head_argv()`) stops
that, and it is not automated here (owner decision).
"""
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid

GENESIS = "0" * 64
KEY_BYTES = 32
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_LOCK = threading.RLock()
_TIME_SOURCE = {"fn": None}
_CACHE = {}                 # chain id -> Chain (this process's handle; re-synced under lock on use)
_SESSION = {"chain": None}
_PROTECTED = ("seq", "prev", "h", "event")


def engagements_dir():
    import suite
    d = os.path.join(suite.DATA, "engagements")
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def set_time_source(fn):
    """fn() -> epoch seconds from GPS (or None). Recorded as gps_t on every record."""
    _TIME_SOURCE["fn"] = fn


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str).encode("utf-8", "surrogatepass")


def valid_id(cid):
    return isinstance(cid, str) and bool(_ID_RE.match(cid)) and ".." not in cid


def new_id(name=""):
    slug = "".join(c if c.isalnum() else "-" for c in str(name or "")).strip("-")[:24].lower()
    return "%s-%s%s" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:8],
                        ("-" + slug) if slug else "")


class ChainError(Exception):
    """The chain could not be opened, verified or appended to. Callers fail closed."""


class Chain:
    """An open, verified, append-only chain. Use Chain.create() / Chain.open()."""

    def __init__(self, cid, directory=None, key=None):
        if not valid_id(cid):
            raise ChainError("invalid chain id %r" % (cid,))
        self.id = cid
        self.dir = directory or engagements_dir()
        self.path = os.path.join(self.dir, cid + ".jsonl")
        self.key_path = os.path.join(self.dir, cid + ".key")
        self.head_path = os.path.join(self.dir, cid + ".head")
        self._key = key
        self.records = []
        self._mono0 = time.monotonic_ns()
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- create / open
    @classmethod
    def create(cls, cid=None, name="", directory=None):
        cid = cid or new_id(name)
        c = cls(cid, directory, key=secrets.token_bytes(KEY_BYTES))
        for p in (c.path, c.key_path, c.head_path):
            if os.path.lexists(p):
                raise ChainError("chain %s already exists — open() it, never start a second genesis"
                                 % cid)
        _write_private(c.key_path, c._key)
        _write_private(c.path, b"")
        _write_private(c.head_path, c._head_line(0, GENESIS))
        return c

    @classmethod
    def open(cls, cid, directory=None):
        c = cls(cid, directory)
        try:
            _check_private(c.key_path)
            with open(c.key_path, "rb") as fh:
                c._key = fh.read()
        except OSError as e:
            raise ChainError("chain %s: key unreadable (%s)" % (cid, e))
        if len(c._key) < KEY_BYTES:
            raise ChainError("chain %s: key file is damaged (%d bytes)" % (cid, len(c._key)))
        c._load_and_verify()
        return c

    @classmethod
    def exists(cls, cid, directory=None):
        d = directory or engagements_dir()
        return valid_id(cid) and os.path.exists(os.path.join(d, cid + ".jsonl"))

    # ---------------------------------------------------------------- hashing
    def _h(self, prev, rec):
        body = dict(rec)
        body.pop("h", None)
        return hmac.new(self._key, self.id.encode() + b"|" + prev.encode() + b"|" + canonical(body),
                        hashlib.sha256).hexdigest()

    def _head_mac(self, n, h):
        return hmac.new(self._key, ("%s|%d|%s" % (self.id, n, h)).encode(), hashlib.sha256).hexdigest()

    def _head_line(self, n, h):
        return ("%d %s %s" % (n, h, self._head_mac(n, h))).encode()

    def _parse(self, raw):
        recs = []
        prev = GENESIS
        for n, line in enumerate(raw.splitlines()):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                raise ChainError("chain %s: record %d is not JSON" % (self.id, n))
            if rec.get("seq") != len(recs):
                raise ChainError("chain %s: record %d has seq %r (expected %d) — rewritten or reordered"
                                 % (self.id, n, rec.get("seq"), len(recs)))
            if rec.get("prev") != prev:
                raise ChainError("chain %s: record %d does not chain to its predecessor" % (self.id, n))
            if not hmac.compare_digest(self._h(prev, rec), str(rec.get("h", ""))):
                raise ChainError("chain %s: record %d fails its HMAC — altered" % (self.id, n))
            prev = rec["h"]
            recs.append(rec)
        return recs, prev

    def _check_head(self, recs, prev):
        try:
            with open(self.head_path) as fh:
                parts = fh.read().split()
        except OSError:
            raise ChainError("chain %s: head file missing — cannot prove the chain is complete" % self.id)
        if len(parts) != 3 or not parts[0].isdigit():
            raise ChainError("chain %s: head file malformed" % self.id)
        n, h, mac = int(parts[0]), parts[1], parts[2]
        if not hmac.compare_digest(self._head_mac(n, h), mac):
            raise ChainError("chain %s: head fails its HMAC — rewritten without the key" % self.id)
        if n != len(recs) or h != prev:
            raise ChainError("chain %s: head says %d records ending %s, file has %d ending %s — "
                             "records were dropped or the file was replaced"
                             % (self.id, n, h[:12], len(recs), prev[:12]))

    def _load_and_verify(self, fd=None):
        """Load + verify under a SHARED lock (RA-CL3 N4) unless the caller already holds the
        exclusive lock on `fd`. Returns the byte length read."""
        own = fd is None
        if own:
            try:
                _check_private(self.path)
                _check_private(self.head_path)
                fd = os.open(self.path, os.O_RDONLY)
            except OSError as e:
                raise ChainError("chain %s: unreadable (%s)" % (self.id, e))
            fcntl.flock(fd, fcntl.LOCK_SH)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            chunks = []
            while True:
                b = os.read(fd, 1 << 20)
                if not b:
                    break
                chunks.append(b)
            raw = b"".join(chunks)
            recs, prev = self._parse(raw)
            self._check_head(recs, prev)
        except OSError as e:
            raise ChainError("chain %s: unreadable (%s)" % (self.id, e))
        finally:
            if own:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
        self.records = recs
        return len(raw)

    def verify(self):
        """(ok, reason). Re-reads the file from disk and re-verifies every record and the head.
        On failure the in-memory records are DROPPED (nothing is served from memory — RA-CL3 H9)."""
        try:
            self._load_and_verify()
        except ChainError as e:
            self.records = []
            return False, str(e)
        return True, "%d records intact" % len(self.records)

    @property
    def head(self):
        return self.records[-1]["h"] if self.records else GENESIS

    # ---------------------------------------------------------------- append
    def record(self, event, _only_if=None, **fields):
        """Append one record durably. Raises ChainError if it cannot — callers that are gates
        must then refuse. A half-written append is rolled back (N3). Returns the record.

        `_only_if(records) -> bool` (RA-CL3c N17) is evaluated under the EXCLUSIVE lock against the
        freshly re-read records; if it returns False nothing is appended and None is returned.
        Use it for a record that is only true if nothing else happened first (END's void)."""
        with self._lock:
            try:
                lock_fd = os.open(self.path, os.O_RDWR)
            except OSError as e:
                raise ChainError("chain %s: cannot open for append (%s)" % (self.id, e))
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                prev_len = self._load_and_verify(fd=lock_fd)     # re-sync: others may have appended
                if _only_if is not None and not _only_if(list(self.records)):
                    return None
                prev = self.head
                rec = {"seq": len(self.records), "t": time.time(),
                       "mono_ns": time.monotonic_ns() - self._mono0, "wpid": os.getpid(),
                       "event": str(event), "prev": prev}
                g = _TIME_SOURCE["fn"]
                if g is not None:
                    try:
                        gt = g()
                        if gt is not None:
                            rec["gps_t"] = float(gt)
                    except Exception:
                        pass
                for k, v in fields.items():
                    if k not in _PROTECTED:                  # N5: a caller's pid/t win
                        rec[k] = v
                rec["h"] = self._h(prev, rec)
                line = canonical(rec) + b"\n"
                try:
                    os.lseek(lock_fd, 0, os.SEEK_END)
                    n = os.write(lock_fd, line)
                    if n != len(line):
                        raise OSError("short write")
                    os.fsync(lock_fd)
                    _write_private(self.head_path, self._head_line(len(self.records) + 1, rec["h"]))
                except Exception as e:
                    try:                                       # N3: never leave an orphan line
                        os.ftruncate(lock_fd, prev_len)
                        os.fsync(lock_fd)
                    except OSError:
                        pass
                    raise ChainError("chain %s: append failed (%s) — rolled back" % (self.id, e))
                self.records.append(rec)
                return rec
            except ChainError:
                raise
            except OSError as e:
                raise ChainError("chain %s: append failed (%s)" % (self.id, e))
            finally:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)

    # ---------------------------------------------------------------- views
    def states(self):
        """H9: one row per authorization, carried through its ticket, newest first.
        state ∈ AUTHORIZED · ISSUED · RUNNING · EXECUTED · FAILED · KILLED · REFUSED · UNCONFIRMED."""
        rows, order, by_ticket = {}, [], {}
        pending = {}                                    # (action, target) -> key of AUTHORIZED row
        for r in self.records:
            ev = r.get("event")
            if ev == "authorize":
                key = ("a", r["seq"])
                rows[key] = {"seq": r["seq"], "t": r["t"], "action": r.get("action", ""),
                             "target": r.get("target", ""), "state": "AUTHORIZED",
                             "binding": r.get("binding", ""), "detail": "", "ticket": None}
                order.append(key)
                pending[(r.get("action", ""), str(r.get("target", "")))] = key
            elif ev == "refuse_ticket" and r.get("ticket") in by_ticket:
                # RA-CL3b B3: a known ticket refused at redeem, or voided at END, is that
                # action's row — REFUSED, not a second row beside a stale ISSUED one
                # RA-CL3c N17: a refusal only ever replaces a not-yet-used state; it can never
                # hide a RUNNING / EXECUTED / FAILED / KILLED outcome
                row = rows[by_ticket[r["ticket"]]]
                if row["state"] in ("AUTHORIZED", "ISSUED"):
                    row["state"], row["detail"] = "REFUSED", _short_reason(r.get("reason", ""))
            elif ev in ("refuse", "refuse_ticket"):
                key = ("r", r["seq"])
                short = _short_reason(r.get("reason", ""))
                rows[key] = {"seq": r["seq"], "t": r["t"], "action": r.get("action") or r.get("label", ""),
                             "target": r.get("target", ""), "state": "REFUSED",
                             "binding": "", "detail": short, "ticket": r.get("ticket")}
                order.append(key)
            elif ev in ("issue", "spawn", "exit", "write", "kill", "unconfirmed"):
                tid = r.get("ticket")
                key = by_ticket.get(tid)
                if key is None:
                    # N10: fold the ticket into the AUTHORIZED row it came from (same action+target)
                    akey = pending.pop((r.get("label", ""), str(r.get("target", ""))), None)
                    if akey is not None:
                        key = akey
                        rows[key]["ticket"] = tid
                    else:
                        key = ("t", tid)
                        rows[key] = {"seq": r["seq"], "t": r["t"], "action": r.get("label", ""),
                                     "target": r.get("target", ""), "state": "ISSUED",
                                     "binding": r.get("binding", ""), "detail": "", "ticket": tid}
                        order.append(key)
                    by_ticket[tid] = key
                row = rows[key]
                if ev == "issue":
                    row["state"] = "ISSUED"
                elif ev == "spawn":
                    row["state"], row["detail"] = "RUNNING", "pid %s" % r.get("pid")
                elif ev == "exit":
                    code = r.get("exit_code")
                    if r.get("stopped"):
                        row["state"], row["detail"] = "KILLED", str(r.get("stopped"))
                    elif code == 0:
                        row["state"], row["detail"] = "EXECUTED", "exit 0"
                    else:
                        row["state"], row["detail"] = "FAILED", "exit %s" % code
                elif ev == "write":
                    row["state"], row["detail"] = "EXECUTED", "%s bytes" % r.get("bytes")
                elif ev == "kill":
                    row["state"], row["detail"] = "KILLED", str(r.get("reason", ""))
                elif ev == "unconfirmed" and row["state"] == "RUNNING":
                    # RA-CL3c N16: END could not confirm this process ended. Not KILLED: nothing
                    # was signalled by END and it may still be running. A later exit overrides.
                    row["state"], row["detail"] = "UNCONFIRMED", str(r.get("reason", ""))
        return [rows[k] for k in reversed(order)]

    def sign_head_argv(self, out_path=None, key=None):
        """gpg detach-signature of the chain file (owner/tool-gated; never run here)."""
        argv = ["gpg", "--batch", "--yes"]
        if key:
            argv += ["--local-user", key]
        argv += ["--detach-sign", "--armor", "--output", out_path or self.path + ".asc", self.path]
        return argv


def _short_reason(why):
    why = str(why or "")
    return ("scope" if "not in the engagement scope" in why else
            "ended" if "engagement ended" in why else
            "expired" if "expired" in why else
            "no eng" if "no active engagement" in why else
            "stale" if "stale" in why else
            "rf lock" if "silenced" in why or "SUITE_TX_LOCK" in why else why[:12])


# -------------------------------------------------------------------- process-wide routing
def for_id(cid):
    """The Chain for an id: cached per process, (re)opened when first seen. Raises ChainError."""
    if not valid_id(cid):
        raise ChainError("invalid chain id %r" % (cid,))
    with _LOCK:
        c = _CACHE.get(cid)
        if c is None:
            c = Chain.open(cid)
            _CACHE[cid] = c
        return c


def active_id():
    """The chain id of the engagement in force right now, from the engagement engine (the hub's
    own engagement, or the hub's as published to a bound child) — or None. RA-CL3 B1/B2."""
    try:
        import engagement
        return engagement.current_chain_id()
    except Exception:
        return None


def current(create_session=True):
    """The chain that records go to: the engagement in force (by id, every process), else this
    process's session chain (TX without an engagement is still evidence). Raises ChainError when
    an engagement is in force but its chain cannot be opened (fail closed)."""
    cid = active_id()
    if cid:
        return for_id(cid)
    with _LOCK:
        if _SESSION["chain"] is None and create_session:
            _SESSION["chain"] = Chain.create(name="session-%d" % os.getpid())
            _SESSION["chain"].record("session.open", pid=os.getpid())
            _CACHE[_SESSION["chain"].id] = _SESSION["chain"]   # tickets bound to it use for_id
        return _SESSION["chain"]


def record(event, **fields):
    """Route a record to the current chain. Raises ChainError on failure (fail closed)."""
    return current().record(event, **fields)


def set_open(chain):
    """Kept for callers of the old API: the open engagement chain is now found by id."""
    if chain is not None:
        with _LOCK:
            _CACHE[chain.id] = chain


def reset_for_tests():
    with _LOCK:
        _CACHE.clear()
        _SESSION["chain"] = None


# -------------------------------------------------------------------- file helpers
def _write_private(path, data):
    if os.path.islink(path):
        raise OSError("refusing to write through a symlink: %s" % path)
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dfd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _check_private(path):
    st = os.lstat(path)
    if os.path.islink(path):
        raise ChainError("%s is a symlink" % path)
    if st.st_uid != os.getuid() or (st.st_mode & 0o077):
        raise ChainError("%s is not private to this user (mode %o)" % (path, st.st_mode & 0o777))
