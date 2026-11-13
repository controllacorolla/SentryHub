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
    assert E.start("job", "", ["X"], "op")[0] is False          # no authorization ref
    assert E.start("job", "ROE-1", [], "op")[0] is False         # no scope
    assert E.start("", "ROE-1", ["X"], "op")[0] is False         # no name
    ok, why = E.start("job", "ROE-1", ["BADGE-*"], "KD0ABC")
    assert ok and E.is_active()


def test_in_scope_exact_and_wildcard():
    E.start("job", "ROE-1", ["AA:BB:CC:*", "BADGE-7"], "op")
    assert E.in_scope("AA:BB:CC:11:22:33") and E.in_scope("BADGE-7")
    assert not E.in_scope("DD:EE:FF:00:00:00") and not E.in_scope("BADGE-8")


def test_authorize_in_and_out_of_scope():
    E.start("job", "ROE-1", ["BADGE-*"], "op")
    ok, why = E.authorize_action("rfid:clone", "BADGE-9")
    assert ok and "authorized" in why
    ok2, why2 = E.authorize_action("rfid:clone", "SERVER-ROOM")
    assert not ok2 and "not in the engagement scope" in why2


def test_action_logged_to_evidence_chain():
    import evidence
    ch = evidence.EvidenceChain()
    E.start("job", "ROE-1", ["BADGE-*"], "op")
    E.authorize_action("rfid:clone", "BADGE-1", evidence_chain=ch)
    assert len(ch.records) == 1 and ch.verify()[0] is True
    assert ch.records[0]["meta"]["target"] == "BADGE-1"
    assert len(E.actions()) == 1


def test_end_clears():
    E.start("job", "ROE-1", ["X"], "op")
    assert E.end() == "job" and not E.is_active()
