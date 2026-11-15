#!/usr/bin/env python3
"""chain.py — THE evidence chain (audit G6, G7, H9; cluster CL3).

One chain per engagement, on disk, shared by every process of the session:

    DATA/engagements/<id>.jsonl   append-only records, one JSON object per line
    DATA/engagements/<id>.key     32 random bytes, mode 0600 — the per-engagement HMAC key
    DATA/engagements/<id>.head    the hash of the last record (so truncation is detected)

Every record is hashed as a WHOLE: `h = HMAC-SHA256(key, prev || canonical_json(record - h))`,
where canonical JSON has sorted keys and no whitespace. Rewriting any field — operator,
engagement, seq, file, argv, exit code — breaks the chain; dropping the last record no longer
verifies because `.head` names it; without the key a record cannot be re-forged. Opening an
existing chain loads it, verifies it and CONTINUES it (no second genesis). Every append is
`flock`ed, fsynced and raises on failure — a record that could not be made durable was not made,
and the gate that asked for it (engagement.authorize_action) refuses (G6: no durable record, no
authorization).

What goes in (H9 — authorizations and executions are different states):
    engagement.open / engagement.close   scope in force, operator, expiry
    authorize                            action, target, binding (the gate said yes)
    issue / spawn / exit / write / kill  from the executor, with pid and the REAL exit code
    refuse                               a gate said no (kept so the trail shows attempts)

Time: wall clock `t`, a monotonic counter `mono_ns` since this process opened the chain, `pid`,
and `gps_t` when a time source has been registered with set_time_source().

The HMAC key is only as private as the files are: it keeps the trail tamper-evident against
anything that cannot read 0600 files of this user. For a stronger head, sign_head_argv() gives the
gpg command (owner-gated, tool-gated, never run here).
"""
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid

GENESIS = "0" * 64
_LOCK = threading.RLock()
_TIME_SOURCE = {"fn": None}
_OPEN = {"chain": None}          # the process-wide open chain (the active engagement's, or a session chain)
_SESSION = {"chain": None}


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
                      default=str).encode("utf-8")


def new_id(name=""):
    slug = "".join(c if c.isalnum() else "-" for c in str(name or "")).strip("-")[:24].lower()
    return "%s-%s%s" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:8],
                        ("-" + slug) if slug else "")


class ChainError(Exception):
    """The chain could not be opened, verified or appended to. Callers fail closed."""


class Chain:
    """An open, verified, append-only chain. Use Chain.create() / Chain.open()."""

    def __init__(self, cid, directory=None, key=None):
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
        c = cls(cid, directory, key=secrets.token_bytes(32))
        if os.path.exists(c.path) or os.path.exists(c.key_path):
            raise ChainError("chain %s already exists — open() it, never start a second genesis" % cid)
        _write_private(c.key_path, c._key)
        _write_private(c.path, b"")
        _write_private(c.head_path, GENESIS.encode())
        return c

    @classmethod
    def open(cls, cid, directory=None):
        c = cls(cid, directory)
        try:
            with open(c.key_path, "rb") as fh:
                c._key = fh.read()
        except OSError as e:
            raise ChainError("chain %s: key unreadable (%s)" % (cid, e))
        if len(c._key) < 16:
            raise ChainError("chain %s: key file is damaged" % cid)
        _check_private(c.key_path)
        c._load_and_verify()
        return c

    @classmethod
    def exists(cls, cid, directory=None):
        d = directory or engagements_dir()
        return os.path.exists(os.path.join(d, cid + ".jsonl"))

    # ---------------------------------------------------------------- hashing
    def _h(self, prev, rec):
        body = dict(rec)
        body.pop("h", None)
        return hmac.new(self._key, prev.encode() + b"|" + canonical(body), hashlib.sha256).hexdigest()

    def _load_and_verify(self):
        recs = []
        try:
            with open(self.path, "rb") as fh:
                raw = fh.read()
        except OSError as e:
            raise ChainError("chain %s: unreadable (%s)" % (self.id, e))
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
        try:
            with open(self.head_path) as fh:
                head = fh.read().strip()
        except OSError:
            raise ChainError("chain %s: head file missing — cannot prove the chain is complete" % self.id)
        if head != prev:
            raise ChainError("chain %s: head %s does not match the last record %s — records were "
                             "dropped or the file was replaced" % (self.id, head[:12], prev[:12]))
        self.records = recs

    def verify(self):
        """(ok, reason). Re-reads the file from disk and re-verifies every record and the head."""
        try:
            self._load_and_verify()
        except ChainError as e:
            return False, str(e)
        return True, "%d records intact" % len(self.records)

    @property
    def head(self):
        return self.records[-1]["h"] if self.records else GENESIS

    # ---------------------------------------------------------------- append
    def record(self, event, **fields):
        """Append one record durably. Raises ChainError if it cannot — callers that are gates
        must then refuse. Returns the record."""
        with self._lock:
            lock_fd = os.open(self.path, os.O_RDWR)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                # another process may have appended: re-sync before chaining
                self._load_and_verify()
                prev = self.head
                rec = {"seq": len(self.records), "t": time.time(),
                       "mono_ns": time.monotonic_ns() - self._mono0, "pid": os.getpid(),
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
                    if k not in rec:
                        rec[k] = v
                rec["h"] = self._h(prev, rec)
                line = canonical(rec) + b"\n"
                os.lseek(lock_fd, 0, os.SEEK_END)
                n = os.write(lock_fd, line)
                if n != len(line):
                    raise ChainError("short write to %s" % self.path)
                os.fsync(lock_fd)
                _write_private(self.head_path, rec["h"].encode())
                self.records.append(rec)
                return rec
            except OSError as e:
                raise ChainError("chain %s: append failed (%s)" % (self.id, e))
            finally:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)

    # ---------------------------------------------------------------- views
    def states(self):
        """H9: one row per authorization/ticket with its CURRENT state, newest first.
        state ∈ AUTHORIZED · ISSUED · RUNNING · EXECUTED · KILLED · REFUSED · FAILED."""
        rows = {}
        order = []
        for r in self.records:
            ev = r.get("event")
            if ev == "authorize":
                key = ("a", r["seq"])
                rows[key] = {"seq": r["seq"], "t": r["t"], "action": r.get("action", ""),
                             "target": r.get("target", ""), "state": "AUTHORIZED",
                             "binding": r.get("binding", ""), "detail": ""}
                order.append(key)
            elif ev == "refuse":
                key = ("r", r["seq"])
                why = str(r.get("reason", ""))
                short = ("scope" if "not in the engagement scope" in why else
                         "expired" if "expired" in why else
                         "no eng" if "no active engagement" in why else
                         "stale" if "stale" in why else why[:12])
                rows[key] = {"seq": r["seq"], "t": r["t"], "action": r.get("action", ""),
                             "target": r.get("target", ""), "state": "REFUSED",
                             "binding": "", "detail": short}
                order.append(key)
            elif ev in ("issue", "spawn", "exit", "write", "kill"):
                tid = r.get("ticket")
                key = ("t", tid)
                if key not in rows:
                    rows[key] = {"seq": r["seq"], "t": r["t"], "action": r.get("label", ""),
                                 "target": r.get("target", ""), "state": "ISSUED",
                                 "binding": r.get("binding", ""), "detail": ""}
                    order.append(key)
                row = rows[key]
                if ev == "spawn":
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
        return [rows[k] for k in reversed(order)]

    def sign_head_argv(self, out_path=None, key=None):
        """gpg detach-signature of the chain file (owner/tool-gated; never run here)."""
        argv = ["gpg", "--batch", "--yes"]
        if key:
            argv += ["--local-user", key]
        argv += ["--detach-sign", "--armor", "--output", out_path or self.path + ".asc", self.path]
        return argv


# -------------------------------------------------------------------- process-wide routing
def set_open(chain):
    """Make `chain` the process-wide chain (the active engagement's). None → session chain."""
    with _LOCK:
        _OPEN["chain"] = chain


def current(create_session=True):
    """The chain that records go to: the open engagement chain, else a per-process session chain
    (TX without an engagement, e.g. a conducted bench run, is still evidence)."""
    with _LOCK:
        if _OPEN["chain"] is not None:
            return _OPEN["chain"]
        if _SESSION["chain"] is None and create_session:
            _SESSION["chain"] = Chain.create(name="session-%d" % os.getpid())
            _SESSION["chain"].record("session.open", pid=os.getpid())
        return _SESSION["chain"]


def record(event, **fields):
    """Route a record to the current chain. Raises ChainError on failure (fail closed)."""
    return current().record(event, **fields)


def reset_for_tests():
    with _LOCK:
        _OPEN["chain"] = None
        _SESSION["chain"] = None


# -------------------------------------------------------------------- file helpers
def _write_private(path, data):
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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
    st = os.stat(path)
    if st.st_uid != os.getuid() or (st.st_mode & 0o077):
        raise ChainError("%s is not private to this user (mode %o)" % (path, st.st_mode & 0o777))
