"""PALISADE event bus — the one typed stream every callsign publishes to.

One small, typed contract so OPS (now) and sitrep / fusion / record+replay (later) all consume
the same thing without a refactor:

    event = {
        "type":     "contact" | "decode" | "alert",
        "source":   callsign str, e.g. "ATLAS", "BABEL", "RECON"
        "severity": "info" | "live" | "warn" | "alert",
        "ts":       float epoch seconds,
        "payload":  dict, type-specific (see make_* helpers),
        "demo":     bool — True only for synthetic demo traffic (audit H7; default False)
    }

Publishing is thread-safe: a worker QThread calls bus.publish(...), which appends to a bounded
log (under a lock) and emits a Qt signal that Qt delivers on the GUI thread (queued connection),
so subscribers touch widgets safely. Nothing here renders — consumers decide how to show it.
"""
import math
import copy
import threading
import time
from collections import deque

from PySide6 import QtCore

TYPES = ("contact", "decode", "alert")
SEVERITIES = ("info", "live", "warn", "alert")

# Operator home position (audit H5). There is NO built-in default any more: a hard-coded Seattle
# made every range and bearing a guess presented as a measurement. HOME is loaded at startup from
# the operator's saved setting (load_home), set live from SYSTEM › SETTINGS (set_home), and until
# then is None: pages say HOME NOT SET and suppress range and bearing. Demo mode uses DEMO_HOME and
# says so. GPS is not wired yet (audit §9 / CL6); when it is, it takes precedence (source "gps").
HOME = None
HOME_SOURCE = None                    # "settings" | "demo" | "gps" | None
DEMO_HOME = (47.6, -122.3)
_FRAME = {"origin": None}             # provisional map origin while HOME is not set
_EARTH_NM = 3440.065


def home():
    """The operator's HOME (lat, lon), or None when it has not been set (H5)."""
    return HOME


def home_set():
    return HOME is not None


def set_home(latlon, source="settings"):
    """Set HOME live for every consumer and tell them (bus.home_changed). None clears it."""
    global HOME, HOME_SOURCE
    if latlon is None:
        HOME, HOME_SOURCE = None, None
    else:
        lat, lon = float(latlon[0]), float(latlon[1])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("HOME out of range: %r" % (latlon,))
        HOME, HOME_SOURCE = (lat, lon), source
    _FRAME["origin"] = None
    try:
        bus.home_changed.emit()
    except (NameError, RuntimeError):
        pass


def load_home(demo=False, loader=None):
    """At startup: the operator's saved HOME (SYSTEM › SETTINGS, suite settings 'palisade_ui'),
    else DEMO_HOME in demo mode, else None — never a silent default. Returns the source used."""
    saved = None
    try:
        if loader is not None:
            saved = loader()
        else:
            import suite
            s, _p = suite.settings("palisade_ui", {})
            saved = s.get("home")
        if saved is not None:
            saved = (float(saved[0]), float(saved[1]))
            if not (-90 <= saved[0] <= 90 and -180 <= saved[1] <= 180):
                saved = None
    except Exception:
        saved = None
    if saved is not None:
        set_home(saved, "settings")
    elif demo:
        set_home(DEMO_HOME, "demo")
    else:
        set_home(None)
    return HOME_SOURCE


def frame_origin(lat=None, lon=None):
    """The origin of the shared local frame: HOME when set; otherwise a provisional origin latched
    on the first position seen, so the map can still draw contacts relative to each other. Callers
    must not present range/bearing from a provisional origin (check home_set())."""
    if HOME is not None:
        return HOME
    if _FRAME["origin"] is None and lat is not None and lon is not None:
        _FRAME["origin"] = (float(lat), float(lon))
    return _FRAME["origin"]


def to_xy(lat, lon, home=None):
    """(x east, y north) in nautical miles from home — the local frame for the map / PPI. Without
    a HOME this is relative to the provisional frame origin (see frame_origin)."""
    hlat, hlon = home or frame_origin(lat, lon)
    p1, p2 = math.radians(hlat), math.radians(lat)
    dl = math.radians(lon - hlon)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    d = 2 * _EARTH_NM * math.asin(min(1.0, math.sqrt(a)))
    ex = math.sin(dl) * math.cos(p2)
    ny = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    brg = math.atan2(ex, ny)
    return d * math.sin(brg), d * math.cos(brg)


def make_event(etype, source, payload, severity="info", ts=None, demo=False):
    assert etype in TYPES, "bad event type: %r" % etype
    assert severity in SEVERITIES, "bad severity: %r" % severity
    return {"type": etype, "source": source, "severity": severity,
            "ts": time.time() if ts is None else ts, "payload": dict(payload),
            "demo": bool(demo)}


# typed constructors — keep payload shapes consistent across publishers
def contact(source, cid, lat, lon, alt=None, kind="air", label=None, severity="live", demo=False,
            **extra):
    """A positioned emitter (aircraft/ship/APRS/drone/DF/balloon). Geo-native: carries lat/lon
    (+ alt/kind); consumers convert to their local frame with to_xy()."""
    p = {"id": cid, "lat": lat, "lon": lon, "alt": alt, "kind": kind, "label": label or cid}
    p.update(extra)
    return make_event("contact", source, p, severity, demo=demo)


def decode(source, proto, cid, summary, severity="info", demo=False, **extra):
    """A decoded message (ADS-B/AIS/POCSAG/…)."""
    p = {"proto": proto, "id": cid, "summary": summary}
    p.update(extra)
    return make_event("decode", source, p, severity, demo=demo)


def alert(source, text, severity="warn", demo=False, **extra):
    """Something to surface on the OPS alert strip (drone RID, open AP, MIL inbound, low batt)."""
    p = {"text": text}
    p.update(extra)
    return make_event("alert", source, p, severity, demo=demo)


class EventBus(QtCore.QObject):
    """A6: publish() stores a COPY (publishers cannot mutate what subscribers see), the retained
    log is bounded and resizable (set_retention), and the queued signal backlog is bounded: when
    more than `maxlen` events are still waiting for a stalled GUI thread, further CONTACT and
    DECODE events are kept in the log but not emitted, and `dropped()` says how many.
    ALERT events are never dropped (CL5-fix 8 / N5): a Tornado Warning published during a GUI
    stall under heavy contact traffic must still reach the AlertStore and the drawer. Alerts are
    rare and small, so delivering every one cannot grow the backlog without bound in practice."""
    published = QtCore.Signal(dict)         # emitted (queued) to the GUI thread for every event
    home_changed = QtCore.Signal()          # H5: HOME was set / cleared — re-centre, re-predict

    def __init__(self, maxlen=1000, parent=None):
        super().__init__(parent)
        self._log = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._pending = 0
        self._dropped = 0
        self._maxlen = maxlen
        self.published.connect(self._delivered, QtCore.Qt.QueuedConnection)

    def publish(self, event):
        ev = copy.deepcopy(event)
        with self._lock:
            self._log.append(ev)
            if self._pending >= self._maxlen and ev.get("type") != "alert":
                self._dropped += 1
                return copy.deepcopy(ev)
            self._pending += 1
        self.published.emit(ev)
        return copy.deepcopy(ev)                 # N13: the caller never aliases the log entry

    def _delivered(self, _ev):
        with self._lock:
            if self._pending > 0:
                self._pending -= 1

    def set_retention(self, maxlen):
        with self._lock:
            self._maxlen = int(maxlen)
            self._log = deque(self._log, maxlen=int(maxlen))

    def pending(self):
        with self._lock:
            return self._pending

    def dropped(self):
        with self._lock:
            return self._dropped

    def recent(self, n=50, etype=None, source=None):
        with self._lock:
            items = list(self._log)
        if etype is not None:
            items = [e for e in items if e["type"] == etype]
        if source is not None:
            items = [e for e in items if e["source"] == source]
        return items[-n:]

    def clear(self):
        with self._lock:
            self._log.clear()
            self._pending = 0
            self._dropped = 0


# module-level singleton — one bus for the process
bus = EventBus()
