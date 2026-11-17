"""HOME follows GPS (owner 2026-11-17: "location should be automatic"; pulled into v0.1 from CL6).

When the operator leaves "HOME follows GPS" on (the default), the hub reads gpsd every POLL_S
seconds off the GUI thread. A fix is used only when it is trustworthy:
  - a TPV with mode 2 (2D) or 3 (3D), numeric lat/lon in range (bools refused), not the 0/0 that
    some receivers report before they have a fix, and a horizontal error (epx/epy) under MAX_ERR_M
    when the receiver reports one;
  - the first fix of a run, and any fix more than JUMP_NM from the current GPS HOME, must be
    confirmed by a second one within CONFIRM_NM (a single cold-start or multipath jump never
    moves HOME).
HOME then moves only when the position has moved MOVE_NM or more (no tile refetch every few metres).
When the fix is lost, HOME stays where the last good fix put it and the status says so. The typed
HOME (SYSTEM > SETTINGS, saved) is the fallback: it is loaded at start and stays HOME until a
confirmed fix arrives. Nothing here persists the GPS HOME, so a restart without a fix falls back to
the typed HOME again. Demo mode and the offscreen test seam never read gpsd.
"""
import math
import threading
import time

from PySide6 import QtCore

from . import eventbus

POLL_S = 10.0
CONFIRM_NM = 0.5
MOVE_NM = 0.25
JUMP_NM = 5.0             # a following HOME that jumps this far in one poll needs confirming again
MAX_ERR_M = 250.0
SETTING = "home_follows_gps"


def follows_gps(loader=None):
    """The saved choice (default ON). loader() -> the palisade_ui settings dict (test seam)."""
    try:
        if loader is not None:
            s = loader()
        else:
            import suite
            s, _p = suite.settings("palisade_ui", {})
        v = s.get(SETTING, True)
        return v if isinstance(v, bool) else True
    except Exception:
        return True


def usable(fix):
    """(lat, lon) from a gpsd TPV if it is a fix we may put HOME on, else None."""
    if not isinstance(fix, dict) or fix.get("mode") not in (2, 3):
        return None
    lat, lon = fix.get("lat"), fix.get("lon")
    for v in (lat, lon):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if abs(lat) < 0.01 and abs(lon) < 0.01:          # "null island": a receiver with no real fix
        return None
    for k in ("epx", "epy"):
        e = fix.get(k)
        if isinstance(e, (int, float)) and not isinstance(e, bool) and e > MAX_ERR_M:
            return None
    return float(lat), float(lon)


def distance_nm(a, b):
    x, y = eventbus.to_xy(b[0], b[1], home=a)
    return math.hypot(x, y)


class GpsHome(QtCore.QObject):
    """The hub's GPS -> HOME follower. status_changed(text, state) feeds SETTINGS (state is one of
    'live' | 'warn' | 'neutral')."""

    status_changed = QtCore.Signal(str, str)
    _fix_read = QtCore.Signal(object)

    def __init__(self, reader=None, enabled=True, parent=None):
        super().__init__(parent)
        self._reader = reader or self._gpsd
        self.enabled = bool(enabled)
        self._pending = None          # first fix of a run, waiting for confirmation
        self._busy = False
        self._last_ok = None          # time of the last usable fix
        self.status = ("GPS: waiting for a fix", "neutral")
        self._fix_read.connect(self._on_fix)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(int(POLL_S * 1000))
        self._timer.timeout.connect(self.poll)

    @staticmethod
    def _gpsd():
        import suite
        return suite.gps_fix(timeout=3.0)

    def start(self):
        self._timer.start()
        QtCore.QTimer.singleShot(0, self.poll)

    def stop(self):
        self._timer.stop()

    def set_enabled(self, on):
        self.enabled = bool(on)
        self._pending = None
        if not self.enabled:
            self._set_status("HOME: manual (GPS follow off)", "neutral")
        else:
            self._set_status("GPS: waiting for a fix", "neutral")
            QtCore.QTimer.singleShot(0, self.poll)

    def poll(self):
        if not self.enabled or self._busy:
            return
        self._busy = True
        reader = self._reader

        def run():
            try:
                fix = reader()
            except Exception:
                fix = None
            self._fix_read.emit(fix)
        threading.Thread(target=run, daemon=True).start()

    def _set_status(self, text, state):
        self.status = (text, state)
        self.status_changed.emit(text, state)

    def _on_fix(self, fix):
        self._busy = False
        if not self.enabled:
            return
        ll = usable(fix)
        if ll is None:
            self._pending = None
            if eventbus.HOME_SOURCE == "gps":
                age = int(time.time() - self._last_ok) if self._last_ok else 0
                self._set_status("GPS: no fix — HOME held at the last fix (%ds ago)" % age, "warn")
            else:
                self._set_status("GPS: no fix — HOME is the typed one"
                                 if eventbus.home_set() else "GPS: no fix — HOME NOT SET", "warn")
            return
        cur = eventbus.home()
        jump = eventbus.HOME_SOURCE == "gps" and cur is not None and distance_nm(cur, ll) > JUMP_NM
        if eventbus.HOME_SOURCE != "gps" or jump:
            # a run starts (or HOME would jump): confirm with a second fix close by first
            if self._pending is None or distance_nm(self._pending, ll) > CONFIRM_NM:
                self._pending = ll
                self._set_status("GPS: fix %.4f, %.4f — confirming" % ll, "neutral")
                return
        self._pending = None
        self._last_ok = time.time()
        mode = "3D" if fix.get("mode") == 3 else "2D"
        if eventbus.HOME_SOURCE != "gps" or cur is None or distance_nm(cur, ll) >= MOVE_NM:
            eventbus.set_home(ll, "gps")
        self._set_status("HOME: GPS %s fix %.4f, %.4f" % ((mode,) + eventbus.home()), "live")
