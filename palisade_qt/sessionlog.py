"""The session log (audit C4): one place every fault, error and network request is recorded, so
nothing a page or engine swallows is lost, and a fault indicator the shell can draw.

    sessionlog.record("fault", "BABEL", "decoder exited after 0.4s")   # any thread
    sessionlog.log().faults_unseen()                                   # the strip's indicator
    sessionlog.note_exception("radio_arbiter", "release failed")       # inside an except block

Entries also go to ~/.cache/uconsole-suite/session.log (rotated at LOG_MAX bytes), which is what
an operator sends home after a field day. Errors used to go to stderr, which nobody sees on the
handheld.

Levels: "fault" and "error" light the indicator until seen; "warn", "info" and "net" do not.
"""
import os
import threading
import time
import traceback

from PySide6 import QtCore

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEVELS = ("fault", "error", "warn", "net", "info")
ATTENTION = ("fault", "error")
CAP = 1000
LOG_MAX = 1 << 20
DEDUPE_S = 60.0


def _path():
    return os.path.join(os.path.expanduser("~"), ".cache", "uconsole-suite", "session.log")


class SessionLog(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self.items = []              # newest first: {id, ts, level, source, text, count}
        self._next_id = 1
        self._seen_id = 0            # everything up to here is seen …
        self._seen_ids = set()       # … plus these (seen one by one, on screen: RA-CL8b)

    # ---- write (any thread) ----
    def record(self, level, source, text):
        level = level if level in LEVELS else "info"
        text = " ".join(str(text).split())[:400]
        source = str(source or "?")[:40]
        now = time.time()
        with self._lock:
            # the same message from the same source within DEDUPE_S bumps a count: a retry loop
            # must not bury everything else
            for it in self.items[:20]:
                if (it["level"], it["source"], it["text"]) == (level, source, text) and \
                        now - it["ts"] < DEDUPE_S:
                    it["count"] += 1
                    it["ts"] = now
                    if self._is_seen(it["id"]):
                        # RA-CL8: a repeat after the operator saw it is news again: new id, so the
                        # fault indicator lights; moved to the top where the newest entries are
                        it["id"] = self._next_id
                        self._next_id += 1
                        self.items.remove(it)
                        self.items.insert(0, it)
                    break
            else:
                self.items.insert(0, {"id": self._next_id, "ts": now, "level": level,
                                      "source": source, "text": text, "count": 1})
                self._next_id += 1
                del self.items[CAP:]
        self._write(now, level, source, text)
        try:
            self.changed.emit()
        except RuntimeError:
            pass

    def _write(self, ts, level, source, text):
        path = _path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > LOG_MAX:
                os.replace(path, path + ".1")
            with open(path, "a") as f:
                f.write("%s %-5s %s: %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
                                             level.upper(), source, text))
        except OSError:
            pass                       # a full or read-only disk must not take the UI down

    # ---- read ----
    def snapshot(self):
        with self._lock:
            return [dict(it) for it in self.items]

    def faults_unseen(self):
        """Faults/errors recorded since the operator last opened the log (the strip indicator)."""
        with self._lock:
            return sum(1 for it in self.items if it["level"] in ATTENTION and not self._is_seen(it["id"]))

    def first_unseen_id(self):
        """Id of the oldest fault/error not yet seen, or None."""
        with self._lock:
            ids = [it["id"] for it in self.items
                   if it["level"] in ATTENTION and not self._is_seen(it["id"])]
        return min(ids) if ids else None

    def _is_seen(self, item_id):
        return item_id <= self._seen_id or item_id in self._seen_ids

    def mark_seen(self, ids=None):
        """Mark faults seen: all of them (ids=None), or only these ids (the rows the operator
        actually has on screen). Emits changed only when the unseen count moved."""
        with self._lock:
            before = sum(1 for it in self.items if it["level"] in ATTENTION
                         and not self._is_seen(it["id"]))
            if ids is None:
                self._seen_id = self._next_id - 1
                self._seen_ids.clear()
            else:
                self._seen_ids.update(ids)
            after = sum(1 for it in self.items if it["level"] in ATTENTION
                        and not self._is_seen(it["id"]))
        if after != before:
            self.changed.emit()

    def clear_for_tests(self):
        with self._lock:
            self.items = []
            self._seen_id = self._next_id - 1


_log = None
_log_lock = threading.Lock()


def log():
    global _log
    with _log_lock:
        if _log is None:
            _log = SessionLog()
            app = QtCore.QCoreApplication.instance()
            if app is not None:
                _log.moveToThread(app.thread())
        return _log


def record(level, source, text):
    try:
        log().record(level, source, text)
    except Exception:
        pass


def note_exception(source, what=""):
    """Call inside an `except` block: records the exception (type, message, last frame) as an
    error instead of dropping it."""
    import sys
    et, ev, tb = sys.exc_info()
    if et is None:
        record("error", source, what or "error")
        return
    frame = ""
    try:
        last = traceback.extract_tb(tb)[-1]
        frame = " (%s:%d)" % (os.path.basename(last.filename), last.lineno)
    except Exception:
        pass
    record("error", source, "%s%s: %s%s" % ((what + " — ") if what else "", et.__name__, ev, frame))


def install_hooks():
    """Uncaught exceptions on the GUI thread or any worker thread land in the log too."""
    import sys

    prev = sys.excepthook

    def _hook(et, ev, tb):
        try:
            record("error", "uncaught", "%s: %s" % (et.__name__, ev))
        except Exception:
            pass
        prev(et, ev, tb)
    sys.excepthook = _hook

    prev_t = threading.excepthook

    def _thook(args):
        try:
            record("error", "thread %s" % getattr(args.thread, "name", "?"),
                   "%s: %s" % (args.exc_type.__name__, args.exc_value))
        except Exception:
            pass
        prev_t(args)
    threading.excepthook = _thook


def watch_network():
    """NET requests and mode changes from netpolicy go into the log (blocked ones as warn)."""
    import sys
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    import netpolicy

    def _on(ev):
        kind, mode, host, purpose = ev
        if kind == "mode":
            record("info", "NET", "network mode set to %s" % mode)
        elif kind == "blocked":
            record("warn", "NET", "blocked %s (%s) — mode %s" % (host, purpose or "request", mode))
        elif kind == "granted":
            record("warn", "NET", "operator-granted %s (%s) despite mode %s"
                   % (host, purpose or "request", mode))
        else:
            record("net", "NET", "%s (%s)" % (host, purpose or "request"))
    netpolicy.add_listener(_on)
    return _on
