"""RA-CL4 PoCs, gate/evidence side (fix/cl4-honest-state @ 461f5e2): END orphan kills with real
process groups (N20, N22, N23, N24), the executor's own group kill (N20), chain crash recovery
(N13), malformed input (N12) and snapshot rollback (R1).
FIXED_* / OK_* = the fix holds (test passes). DEFECT_* = the defect reproduces (test passes when it does).
Run: SUITE=<worktree> pytest -q poc_ra_cl4_gates.py   (Linux; reads /proc)"""
import os
import signal
import subprocess
import sys
import time

import pytest

SUITE_DIR = os.environ["SUITE"]
sys.path.insert(0, SUITE_DIR)
sys.path.insert(0, os.path.join(SUITE_DIR, "plan", "briefs", "RA-CL3d-poc"))

import chain  # noqa: E402
import engagement as E  # noqa: E402
import gatestate  # noqa: E402
import txguard as G  # noqa: E402
import poc_ra_cl3d as D  # noqa: E402  (helpers only: _start, _forge_spawn, _Spy, _orphan, ...)

OP = D.OP
ALLOWED_PROGRAMS = D.ALLOWED_PROGRAMS
IGN = D.IGN


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    import suite
    import executor
    monkeypatch.setattr(suite, "DATA", str(tmp_path / "data"))
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    monkeypatch.delenv("PALISADE_GATE_STATE", raising=False)
    monkeypatch.setattr(E, "_profile_operator", lambda: OP, raising=False)
    G.reset_session(); E.reset(); executor.reset(); chain.reset_for_tests()
    yield
    executor.kill_all("teardown")
    executor.reset(); G.reset_session(); E.reset(); chain.reset_for_tests()


def _end_recs(info):
    return [r for r in D._recs(info["path"]) if r.get("by") == "end"]


def _group_cmd():
    """leader exits on SIGTERM (exec sleep); a helper in the same group ignores SIGTERM."""
    return "%s -c '%s' & exec sleep 30" % (sys.executable, IGN)


# ---------------------------------------------------------------- N20 (Medium in RA-CL3d)
def test_FIXED_n20_member_ignoring_sigterm_is_sigkilled_and_row_is_killed(tmp_path):
    info = D._start()
    pub, env = D._bound_env(tmp_path)
    orphan = None
    try:
        orphan = D._orphan(env, "10.0.0.81", repr(["sh", "-c", _group_cmd()]))
        time.sleep(0.4)
        members = D._group_members(orphan)
        assert orphan in members and len(members) == 2, members
        helper = [m for m in members if m != orphan][0]
        t0 = time.monotonic()
        E.end()
        dt = time.monotonic() - t0
        time.sleep(0.3)
        ek = _end_recs(info)
        print("END %.2fs records %s" % (dt, [(r["event"], r.get("reason")) for r in ek]))
        assert not D._alive(helper) and not D._alive(orphan)
        assert [(r["event"], r["reason"], r.get("verified_gone")) for r in ek] == [
            ("kill", "orphan at END", True)]
        assert [r["state"] for r in D._states_at_close(info)] == ["KILLED"]
    finally:
        pub.close()
        if orphan and D._group_members(orphan):
            os.killpg(orphan, signal.SIGKILL)


def test_FIXED_n20_member_surviving_sigkill_is_unconfirmed_never_killed(tmp_path, monkeypatch):
    """Real group: the leader exits on SIGTERM, the helper ignores SIGTERM, and SIGKILL to the group
    is swallowed (simulated D-state: the only way a process 'survives' SIGKILL in a test)."""
    info = D._start()
    pub, env = D._bound_env(tmp_path)
    orphan = None
    try:
        orphan = D._orphan(env, "10.0.0.82", repr(["sh", "-c", _group_cmd()]))
        time.sleep(0.4)
        helper = [m for m in D._group_members(orphan) if m != orphan][0]
        real_killpg, real_kill = os.killpg, os.kill
        sent = []

        def killpg(pg, sig):
            if sig == signal.SIGKILL and pg == orphan:
                sent.append(("killpg", pg, sig))
                return None                         # swallowed
            return real_killpg(pg, sig)

        def kill(pid, sig):
            if sig == signal.SIGKILL and pid in (orphan, helper):
                sent.append(("kill", pid, sig))
                return None
            return real_kill(pid, sig)
        os.killpg, os.kill = killpg, kill
        try:
            E.end()
        finally:
            os.killpg, os.kill = real_killpg, real_kill
        assert D._alive(helper)
        ek = _end_recs(info)
        print("END records", [(r["event"], r.get("reason")) for r in ek], "SIGKILLs", sent)
        assert [r["event"] for r in ek] == ["unconfirmed"]
        assert "survived" in ek[0]["reason"]
        assert [r["state"] for r in D._states_at_close(info)] == ["UNCONFIRMED"]
    finally:
        pub.close()
        if orphan and D._group_members(orphan):
            os.killpg(orphan, signal.SIGKILL)


def test_FIXED_n20_hub_owned_kill_member_ignoring_sigterm_is_killed():
    import executor
    import netpent
    D._start()
    ok, why, t = netpent.prepare("portscan", "10.0.0.83")
    assert ok, why
    h = executor.start(t, spawner=lambda a: subprocess.Popen(
        ["sh", "-c", _group_cmd()], stdout=subprocess.PIPE, start_new_session=True))
    time.sleep(0.4)
    members = D._group_members(h.proc.pid)
    helper = [m for m in members if m != h.proc.pid][0]
    E.end()
    h.wait(10)
    try:
        assert not D._alive(helper)
    finally:
        if D._group_members(h.proc.pid):
            os.killpg(h.proc.pid, signal.SIGKILL)


def test_FIXED_n20_hub_owned_kill_with_a_sigkill_survivor_reads_unconfirmed(monkeypatch):
    import executor
    import netpent
    info = D._start()
    ok, why, t = netpent.prepare("portscan", "10.0.0.84")
    assert ok, why
    # the helper does NOT hold the stdout pipe, so the leader's exit is recorded first
    cmd = "%s -c '%s' >/dev/null 2>&1 & exec sleep 30" % (sys.executable, IGN)
    h = executor.start(t, spawner=lambda a: subprocess.Popen(
        ["sh", "-c", cmd], stdout=subprocess.PIPE, start_new_session=True))
    time.sleep(0.4)
    pg = h.proc.pid
    helper = [m for m in D._group_members(pg) if m != pg][0]
    real_killpg = os.killpg

    def killpg(p, sig):
        if p == pg and sig == signal.SIGKILL:
            return None
        return real_killpg(p, sig)
    os.killpg = killpg
    try:
        try:
            h.stop("operator stop")
        finally:
            os.killpg = real_killpg
        ch = chain.Chain.open(info["id"])
        ev = [(r["event"], r.get("group_survivor")) for r in ch.records if r.get("ticket") == t.id]
        st = [r["state"] for r in ch.states() if r.get("ticket") == t.id]
        print("trail", ev, "state", st)
        assert D._alive(helper)
        assert st == ["UNCONFIRMED"], (ev, st)
    finally:
        if D._group_members(pg):
            real_killpg(pg, signal.SIGKILL)


# ---------------------------------------------------------------- N24 wall time
def test_OK_n24_four_sigterm_ignoring_orphans_one_wait(tmp_path):
    info = D._start()
    pub, env = D._bound_env(tmp_path)
    orphans = []
    try:
        for i in range(4):
            orphans.append(D._orphan(env, "10.0.0.%d" % (90 + i),
                                     repr([sys.executable, "-c", IGN])))
        time.sleep(0.3)
        t0 = time.monotonic()
        E.end()
        dt = time.monotonic() - t0
        print("END wall %.2fs for 4 SIGTERM-ignoring orphans (RA-CL3d: 6.31 s)" % dt)
        assert all(not D._alive(p) for p in orphans)
        assert dt < 4.5
        assert sorted(r["event"] for r in _end_recs(info)) == ["kill"] * 4
    finally:
        pub.close()
        for p in orphans:
            try:
                os.killpg(p, signal.SIGKILL)
            except OSError:
                pass


# ---------------------------------------------------------------- N23 own group / parent
def test_FIXED_n23_forged_record_naming_hub_pgrp_leader_or_parent_gets_no_signal(monkeypatch):
    pg, pp = os.getpgrp(), os.getppid()
    info = D._start()
    tids = []
    for i, pid in enumerate({pg, pp} - {os.getpid()}):
        tids.append(D._forge_spawn(info, "10.0.0.%d" % (60 + i), pid, gatestate.proc_start(pid)))
    spy = D._Spy(monkeypatch, guard={pg, pp})
    E.end()
    print("signals to pgrp/ppid:", spy.to(pg) + spy.to(pp))
    assert spy.to(pg) == [] and spy.to(pp) == []


def test_DEFECT_n23_forged_keyed_record_naming_hub_session_leader_is_signalled(monkeypatch):
    """N23 refuses getpid/getppid/getpgrp but not getsid (the login shell / terminal session
    leader) or any other ancestor. With the chain key a record naming the session leader with its
    real start time makes END TERM/KILL that process group. The key is the boundary (same uid can
    already signal it) — informational, Low."""
    sid = os.getsid(0)
    if sid in (os.getpid(), os.getppid(), os.getpgrp()) or sid <= 1:
        pytest.skip("session leader coincides with an excluded pid here")
    info = D._start()
    D._forge_spawn(info, "10.0.0.70", sid, gatestate.proc_start(sid))
    spy = D._Spy(monkeypatch, guard={sid})
    E.end()
    print("signals to session leader %d: %s" % (sid, spy.to(sid)))
    assert spy.to(sid)


# ---------------------------------------------------------------- identity flips during END
def test_DEFECT_kill_recorded_by_end_for_an_orphan_that_exited_on_its_own(monkeypatch):
    """_settle_tickets decides "match" and queues the orphan; if the process exits on its own
    before _kill_orphans looks again, _kill_orphans returns (verified_gone=True) without sending
    any signal and END records `kill` "orphan at END" — a kill END never made. The process IS
    gone, so this is never a false KILLED for a survivor. Low."""
    info = D._start()
    v = subprocess.Popen(["sleep", "30"], start_new_session=True)
    time.sleep(0.05)
    tid = D._forge_spawn(info, "10.0.0.71", v.pid, gatestate.proc_start(v.pid))
    real = E._identity
    real_kill = os.kill
    calls = {"n": 0}

    def ident(pid, pstart):
        calls["n"] += 1
        if pid == v.pid and calls["n"] == 1:
            r = real(pid, pstart)
            real_kill(v.pid, signal.SIGKILL); v.wait()   # it exits on its own right after END's check
            return r
        return real(pid, pstart)
    monkeypatch.setattr(E, "_identity", ident)
    spy = D._Spy(monkeypatch)
    E.end()
    recs = [r for r in _end_recs(info) if r.get("ticket") == tid]
    print("END records", [(r["event"], r.get("reason")) for r in recs], "signals", spy.to(v.pid))
    assert spy.to(v.pid) == []
    assert [r["event"] for r in recs] == ["kill"]


# ---------------------------------------------------------------- N13 real kill -9 mid-append
CRASH = """
import os, sys, signal
sys.path.insert(0, os.environ['SUITE'])
import suite; suite.DATA = os.environ['DATA']
import chain
c = chain.Chain.open(os.environ['CID'])
real = chain._write_private
def boom(path, data):
    if path.endswith('.head'):
        os.kill(os.getpid(), signal.SIGKILL)      # after the line fsync, before the head rename
    return real(path, data)
chain._write_private = boom
c.record('note', text='the line that was written')
"""


def test_FIXED_n13_kill9_between_line_fsync_and_head_rename_then_reopen_and_append():
    import suite
    info = D._start()
    n0 = len(D._recs(info["path"]))
    env = dict(os.environ, SUITE=SUITE_DIR, DATA=suite.DATA, CID=info["id"])
    p = subprocess.run([sys.executable, "-c", CRASH], env=env, capture_output=True, text=True)
    assert p.returncode == -signal.SIGKILL, p.stderr
    assert len(D._recs(info["path"])) == n0 + 1        # the orphan line is on disk
    chain.reset_for_tests()
    c = chain.Chain.open(info["id"])
    ok, why = c.verify()
    assert ok, why
    c.record("note", text="after recovery")
    c2 = chain.Chain.open(info["id"])
    ev = [r["event"] for r in c2.records]
    print("tail", ev[-3:])
    assert ev[-3:] == ["note", "recovered", "note"] and c2.verify()[0]
    # and the engagement keeps authorizing on it
    ok, why = E.authorize_action("net:portscan", "10.0.0.5", kind="ip")
    assert ok, why


def test_RESIDUAL_torn_partial_line_still_bricks_but_fails_closed():
    """Power loss before the line's fsync can leave a partial (torn) last line. Out of N13's scope
    (N13 is a complete line + missing head). The chain refuses (fail closed); nothing raises raw."""
    info = D._start()
    with open(info["path"], "ab") as fh:
        fh.write(b'{"seq": 99, "event": "no')
    chain.reset_for_tests()
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])
    ok, why = E.authorize_action("net:portscan", "10.0.0.5", kind="ip")
    assert not ok


# ---------------------------------------------------------------- N12 malformed input
@pytest.mark.parametrize("head", [b"\xff\xfe\x00", b"1 2", b"99999999999999999999 a b",
                                  b"-1 a b", b"\xd9\xa1 a b", b""])
def test_FIXED_n12_malformed_head_is_chainerror_and_gate_fails_closed(head):
    info = D._start()
    with open(info["path"][:-len(".jsonl")] + ".head", "wb") as fh:
        fh.write(head)
    chain.reset_for_tests()
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])
    assert E.chain_info() is None and E.chain_states() == []
    ok, _why = E.authorize_action("net:portscan", "10.0.0.5", kind="ip")
    assert not ok


@pytest.mark.parametrize("line", [b"1", b"[]", b"null", b'"x"', b"[" * 50000 + b"]" * 50000])
def test_FIXED_n12_non_object_or_hostile_line_is_chainerror(line):
    info = D._start()
    raw = open(info["path"], "rb").read().splitlines()
    raw.insert(1, line)
    with open(info["path"], "wb") as fh:
        fh.write(b"\n".join(raw) + b"\n")
    chain.reset_for_tests()
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])


# ---------------------------------------------------------------- R1 snapshot rollback
def test_FIXED_r1_rollback_under_a_running_hub_is_refused_and_restart_is_the_documented_limit():
    import shutil
    info = D._start()
    head = info["path"][:-len(".jsonl")] + ".head"
    snap = (open(info["path"], "rb").read(), open(head, "rb").read())
    for i in range(3):
        assert E.authorize_action("net:portscan", "10.0.0.%d" % (10 + i), kind="ip")[0]
    with open(info["path"], "wb") as fh:
        fh.write(snap[0])
    with open(head, "wb") as fh:
        fh.write(snap[1])
    ok, why = chain.for_id(info["id"]).verify()
    print("in-session verify after rollback:", ok, why)
    assert not ok
    assert not E.authorize_action("net:portscan", "10.0.0.20", kind="ip")[0]
    chain.reset_for_tests()                         # a restart: the documented limit
    c = chain.Chain.open(info["id"])
    assert c.verify()[0]
    assert shutil  # noqa
    doc = chain.__doc__
    assert "snapshot rollback" in doc and "off-device anchor" in doc
