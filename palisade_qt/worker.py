"""The kit's worker contract — a QThread with a cooperative, INTERRUPTIBLE stop (CL5).

This is the R1/R3 fix made reusable, hardened by the audit (A2 + "Workers", §15.1):

  * stop() wakes the worker at once: the inter-step wait is a condition with the interval as its
    timeout, not a 10 ms poll, and blocking helpers (sleep(), wait_for(), poll_process()) all
    return early on stop. A worker that honours them joins in milliseconds.
  * pause() / resume(): the page tells its worker when it is hidden (PalisadeApp.set_active);
    a paused worker sleeps on the same condition and costs nothing. Workers that must keep
    running while hidden (a radio decoder that owns the dongle) set PAUSE_WHEN_HIDDEN = False.
  * repeated step() failures back off (interval doubles up to BACKOFF_MAX_MS) and raise ONE
    visible fault (`fault` signal) instead of repeating the same error every interval; a
    successful step clears the fault.

Apps subclass Worker and implement step() (periodic) or run() (own loop, still honouring
self.stopping and using self.sleep()); PalisadeApp owns start/stop and never aborts the process
if a worker refuses to join (see app.py).
"""
import atexit
import threading
import weakref

from PySide6 import QtCore

_LIVE = weakref.WeakSet()          # every Worker ever constructed and still referenced


def drain_all(wait_ms=2000):
    """At interpreter exit: stop and join every worker still running; terminate() the ones that
    will not join, so Python never finalizes with a running QThread (the SIGABRT the audit saw:
    QThread::~QThread on a running thread at Py_Finalize). Also used by tests. Returns how many
    had to be terminated."""
    killed = 0
    for w in list(_LIVE):
        try:
            if not w.isRunning():
                continue
            w.stop()
            if w.wait(wait_ms):
                continue
            w.terminate()
            w.wait(1000)
            killed += 1
        except Exception:
            pass
    return killed


atexit.register(drain_all)


class Worker(QtCore.QThread):
    row = QtCore.Signal(object)       # one feed row / sample to the GUI thread
    status = QtCore.Signal(dict)      # periodic status (SDR/GPS/PWR …) to the header
    error = QtCore.Signal(str)        # a fault the app should surface (R2: never swallowed)
    fault = QtCore.Signal(str)        # a persistent fault: step() keeps failing ("" when cleared)

    PAUSE_WHEN_HIDDEN = True
    BACKOFF_AFTER = 3                 # consecutive failures before backing off
    BACKOFF_MAX_MS = 30_000

    def __init__(self, demo=False, interval_ms=500, parent=None):
        super().__init__(parent)
        self.demo = demo
        self.interval_ms = int(interval_ms)
        self._stop = False
        self._paused = False
        self._poked = False
        self._cv = threading.Condition()
        self._failures = 0
        self._faulted = False
        _LIVE.add(self)

    # ---- control (any thread) ----
    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        self.requestInterruption()

    def poke(self):
        """Wake the worker from its current sleep()/interval now (a flag it must act on changed:
        RUN, page hidden, a revoke). Thread-safe and non-blocking — the GUI thread only ever sets
        flags and pokes; the worker thread does the slow kill/wait/release itself (CL5-fix 6)."""
        with self._cv:
            self._poked = True
            self._cv.notify_all()

    def pause(self, on=True):
        with self._cv:
            self._paused = bool(on)
            self._cv.notify_all()

    def resume(self):
        self.pause(False)

    @property
    def stopping(self):
        return self._stop

    @property
    def paused(self):
        return self._paused

    # ---- blocking helpers for subclasses (all return early on stop) ----
    def sleep(self, ms):
        """Wait up to ms milliseconds, or until stop() / poke(). Returns True if stopping."""
        deadline = QtCore.QDeadlineTimer(int(ms))
        with self._cv:
            while not self._stop and not self._poked and not deadline.hasExpired():
                self._cv.wait(max(0.001, deadline.remainingTime() / 1000.0))
            self._poked = False
        return self._stop

    def wait_for(self, predicate, timeout_ms, poll_ms=50):
        """Poll predicate() every poll_ms until it is true, the timeout passes, or stop().
        Returns the predicate's last value (False on stop / timeout)."""
        deadline = QtCore.QDeadlineTimer(int(timeout_ms))
        while not self._stop:
            v = predicate()
            if v:
                return v
            if deadline.hasExpired():
                return False
            self.sleep(min(poll_ms, max(1, deadline.remainingTime())))
        return False

    def poll_process(self, proc, timeout_ms=None, poll_ms=100):
        """Wait for a subprocess to exit, interruptibly. Returns its returncode, or None if still
        running when stop() or the timeout came."""
        deadline = QtCore.QDeadlineTimer(int(timeout_ms)) if timeout_ms is not None else None
        while not self._stop:
            rc = proc.poll()
            if rc is not None:
                return rc
            if deadline is not None and deadline.hasExpired():
                return None
            self.sleep(poll_ms)
        return proc.poll()

    def _wait_interval(self):
        """Sleep the interval (longer while backing off); block while paused."""
        with self._cv:
            while not self._stop and self._paused:
                self._cv.wait(0.5)
        self.sleep(self._current_interval())

    def _current_interval(self):
        if self._failures < self.BACKOFF_AFTER:
            return self.interval_ms
        n = min(self._failures - self.BACKOFF_AFTER + 1, 8)
        return min(self.BACKOFF_MAX_MS, self.interval_ms * (2 ** n))

    # ---- the loop ----
    def step(self):
        return None

    def run(self):
        while not self._stop:
            if not self._paused:
                try:
                    self.step()
                    if self._failures:
                        self._failures = 0
                    if self._faulted:
                        self._faulted = False
                        self.fault.emit("")
                except Exception as e:                 # R2: surface, don't swallow
                    self._failures += 1
                    msg = str(e)[:200]
                    if self._failures < self.BACKOFF_AFTER:
                        self.error.emit(msg)
                    elif not self._faulted:
                        self._faulted = True
                        self.error.emit(msg)
                        self.fault.emit("FAULT: %s (×%d, backing off to %d s)" % (
                            msg, self._failures, self._current_interval() // 1000 or 1))
            self._wait_interval()
