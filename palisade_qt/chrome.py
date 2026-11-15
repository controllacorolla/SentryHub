"""Shell-owned chrome state: the four fixed status slots in the top strip.

MODE, RADIO, TX and ENGAGEMENT are global facts about the device, so the SHELL reads them from the
engines and draws them; a page can never write them (the old single overwritable chip is gone —
D4/H7). This module only READS engine state (txguard, engagement, the radio arbiter); it changes
nothing in any engine or gate.

  MODE        LIVE | DEMO                      from the hub's own demo flag
  RADIO       FREE | HELD · <owner>            from radio_arbiter (its `changed` signal — never the
                                               arbiter lock, which can block during an acquire)
  TX          OFF | PERMITTED | ARMED          txguard armed -> ARMED; else a page-reported permit
                                               (BENCH's conducted gate passing) -> PERMITTED; else OFF
  ENGAGEMENT  NONE | ACTIVE · <scope>          from engagement.info()

txguard and engagement expose no change signals (that is audit finding G12, cluster CL2), so those
two are polled on a short GUI-thread timer; both reads are plain dict lookups.
"""
from PySide6 import QtCore

from . import radio_arbiter

_permits = {}          # source -> bool: a page whose own TX gate currently passes (e.g. BENCH)


def report_tx_permit(source, permitted):
    """A page tells the shell whether ITS transmit gate currently passes. Display only."""
    if permitted:
        _permits[source] = True
    else:
        _permits.pop(source, None)


def tx_permit_sources():
    return sorted(_permits)


def reset():
    _permits.clear()


def read_tx():
    """'ARMED' | 'PERMITTED' | 'OFF' — read-only view of the engines."""
    try:
        import txguard
        if txguard.is_armed():
            return "ARMED"
    except Exception:
        pass
    return "PERMITTED" if _permits else "OFF"


def read_engagement():
    """('ACTIVE', scope summary, name) or ('NONE', '', '')."""
    try:
        import engagement
        info = engagement.info()
    except Exception:
        return "NONE", "", ""
    if not info.get("active"):
        return "NONE", "", ""
    scope = [str(s) for s in info.get("scope") or []]
    summary = scope[0] if len(scope) == 1 else "%s +%d" % (scope[0], len(scope) - 1) if scope else "?"
    return "ACTIVE", summary, str(info.get("name") or "")


class ChromeState(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, demo=False, parent=None, poll_ms=500):
        super().__init__(parent)
        self.mode = "DEMO" if demo else "LIVE"
        self._owner = radio_arbiter.arbiter.owner() or ""
        self._tx = read_tx()
        self._eng = read_engagement()
        radio_arbiter.arbiter.changed.connect(self._on_radio)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._timer.start(poll_ms)

    def _on_radio(self, owner):
        self._owner = owner or ""
        self.changed.emit()

    def poll(self):
        tx, eng = read_tx(), read_engagement()
        if tx != self._tx or eng != self._eng:
            self._tx, self._eng = tx, eng
            self.changed.emit()

    def radio(self):
        """('HELD', label) or ('FREE', '')."""
        if self._owner:
            return "HELD", radio_arbiter.OWNER_LABELS.get(self._owner, self._owner)
        return "FREE", ""

    def tx(self):
        return self._tx

    def engagement(self):
        return self._eng

    def stop(self):
        self._timer.stop()
        try:
            radio_arbiter.arbiter.changed.disconnect(self._on_radio)
        except (TypeError, RuntimeError):
            pass
