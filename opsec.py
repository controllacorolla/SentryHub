#!/usr/bin/env python3
"""opsec.py — one-button RF-dark posture: the single source of truth for "are we emitting?".

PALISADE is a transmit-capable suite. OPSEC Mode is the operator's panic switch to a known-silent
posture: arm it and every transmit path in the suite must refuse — RF key-up (txguard), active
target actions that emit (CAN frames, RFID write/clone, USB-HID inject, Wi-Fi/BLE active ops,
network scans — engagement), LoRa/mesh TX. From any page the operator confirms at a glance that
nothing is leaving the device.

Enforcement is at the GATE, never only in the UI. The two authorization choke points every TX /
active path already funnels through consult this module:

  * txguard.decide() / txguard.authorize()  -> all RF key-up            (checks is_armed())
  * engagement.authorize_action()           -> all active target actions (checks guard_action())

So arming OPSEC makes transmitting impossible for every current module AND any future TX path that
goes through those gates — not a per-call-site flag a new tool can forget. The one active action
OPSEC does NOT block is pure offline analysis (passaudit cracking a handshake you already hold):
that emits nothing and touches no target, so an "RF-dark" posture leaves it alone.

Honesty: this module blocks and reports; it does not pretend to sense RF it cannot see. The watcher
warns only on what it can actually observe — an emission reported through note_activity(), or a TX
gate left live while OPSEC is engaged (poll()) — never on invented signals.

Pure module: standard library only, no Qt / radio / network / settings I/O. State is process-global
and in-memory (a posture is chosen deliberately each session, never persisted). The event bus and
evidence chain are *injected* (set_bus / set_evidence_chain) so the module stays import-light and
fully unit-testable without the GUI.

Scope: the posture is process-local. Every callsign is an in-process Qt gate caller, so all of them
honour it; if a not-yet-migrated tool is ever launched as a separate subprocess (shell.TK_HOSTS,
currently empty), OPSEC would need to be propagated to that process — it is not, today.
"""
import threading
import time

# --- posture state (in-memory, process-global; never persisted) ----------------------------
_LOCK = threading.RLock()
_STATE = {"armed": False, "since": None, "operator": None}

# the one reason string every gate reports when it refuses because OPSEC is armed
BLOCK_REASON = "TX BLOCKED BY OPSEC — RF-dark posture armed"

# --- registry of TX-capable modules (the watcher's "what could emit" list) -----------------
# Seeded with the full known TX / active surface so the watcher is complete even if a module was
# never imported; each TX module also register()s itself at import (declares its own capability).
_REGISTRY = {}

DEFAULT_EMITTERS = [
    ("BENCH", "rf-tx", "conducted HackRF key-up (txguard)"),
    ("REPLAY", "rf-tx", "IQ replay on ISM (txguard)"),
    ("DIGIMODES", "rf-tx", "ham digital-mode TX (txguard)"),
    ("RADIO", "rf-tx", "generic TX controller (txguard)"),
    ("MESH", "rf-tx", "LoRa / Meshtastic TX (txguard)"),
    ("CANBUS", "active-tx", "CAN frame injection (engagement)"),
    ("PROXMARK", "active-tx", "RFID write / clone / sim (engagement)"),
    ("USBHID", "active-tx", "USB-HID keystroke injection (engagement)"),
    ("WIFIPENT", "active-tx", "Wi-Fi capture / targeted deauth (engagement)"),
    ("BLEPENT", "active-tx", "BLE GATT connect / write (engagement)"),
    ("ZWAVE", "active-tx", "Z-Wave inject (engagement)"),
    ("ZIGBEE", "active-tx", "Zigbee inject (engagement)"),
    ("FLIPPER", "active-tx", "Flipper sub-GHz / IR / RFID TX (engagement)"),
    ("BUSLAB", "active-tx", "SPI flash / JTAG write (engagement)"),
    ("NETPENT", "network", "active network scan — outbound (engagement)"),
]

# engagement action-prefixes OPSEC does NOT block: pure offline analysis (no emission, no target
# contact). passaudit cracks a capture you already hold, so RF-dark leaves it runnable.
_OFFLINE_PREFIXES = ("passaudit",)

# --- injected sinks (duck-typed; default None keeps the module standalone) ------------------
_bus = None               # anything with .publish(event_dict); OPS consumes it
_evidence_chain = None    # an evidence.EvidenceChain (anything with .add(name, data=, meta=))
_subscribers = []         # callables(state_dict) for immediate UI (the TopBar chip)

# --- emission observations (honest watcher state) ------------------------------------------
_emissions = []           # recent reported/observed emissions (for the registry view / tests)


# ---------------------------------------------------------------- registration
def register(name, kind="active-tx", desc=""):
    """A TX-capable module declares itself so the watcher knows what could emit. Idempotent."""
    with _LOCK:
        _REGISTRY[str(name)] = {"kind": kind, "desc": desc}


def registry():
    with _LOCK:
        return {k: dict(v) for k, v in _REGISTRY.items()}


for _n, _k, _d in DEFAULT_EMITTERS:         # seed the known surface at import
    register(_n, _k, _d)


# ---------------------------------------------------------------- injected sinks
def set_bus(bus):
    """Inject the event bus OPSEC publishes arm/disarm + watcher alerts to (OPS consumes it)."""
    global _bus
    _bus = bus


def set_evidence_chain(chain):
    """Inject the tamper-evident chain posture changes are logged to (via engagement)."""
    global _evidence_chain
    _evidence_chain = chain


def subscribe(fn):
    """Register a state-change listener (e.g. the TopBar chip). Called fn(state_dict) on toggle."""
    if fn not in _subscribers:
        _subscribers.append(fn)


def unsubscribe(fn):
    try:
        _subscribers.remove(fn)
    except ValueError:
        pass


# ---------------------------------------------------------------- posture queries
def is_armed():
    return _STATE["armed"]


def status():
    with _LOCK:
        return dict(_STATE)


# ---------------------------------------------------------------- the gate consults
def guard(source=None):
    """(ok, reason) for an RF key-up path. ok is False whenever OPSEC is armed."""
    if _STATE["armed"]:
        return False, BLOCK_REASON
    return True, ""


def blocks_action(action):
    """Does the current posture block this engagement action? Armed OPSEC blocks every active,
    target-touching action EXCEPT pure offline analysis (passaudit)."""
    if not _STATE["armed"]:
        return False
    domain = str(action or "").split(":", 1)[0].strip().lower()
    return domain not in _OFFLINE_PREFIXES


def guard_action(action):
    """(blocked, reason) for an engagement action under the current posture."""
    if blocks_action(action):
        return True, BLOCK_REASON
    return False, ""


# ---------------------------------------------------------------- arm / disarm
def arm(operator=None):
    """Enter RF-dark posture. Idempotent. Forces the TX kill switch off, logs to the evidence
    chain (via engagement), and announces on the event bus + to UI subscribers."""
    return _set(True, operator)


def disarm(operator=None):
    """Leave RF-dark posture. Does NOT re-arm TX — the operator re-arms transmit deliberately."""
    return _set(False, operator)


def set_armed(on, operator=None):
    return _set(bool(on), operator)


def _set(on, operator):
    with _LOCK:
        if _STATE["armed"] == on:
            if operator:
                _STATE["operator"] = operator       # refresh operator, don't re-announce
            return dict(_STATE)
        _STATE["armed"] = on
        _STATE["since"] = time.time() if on else None
        _STATE["operator"] = operator
        st = dict(_STATE)
    if on:
        _force_tx_off()                             # physically disengage the TX kill switch
    _log_posture(st)
    who = " (operator %s)" % operator if operator else ""
    if on:
        text = "OPSEC ARMED — RF-dark; every TX path refused%s" % who
    else:
        text = "OPSEC OFF — TX paths return to their own gates%s" % who
    _publish(text, "info", armed=on, operator=operator)
    _notify(st)
    return st


def _force_tx_off():
    try:
        import txguard
        txguard.arm(False)      # drop armed + session unlock; re-arming TX is then deliberate
    except Exception:
        pass


def _log_posture(st):
    try:
        import engagement
        engagement.record_evidence(
            "opsec:" + ("armed" if st["armed"] else "disarmed"),
            meta={"armed": st["armed"], "operator": st.get("operator"), "since": st.get("since")},
            evidence_chain=_evidence_chain)
    except Exception:
        pass


# ---------------------------------------------------------------- event bus + subscribers
def _alert(text, severity, **extra):
    payload = {"text": text}
    payload.update(extra)
    return {"type": "alert", "source": "OPSEC", "severity": severity,
            "ts": time.time(), "payload": payload}


def _publish(text, severity, **extra):
    bus = _bus
    if bus is None:
        return
    try:
        bus.publish(_alert(text, severity, **extra))
    except Exception:
        pass


def _notify(state):
    for fn in list(_subscribers):
        try:
            fn(dict(state))
        except Exception:
            pass


# ---------------------------------------------------------------- emission watcher
def note_activity(source, detail="", kind="tx"):
    """Report an actual emission / outbound event from instrumented code. While OPSEC is armed this
    is UNEXPECTED (every gate should have refused) and raises a warning on the bus; while disarmed
    it is recorded as expected and no alarm is raised. Honest — a caller reports real activity, the
    module infers nothing."""
    rec = {"ts": time.time(), "source": source, "detail": detail, "kind": kind,
           "armed": _STATE["armed"]}
    with _LOCK:
        _emissions.append(rec)
        del _emissions[:-200]
    if _STATE["armed"]:
        _publish("Unexpected %s from %s while RF-dark: %s" % (kind, source, detail or "activity"),
                 "warn", emitter=source, kind=kind, detail=detail)
    return rec


def poll():
    """Periodic consistency sweep the watcher thread calls. Returns a list of anomaly dicts and
    publishes each as a warning. Only observable contradictions are reported — never invented RF."""
    anomalies = []
    if not _STATE["armed"]:
        return anomalies
    try:
        import txguard
        if txguard.is_armed():          # a TX gate left live while we claim RF-dark is observable
            anomalies.append({"kind": "txguard-live",
                              "detail": "TX kill switch is armed while OPSEC is engaged"})
    except Exception:
        pass
    for a in anomalies:
        _publish("OPSEC watch: " + a["detail"], "warn", **a)
    return anomalies


def recent_emissions(n=50):
    with _LOCK:
        return list(_emissions[-n:])


# ---------------------------------------------------------------- lifecycle (startup / tests)
def reset():
    """Drop posture + injected sinks + observations + subscribers. For startup and test isolation;
    the capability registry (what could emit) is static and is preserved."""
    global _bus, _evidence_chain
    with _LOCK:
        _STATE.update(armed=False, since=None, operator=None)
        _emissions.clear()
    _bus = None
    _evidence_chain = None
    del _subscribers[:]


if __name__ == "__main__":
    print("OPSEC posture module. Armed:", is_armed())
    print("Registered emitters:")
    for name, meta in sorted(registry().items()):
        print("  %-10s %-10s %s" % (name, meta["kind"], meta["desc"]))
