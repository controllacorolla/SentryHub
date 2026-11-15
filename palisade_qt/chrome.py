"""Shell-owned chrome state: the four fixed status slots in the top strip.

MODE, RADIO, TX and ENGAGEMENT are global facts about the device, so the SHELL reads them from the
engines and draws them; a page can never write them (the old single overwritable chip is gone —
D4/H7). This module only READS engine state (txguard, engagement, the radio arbiter); it changes
nothing in any engine or gate.

  MODE        LIVE | DEMO                      from the hub's own demo flag
  RADIO       FREE | HELD · <owner>            from radio_arbiter (its `changed` signal — never the
                                               arbiter lock, which can block during an acquire)
  TX          OFF | PERMITTED | ARMED | UNLOCKED | UNKNOWN
                                               txguard armed + unlocked -> UNLOCKED; armed -> ARMED; else a page-reported permit
                                               (BENCH's conducted gate passing) -> PERMITTED; else OFF.
                                               UNKNOWN if txguard cannot be read.
  ENGAGEMENT  NONE | <scope> | EXPIRED | UNKNOWN
                                               from engagement.info(); EXPIRED once past its expiry; the strip paints the scope
                                               summary as the word (amber diamond = active);
                                               UNKNOWN if it cannot be read

A reader that raises never falls back to the all-clear word (OFF / NONE): it reports UNKNOWN, which
the strip draws amber with its own shape (RA-CL1).

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
    """Test isolation only. PANIC does not call this: clearing the registry would make the TX slot
    read OFF while a page's own gate still passes."""
    _permits.clear()


def read_tx():
    """'UNLOCKED' | 'ARMED' | 'PERMITTED' | 'OFF' | 'UNKNOWN' — read-only view of the engines."""
    try:
        import txguard
        armed = txguard.is_armed()
        unlocked = armed and txguard.session_unlocked()
    except Exception:
        return "UNKNOWN"
    if armed:
        return "UNLOCKED" if unlocked else "ARMED"
    return "PERMITTED" if _permits else "OFF"


SCOPE_CHARS = 10          # a single target this short is shown as itself; longer -> the count
# words the strip uses for states: a target spelled like one must never be painted as the slot's
# word (an active engagement on a host named "none" would read ENG NONE — RA-CL1b N4)
STATE_WORDS = {"NONE", "OFF", "UNKNOWN", "FREE", "ACTIVE", "ARMED", "PERMITTED", "LIVE", "DEMO"}


SCOPE_MAX = 999


def scope_summary(scope):
    """Short, never-elided scope text for the strip: the target itself when there is one short
    target, else the count. The full list is in the ENGAGEMENT panel."""
    scope = [str(s) for s in scope or []]
    if len(scope) == 1 and len(scope[0]) <= SCOPE_CHARS and scope[0].strip().upper() not in STATE_WORDS:
        return scope[0]
    if len(scope) > SCOPE_MAX:
        # RA-CL1c F2: "1000 targets" pushed the strip past 1280 px. "999 targets" (11 chars) is the
        # widest value the strip is sized for, so the capped form may not be longer than that.
        return "%d+ tgts" % SCOPE_MAX
    return "%d target%s" % (len(scope), "" if len(scope) == 1 else "s")


def read_engagement():
    """('ACTIVE', scope summary, name) | ('EXPIRED', '', name) | ('NONE', '', '') |
    ('UNKNOWN', '', '')."""
    try:
        import engagement
        info = engagement.info()
        active = bool(info.get("active"))
        expired = bool(info.get("expired"))
    except Exception:
        return "UNKNOWN", "", ""
    if expired:
        return "EXPIRED", "", str(info.get("name") or "")
    if not active:
        return "NONE", "", ""
    return "ACTIVE", scope_summary(info.get("scope")), str(info.get("name") or "")


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
