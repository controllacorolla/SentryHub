"""RA-CL3d PoCs — attacks on CL3-fix3 (fix/cl3-evidence @ e5a0e54): the owner-decided orphan kill
at END (engagement._same_process / _kill_orphan / _settle_tickets), Chain.record(_only_if=...),
and the states() fold for `unconfirmed` / refusal-only-on-unused.
OK_* = the fix holds. DEFECT_* = the defect reproduces (the test PASSES when it does).
Run: SUITE=<worktree> pytest -q poc_ra_cl3d.py   (Linux; the orphan tests read /proc)"""
import json
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

SUITE_DIR = os.environ["SUITE"]
sys.path.insert(0, SUITE_DIR)

import chain  # noqa: E402
import engagement as E  # noqa: E402
import gatestate  # noqa: E402
import txguard as G  # noqa: E402

OP = "KD0ABC"
ALLOWED_PROGRAMS = frozenset({"nmap"})
IGN = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"


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


def _start(name="job", scope=("10.0.0.0/24",)):
    ok, why = E.start(name, "ROE-1", list(scope), OP)
    assert ok, why
    G.arm(True); G.unlock_session(True)
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


def _group_members(pgid):
    out = []
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open("/proc/%s/stat" % d) as fh:
                    f = fh.read().rsplit(")", 1)[1].split()
                if int(f[2]) == pgid and f[0] != "Z":
                    out.append(int(d))
            except (OSError, ValueError, IndexError):
                pass
    return out


def _states_at_close(info):
    c = chain.Chain.open(info["id"])
    names = [r["event"] for r in c.records]
    c.records = c.records[:names.index("engagement.close")]
    return c.states()


def _forge_spawn(info, target, pid, pstart, **extra):
    """An engagement ticket + a spawn record naming (pid, pstart), written WITH the chain key (the
    only way a record verifies). Returns the ticket id."""
    import netpent
    ok, why, t = netpent.prepare("portscan", target)
    assert ok, why
    chain.for_id(info["id"]).record("spawn", ticket=t.id, label=t.label, argv=["nmap", target],
                                     pid=pid, pstart=pstart, **extra)
    return t.id


class _Spy:
    """os.kill / os.killpg spy: records every signal END sends; never delivers one to a guarded pid."""
    def __init__(self, monkeypatch, guard=()):
        self.calls, self.guard = [], set(guard)
        self._k, self._kpg = os.kill, os.killpg
        monkeypatch.setattr(os, "kill", self.kill)
        monkeypatch.setattr(os, "killpg", self.killpg)

    def kill(self, pid, sig):
        if sig != 0:
            self.calls.append(("kill", pid, sig))
        if pid in self.guard and sig != 0:
            return None
        return self._k(pid, sig)

    def killpg(self, pg, sig):
        if sig != 0:
            self.calls.append(("killpg", pg, sig))
        if pg in self.guard and sig != 0:
            return None
        return self._kpg(pg, sig)

    def to(self, pid):
        return [c for c in self.calls if c[1] == pid]


# ============================================================== 2a: identity — END must not signal
def _victim():
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    time.sleep(0.05)
    return p


@pytest.mark.parametrize("case", ["recycled_start", "pid0", "pid1", "own_pid", "bool_pid", "str_pid",
                                  "float_pid", "neg_pid", "missing_pstart", "empty_pstart",
                                  "forged_pstart", "pstart_wrong_type"])
def test_OK_end_sends_no_signal_without_an_exact_identity_match(case, monkeypatch):
    info = _start()
    v = _victim()
    real = gatestate.proc_start(v.pid)
    pid, pstart = {
        "recycled_start": (v.pid, real[:-1] + str((int(real[-1]) + 1) % 10)),
        "pid0": (0, real), "pid1": (1, gatestate.proc_start(1)), "own_pid": (os.getpid(), gatestate.proc_start(os.getpid())),
        "bool_pid": (True, real), "str_pid": (str(v.pid), real), "float_pid": (float(v.pid), real),
        "neg_pid": (-v.pid, real), "missing_pstart": (v.pid, None), "empty_pstart": (v.pid, ""),
        "forged_pstart": (v.pid, "linux:0"), "pstart_wrong_type": (v.pid, 12345),
    }[case]
    tid = _forge_spawn(info, "10.0.0.9", pid, pstart)
    spy = _Spy(monkeypatch, guard={0, 1, os.getpid(), os.getpgrp(), v.pid, -v.pid})
    try:
        E.end()
        sent = [c for c in spy.calls if c[1] in (0, 1, os.getpid(), os.getpgrp(), v.pid, -v.pid)]
        assert sent == [], sent
        assert _alive(v.pid)
        recs = [r for r in _recs(info["path"]) if r.get("ticket") == tid and r.get("by") == "end"]
        assert [r["event"] for r in recs] == ["unconfirmed"], recs
        assert "END sent no signal" in recs[0]["reason"]
        assert [r["state"] for r in _states_at_close(info)] == ["UNCONFIRMED"]
    finally:
        v.kill(); v.wait()


def test_DEFECT_own_process_group_leader_is_signalled_by_a_forged_record(monkeypatch):
    """_same_process excludes the hub's own pid but NOT the hub's own process-group leader (its
    launcher: a shell, the session leader). A spawn record naming getpgrp() with its real start
    time makes END os.kill() it (killpg is skipped for own group, kill is not). Needs the chain key."""
    pg = os.getpgrp()
    if pg == os.getpid():
        pytest.skip("the test process leads its own group")
    info = _start()
    tid = _forge_spawn(info, "10.0.0.8", pg, gatestate.proc_start(pg))
    spy = _Spy(monkeypatch, guard={pg})                    # never actually delivered
    E.end()
    print("signals to own pgrp leader", spy.to(pg))
    assert spy.to(pg) and all(c[0] == "kill" for c in spy.to(pg))
    assert tid


def test_DEFECT_forged_record_with_the_key_kills_any_same_uid_process_group():
    """A record forged WITH the chain key, naming another of the user's processes with its real
    start time, makes END SIGTERM/SIGKILL that process's whole group and log it as an orphan kill.
    Rating: the key (0600, same uid) is the boundary — anyone holding it can already kill the
    user's processes directly; END adds no new capability. Low/informational."""
    info = _start()
    leader = subprocess.Popen(["sh", "-c", "sleep 30 & sleep 30"], start_new_session=True)
    time.sleep(0.2)
    members = _group_members(leader.pid)
    assert len(members) >= 2
    _forge_spawn(info, "10.0.0.7", leader.pid, gatestate.proc_start(leader.pid))
    E.end()
    leader.wait(5)
    time.sleep(0.2)
    assert not any(_alive(m) for m in members)              # the whole foreign group is gone
    ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
    assert [(r["event"], r["reason"]) for r in ek] == [("kill", "orphan at END")]


# ============================================================== 2b: the orphan's group
HDR = ("import os, sys, json, time, signal, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']\n"
       "import engagement as E, executor, chain\n"
       "E._profile_operator=lambda: 'KD0ABC'\n"
       "import subprocess\nALLOWED_PROGRAMS=frozenset({'nmap'})\n"
       "SP=lambda real: (lambda argv: subprocess.Popen(real, stdout=subprocess.PIPE, start_new_session=True))\n"
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


def test_DEFECT_group_member_ignoring_sigterm_survives_a_verified_gone_orphan_kill(tmp_path):
    """The orphan leads its group; its leader exits on SIGTERM, a helper in the same group ignores
    SIGTERM. _kill_orphan checks only the LEADER's identity: once the leader is gone it returns
    'verified gone', never sends SIGKILL, and END records kill "orphan at END" verified_gone=True —
    while the helper (same gated process group) keeps running. Row: KILLED."""
    info = _start()
    pub, env = _bound_env(tmp_path)
    cmd = "%s -c '%s' & exec sleep 30" % (sys.executable, IGN)
    try:
        orphan = _orphan(env, "10.0.0.81", repr(["sh", "-c", cmd]))
        time.sleep(0.4)
        members = _group_members(orphan)
        assert orphan in members and len(members) == 2, members
        helper = [m for m in members if m != orphan][0]
        E.end()
        time.sleep(0.5)
        ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
        print("END records", [(r["event"], r.get("reason"), r.get("verified_gone")) for r in ek])
        assert [(r["event"], r["reason"], r["verified_gone"]) for r in ek] == [
            ("kill", "orphan at END", True)]
        assert [r["state"] for r in _states_at_close(info)] == ["KILLED"]
        assert not _alive(orphan)
        assert _alive(helper)          # DEFECT: the 'verified gone' group still has a live member
    finally:
        pub.close()
        try:
            os.killpg(orphan, signal.SIGKILL)
        except OSError:
            pass


def test_PREEXISTING_hub_executor_kill_has_the_same_group_semantics():
    """Context for the finding above: the executor's own _kill_group also waits only for the
    leader, so a SIGTERM-ignoring group member survives a hub-owned kill too (row KILLED)."""
    import executor
    import netpent
    _start()
    ok, why, t = netpent.prepare("portscan", "10.0.0.82")
    assert ok, why
    cmd = "%s -c '%s' & exec sleep 30" % (sys.executable, IGN)
    h = executor.start(t, spawner=lambda a: subprocess.Popen(["sh", "-c", cmd], stdout=subprocess.PIPE,
                                                               start_new_session=True))
    time.sleep(0.4)
    members = _group_members(h.proc.pid)
    helper = [m for m in members if m != h.proc.pid][0]
    E.end()
    h.wait(10)
    try:
        assert _alive(helper)
    finally:
        os.killpg(h.proc.pid, signal.SIGKILL) if _group_members(h.proc.pid) else None


def test_OK_end_never_signals_the_hubs_own_group_or_a_childs_group(tmp_path, monkeypatch):
    """Real orphan: END signals exactly the orphan's own group, never the hub's group, never the
    (dead) child's pid/group, never a sibling child's group."""
    _start()
    pub, env = _bound_env(tmp_path)
    try:
        good = _popen(CHILD_RUN % ("10.0.0.83", "10.0.0.83", "['sleep','30']"), env)
        gl = good.stdout.readline()
        assert gl.startswith("STARTED")
        good_proc = int(gl.split()[1])
        dead = _popen(CHILD_RUN % ("10.0.0.84", "10.0.0.84", "['sleep','30']"), env)
        dl = dead.stdout.readline()
        orphan = int(dl.split()[1])
        dead_pid = dead.pid
        dead.send_signal(signal.SIGKILL); dead.wait(5)
        spy = _Spy(monkeypatch)
        E.end()
        good.communicate(timeout=30)
    finally:
        pub.close()
    end_sigs = [c for c in spy.calls if c[1] not in (good_proc,)]   # good child's own sweep is its own
    print(spy.calls)
    assert end_sigs and all(c[1] == orphan for c in end_sigs), end_sigs
    assert not spy.to(os.getpgrp()) and not spy.to(os.getpid()) and not spy.to(dead_pid)
    assert all(c[0] == "killpg" for c in end_sigs)
    assert not _alive(orphan)


# ============================================================== 2c: TERM-ignoring / SIGKILL-proof / zombie
def test_OK_orphan_ignoring_sigterm_is_sigkilled_and_recorded_verified(tmp_path):
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        orphan = _orphan(env, "10.0.0.85", "[sys.executable, '-c', %r]" % IGN)
        time.sleep(0.3)
        t0 = time.monotonic()
        E.end()
        dt = time.monotonic() - t0
    finally:
        pub.close()
    ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
    print("END %.2fs" % dt, ek)
    assert [(r["event"], r["reason"], r["verified_gone"]) for r in ek] == [("kill", "orphan at END", True)]
    assert not _alive(orphan)
    assert dt < E.END_DRAIN_S + 1.0 + 1.0 + 0.5


def test_OK_orphan_that_survives_sigkill_is_unconfirmed_never_killed(tmp_path, monkeypatch):
    """Simulates an uninterruptible (D-state) process: signals to it are swallowed. END must record
    `unconfirmed` 'signalled, still alive', row UNCONFIRMED, never KILLED."""
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        orphan = _orphan(env, "10.0.0.86", "['sleep','30']")
        time.sleep(0.3)
        spy = _Spy(monkeypatch, guard={orphan})
        t0 = time.monotonic()
        E.end()
        dt = time.monotonic() - t0
        ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
        print("END %.2fs" % dt, spy.to(orphan), ek)
        assert [s for _, _, s in spy.to(orphan)] == [signal.SIGTERM, signal.SIGKILL]
        assert [(r["event"], r["reason"]) for r in ek] == [("unconfirmed", "orphan at END: signalled, still alive")]
        assert [r["state"] for r in _states_at_close(info)] == ["UNCONFIRMED"]
        assert _alive(orphan)
    finally:
        pub.close()
        try:
            os.killpg(orphan, signal.SIGKILL)
        except OSError:
            pass


def test_DEFECT_zombie_orphan_reason_says_pid_does_not_match(tmp_path):
    """A bound child is SIGSTOPped; its process exits on its own before END and stays a zombie
    (the stopped parent cannot reap it). END: _same_process is False (zombie) and records
    `unconfirmed` '... pid N does not match the process logged at launch, END sent no signal'.
    The state is honest (UNCONFIRMED, no signal), but the reason is wrong: the pid DOES match; the
    process has already exited. When the child resumes its exit lands after close and wins."""
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        p = _popen(CHILD_RUN % ("10.0.0.87", "10.0.0.87", "['sleep','0.3']"), env)
        line = p.stdout.readline()
        pid = int(line.split()[1])
        p.send_signal(signal.SIGSTOP)
        time.sleep(0.8)
        with open("/proc/%d/stat" % pid) as fh:
            assert fh.read().rsplit(")", 1)[1].split()[0] == "Z"
        E.end()
        p.send_signal(signal.SIGCONT)
        p.communicate(timeout=30)
    finally:
        pub.close()
    recs = _recs(info["path"])
    ek = [r for r in recs if r.get("by") == "end"]
    print(ek)
    assert [r["event"] for r in ek] == ["unconfirmed"]
    assert "does not match the process logged at launch" in ek[0]["reason"]
    assert [r["state"] for r in _states_at_close(info)] == ["UNCONFIRMED"]
    # after SIGCONT the child's exit wins (EXECUTED); in some runs its sweep also records a kill of
    # the already-exited process (N21 race) and the row reads KILLED
    assert [r["state"] for r in chain.Chain.open(info["id"]).states()] in (["EXECUTED"], ["KILLED"])


def test_DEFECT_rollover_resumed_child_writes_an_untrue_tail_after_ends_verified_kill(tmp_path):
    """Rollover (END alpha, START bravo while the bound child is SIGSTOPped): END kills the child's
    process (verified) and records KILLED before close. The child resumes; its wait() reaps the
    already-dead process and records `exit` exit_code=-15, stopped=None. Then, in about half the
    runs, its sweep ALSO records `kill` "gate closed: engagement changed" for a process that had
    already exited (a 2nd kill for one ticket, after the exit). Either way the post-close tail is
    untrue: (a) only the exit -> the fold shows FAILED 'exit -15' (a tool failure, not END's kill);
    (b) exit then kill -> a kill of a dead process, row KILLED by the child's reason."""
    alpha = _start("alpha")
    pub, env = _bound_env(tmp_path)
    try:
        p = _popen(CHILD_RUN % ("10.0.0.88", "10.0.0.88", "['sleep','30']"), env)
        assert p.stdout.readline().startswith("STARTED")
        p.send_signal(signal.SIGSTOP)
        E.end()
        ok, why = E.start("bravo", "ROE-2", ["10.0.0.0/24"], OP)
        assert ok, why
        p.send_signal(signal.SIGCONT)
        p.communicate(timeout=30)
    finally:
        pub.close()
    a = _recs(alpha["path"])
    names = [r["event"] for r in a]
    close = names.index("engagement.close")
    tail = [(r["event"], r.get("stopped"), r.get("exit_code")) for r in a[close + 1:]]
    rows = chain.Chain.open(alpha["id"]).states()
    print("TAIL", tail, rows)
    assert [r["state"] for r in _states_at_close(alpha)] == ["KILLED"]
    assert [r["event"] for r in a if r.get("by") == "end"] == ["kill"]
    if tail == [("exit", None, -15)]:
        assert [(r["state"], r["detail"]) for r in rows] == [("FAILED", "exit -15")]   # (a)
    else:
        assert tail == [("exit", None, -15), ("kill", None, None)], tail               # (b)
        assert names.count("kill") == 2


# ============================================================== 2d: wall time / exceptions
def test_OK_end_wall_time_with_four_sigterm_ignoring_orphans(tmp_path):
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
    print("END with 4 TERM-ignoring orphans: %.2fs" % dt)
    ek = [r for r in _recs(info["path"]) if r.get("by") == "end"]
    assert len(ek) == 4 and all(r["verified_gone"] for r in ek)
    assert not any(_alive(o) for o in orphans)
    assert dt < E.END_DRAIN_S + 4 * 2.2                    # serial: ~1 s TERM grace per orphan


def test_OK_end_completes_when_a_step_raises(tmp_path, monkeypatch):
    """_kill_orphan raises for the first orphan: END still settles the second and closes."""
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        o1 = _orphan(env, "10.0.0.95", "['sleep','30']")
        o2 = _orphan(env, "10.0.0.96", "['sleep','30']")
        real = E._kill_orphan
        monkeypatch.setattr(E, "_kill_orphan", lambda pid, ps, **k: (_ for _ in ()).throw(
            RuntimeError("boom")) if pid == o1 else real(pid, ps, **k))
        assert E.end() == "job"
    finally:
        pub.close()
    recs = _recs(info["path"])
    assert recs[-1]["event"] == "engagement.close" and not E.is_active()
    ek = {r["pid"]: r["event"] for r in recs if r.get("by") == "end"}
    print(ek)
    assert ek == {o2: "kill"}            # the raising one got no record (stays RUNNING at close)
    assert not _alive(o2)
    os.killpg(o1, signal.SIGKILL)


# ============================================================== 3: Chain.record(_only_if=...)
def test_OK_only_if_skip_and_raise_leave_the_chain_intact():
    c = chain.Chain.create(name="oi")
    c.record("note", i=0)
    raw = open(c.path, "rb").read(); head = open(c.head_path, "rb").read()
    assert c.record("note", _only_if=lambda recs: False, i=1) is None
    assert open(c.path, "rb").read() == raw and open(c.head_path, "rb").read() == head
    with pytest.raises(ZeroDivisionError):
        c.record("note", _only_if=lambda recs: 1 / 0, i=2)
    assert open(c.path, "rb").read() == raw and open(c.head_path, "rb").read() == head
    assert c.verify()[0]
    assert c.record("note", _only_if=lambda recs: True, i=3)["seq"] == 1
    assert chain.Chain.open(c.id).verify()[0]


WRITER = """
import sys, time; sys.path.insert(0, %r)
import suite; suite.DATA = %r
import chain
c = chain.Chain.open(%r)
for i in range(60):
    c.record("note", w=%d, i=i)
    if i == 30: c.record("stop", w=%d)
"""


def test_OK_only_if_is_atomic_against_concurrent_writer_processes():
    """3 writer processes append; one writes `stop`. The main process appends `cond` only if no
    `stop` exists yet. No `cond` may follow a `stop`, and the chain must verify."""
    import suite
    c = chain.Chain.create(name="race")
    ws = [subprocess.Popen([sys.executable, "-c", WRITER % (SUITE_DIR, suite.DATA, c.id, w, w)])
          for w in range(3)]
    n = 0
    while any(w.poll() is None for w in ws):
        if c.record("cond", _only_if=lambda recs: not any(r["event"] == "stop" for r in recs)):
            n += 1
    for w in ws:
        w.wait()
    final = chain.Chain.open(c.id)
    assert final.verify()[0]
    names = [r["event"] for r in final.records]
    first_stop = names.index("stop")
    print("cond appended", n, "first stop at", first_stop, "len", len(names))
    assert "cond" not in names[first_stop:]
    assert names.count("note") == 180


# ============================================================== 4: states()
def test_OK_states_unconfirmed_and_refusal_rules_hide_no_outcome():
    c = chain.Chain.create(name="fold3")
    T = lambda ch: ch * 32      # noqa: E731
    for tk, tgt in (("a", "1"), ("b", "2"), ("c", "3"), ("d", "4")):
        c.record("issue", ticket=T(tk), label="net:portscan", target="10.0.0." + tgt)
        c.record("spawn", ticket=T(tk), label="net:portscan", pid=1)
    # unconfirmed only replaces RUNNING; a later kill / exit wins
    c.record("unconfirmed", ticket=T("a"), reason="x", by="end")
    c.record("kill", ticket=T("a"), reason="late")
    c.record("unconfirmed", ticket=T("b"), reason="x", by="end")
    c.record("exit", ticket=T("b"), exit_code=0)
    # an unconfirmed after a kill/exit never downgrades it
    c.record("kill", ticket=T("c"), reason="k")
    c.record("unconfirmed", ticket=T("c"), reason="x", by="end")
    # a refusal can never replace RUNNING/EXECUTED
    c.record("refuse_ticket", ticket=T("d"), reason="ended", by="end")
    rows = {r["target"]: r["state"] for r in c.states()}
    assert rows == {"10.0.0.1": "KILLED", "10.0.0.2": "EXECUTED", "10.0.0.3": "KILLED",
                    "10.0.0.4": "RUNNING"}, rows
    c.record("exit", ticket=T("d"), exit_code=0)
    c.record("refuse_ticket", ticket=T("d"), reason="ended", by="end")
    assert {r["target"]: r["state"] for r in c.states()}["10.0.0.4"] == "EXECUTED"
    # a write is never hidden by a later refusal
    c.record("issue", ticket=T("e"), label="hid:inject", target="10.0.0.5")
    c.record("write", ticket=T("e"), bytes=3)
    c.record("refuse_ticket", ticket=T("e"), reason="ended", by="end")
    assert {r["target"]: r["state"] for r in c.states()}["10.0.0.5"] == "EXECUTED"
