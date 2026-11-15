"""Shell-owned chrome state: the four fixed status slots in the top strip.

MODE, RADIO, TX and ENGAGEMENT are global facts about the device, so the SHELL reads them from the
engines and draws them; a page can never write them (the old single overwritable chip is gone —
D4/H7). This module only READS engine state (txguard, engagement, the radio arbiter); it changes
nothing in any engine or gate.

  MODE        LIVE | DEMO                      from the hub's own demo flag
  RADIO       FREE | HELD · <owner>            from radio_arbiter (its `changed` signal — never the
                                               arbiter lock, which can block during an acquire)
  TX          OFF | PERMITTED | ARMED |        txguard armed + unlocked -> UNLOCKED; armed -> ARMED;
              UNLOCKED                         else a page-reported permit (BENCH's conducted gate
                                               passing) -> PERMITTED; else OFF
  ENGAGEMENT  NONE | ACTIVE · <scope> |        from engagement.info(); EXPIRED once past its expiry
              EXPIRED

txguard and engagement emit change notifications (audit G12): GateSignals bridges them into one Qt
signal (queued onto the GUI thread), and the slots, the FORGE replay banner and engagement cards,
RECON's gated tools, BENCH and the ENGAGEMENT / TX panels all subscribe. A slow timer remains only
for what changes with time and not by a call: engagement expiry and a hub's shared state.
"""
from PySide6 import QtCore

from . import radio_arbiter


class GateSignals(QtCore.QObject):
    """One process-wide bridge: txguard / engagement listener -> Qt `changed` signal."""
    changed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        import engagement
        import txguard
        txguard.subscribe(self._fire)
        engagement.subscribe(self._fire)

    def _fire(self):
        try:
            self.changed.emit()
        except RuntimeError:          # app torn down
            pass


_SIGNALS = {"obj": None}


def gate_signals():
    if _SIGNALS["obj"] is None:
        _SIGNALS["obj"] = GateSignals()
    return _SIGNALS["obj"]

_permits = {}          # source -> bool: a page whose own TX gate currently passes (e.g. BENCH)


def report_tx_permit(source, permitted):
    """A page tells the shell whether ITS transmit gate currently passes. Display only. A change
    re-fires the gate signal so the TX slot never keeps a permit the page has withdrawn (the slot
    may have repainted before the page saw the same engine change)."""
    before = bool(_permits.get(source))
    if permitted:
        _permits[source] = True
    else:
        _permits.pop(source, None)
    if before != bool(permitted) and _SIGNALS["obj"] is not None:
        _SIGNALS["obj"]._fire()


def tx_permit_sources():
    return sorted(_permits)


def reset():
    _permits.clear()


def read_tx():
    """'UNLOCKED' | 'ARMED' | 'PERMITTED' | 'OFF' — read-only view of the engines."""
    try:
        import txguard
        if txguard.is_armed():
            return "UNLOCKED" if txguard.session_unlocked() else "ARMED"
    except Exception:
        pass
    return "PERMITTED" if _permits else "OFF"


def read_engagement():
    """('ACTIVE', scope summary, name) | ('EXPIRED', '', name) | ('NONE', '', '')."""
    try:
        import engagement
        info = engagement.info()
    except Exception:
        return "NONE", "", ""
    if info.get("expired"):
        return "EXPIRED", "", str(info.get("name") or "")
    if not info.get("active"):
        return "NONE", "", ""
    scope = [str(s) for s in info.get("scope") or []]
    summary = scope[0] if len(scope) == 1 else "%s +%d" % (scope[0], len(scope) - 1) if scope else "?"
    return "ACTIVE", summary, str(info.get("name") or "")


class ChromeState(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, demo=False, parent=None, poll_ms=1000):
        super().__init__(parent)
        self.mode = "DEMO" if demo else "LIVE"
        self._owner = radio_arbiter.arbiter.owner() or ""
        self._tx = read_tx()
        self._eng = read_engagement()
        radio_arbiter.arbiter.changed.connect(self._on_radio)
        gate_signals().changed.connect(self.poll)          # engine-driven (G12)
        self._timer = QtCore.QTimer(self)                  # expiry / hub shared state only
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
        for sig, slot in ((radio_arbiter.arbiter.changed, self._on_radio),
                          (gate_signals().changed, self.poll)):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
