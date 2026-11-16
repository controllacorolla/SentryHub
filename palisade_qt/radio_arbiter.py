"""The radio arbiter — one owner of the single SDR at a time (CL5: A1, A3).

The uConsole has one built-in RTL dongle. ATLAS's lease-using layers (APRS, AIS), PRISM and the
PROWL decoders must never both open it, and readsb/ADS-B is the baseline that resumes when no
layer holds it. This is the single source of truth for "who holds the radio".

States (A3): FREE · ACQUIRING(name) · HELD(name). request() decides ownership at once under the
lock and starts the slow acquire (RtlLease.acquire can take ~90 s: it pauses readsb) OUTSIDE the
lock on a thread, so owner()/state() never block the GUI. While ACQUIRING the requester is the
logical owner (nobody else is granted); HELD once the lease is really in hand.

Revocation (A1): revoke(name) does NOT release on the holder's behalf. It emits `revoked(name)`;
the holder stops its pipeline, waits for it to exit, then calls release(name). If the holder has
not acknowledged within REVOKE_TIMEOUT_S the arbiter frees anyway (the pipeline is then the
holder's leak to report), and only then does readsb restart. `_make_lease` is a seam so tests
never open a real radio.
"""
import threading
import time

from PySide6 import QtCore

REVOKE_TIMEOUT_S = 5.0
FAIL_RETRY_S = 20.0          # H4: after a failed acquire, the same holder is not re-granted for this


def _note(what):
    """C4: a swallowed lease error goes to the session log (and the strip's fault indicator)."""
    try:
        from . import sessionlog
        sessionlog.note_exception("RADIO", what)
    except Exception:
        pass


class LeaseFailed(Exception):
    """The real lease could not be taken (readsb would not stop, sudo refused …). The radio is NOT
    granted (audit H4): the arbiter returns to FREE and says why."""


def _make_lease(name):
    """Acquire the shared SDR lease (pauses readsb, frees the dongle). SLOW — never call under the
    arbiter lock. Returns the lease, or None when there is no suite lease module on this host (the
    dev host / tests: nothing else uses the dongle, so the radio is ours). Raises LeaseFailed when
    the module is there and the acquire failed (H4: that used to be swallowed and the radio granted
    anyway, so a decoder raced readsb for the dongle under a HELD chip)."""
    try:
        import suite
        lease_cls = suite.RtlLease
    except Exception:
        return None
    lease = lease_cls(name)
    try:
        lease.acquire()
    except Exception as e:
        try:
            lease.release()               # put back whatever it paused before failing
        except Exception:
            _note("lease release after a failed acquire (%s)" % name)
        raise LeaseFailed(str(e)[:160] or type(e).__name__)
    return lease


class RadioArbiter(QtCore.QObject):
    changed = QtCore.Signal(str)        # owner name ("" when free) — also fires on ACQUIRING→HELD
    revoked = QtCore.Signal(str)        # the named holder must stop its pipeline and release()
    failed = QtCore.Signal(str, str)    # (name, why): the acquire failed, the radio was NOT granted
    # (event, owner, note) captured AT the transition (N11: changed() + a late state() read logged
    # HELD, HELD for a fast acquire). event: ACQUIRING | HELD | RELEASE; note on a RELEASE says
    # how ("" = the holder released, "FORCED FREE …", "PANIC").
    transition = QtCore.Signal(str, str, str)

    def __init__(self):
        super().__init__()
        self._owner = None
        self._state = "FREE"            # FREE | ACQUIRING | HELD
        self._lease = None
        self._lock = threading.Lock()
        self._gen = 0                   # bumps on every ownership change; stale acquires drop out
        self._revoke_timer = None
        self._failures = {}             # name -> why its last acquire failed (H4); cleared on grant

    # ---- ownership ----
    def request(self, name):
        """Become the single radio owner. Returns True if granted (now or already ours), False if
        another holder has it. Never blocks on the radio."""
        with self._lock:
            f = self._failures.get(name)
            if f is not None and self._owner is None and time.monotonic() - f[1] < FAIL_RETRY_S:
                return False                 # H4: back off after a failed acquire, say why
            if self._owner is None:
                self._owner, self._state = name, "ACQUIRING"
                self._gen += 1
                gen = self._gen
                start = True
            else:
                start = False
                granted = self._owner == name
        if not start:
            return granted
        self.transition.emit("ACQUIRING", name, "")
        self.changed.emit(name)
        threading.Thread(target=self._acquire, args=(name, gen), name="radio-acquire",
                         daemon=False).start()
        return True

    def _acquire(self, name, gen):
        try:
            lease = _make_lease(name)        # slow; outside the lock
        except Exception as e:               # H4: a failed acquire is NOT a grant
            why = str(e) or type(e).__name__
            with self._lock:
                mine = self._gen == gen and self._owner == name
                if mine:
                    self._owner, self._state, self._lease = None, "FREE", None
                    self._gen += 1
                    self._failures[name] = (why, time.monotonic())
                    t, self._revoke_timer = self._revoke_timer, None
                else:
                    t = None
            if t is not None:
                t.cancel()
            if mine:
                import sys
                print("[radio] %s: acquire failed — %s" % (name, why), file=sys.stderr)
                self.transition.emit("FAILED", name, why)
                self.failed.emit(name, why)
                self.changed.emit("")
            return
        with self._lock:
            if self._gen != gen or self._owner != name:
                stale = True                 # released / revoked while acquiring
            else:
                stale = False
                self._lease, self._state = lease, "HELD"
                self._failures.pop(name, None)
        if stale:
            if lease is not None:
                try:
                    lease.release()
                except Exception:
                    _note("lease release (%s)" % name)
            return
        self.transition.emit("HELD", name, "")
        self.changed.emit(name)

    def release(self, name):
        self._release(name)

    def _release(self, name, gen=None, note=""):
        """Free the radio if `name` holds it (and, when gen is given, only if ownership has not
        changed since — N12: a revoke timer must never free a re-grant)."""
        with self._lock:
            if self._owner != name or (gen is not None and self._gen != gen):
                return False
            lease, self._lease, self._owner, self._state = self._lease, None, None, "FREE"
            self._gen += 1
            t, self._revoke_timer = self._revoke_timer, None
        if t is not None:
            t.cancel()
        # announce FREE as soon as it is FREE (CL5-fix2): the lease release below restarts readsb
        # and can take seconds; the strip must not show the old holder for that long
        self.transition.emit("RELEASE", name, note)
        self.changed.emit("")
        if lease is not None:
            try:
                lease.release()                   # readsb / the autopilot resume
            except Exception:
                _note("lease release — readsb may not have resumed")
        return True

    def revoke(self, name=None, timeout_s=None):
        """Ask the holder to give the radio back (A1). Returns the name asked, or None if free.
        The holder's acknowledgement is its own release(); after timeout_s the arbiter frees."""
        with self._lock:
            holder = self._owner
            if holder is None or (name is not None and name != holder):
                return None
            if self._revoke_timer is not None:
                return holder                     # already asked; the clock is running
            t = threading.Timer(REVOKE_TIMEOUT_S if timeout_s is None else timeout_s,
                                self._revoke_expired, args=(holder, self._gen))
            t.daemon = True
            self._revoke_timer = t
        self.revoked.emit(holder)
        t.start()
        return holder

    def _revoke_expired(self, holder, gen):
        with self._lock:
            if self._gen != gen or self._owner != holder:
                return                            # it acknowledged in time
            self._revoke_timer = None
        import sys
        print("[radio] %s did not release within the revoke timeout — forcing free" % holder,
              file=sys.stderr)
        self._release(holder, gen, note="FORCED FREE — holder did not acknowledge")

    def panic_free(self):
        """PANIC (CL5-fix 5): the operator wants the radio stopped now. The shell has already set
        every page's hold-off flag and killed the child process tree, so this tells the holder
        (revoked(name): it drops its pipeline and stays off) and frees at once, without the
        revoke grace period. Returns the name that held it, or None if it was free."""
        with self._lock:
            holder = self._owner
        if holder is None:
            return None
        self.revoked.emit(holder)
        self._release(holder, note="PANIC")
        return holder

    # ---- reads (never block) ----
    def owner(self):
        with self._lock:
            return self._owner

    def state(self):
        """('FREE', None) | ('ACQUIRING', name) | ('HELD', name)."""
        with self._lock:
            return self._state, self._owner

    def held_by(self, name):
        """True only when `name` really holds the dongle (HELD, not ACQUIRING). A holder starts
        its decoder only on this (CL5-fix 1 / N1): during ACQUIRING readsb may still own the
        dongle and RtlLease.acquire kills rtl_fm & co, so a decoder started early dies or races."""
        with self._lock:
            return self._owner == name and self._state == "HELD"

    def revoking(self):
        with self._lock:
            return self._revoke_timer is not None

    def failure(self, name):
        """Why `name`'s last acquire failed, or None (H4). Cleared when it is next granted."""
        with self._lock:
            f = self._failures.get(name)
            return f[0] if f else None

    def retry_in(self, name):
        """Seconds until `name` may request again after a failed acquire (0 = now)."""
        with self._lock:
            f = self._failures.get(name)
        if not f:
            return 0
        return max(0, int(FAIL_RETRY_S - (time.monotonic() - f[1]) + 0.999))

    def reset_for_tests(self):
        with self._lock:
            self._owner, self._state, self._lease = None, "FREE", None
            self._gen += 1
            t, self._revoke_timer = self._revoke_timer, None
            self._failures.clear()
        if t is not None:
            t.cancel()


# process-wide singleton — one radio, one arbiter
arbiter = RadioArbiter()

# lease name -> short label for the "RADIO BUSY — held by X" chrome
# <= 8 characters each: these are the state word of the strip's fixed-width SDR slot
OWNER_LABELS = {"ATLAS-APRS": "APRS", "ATLAS-AIS": "AIS", "BABEL": "BABEL",
                "PROWL-SCAN": "PROWL SC", "PROWL-FM": "PROWL FM", "PROWL-NWR": "PROWL WX",
                "BABEL-SSTV": "SSTV", "PRISM": "PRISM"}


def lost_reason(name, default="radio taken back"):
    """What a holder that found itself not owning the radio should say: the acquire failure when
    that is what happened (H4), else `default`."""
    why = arbiter.failure(name)
    return ("radio acquire failed: %s" % why)[:90] if why else default


def busy_text(name):
    """The status word for a refused request(name): the acquire failure (H4), or RADIO BUSY."""
    why = arbiter.failure(name)
    if why and arbiter.owner() is None:
        return ("RADIO FAILED — %s (retry in %ds)" % (why, arbiter.retry_in(name)))[:90]
    return "RADIO BUSY"


def owner_label():
    o = arbiter.owner()
    return OWNER_LABELS.get(o, o) if o else None


def wait_held(name, timeout_s=10.0):
    """Test/CLI helper: block until the arbiter reports HELD for name (or FREE), or timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st, o = arbiter.state()
        if o != name or st == "HELD":
            return st == "HELD"
        time.sleep(0.02)
    return False
