"""The radio arbiter — one owner of the single SDR at a time.

The uConsole has one built-in RTL dongle. ATLAS's lease-using layers (APRS 144.39, AIS 162 MHz,
later PRISM) must never both open it, and readsb/ADS-B is the baseline that resumes when no layer
holds it. This small helper is the single source of truth for "who holds the radio"; a layer that
wants it but can't get it renders an honest RADIO BUSY state instead of an empty map.

It is deliberately minimal — the seed of the OVERWATCH radio director. No time-sharing or
rotation: exactly one owner until it releases.

Policy: first requester wins and keeps it until it releases (no pre-emptive takeover here; the UI
can offer the operator a manual takeover by releasing one layer before enabling another).
`_make_lease` is a seam so tests never open a real radio.
"""
import threading

from PySide6 import QtCore


def _make_lease(name):
    """Acquire the shared SDR lease (pauses readsb, frees the dongle). None if unavailable."""
    try:
        import suite
        lease = suite.RtlLease(name)
        lease.acquire()
        return lease
    except Exception:
        return None


class RadioArbiter(QtCore.QObject):
    changed = QtCore.Signal(str)        # new owner name, or "" when the radio is free

    def __init__(self):
        super().__init__()
        self._owner = None
        self._lease = None
        self._lock = threading.Lock()

    def request(self, name):
        """Become the single radio owner. True if granted (now or already ours); False if busy."""
        acquired = False
        with self._lock:
            if self._owner is None:
                self._lease = _make_lease(name)   # logical ownership even if no real radio here
                self._owner = name
                acquired = True
            granted = self._owner == name
        if acquired:
            self.changed.emit(name)
        return granted

    def release(self, name):
        with self._lock:
            if self._owner != name:
                return
            lease, self._lease, self._owner = self._lease, None, None
        if lease is not None:
            try:
                lease.release()                   # readsb / the autopilot resume
            except Exception:
                pass
        self.changed.emit("")

    def owner(self):
        with self._lock:
            return self._owner


# process-wide singleton — one radio, one arbiter
arbiter = RadioArbiter()

# lease name -> short label for the "RADIO BUSY — held by X" chrome
OWNER_LABELS = {"ATLAS-APRS": "APRS", "ATLAS-AIS": "AIS", "BABEL": "BABEL"}


def owner_label():
    o = arbiter.owner()
    return OWNER_LABELS.get(o, o) if o else None
