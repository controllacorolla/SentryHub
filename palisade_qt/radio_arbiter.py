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


def _make_lease(name):
    """Acquire the shared SDR lease (pauses readsb, frees the dongle). None if unavailable.
    SLOW — never call under the arbiter lock."""
    try:
        import suite
        lease = suite.RtlLease(name)
        lease.acquire()
        return lease
    except Exception:
        return None


class RadioArbiter(QtCore.QObject):
    changed = QtCore.Signal(str)        # owner name ("" when free) — also fires on ACQUIRING→HELD
    revoked = QtCore.Signal(str)        # the named holder must stop its pipeline and release()

    def __init__(self):
        super().__init__()
        self._owner = None
        self._state = "FREE"            # FREE | ACQUIRING | HELD
        self._lease = None
        self._lock = threading.Lock()
        self._gen = 0                   # bumps on every ownership change; stale acquires drop out
        self._revoke_timer = None

    # ---- ownership ----
    def request(self, name):
        """Become the single radio owner. Returns True if granted (now or already ours), False if
        another holder has it. Never blocks on the radio."""
        with self._lock:
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
        self.changed.emit(name)
        threading.Thread(target=self._acquire, args=(name, gen), name="radio-acquire",
                         daemon=False).start()
        return True

    def _acquire(self, name, gen):
        lease = _make_lease(name)            # slow; outside the lock
        with self._lock:
            if self._gen != gen or self._owner != name:
                stale = True                 # released / revoked while acquiring
            else:
                stale = False
                self._lease, self._state = lease, "HELD"
        if stale:
            if lease is not None:
                try:
                    lease.release()
                except Exception:
                    pass
            return
        self.changed.emit(name)

    def release(self, name):
        with self._lock:
            if self._owner != name:
                return
            lease, self._lease, self._owner, self._state = self._lease, None, None, "FREE"
            self._gen += 1
            t, self._revoke_timer = self._revoke_timer, None
        if t is not None:
            t.cancel()
        if lease is not None:
            try:
                lease.release()                   # readsb / the autopilot resume
            except Exception:
                pass
        self.changed.emit("")

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
        self.release(holder)

    # ---- reads (never block) ----
    def owner(self):
        with self._lock:
            return self._owner

    def state(self):
        """('FREE', None) | ('ACQUIRING', name) | ('HELD', name)."""
        with self._lock:
            return self._state, self._owner

    def revoking(self):
        with self._lock:
            return self._revoke_timer is not None

    def reset_for_tests(self):
        with self._lock:
            self._owner, self._state, self._lease = None, "FREE", None
            self._gen += 1
            t, self._revoke_timer = self._revoke_timer, None
        if t is not None:
            t.cancel()


# process-wide singleton — one radio, one arbiter
arbiter = RadioArbiter()

# lease name -> short label for the "RADIO BUSY — held by X" chrome
# <= 8 characters each: these are the state word of the strip's fixed-width SDR slot
OWNER_LABELS = {"ATLAS-APRS": "APRS", "ATLAS-AIS": "AIS", "BABEL": "BABEL",
                "PROWL-SCAN": "PROWL SC", "PROWL-FM": "PROWL FM", "PROWL-NWR": "PROWL WX",
                "BABEL-SSTV": "SSTV", "PRISM": "PRISM"}


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
