#!/usr/bin/env python3
"""gatestate.py — one source of gate state across processes (audit L1).

The Qt shell is one process. The Tk hub runs most tools in-process, but anything it launches as a
child process (and anything a child launches) used to carry its own per-process arm / unlock /
engagement state, so the hub's master kill switch and the power auto-disarm reached none of them.

The hub is the PUBLISHER: it writes arm, unlock and the engagement (name, typed scope, operator,
expiry) to a session-scoped file in the runtime directory every time either engine changes, and
removes the file when it exits. Children are launched with child_env(): PALISADE_GATE_STATE names
the file, and SUITE_TX_LOCK=1 is exported whenever the hub is disarmed.

A process started with PALISADE_GATE_STATE set is BOUND: txguard and engagement read the hub's state
instead of their own, cannot arm / unlock / open an engagement themselves, and FAIL CLOSED (disarmed,
no engagement) if the file is missing, unreadable, not owned by this user, writable by others, or
was written by a hub process that is no longer alive. A process started without the variable owns
its own state exactly as before (default disarmed, no engagement).
"""
import atexit
import json
import os
import tempfile
import time
import uuid

ENV = "PALISADE_GATE_STATE"
STALE = {"stale": True, "armed": False, "unlocked": False, "engagement": None}
_ROLE = {"publisher": None}


def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.join(
        tempfile.gettempdir(), "palisade-%d" % os.getuid())
    d = os.path.join(base, "uconsole-suite")
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def default_path():
    return os.path.join(runtime_dir(), "gate-%d.json" % os.getpid())


def _write(path, obj):
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(obj))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:          # alive, but another user's process: not our hub
        return False
    except (OSError, ValueError, TypeError):
        return False


def read(path):
    """The published state, or None when it cannot be trusted (missing, malformed, foreign,
    writable by others, or its hub is dead). Callers treat None as STALE."""
    try:
        st = os.stat(path)
        if st.st_uid != os.getuid() or (st.st_mode & 0o022):
            return None
        with open(path) as fh:
            obj = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(obj, dict) or not _alive(obj.get("pid")):
        return None
    if not isinstance(obj.get("armed"), bool) or not isinstance(obj.get("unlocked"), bool):
        return None
    eng = obj.get("engagement")
    if eng is not None and not isinstance(eng, dict):
        return None
    return {"stale": False, "armed": obj["armed"], "unlocked": obj["armed"] and obj["unlocked"],
            "engagement": eng, "pid": obj["pid"], "t": obj.get("t")}


def shared_state():
    """None when this process owns its own gate state (no hub, or this IS the hub). Otherwise the
    hub's state, or STALE (fail closed) when it cannot be read."""
    if _ROLE["publisher"] is not None:
        return None
    path = os.environ.get(ENV)
    if not path:
        return None
    st = read(path)
    return dict(STALE) if st is None else st


def bound():
    return shared_state() is not None


class Publisher:
    """The hub's side. Creating one makes this process the owner of the session state."""

    def __init__(self, path=None):
        self.path = path or default_path()
        self.nonce = uuid.uuid4().hex
        _ROLE["publisher"] = self
        import engagement
        import txguard
        txguard.subscribe(self.publish_from_engines)
        engagement.subscribe(self.publish_from_engines)
        atexit.register(self.close)
        self.publish_from_engines()

    def publish(self, armed, unlocked, engagement):
        _write(self.path, {"pid": os.getpid(), "nonce": self.nonce, "t": time.time(),
                           "armed": bool(armed) is True, "unlocked": bool(unlocked) is True,
                           "engagement": engagement})

    def publish_from_engines(self):
        import engagement
        import txguard
        try:
            self.publish(txguard.is_armed(), txguard.session_unlocked(),
                         engagement.export_state())
        except OSError:
            pass                # children fail closed on a stale / missing file

    def close(self):
        try:
            import engagement
            import txguard
            txguard.unsubscribe(self.publish_from_engines)
            engagement.unsubscribe(self.publish_from_engines)
        except Exception:
            pass
        try:
            os.remove(self.path)
        except OSError:
            pass
        if _ROLE["publisher"] is self:
            _ROLE["publisher"] = None


def child_env(path=None, base=None):
    """Environment for a child process: bound to the hub's state file, hard-locked while the hub is
    disarmed. An inherited SUITE_TX_LOCK is never removed (stricter wins)."""
    env = dict(os.environ if base is None else base)
    pub = _ROLE["publisher"]
    path = path or (pub.path if pub is not None else None)
    if not path:
        env["SUITE_TX_LOCK"] = "1"               # no session to bind to: lock the child
        return env
    env[ENV] = path
    st = read(path)
    if st is None or not st["armed"]:
        env["SUITE_TX_LOCK"] = "1"
    return env
