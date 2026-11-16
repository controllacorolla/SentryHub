"""Tests for the engagement authorization gate."""
import pytest

import engagement as E


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_action_denied_without_engagement():
    ok, why = E.authorize_action("rfid:clone", "BADGE-1")
    assert not ok and "no active engagement" in why.lower()


def test_start_requires_scope_and_authorization():
    assert E.start("job", "", ["X"], "KD0ABC")[0] is False          # no authorization ref
    assert E.start("job", "ROE-1", [], "KD0ABC")[0] is False         # no scope
    assert E.start("", "ROE-1", ["X"], "KD0ABC")[0] is False         # no name
    assert E.start("job", "ROE-1", ["BADGE-*"], "KD0ABC")[0] is False   # glob: refused (CL2/G4)
    ok, why = E.start("job", "ROE-1", ["BADGE-7"], "KD0ABC")
    assert ok and E.is_active()


def test_in_scope_exact_and_oui():
    E.start("job", "ROE-1", ["AA:BB:CC:*", "BADGE-7"], "KD0ABC")      # a MAC OUI is the one wildcard
    assert E.in_scope("AA:BB:CC:11:22:33") and E.in_scope("BADGE-7")
    assert not E.in_scope("DD:EE:FF:00:00:00") and not E.in_scope("BADGE-8")


def test_authorize_in_and_out_of_scope():
    E.start("job", "ROE-1", ["BADGE-9"], "KD0ABC")
    ok, why = E.authorize_action("rfid:clone", "BADGE-9")
    assert ok and "authorized" in why
    ok2, why2 = E.authorize_action("rfid:clone", "SERVER-ROOM")
    assert not ok2 and "not in the engagement scope" in why2


def test_action_logged_to_evidence_chain():
    """CL3: the ONE durable chain (chain.Chain) records the authorization; a legacy per-page
    EvidenceChain passed as evidence_chain= is accepted for API compatibility but no longer
    consulted (audit G7: one chain, not one per page)."""
    import chain
    import evidence
    legacy = evidence.EvidenceChain()
    E.start("job", "ROE-1", ["BADGE-1"], "KD0ABC")
    assert E.authorize_action("rfid:clone", "BADGE-1", evidence_chain=legacy)[0]
    assert legacy.records == []
    info = E.chain_info()
    ch = chain.Chain.open(info["id"])
    auth = [r for r in ch.records if r["event"] == "authorize"]
    assert len(auth) == 1 and auth[0]["target"] == "BADGE-1" and ch.verify()[0] is True
    assert len(E.actions()) == 1


def test_end_clears():
    E.start("job", "ROE-1", ["X"], "KD0ABC")
    assert E.end() == "job" and not E.is_active()
