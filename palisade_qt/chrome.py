"""Shell-owned chrome state: the four fixed status slots in the top strip.

MODE, RADIO, TX and ENGAGEMENT are global facts about the device, so the SHELL reads them from the
engines and draws them; a page can never write them (the old single overwritable chip is gone —
D4/H7). This module only READS engine state (txguard, engagement, the radio arbiter); it changes
nothing in any engine or gate.

  MODE        LIVE | DEMO                      from the hub's own demo flag
  RADIO       FREE | HELD · <owner>            from radio_arbiter (its `changed` signal — never the
                                               arbiter lock, which can block during an acquire)
  TX          OFF | PERMITTED | ARMED | UNKNOWN
                                               txguard armed -> ARMED; else a page-reported permit
                                               (BENCH's conducted gate passing) -> PERMITTED; else OFF.
                                               UNKNOWN if txguard cannot be read.
  ENGAGEMENT  NONE | <scope> | UNKNOWN         from engagement.info(); the strip paints the scope
                                               summary as the word (amber diamond = active);
                                               UNKNOWN if it cannot be read

A reader that raises never falls back to the all-clear word (OFF / NONE): it reports UNKNOWN, which
the strip draws amber with its own shape (RA-CL1).

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
    """Test isolation only. PANIC does not call this: clearing the registry would make the TX slot
    read OFF while a page's own gate still passes."""
    _permits.clear()


def read_tx():
    """'ARMED' | 'PERMITTED' | 'OFF' | 'UNKNOWN' — read-only view of the engines."""
    try:
        import txguard
        armed = txguard.is_armed()
    except Exception:
        return "UNKNOWN"
    if armed:
        return "ARMED"
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
        # RA-CL1c F2: "1000 targets" pushed the strip past 1280 px. The capped form ("999+ tgts",
        # 9 chars) is no longer than the widest single target (SCOPE_CHARS).
        return "%d+ tgts" % SCOPE_MAX
    if len(scope) >= 100:
        # RA-MAIN-1 F1: "999 targets" (11 chars) left 1 px of the 1280 strip in SUN. Three-digit
        # counts use the short form so no scope summary is longer than SCOPE_CHARS (10).
        return "%d tgts" % len(scope)
    return "%d target%s" % (len(scope), "" if len(scope) == 1 else "s")


def read_engagement():
    """('ACTIVE', scope summary, name) | ('NONE', '', '') | ('UNKNOWN', '', '')."""
    try:
        import engagement
        info = engagement.info()
        active = bool(info.get("active"))
    except Exception:
        return "UNKNOWN", "", ""
    if not active:
        return "NONE", "", ""
    return "ACTIVE", scope_summary(info.get("scope")), str(info.get("name") or "")


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
        """('HELD', label) · ('ACQUIRING', label) · ('FREE', '') — straight from the arbiter (A3)."""
        st, owner = radio_arbiter.arbiter.state()
        if owner:
            return ("ACQUIRING" if st == "ACQUIRING" else "HELD"), \
                radio_arbiter.OWNER_LABELS.get(owner, owner)
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
