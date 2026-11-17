"""Gate-catalog tests for the full-toolkit scope (owner decision 2026-11-17, "all tools in scope").

Each newly catalogued active tool must be (a) in its module's ALLOWED_PROGRAMS, (b) accepted by the
engagement program allowlist and never a shell/interpreter, and (c) REFUSED by the gate with no
open engagement and with an out-of-scope target, while a correctly scoped engagement yields a
single-use ticket. This proves the catalog is real and the gate holds for every entry.
"""
import pytest

import engagement as E
import netpent as NET
import blepent as BLE
import proxmark as PM
import rfemit


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


# ---- the allowlist wiring is correct for every catalogued program ------------------------------
@pytest.mark.parametrize("mod", [NET, BLE, PM])
def test_catalog_programs_are_allowed_and_never_shells(mod):
    for prog in mod.CATALOG_PROGRAMS:
        assert prog in mod.ALLOWED_PROGRAMS
        assert prog not in E.NEVER_PROGRAMS
        ok, _why = E.program_allowed([prog, "x"], mod.ALLOWED_PROGRAMS, mod.__name__)
        assert ok, "%s should be an allowed program for %s" % (prog, mod.__name__)


# ---- RECON network + web catalog (netpent) -----------------------------------------------------
@pytest.mark.parametrize("tool", sorted(NET.CATALOG_PROGRAMS))
def test_net_catalog_refused_without_engagement(tool):
    ok, why, ticket = NET.catalog_prepare(tool, "203.0.113.5")
    assert ok is False and ticket is None and "engagement" in why.lower()


@pytest.mark.parametrize("tool", sorted(NET.CATALOG_PROGRAMS))
def test_net_catalog_refused_out_of_scope(tool):
    E.start("lab audit", "self-owned", ["192.168.1.0/24"], "KD0ABC")
    ok, _why, ticket = NET.catalog_prepare(tool, "203.0.113.5")   # not in the /24
    assert ok is False and ticket is None


@pytest.mark.parametrize("tool", sorted(NET.CATALOG_PROGRAMS))
def test_net_catalog_in_scope_builds_gated_ticket(tool):
    E.start("lab audit", "self-owned", ["192.168.1.0/24"], "KD0ABC")
    ok, why, ticket = NET.catalog_prepare(tool, "192.168.1.10")
    if rfemit.classify(argv=[tool, "192.168.1.10"]) is not None:
        # an RF emitter (e.g. bettercap) is double-gated: in scope, but refused by txguard while
        # TX is locked (strict default) — the extra gate holds
        assert ok is False and ticket is None and ("tx" in why.lower() or "rf" in why.lower())
    else:
        assert ok and ticket is not None
        assert ticket.argv[0] == tool and "192.168.1.10" in ticket.argv


def test_net_catalog_rejects_unknown_tool():
    E.start("lab audit", "self-owned", ["192.168.1.0/24"], "KD0ABC")
    assert NET.catalog_prepare("rm", "192.168.1.10")[0] is False


def test_net_catalog_rejects_option_like_target():
    E.start("lab audit", "self-owned", ["192.168.1.0/24"], "KD0ABC")
    assert NET.catalog_prepare("nikto", "--config=/etc/x")[0] is False


# ---- BLE catalog (blepent) ---------------------------------------------------------------------
@pytest.mark.parametrize("tool", sorted(BLE.CATALOG_PROGRAMS))
def test_ble_catalog_refused_without_engagement(tool):
    ok, why, ticket = BLE.catalog_prepare(tool, "AA:BB:CC:DD:EE:FF")
    assert ok is False and ticket is None and "engagement" in why.lower()


@pytest.mark.parametrize("tool", sorted(BLE.CATALOG_PROGRAMS))
def test_ble_catalog_refused_out_of_scope(tool):
    E.start("ble audit", "self-owned", ["AA:BB:CC:DD:EE:FF"], "KD0ABC")
    ok, _why, ticket = BLE.catalog_prepare(tool, "11:22:33:44:55:66")   # different MAC
    assert ok is False and ticket is None


@pytest.mark.parametrize("tool", sorted(BLE.CATALOG_PROGRAMS))
def test_ble_catalog_in_scope_is_gated(tool):
    E.start("ble audit", "self-owned", ["AA:BB:CC:DD:EE:FF"], "KD0ABC")
    ok, why, ticket = BLE.catalog_prepare(tool, "AA:BB:CC:DD:EE:FF")
    if rfemit.classify(argv=[tool, "AA:BB:CC:DD:EE:FF"]) is not None:
        # btlejack radiates BLE: in scope, but txguard-gated while TX is locked
        assert ok is False and ticket is None and ("tx" in why.lower() or "rf" in why.lower())
    else:
        assert ok and ticket is not None and ticket.argv[0] == tool


# ---- RFID catalog (proxmark/libnfc) — label-only -----------------------------------------------
@pytest.mark.parametrize("tool", sorted(PM.CATALOG_PROGRAMS))
def test_rfid_catalog_refused_without_engagement(tool):
    ok, why, ticket = PM.catalog_prepare(tool, "BADGE-7")
    assert ok is False and ticket is None and "engagement" in why.lower()


@pytest.mark.parametrize("tool", sorted(PM.CATALOG_PROGRAMS))
def test_rfid_catalog_refused_out_of_scope(tool):
    E.start("rfid audit", "self-owned", ["BADGE-7"], "KD0ABC")
    ok, _why, ticket = PM.catalog_prepare(tool, "DOOR-9")   # label not in scope
    assert ok is False and ticket is None


@pytest.mark.parametrize("tool", sorted(PM.CATALOG_PROGRAMS))
def test_rfid_catalog_in_scope_builds_label_only_ticket(tool):
    E.start("rfid audit", "self-owned", ["BADGE-7"], "KD0ABC")
    ok, _why, ticket = PM.catalog_prepare(tool, "BADGE-7")
    assert ok and ticket is not None and ticket.argv[0] == tool
    assert ticket.binding == "label-only"
