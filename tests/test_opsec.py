"""OPSEC Mode — the one-button RF-dark posture, tested at the gate (not the UI).

Proves the load-bearing promise: while OPSEC is armed, every transmit / active path in the suite
refuses with an honest reason — exercised through each module's REAL gate function, not a mock —
and while disarmed the gates behave exactly as before. Also covers the evidence-chain posture log
and the emission watcher. Pure logic; no Qt, no radio.
"""
import os
import sys

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

import pytest

import opsec
import txguard
import engagement
import evidence


@pytest.fixture(autouse=True)
def _clean():
    """Isolate posture state so an armed test never leaks into another (or into the txguard /
    engagement suites that share this process)."""
    opsec.reset()
    txguard.reset_session()
    engagement.reset()
    yield
    opsec.reset()
    txguard.reset_session()
    engagement.reset()


def _open_engagement():
    ok, _ = engagement.start("audit", "ROE-7", ["7E8", "aa:bb:cc:dd:ee:ff", "192.168.1.0/24",
                                                "AA:BB:CC:*"], "KD0ABC")
    assert ok


# --------------------------------------------------------------------- RF key-up (txguard)
def test_disarmed_rf_tx_passes_as_before():
    txguard.arm(True)
    txguard.unlock_session(True)
    ok, why, pwr = txguard.authorize("replay", 433_920_000, settings={"tx_enabled": True})
    assert ok, why
    okd, _ = txguard.decide(915_000_000, settings={"tx_enabled": True})
    assert okd
    oka, _ = txguard.allowed_tx()
    assert oka


def test_armed_blocks_every_rf_path_with_honest_reason():
    txguard.arm(True)
    txguard.unlock_session(True)
    opsec.arm(operator="KD0ABC")
    for ok, reason in (
        txguard.decide(433_920_000, settings={"tx_enabled": True, "callsign": "KD0ABC"}),
        txguard.allowed_tx(),
        txguard.decide(service="lora", settings={"tx_enabled": True}),       # LoRa too
    ):
        assert ok is False and "OPSEC" in reason
    ok, reason, pwr = txguard.authorize("replay", 433_920_000, settings={"tx_enabled": True})
    assert ok is False and "OPSEC" in reason and pwr == 0


def test_arming_opsec_forces_tx_kill_switch_off():
    txguard.arm(True)
    txguard.unlock_session(True)
    assert txguard.is_armed() and txguard.session_unlocked()
    opsec.arm()
    assert not txguard.is_armed(), "arming OPSEC must drop the TX kill switch"
    assert not txguard.session_unlocked()


# --------------------------------------------------------------- active target actions (engagement)
def test_disarmed_active_actions_pass_when_in_scope():
    _open_engagement()
    ok, _ = engagement.authorize_action("canbus:tx:0x7E8@can0", "7E8")
    assert ok


@pytest.mark.parametrize("action,target", [
    ("canbus:tx:0x7E8@can0", "7E8"),
    ("proxmark:lf_hid_clone", "aa:bb:cc:dd:ee:ff"),
    ("usbhid:inject", "aa:bb:cc:dd:ee:ff"),
    ("wifi:deauth", "AA:BB:CC:11:22:33"),
    ("ble:write", "aa:bb:cc:dd:ee:ff"),
    ("net:portscan", "192.168.1.0/24"),
])
def test_armed_blocks_every_active_action(action, target):
    _open_engagement()
    opsec.arm()
    ok, reason = engagement.authorize_action(action, target)
    assert ok is False and "OPSEC" in reason


def test_offline_passaudit_not_blocked_by_opsec():
    """OPSEC is about emission; a purely offline crack of a capture you already hold emits nothing,
    so RF-dark must leave it runnable (honest, not over-broad)."""
    _open_engagement()
    engagement._ENG["scope"].append("aa:bb:cc:dd:ee:ff")
    opsec.arm()
    ok, reason = engagement.authorize_action("passaudit:hashcat", "aa:bb:cc:dd:ee:ff")
    assert ok is True, reason


# ------------------------------------------------- the brief's named modules, via their real gates
def test_named_modules_refuse_through_their_own_prepare_functions():
    import bench
    import replay
    import canbus
    import proxmark
    import usbhid
    import wifipent
    import blepent
    _open_engagement()
    engagement._ENG["scope"].append("de:ad:be:ef:00:01")
    opsec.arm()

    # RF TX modules
    called = {"ran": False}
    ok, msg = bench.transmit({"tx_enabled": True, "bench_conducted_ack": True,
                              "iq_file": "/tmp/x.iq", "freq_hz": 915_000_000},
                             run=lambda argv: called.__setitem__("ran", True))
    assert ok is False and "OPSEC" in msg
    assert called["ran"] is False, "a blocked transmit must never spawn the transmitter"

    ok, reason, argv = replay.prepare_replay("c.iq", 433_920_000, 2_000_000, confirmed=True)
    assert ok is False and "OPSEC" in reason and argv is None

    # active-TX modules (engagement-gated)
    for ok, reason, argv in (
        canbus.prepare_send("can0", 0x7E8, b"\x01", "7E8"),
        proxmark.prepare("lf_hid_clone", target="de:ad:be:ef:00:01", id="2004"),
        usbhid.prepare("STRING hi", "de:ad:be:ef:00:01"),
        wifipent.prepare("deauth", "AA:BB:CC:11:22:33"),
        blepent.prepare("write", "de:ad:be:ef:00:01", handle=1, value="01"),
    ):
        assert ok is False and "OPSEC" in reason and argv is None


# --------------------------------------------------------------------- evidence chain (engagement)
def test_toggle_logged_to_evidence_chain_via_engagement():
    chain = evidence.EvidenceChain()
    opsec.set_evidence_chain(chain)
    opsec.arm(operator="KD0ABC")
    opsec.disarm(operator="KD0ABC")
    names = [r["name"] for r in chain.records]
    assert "opsec:armed" in names and "opsec:disarmed" in names
    ok, bad = chain.verify()
    assert ok, "posture log must leave the chain intact (bad seq %r)" % bad
    # recorded to engagement's non-action event trail — NOT the action/target trail actions()
    assert any(e.get("event") == "opsec:armed" for e in engagement.events())
    assert engagement.actions() == [], "posture events must not pollute the authorized-action trail"


# --------------------------------------------------------------------- emission watcher
def test_emission_while_armed_warns_on_bus():
    seen = []

    class Bus:
        def publish(self, ev):
            seen.append(ev)

    opsec.set_bus(Bus())
    opsec.arm()
    seen.clear()                       # drop the arm 'info' alert; want only the emission warning
    opsec.note_activity("rogue-tx", "HackRF keyed at 915 MHz", kind="tx")
    warns = [e for e in seen if e["severity"] == "warn"]
    assert warns and e_src(warns[0]) == "OPSEC"
    assert "rogue-tx" in warns[0]["payload"]["text"]


def test_no_warning_when_disarmed():
    seen = []

    class Bus:
        def publish(self, ev):
            seen.append(ev)

    opsec.set_bus(Bus())
    opsec.note_activity("expected-tx", "authorized burst", kind="tx")   # disarmed: no alarm
    assert not [e for e in seen if e["severity"] == "warn"]


def test_poll_detects_tx_gate_left_live():
    seen = []

    class Bus:
        def publish(self, ev):
            seen.append(ev)

    opsec.set_bus(Bus())
    opsec.arm()
    txguard.arm(True)                  # re-arm TX behind OPSEC's back — an observable contradiction
    anomalies = opsec.poll()
    assert any(a["kind"] == "txguard-live" for a in anomalies)
    assert any(e["severity"] == "warn" for e in seen)


def test_poll_silent_when_consistent():
    opsec.arm()
    assert opsec.poll() == [], "arming forced TX off, so a fresh poll finds nothing"


# --------------------------------------------------------------------- registry
def test_posture_events_do_not_pollute_the_action_trail():
    """Regression for the RECON crash: record_evidence must keep posture events OUT of actions(),
    which consumers (recon._render_actions) index as a['action']/a['target']."""
    _open_engagement()
    engagement.authorize_action("canbus:tx:0x7E8@can0", "7E8")        # one real authorized action
    opsec.set_evidence_chain(evidence.EvidenceChain())
    opsec.arm()
    opsec.disarm()                                                     # two posture events
    trail = engagement.actions()
    assert len(trail) == 1, "only authorized actions belong in the action trail"
    for a in trail:
        assert "action" in a and "target" in a, "actions() must index cleanly (no KeyError in RECON)"
    assert len(engagement.events()) == 2, "posture events live in events(), not actions()"


def test_modules_self_register_with_their_own_capability_string():
    """Importing a TX module must (re)register it with ITS OWN desc — which differs from opsec's
    seed ('…-gated' vs '(…)') — so this fails if a module's register() call is deleted, rather than
    passing on the seed alone."""
    import importlib
    for mod in ("bench", "replay", "canbus", "proxmark", "usbhid", "wifipent", "blepent"):
        importlib.import_module(mod)            # import for the register() side-effect
    reg = opsec.registry()
    expected = {
        "BENCH": "conducted HackRF key-up (txguard-gated)",
        "REPLAY": "IQ replay on ISM bands (txguard-gated)",
        "CANBUS": "CAN frame injection — engagement-gated",
        "PROXMARK": "RFID write / clone / sim — engagement-gated",
        "USBHID": "USB-HID keystroke injection — engagement-gated",
        "WIFIPENT": "Wi-Fi capture / targeted deauth — engagement-gated",
        "BLEPENT": "BLE GATT connect / read / write — engagement-gated",
    }
    for name, desc in expected.items():
        assert name in reg and reg[name]["desc"] == desc, \
            "%s must self-register at import (got %r)" % (name, reg.get(name))
    # the seed also covers central-gated paths that don't self-register here
    for name in ("MESH", "NETPENT", "RADIO", "DIGIMODES"):
        assert name in reg, "%s should be a seeded emitter" % name


def e_src(ev):
    return ev.get("source")
