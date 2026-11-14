"""PALISADE event bus — the one typed stream every callsign publishes to.

One small, typed contract so OPS (now) and sitrep / fusion / record+replay (later) all consume
the same thing without a refactor:

    event = {
        "type":     "contact" | "decode" | "alert",
        "source":   callsign str, e.g. "ATLAS", "BABEL", "RECON"
        "severity": "info" | "live" | "warn" | "alert",
        "ts":       float epoch seconds,
        "payload":  dict, type-specific (see make_* helpers),
    }

Publishing is thread-safe: a worker QThread calls bus.publish(...), which appends to a bounded
log (under a lock) and emits a Qt signal that Qt delivers on the GUI thread (queued connection),
so subscribers touch widgets safely. Nothing here renders — consumers decide how to show it.
"""
import threading
import time
from collections import deque

from PySide6 import QtCore

TYPES = ("contact", "decode", "alert")
SEVERITIES = ("info", "live", "warn", "alert")


def make_event(etype, source, payload, severity="info", ts=None):
    assert etype in TYPES, "bad event type: %r" % etype
    assert severity in SEVERITIES, "bad severity: %r" % severity
    return {"type": etype, "source": source, "severity": severity,
            "ts": time.time() if ts is None else ts, "payload": dict(payload)}


# typed constructors — keep payload shapes consistent across publishers
def contact(source, cid, x_nm, y_nm, label=None, severity="live", **extra):
    """A positioned emitter (aircraft/ship/APRS/drone/DF). x/y in nm from home."""
    p = {"id": cid, "x": x_nm, "y": y_nm, "label": label or cid}
    p.update(extra)
    return make_event("contact", source, p, severity)


def decode(source, proto, cid, summary, severity="info", **extra):
    """A decoded message (ADS-B/AIS/POCSAG/…)."""
    p = {"proto": proto, "id": cid, "summary": summary}
    p.update(extra)
    return make_event("decode", source, p, severity)


def alert(source, text, severity="warn", **extra):
    """Something to surface on the OPS alert strip (drone RID, open AP, MIL inbound, low batt)."""
    p = {"text": text}
    p.update(extra)
    return make_event("alert", source, p, severity)


class EventBus(QtCore.QObject):
    published = QtCore.Signal(dict)         # emitted (queued) to the GUI thread for every event

    def __init__(self, maxlen=1000, parent=None):
        super().__init__(parent)
        self._log = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def publish(self, event):
        with self._lock:
            self._log.append(event)
        self.published.emit(event)
        return event

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


# module-level singleton — one bus for the process
bus = EventBus()
