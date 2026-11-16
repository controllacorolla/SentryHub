"""CL4 — the gate / evidence follow-ups carried from the CL3 audits (RA-CL3b, RA-CL3c, RA-CL3d).

N20  "verified gone" checked only the group LEADER (END's orphan kill and the executor's own kill):
     a group member that ignores SIGTERM kept running while the row read KILLED.
N21  a kill recorded after the process's exit was already recorded; FAILED "exit -15" overriding a
     verified KILLED.
N22  a zombie orphan's reason said "pid does not match" (it matches; it already exited).
N23  END could signal the hub's own process-group leader / parent named by a (keyed) forged record.
N24  END killed orphans one at a time (2 s + ~1 s per SIGTERM-ignoring orphan).
N25  macOS: zombie state never read (kp_proc.p_stat).
N12  a malformed head / non-object line raised a non-ChainError.
N13  (a) a failed directory fsync after the head rename rolled the jsonl back under an advanced
     head (bricked); (b) a crash between line fsync and head write left an unrecoverable chain.
N15  ticket folding by (action, target) — fold by the authorize record's seq instead.
R1   snapshot rollback of jsonl+head while the chain is open verified without the key.
Most tests are derived from the RA-CL3d PoCs (plan/briefs/RA-CL3d-poc/poc_ra_cl3d.py).
"""
import json
import os
import signal
import struct
import subprocess
import sys
import textwrap
import time

import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

import chain  # noqa: E402
import engagement as E  # noqa: E402
import gatestate  # noqa: E402
import txguard as G  # noqa: E402

OP = "KD0ABC"
ALLOWED_PROGRAMS = frozenset({"nmap"})
IGN = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    import suite
    import executor
    monkeypatch.setattr(suite, "DATA", str(tmp_path / "data"))
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    monkeypatch.delenv("PALISADE_GATE_STATE", raising=False)
    monkeypatch.setattr(E, "_profile_operator", lambda: OP, raising=False)
    G.reset_session()
    E.reset()
    executor.reset()
    chain.reset_for_tests()
    yield
    executor.kill_all("test teardown")
    executor.reset()
    G.reset_session()
    E.reset()
    chain.reset_for_tests()


def _start(name="job", scope=("10.0.0.0/24",)):
    ok, why = E.start(name, "ROE-1", list(scope), OP)
    assert ok, why
    G.arm(True)
    G.unlock_session(True)
    return E.chain_info()


def _recs(path):
    with open(path, "rb") as fh:
        return [json.loads(x) for x in fh.read().splitlines() if x.strip()]


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open("/proc/%d/stat" % pid) as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _states_at_close(info):
    c = chain.Chain.open(info["id"])
    names = [r["event"] for r in c.records]
    c.records = c.records[:names.index("engagement.close")]
    return c.states()


def _forge_spawn(info, target, pid, pstart):
    import netpent
    ok, why, t = netpent.prepare("portscan", target)
    assert ok, why
    chain.for_id(info["id"]).record("spawn", ticket=t.id, label=t.label, argv=["nmap", target],
                                    pid=pid, pstart=pstart)
    return t.id


class _Spy:
    """os.kill / os.killpg spy; never delivers a signal to a guarded pid / group."""

    def __init__(self, monkeypatch, guard=(), guard_kill_only=()):
        self.calls, self.guard, self.guard_kill = [], set(guard), set(guard_kill_only)
        self._k, self._kpg = os.kill, os.killpg
        monkeypatch.setattr(os, "kill", self.kill)
        monkeypatch.setattr(os, "killpg", self.killpg)

    def kill(self, pid, sig):
        if sig != 0:
            self.calls.append(("kill", pid, sig))
            if pid in self.guard:
                return None
        return self._k(pid, sig)

    def killpg(self, pg, sig):
        if sig != 0:
            self.calls.append(("killpg", pg, sig))
            if pg in self.guard or (sig == signal.SIGKILL and pg in self.guard_kill):
                return None
        return self._kpg(pg, sig)

    def to(self, pid):
        return [c for c in self.calls if c[1] == pid]


HDR = ("import os, sys, json, time, signal, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']\n"
       "import engagement as E, executor, chain\n"
       "E._profile_operator=lambda: 'KD0ABC'\n"
       "import subprocess\nALLOWED_PROGRAMS=frozenset({'nmap'})\n"
       "SP=lambda real: (lambda argv: subprocess.Popen(real, stdout=subprocess.PIPE, "
       "start_new_session=True))\n"
       "def say(*a):\n"
       "    print(*a); sys.stdout.flush()\n")

CHILD_RUN = """
    ok, why, t = E.issue('net:portscan', '%s', argv=['nmap', '%s'], kind='ip')
    assert ok, why
    h = executor.start(t, spawner=SP(%s))
    say('STARTED', h.proc.pid)
    h.wait(30)
    time.sleep(0.3)
    say('DONE', h.stopped, h.exit_code)
"""


def _bound_env(tmp_path):
    import suite
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    env = gatestate.child_env(pub.path, base=dict(os.environ))
    env["PYTHONPATH"] = SUITE_DIR
    env["PALISADE_TEST_DATA"] = suite.DATA
    env.pop("SUITE_TX_LOCK", None)
    return pub, env


def _popen(code, env):
    return subprocess.Popen([sys.executable, "-c", HDR + textwrap.dedent(code)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _orphan(env, ip, real):
    """A bound child that spawns `real` and is then SIGKILLed: its process is an orphan."""
    p = _popen(CHILD_RUN % (ip, ip, real), env)
    line = p.stdout.readline()
    assert line.startswith("STARTED"), line + p.stderr.read()
    pid = int(line.split()[1])
    p.send_signal(signal.SIGKILL)
    p.wait(5)
    return pid


def _killpg_quiet(pg):
    try:
        os.killpg(pg, signal.SIGKILL)
    except OSError:
        pass


# ===================================================================== N20
@linux_only
def test_n20_orphan_group_member_ignoring_sigterm_is_killed_before_verified_gone(tmp_path):
    """RA-CL3d PoC inverted: the leader exits on SIGTERM, a helper in its group ignores it. END
    must SIGKILL the group and only then record kill "orphan at END" verified_gone."""
    info = _start()
    pub, env = _bound_env(tmp_path)
    cmd = "%s -c '%s' & exec sleep 30" % (sys.executable, IGN)
    orphan = None
    try:
        orphan = _orphan(env, "10.0.0.81", repr(["sh", "-c", cmd]))
        time.sleep(0.4)
        members = gatestate.group_members(orphan)
        assert orphan in members and len(members) == 2, members
        helper = [m for m in members if m != orphan][0]
        E.end()
        ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
        assert [(r["event"], r["reason"], r["verified_gone"]) for r in ek] == [
            ("kill", "orphan at END", True)]
        assert not _alive(orphan) and not _alive(helper)
        assert gatestate.group_members(orphan) == []
    finally:
        pub.close()
        if orphan:
            _killpg_quiet(orphan)


@linux_only
def test_n20_orphan_group_survivor_is_unconfirmed_never_killed(tmp_path, monkeypatch):
    """The group SIGKILL is swallowed (a member stuck in D state): the leader is gone but its group
    is not. END must record `unconfirmed` (group survived) and the row is UNCONFIRMED."""
    info = _start()
    pub, env = _bound_env(tmp_path)
    cmd = "%s -c '%s' & exec sleep 30" % (sys.executable, IGN)
    orphan = None
    try:
        orphan = _orphan(env, "10.0.0.82", repr(["sh", "-c", cmd]))
        time.sleep(0.4)
        _Spy(monkeypatch, guard_kill_only={orphan})
        E.end()
        ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
        assert [r["event"] for r in ek] == ["unconfirmed"], ek
        assert "survived SIGKILL" in ek[0]["reason"]
        assert [r["state"] for r in _states_at_close(info)] == ["UNCONFIRMED"]
    finally:
        pub.close()
        monkeypatch.undo()
        if orphan:
            _killpg_quiet(orphan)


@linux_only
def test_n20_executor_kill_takes_the_whole_group():
    """The hub-owned kill (executor._kill_group) used to wait only for the leader, leaving a
    SIGTERM-ignoring member alive under a KILLED row (RA-CL3d PREEXISTING PoC, inverted)."""
    import executor
    import netpent
    _start()
    ok, why, t = netpent.prepare("portscan", "10.0.0.83")
    assert ok, why
    cmd = "%s -c '%s' & exec sleep 30" % (sys.executable, IGN)
    h = executor.start(t, spawner=lambda a: subprocess.Popen(["sh", "-c", cmd],
                                                               stdout=subprocess.PIPE,
                                                               start_new_session=True))
    try:
        time.sleep(0.4)
        members = gatestate.group_members(h.proc.pid)
        assert len(members) == 2, members
        h.stop("test")
        h.wait(10)
        assert gatestate.group_members(h.proc.pid) == []
        assert not any(_alive(m) for m in members)
    finally:
        _killpg_quiet(h.proc.pid)


def test_n20_executor_kill_with_a_survivor_records_unconfirmed(monkeypatch):
    """When _kill_group cannot empty the group, Handle.stop says so: `unconfirmed` group_survivor
    after the kill, and the trail row is UNCONFIRMED, not KILLED."""
    import executor
    import netpent
    info = _start()
    ok, why, t = netpent.prepare("portscan", "10.0.0.84")
    assert ok, why
    h = executor.start(t, spawner=lambda a: subprocess.Popen(["sleep", "30"],
                                                               stdout=subprocess.PIPE,
                                                               start_new_session=True))
    real = executor._kill_group
    monkeypatch.setattr(executor, "_kill_group", lambda proc, grace=1.0: (real(proc), False)[1])
    h.stop("test")
    evs = [(r["event"], r.get("group_survivor")) for r in _recs(info["path"])
           if r.get("ticket") == t.id]
    assert ("kill", None) in evs and ("unconfirmed", True) in evs
    assert evs.index(("unconfirmed", True)) > evs.index(("kill", None))
    rows = chain.Chain.open(info["id"]).states()
    assert rows[0]["state"] == "UNCONFIRMED"


def test_n20_group_alive_probe_reports_a_live_group_and_an_empty_one():
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        assert gatestate.group_alive(p.pid)
        assert p.pid in gatestate.group_members(p.pid)
    finally:
        p.kill()
        p.wait()
    assert not gatestate.group_alive(p.pid, grace_s=1.0)


# ===================================================================== N21
def test_n21_stop_after_the_exit_is_recorded_writes_no_kill():
    import executor
    import netpent
    info = _start()
    ok, why, t = netpent.prepare("portscan", "10.0.0.85")
    assert ok, why
    h = executor.start(t, spawner=lambda a: subprocess.Popen(["true"], stdout=subprocess.PIPE,
                                                               start_new_session=True))
    h.wait(10)
    assert not h.running()
    h.stop("gate closed: engagement changed")          # the sweep that lost the race
    evs = [r["event"] for r in _recs(info["path"]) if r.get("ticket") == t.id]
    assert evs.count("kill") == 0 and evs[-1] == "exit"
    assert chain.Chain.open(info["id"]).states()[0]["state"] == "EXECUTED"


def test_n21_a_signal_exit_after_a_kill_keeps_killed():
    c = chain.Chain.create(name="n21")
    c.record("authorize", action="net:portscan", target="10.0.0.1")
    c.record("issue", ticket="T1", label="net:portscan", target="10.0.0.1", auth_seq=0)
    c.record("spawn", ticket="T1", label="net:portscan", pid=4242)
    c.record("kill", ticket="T1", label="net:portscan", reason="orphan at END", by="end",
             verified_gone=True)
    c.record("exit", ticket="T1", label="net:portscan", exit_code=-15, stopped=None)
    row = c.states()[0]
    assert row["state"] == "KILLED" and row["detail"] == "orphan at END"
    # an ordinary non-zero exit (no kill before it) is still FAILED
    c.record("authorize", action="net:portscan", target="10.0.0.2")
    c.record("issue", ticket="T2", label="net:portscan", target="10.0.0.2", auth_seq=5)
    c.record("spawn", ticket="T2", label="net:portscan", pid=4243)
    c.record("exit", ticket="T2", label="net:portscan", exit_code=1, stopped=None)
    assert c.states()[0]["state"] == "FAILED"


# ===================================================================== N22
@linux_only
def test_n22_zombie_orphan_reason_says_it_already_exited(tmp_path):
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        p = _popen(CHILD_RUN % ("10.0.0.87", "10.0.0.87", "['sleep','0.3']"), env)
        line = p.stdout.readline()
        assert line.startswith("STARTED"), line
        pid = int(line.split()[1])
        p.send_signal(signal.SIGSTOP)
        time.sleep(0.8)
        assert gatestate.is_zombie(pid) is True
        E.end()
        p.send_signal(signal.SIGCONT)
        p.communicate(timeout=30)
    finally:
        pub.close()
    ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
    assert [r["event"] for r in ek] == ["unconfirmed"]
    assert "already exited (zombie" in ek[0]["reason"]
    assert "does not match" not in ek[0]["reason"]
    assert [r["state"] for r in _states_at_close(info)] == ["UNCONFIRMED"]


# ===================================================================== N23
@pytest.mark.parametrize("who", ["pgrp", "ppid"])
def test_n23_end_never_signals_the_hubs_own_group_leader_or_parent(who, monkeypatch):
    pid = os.getpgrp() if who == "pgrp" else os.getppid()
    if pid in (os.getpid(), 1):
        pytest.skip("the test process leads its own group / has init as parent")
    info = _start()
    _forge_spawn(info, "10.0.0.8", pid, gatestate.proc_start(pid))
    spy = _Spy(monkeypatch, guard={pid})
    E.end()
    assert spy.to(pid) == []
    ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
    assert [r["event"] for r in ek] == ["unconfirmed"]
    assert E._identity(pid, gatestate.proc_start(pid)) == "mismatch"


# ===================================================================== N24
@linux_only
def test_n24_end_kills_orphans_together_not_one_at_a_time(tmp_path):
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        orphans = [_orphan(env, "10.0.0.%d" % (90 + i), "[sys.executable, '-c', %r]" % IGN)
                   for i in range(4)]
        time.sleep(0.3)
        t0 = time.monotonic()
        E.end()
        dt = time.monotonic() - t0
    finally:
        pub.close()
    ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
    assert len(ek) == 4 and all(r["verified_gone"] for r in ek)
    assert not any(_alive(o) for o in orphans)
    # one TERM grace + one KILL wait for all four (it was ~1.05 s per orphan, serially)
    assert dt < E.END_DRAIN_S + 1.0 + 1.0 + 1.0, dt


def test_n24_a_failing_kill_still_closes_and_is_unconfirmed(monkeypatch):
    info = _start()
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        time.sleep(0.1)
        _forge_spawn(info, "10.0.0.9", p.pid, gatestate.proc_start(p.pid))
        monkeypatch.setattr(E, "_kill_orphans", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("boom")))
        assert E.end() == "job"
        recs = _recs(info["path"])
        assert recs[-1]["event"] == "engagement.close"
        ek = [r for r in recs if r.get("by") == "end"]
        assert [r["event"] for r in ek] == ["unconfirmed"]
        assert "could not be completed" in ek[0]["reason"]
    finally:
        p.kill()
        p.wait()


# ===================================================================== N25
def _kinfo(sec, usec, p_stat, p_pid):
    raw = bytearray(648)
    struct.pack_into("qi", raw, 0, sec, usec)
    raw[gatestate._DARWIN_P_STAT] = p_stat
    struct.pack_into("i", raw, gatestate._DARWIN_P_PID, p_pid)
    return bytes(raw)


def test_n25_darwin_kinfo_reads_the_zombie_state():
    start, stat = gatestate._darwin_parse(_kinfo(1700000000, 42, 5, 4242), 4242)
    assert start == "darwin:1700000000.000042" and stat == gatestate._DARWIN_SZOMB
    _s, stat = gatestate._darwin_parse(_kinfo(1700000000, 42, 2, 4242), 4242)
    assert stat == 2                                    # SRUN: alive
    _s, stat = gatestate._darwin_parse(_kinfo(1700000000, 42, 5, 99), 4242)
    assert stat is None                                 # layout unconfirmed -> unknown, not zombie


def test_n25_is_zombie_on_darwin_uses_p_stat(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(gatestate, "_darwin_kinfo", lambda pid: _kinfo(1700000000, 1, 5, pid))
    assert gatestate.is_zombie(4242) is True
    monkeypatch.setattr(gatestate, "_darwin_kinfo", lambda pid: _kinfo(1700000000, 1, 2, pid))
    assert gatestate.is_zombie(4242) is False


# ===================================================================== N12
@pytest.mark.parametrize("head", ["² abc def", "x y", "1 2", "-1 aa bb"])
def test_n12_malformed_head_is_a_chainerror(head):
    c = chain.Chain.create(name="n12")
    c.record("hello")
    with open(c.head_path, "w") as fh:
        fh.write(head)
    chain.reset_for_tests()
    with pytest.raises(chain.ChainError):
        chain.Chain.open(c.id)


@pytest.mark.parametrize("line", [b"1\n", b"[1, 2]\n", b'"text"\n', b"null\n"])
def test_n12_non_object_line_is_a_chainerror(line):
    c = chain.Chain.create(name="n12b")
    with open(c.path, "ab") as fh:
        fh.write(line)
    chain.reset_for_tests()
    with pytest.raises(chain.ChainError):
        chain.Chain.open(c.id)


def test_n12_engagement_fails_closed_when_its_chain_raises_anything(monkeypatch):
    _start()
    monkeypatch.setattr(chain, "for_id", lambda cid: (_ for _ in ()).throw(ValueError("x")))
    assert E._active_chain() is None
    assert E.chain_info() is None
    ok, why = E.authorize_action("net:portscan", "10.0.0.5")
    assert not ok and "no evidence chain" in why


# ===================================================================== N13
def test_n13a_directory_fsync_failure_after_the_head_rename_does_not_brick(monkeypatch):
    import stat as _stat
    c = chain.Chain.create(name="n13a")
    c.record("one")
    real = os.fsync

    def fsync(fd):
        if _stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(5, "EIO on directory fsync")
        return real(fd)
    monkeypatch.setattr(os, "fsync", fsync)
    rec = c.record("two")                         # the append happened: no rollback, no raise
    monkeypatch.setattr(os, "fsync", real)
    assert rec["event"] == "two"
    chain.reset_for_tests()
    again = chain.Chain.open(c.id)
    assert [r["event"] for r in again.records] == ["one", "two"]
    assert again.verify()[0]


def _crash_between_line_and_head(c, monkeypatch, event="lost-head"):
    """Simulate SIGKILL / power loss after the line's fsync, before the head is replaced."""
    real_wp = chain._write_private
    monkeypatch.setattr(chain, "_write_private", lambda path, data: (
        (_ for _ in ()).throw(OSError("power lost")) if path.endswith(".head")
        else real_wp(path, data)))
    monkeypatch.setattr(os, "ftruncate", lambda fd, n: (_ for _ in ()).throw(OSError("dead")))
    with pytest.raises(chain.ChainError):
        c.record(event)
    monkeypatch.undo()


def test_n13b_a_line_written_before_a_crash_is_recovered_on_open(monkeypatch, tmp_path):
    import suite
    c = chain.Chain.create(name="n13b")
    c.record("one")
    _crash_between_line_and_head(c, monkeypatch)
    monkeypatch.setattr(suite, "DATA", str(tmp_path / "data"))     # undo() reverted it
    chain.reset_for_tests()
    again = chain.Chain.open(c.id)
    names = [r["event"] for r in again.records]
    assert names == ["one", "lost-head", "recovered"]
    assert again.records[-1]["recovered_seq"] == 1
    assert again.verify()[0]
    again.record("three")                        # appends continue normally
    chain.reset_for_tests()
    assert chain.Chain.open(c.id).verify()[0]


def test_n13b_recovery_also_happens_on_the_next_append_of_a_cached_handle(monkeypatch, tmp_path):
    import suite
    c = chain.Chain.create(name="n13c")
    c.record("one")
    other = chain.Chain.open(c.id)               # another process's handle
    _crash_between_line_and_head(c, monkeypatch)
    monkeypatch.setattr(suite, "DATA", str(tmp_path / "data"))
    other.record("next")
    assert [r["event"] for r in other.records] == ["one", "lost-head", "recovered", "next"]


def test_n13b_two_unaccounted_lines_are_still_refused(monkeypatch, tmp_path):
    import suite
    c = chain.Chain.create(name="n13d")
    c.record("one")
    head = open(c.head_path, "rb").read()
    c.record("two")
    c.record("three")
    with open(c.head_path, "wb") as fh:          # head two records behind: not a crash shape
        fh.write(head)
    monkeypatch.setattr(suite, "DATA", str(tmp_path / "data"))
    chain.reset_for_tests()
    with pytest.raises(chain.ChainError):
        chain.Chain.open(c.id)


# ===================================================================== N15
def test_n15_ticket_folds_into_the_authorization_it_came_from_by_seq():
    """Two interleaved authorizations of the same action+target (two processes): the ticket of the
    SECOND must fold into the second row, not the first."""
    c = chain.Chain.create(name="n15")
    a1 = c.record("authorize", action="net:portscan", target="10.0.0.1")
    a2 = c.record("authorize", action="net:portscan", target="10.0.0.1")
    c.record("issue", ticket="T2", label="net:portscan", target="10.0.0.1", auth_seq=a2["seq"])
    c.record("spawn", ticket="T2", label="net:portscan", pid=1234)
    rows = {r["seq"]: r for r in c.states()}
    assert rows[a2["seq"]]["state"] == "RUNNING" and rows[a2["seq"]]["ticket"] == "T2"
    assert rows[a1["seq"]]["state"] == "AUTHORIZED" and rows[a1["seq"]]["ticket"] is None
    assert len(rows) == 2


def test_n15_a_custom_label_still_folds():
    c = chain.Chain.create(name="n15b")
    a = c.record("authorize", action="net:portscan", target="10.0.0.1")
    c.record("issue", ticket="T1", label="custom scan label", target="10.0.0.1",
             auth_seq=a["seq"])
    rows = c.states()
    assert len(rows) == 1 and rows[0]["ticket"] == "T1" and rows[0]["state"] == "ISSUED"


def test_n15_engagement_issue_records_the_authorize_seq():
    import netpent
    info = _start()
    ok, why, t = netpent.prepare("portscan", "10.0.0.6")
    assert ok, why
    recs = _recs(info["path"])
    auth = [r for r in recs if r["event"] == "authorize"][-1]
    iss = [r for r in recs if r["event"] == "issue" and r.get("ticket") == t.id][0]
    assert iss["auth_seq"] == auth["seq"]


# ===================================================================== R1
def test_r1_a_snapshot_rollback_while_the_chain_is_open_is_refused():
    c = chain.Chain.create(name="r1")
    c.record("one")
    snap = {p: open(p, "rb").read() for p in (c.path, c.head_path)}
    c.record("two")
    c.record("three")
    for p, data in snap.items():                 # restore an older, internally valid snapshot
        with open(p, "wb") as fh:
            fh.write(data)
    ok, why = c.verify()
    assert not ok and "rolled back" in why
    with pytest.raises(chain.ChainError):
        c.record("four")


def test_r1_docstring_no_longer_overclaims():
    doc = chain.__doc__
    assert "snapshot rollback" in doc and "off-device anchor" in doc
