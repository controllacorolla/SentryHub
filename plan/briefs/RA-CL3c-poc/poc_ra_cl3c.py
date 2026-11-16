"""RA-CL3c PoCs — attacks on CL3-fix2 (END -> _settle_tickets, ticket->chain binding, states fold)
at fix/cl3-evidence 4995c5c. Updated in place by RA-CL3d against CL3-fix3 (e5a0e54):
the N16/N17/N18/N19 DEFECT_* tests now assert the FIXED behaviour; the rollover test changes by
owner decision (END kills an orphan whose pid + start time match).
OK_* = the fix holds. FIXED_* = the RA-CL3c defect no longer reproduces.
Run: SUITE=<worktree> pytest -q poc_ra_cl3c.py"""
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest

SUITE_DIR = os.environ["SUITE"]
sys.path.insert(0, SUITE_DIR)

import chain  # noqa: E402
import engagement as E  # noqa: E402
import txguard as G  # noqa: E402

OP = "KD0ABC"
ALLOWED_PROGRAMS = frozenset({"nmap"})


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


def _sessions(d):
    return sorted(f for f in os.listdir(d) if "-session-" in f and f.endswith(".jsonl"))


def _states_at_close(info):
    """states() over the records up to (not incl.) engagement.close."""
    c = chain.Chain.open(info["id"])
    names = [r["event"] for r in c.records]
    c.records = c.records[:names.index("engagement.close")]
    return c.states()


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:                                   # a zombie is not alive
        with open("/proc/%d/stat" % pid) as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _bound_env(tmp_path):
    import gatestate
    import suite
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    env = gatestate.child_env(pub.path, base=dict(os.environ))
    env["PYTHONPATH"] = SUITE_DIR
    env["PALISADE_TEST_DATA"] = suite.DATA
    env.pop("SUITE_TX_LOCK", None)
    return pub, env


HDR = ("import os, sys, json, time, signal, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']\n"
       "import engagement as E, executor, chain\n"
       "E._profile_operator=lambda: 'KD0ABC'\n"
       "import subprocess\nALLOWED_PROGRAMS=frozenset({'nmap'})\n"
       "IGN=\"import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)\"\n"
       "SP=lambda real: (lambda argv: subprocess.Popen(real, stdout=subprocess.PIPE, start_new_session=True))\n"
       "def say(*a):\n"
       "    print(*a); sys.stdout.flush()\n")


def _popen(code, env):
    return subprocess.Popen([sys.executable, "-c", HDR + textwrap.dedent(code)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


CHILD_RUN = """
    ok, why, t = E.issue('net:portscan', '%s', argv=['nmap', '%s'], kind='ip')
    assert ok, why
    hs = [executor.start(t, spawner=SP(%s))]
    say('STARTED', hs[0].proc.pid)
    for h in hs: h.wait(20)
    time.sleep(0.3)
    s = chain._SESSION['chain']
    say('DONE', [h.stopped for h in hs], [h.exit_code for h in hs], 'SESS', s.id if s else None)
"""


# ============================================================== 2a: N children, one ignores TERM
def test_OK_end_with_four_children_one_ignoring_sigterm(tmp_path):
    info = _start()
    pub, env = _bound_env(tmp_path)
    kids = []
    try:
        for i, prog in enumerate((["sleep", "30"], ["sleep", "30"], ["sleep", "30"], None)):
            real = repr(prog) if prog else "[sys.executable, '-c', IGN]"
            ip = "10.0.0.%d" % (10 + i)
            p = _popen(CHILD_RUN % (ip, ip, real), env)
            line = p.stdout.readline()
            assert line.startswith("STARTED"), line + p.stderr.read()
            kids.append((p, int(line.split()[1])))
        time.sleep(0.3)
        t0 = time.monotonic()
        E.end()
        dt = time.monotonic() - t0
        outs = [p.communicate(timeout=30)[0] for p, _ in kids]
    finally:
        pub.close()
    print("END took %.2fs" % dt, outs)
    assert dt < E.END_DRAIN_S + 1.0
    assert all("SESS None" in o for o in outs)
    recs = _recs(info["path"])
    names = [r["event"] for r in recs]
    close = names.index("engagement.close")
    assert close == len(names) - 1, names
    assert not any(r.get("by") == "end" for r in recs)      # every child reported in time
    assert names.count("kill") == 4 and names.count("exit") == 4
    assert not [r for r in _states_at_close(info) if r["state"] in ("RUNNING", "ISSUED")]
    assert not _sessions(os.path.dirname(info["path"]))
    assert not any(_alive(pid) for _, pid in kids)


def test_FIXED_end_one_child_three_sigterm_ignoring_processes_overruns_the_drain(tmp_path):
    """One child, 3 processes that ignore SIGTERM: the child's sweep stops them one after the other
    (~1 s TERM grace each), so the third kill is not recorded inside END_DRAIN_S.
    RA-CL3d (N19): END now treats the unreported one as an orphan (pid + start match), kills it
    itself (TERM, 1 s, KILL) and records `kill` "orphan at END" only if the child has not already
    recorded one. Never two kills for one ticket. END now takes ~DRAIN + 1 s per such process."""
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        p = _popen("""
            hs = []
            for ip in ('10.0.0.21', '10.0.0.22', '10.0.0.23'):
                ok, why, t = E.issue('net:portscan', ip, argv=['nmap', ip], kind='ip')
                assert ok, why
                hs.append(executor.start(t, spawner=SP([sys.executable, '-c', IGN])))
            say('STARTED', *[h.proc.pid for h in hs])
            for h in hs: h.wait(30)
            time.sleep(0.3)
            s = chain._SESSION['chain']
            say('DONE', [h.exit_code for h in hs], 'SESS', s.id if s else None)
        """, env)
        line = p.stdout.readline()
        assert line.startswith("STARTED"), line + p.stderr.read()
        pids = [int(x) for x in line.split()[1:]]
        time.sleep(0.5)
        t0 = time.monotonic()
        E.end()
        dt = time.monotonic() - t0
        out, err = p.communicate(timeout=60)
    finally:
        pub.close()
    print("END %.2fs" % dt, out, err[-500:])
    assert dt < E.END_DRAIN_S + 2.5 and "SESS None" in out
    recs = _recs(info["path"])
    names = [r["event"] for r in recs]
    close = names.index("engagement.close")
    by_end = [r for r in recs if r.get("by") == "end"]
    after = [r["event"] for r in recs[close + 1:]]
    print("by_end", [(r["event"], r["target"], r.get("reason")) for r in by_end], "after close", after)
    assert not [r for r in _states_at_close(info) if r["state"] in ("RUNNING", "ISSUED")]
    for r in by_end:                              # END's kill is only ever a verified one
        assert r["event"] == "kill" and r["reason"] == "orphan at END" and r["verified_gone"]
    for tid in {r["ticket"] for r in recs if r.get("ticket")}:
        evs = [r["event"] for r in recs if r.get("ticket") == tid]
        assert evs.count("kill") <= 1, evs        # N19: never two kills for one ticket
    assert "kill" not in after                    # no kill lands after close
    assert not any(_alive(x) for x in pids)
    rows = chain.Chain.open(info["id"]).states()
    assert all(r["state"] == "KILLED" for r in rows), rows


# ============================================================== 2b: child SIGKILLed after spawn
def test_FIXED_sigkilled_child_end_kills_the_orphan_and_records_it_truthfully(tmp_path):
    """A bound child is SIGKILLed after spawn. END correctly writes a `kill` (by=end) before close
    and nothing for the child that reported — but END never signals anything: the gated process
    (its own session/process group) is orphaned and KEEPS RUNNING after END, while the trail says
    KILLED ("kill signalled by END")."""
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        good = _popen(CHILD_RUN % ("10.0.0.31", "10.0.0.31", "['sleep','30']"), env)
        dead = _popen(CHILD_RUN % ("10.0.0.32", "10.0.0.32", "['sleep','30']"), env)
        gl, dl = good.stdout.readline(), dead.stdout.readline()
        assert gl.startswith("STARTED") and dl.startswith("STARTED"), gl + dl
        orphan = int(dl.split()[1])
        dead.send_signal(signal.SIGKILL)
        dead.wait(5)
        time.sleep(0.3)
        t0 = time.monotonic()
        E.end()
        dt = time.monotonic() - t0
        good.communicate(timeout=30)
    finally:
        pub.close()
    try:
        recs = _recs(info["path"])
        names = [r["event"] for r in recs]
        close = names.index("engagement.close")
        by_end = [r for r in recs if r.get("by") == "end"]
        print("END %.2fs" % dt, [(r["event"], r["target"], r["reason"]) for r in by_end])
        assert [(r["event"], r["target"]) for r in by_end] == [("kill", "10.0.0.32")]
        assert by_end[0]["seq"] < close
        assert dt < E.END_DRAIN_S + 1.0
        rows = {r["target"]: r["state"] for r in _states_at_close(info)}
        assert rows == {"10.0.0.31": "KILLED", "10.0.0.32": "KILLED"}
        # RA-CL3d: N16 fixed — END killed the orphan (pid + start time matched) and says so
        assert by_end[0]["reason"] == "orphan at END" and by_end[0]["verified_gone"] is True
        assert by_end[0]["pid"] == orphan and by_end[0]["pstart"]
        assert not _alive(orphan)
    finally:
        try:
            os.killpg(orphan, signal.SIGKILL)
        except OSError:
            pass


# ============================================================== 2c: redeem racing END's void
def test_FIXED_redeem_racing_end_void_no_longer_claims_never_used(monkeypatch):
    """A process ticket whose re-check passed just before END, and whose spawner is still starting
    the process when END reads the chain: END sees 'issued, never spawned' and records
    refuse_ticket 'engagement ended before the ticket was used — void' + close. The process then
    spawns (spawn after close), the post-spawn sweep kills it. Final row KILLED (correct), but the
    trail carries a false 'never used — void' and a spawn after engagement.close."""
    import executor
    import netpent
    info = _start()
    ok, why, t = netpent.prepare("portscan", "10.0.0.41")
    assert ok, why
    entered = threading.Event()

    def slow_spawner(argv):
        entered.set()
        time.sleep(0.6)
        return subprocess.Popen(["sleep", "30"], stdout=subprocess.PIPE, start_new_session=True)
    box = {}
    th = threading.Thread(target=lambda: box.setdefault("h", executor.start(t, spawner=slow_spawner)))
    th.start()
    assert entered.wait(5)                # redeemed: re-check passed, ticket consumed
    E.end()
    th.join(10)
    box["h"].wait(10)
    recs = [r for r in _recs(info["path"]) if r.get("ticket") == t.id or r["event"] == "engagement.close"]
    seq = [(r["event"], r.get("by", "")) for r in recs]
    print(seq)
    assert seq[:3] == [("issue", ""), ("refuse_ticket", "end"), ("engagement.close", "")]
    assert ("spawn", "") in seq[3:] and ("exit", "") in seq[3:]
    # RA-CL3d: N18 — the void now states only what END observed; the spawn/kill/exit that follow
    # it are visible and the row ends KILLED (still records after close: the use had passed its gate)
    assert "before the ticket was used" not in recs[1]["reason"]
    assert "no use of this ticket recorded by then" in recs[1]["reason"]
    rows = chain.Chain.open(info["id"]).states()
    assert [r["state"] for r in rows] == ["KILLED"]


class _SlowPort:
    def __init__(self, delay):
        self.delay, self.data = delay, b""

    def write(self, b):
        time.sleep(self.delay)
        self.data += b
        return len(b)


def test_FIXED_void_after_write_no_longer_hides_an_executed_device_write(monkeypatch):
    """states() fold (step 4): a refuse_ticket for a known ticket overwrites the row whatever came
    before. _settle_tickets reads the chain, then writes its void records — not atomically. If a
    device-write ticket's `write` record lands between END's read and END's void, the final row is
    REFUSED 'ended' although the bytes WERE written to the device. (The window is widened here by
    delaying END between its read and its write; the interleaving itself needs no privilege.
    The natural window: a writer's append takes LOCK_EX and so queues behind END's LOCK_SH read,
    landing right after it, and END then writes its voids one by one, each re-verifying the whole
    chain — see test_OK_end_time_on_a_large_chain_… for the measured span.)"""
    info = _start()
    ok, why, t = E.issue("hid:inject", "10.0.0.42", payload=b"STRING x\n", kind="ip")
    assert ok, why
    orig = E._open_tickets
    gate = threading.Event()
    wrote = threading.Event()

    def slow_open(ch):
        r = orig(ch)
        gate.set()
        wrote.wait(5)                  # the write record lands now, after END's read
        return r
    monkeypatch.setattr(E, "_open_tickets", slow_open)
    port = _SlowPort(0.0)
    # the write's re-check passed just before END published `expired`; it lands right after
    # END's read of the chain
    th = threading.Thread(target=lambda: (gate.wait(5), _redeem_write_ignoring_gate(t, port), wrote.set()))
    th.start()
    E.end()
    th.join(10)
    assert port.data == b"STRING x\n"                                    # the bytes went out
    recs = [r for r in _recs(info["path"]) if r.get("ticket") == t.id]
    seq = [(r["event"], r.get("by", "")) for r in recs]
    print(seq)
    assert seq == [("issue", ""), ("write", "")]          # RA-CL3d: N17 — no void after a write
    rows = chain.Chain.open(info["id"]).states()
    assert [r["state"] for r in rows] == ["EXECUTED"]


def _redeem_write_ignoring_gate(t, port):
    """executor.write with the redeem done as if its re-check had passed a moment before END
    published `expired` (the re-check-to-write window): only the gate's verdict is pinned, the
    executor's own bookkeeping and record() are the real ones."""
    import executor
    entry = executor._ISSUED[t.id]
    real = entry["recheck"]
    entry["recheck"] = lambda: (True, "passed before END")
    try:
        return executor.write(t, port, "hid0")
    finally:
        entry["recheck"] = real


# ============================================================== 2d: txguard bench across END (child)
def test_OK_child_txguard_bench_ticket_across_end_not_claimed(tmp_path):
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        p = _popen("""
            import txguard as G
            ok, why, t, _p = G.issue_ticket('bench', ['hackrf_transfer','-t','x','-f','915000000',
                '-s','2000000','-x','0'], 915_000_000,
                settings={'tx_enabled': True, 'bench_conducted_ack': True}, sample_rate=2_000_000)
            assert ok, why
            h = executor.start(t, spawner=SP(['sleep', '1.5']))
            say('STARTED', t.id)
            h.wait(10)
            say('DONE', h.stopped, h.exit_code)
        """, env)
        line = p.stdout.readline()
        assert line.startswith("STARTED"), line + p.stderr.read()
        tid = line.split()[1]
        time.sleep(0.2)
        E.end()
        out, err = p.communicate(timeout=30)
    finally:
        pub.close()
    print(out, err[-400:])
    recs = [r for r in _recs(info["path"]) if r.get("ticket") == tid]
    assert not any(r.get("by") == "end" for r in recs)
    assert [r["event"] for r in recs] in (["issue", "spawn", "exit"], ["issue", "spawn", "kill", "exit"])


# ============================================================== 2e: END with an unusable chain
@pytest.mark.parametrize("how", ["tamper", "perms", "unwritable"])
def test_OK_end_completes_when_the_chain_is_broken(how, monkeypatch):
    import executor
    import netpent
    info = _start()
    ok, why, t = netpent.prepare("portscan", "10.0.0.51")
    h = executor.start(t, spawner=lambda a: subprocess.Popen(["sleep", "30"], stdout=subprocess.PIPE,
                                                               start_new_session=True))
    if how == "tamper":
        raw = open(info["path"], "rb").read().replace(b"10.0.0.51", b"10.0.0.99", 1)
        open(info["path"], "wb").write(raw)
    elif how == "perms":
        os.chmod(info["path"], 0o644)
    else:
        monkeypatch.setattr(chain.Chain, "record",
                            lambda self, *a, **k: (_ for _ in ()).throw(chain.ChainError("ro")))
    t0 = time.monotonic()
    assert E.end() == "job"
    dt = time.monotonic() - t0
    h.wait(10)
    print(how, "END %.2fs" % dt)
    assert dt < E.END_DRAIN_S + 4.5               # hub kill (TERM) + drain at most
    assert not h.running() and not E.is_active()


def test_OK_end_time_on_a_large_chain_with_many_void_tickets(monkeypatch):
    """END re-verifies the whole chain every 50 ms and once per record it writes. With 5000
    records and 20 issued-never-used tickets, how long does END take?"""
    import netpent
    info = _start()
    ch = chain.for_id(info["id"])
    for i in range(5000):
        ch.record("note", i=i)
    for i in range(20):
        ok, why, _t = netpent.prepare("portscan", "10.0.0.%d" % (100 + i))
        assert ok, why
    t_read = []
    orig = E._open_tickets
    monkeypatch.setattr(E, "_open_tickets", lambda ch: (orig(ch), t_read.append(time.time()))[0])
    t0 = time.monotonic()
    E.end()
    dt = time.monotonic() - t0
    print("END on 5000+ records, 20 void tickets: %.2fs" % dt)
    recs = _recs(info["path"])
    names = [r["event"] for r in recs]
    assert names[-1] == "engagement.close" and names.count("refuse_ticket") == 20
    voids = [r["t"] for r in recs if r.get("by") == "end"]
    print("END read -> last void record span: %.2fs" % (voids[-1] - t_read[0]))
    assert dt < 10


# ============================================================== 3: binding attacks
def test_OK_stopped_child_misses_rollover_kill_exit_go_to_alpha_not_bravo(tmp_path):
    """A bound child is SIGSTOPped across END alpha + START bravo (same scope). RA-CL3d (owner
    decision N16): END kills the stopped child's process (pid + start match) and records `kill`
    "orphan at END" (verified_gone) in alpha before close; after close alpha gets only the child's
    `exit` (no second kill). Originally: When the child resumes, its re-check (bound to alpha) fails
    under bravo: the process is killed, kill + exit land in ALPHA (after its close), bravo sees
    nothing, no session chain."""
    alpha = _start("alpha")
    pub, env = _bound_env(tmp_path)
    try:
        p = _popen(CHILD_RUN % ("10.0.0.61", "10.0.0.61", "['sleep','30']"), env)
        line = p.stdout.readline()
        assert line.startswith("STARTED"), line + p.stderr.read()
        proc = int(line.split()[1])
        p.send_signal(signal.SIGSTOP)
        E.end()
        ok, why = E.start("bravo", "ROE-2", ["10.0.0.0/24"], OP)
        assert ok, why
        bravo = E.chain_info()
        p.send_signal(signal.SIGCONT)
        out, err = p.communicate(timeout=30)
    finally:
        pub.close()
    print(out, err[-400:])
    a = _recs(alpha["path"])
    names = [r["event"] for r in a]
    close = names.index("engagement.close")
    print("alpha", [(r["event"], r.get("by", "")) for r in a])
    ek = [r for r in a if r.get("by") == "end"]
    assert [(r["event"], r["reason"], r["verified_gone"], r["pid"]) for r in ek] == [
        ("kill", "orphan at END", True, proc)] and ek[0]["seq"] < close
    tail = a[close + 1:]
    # RA-CL3d: the child's exit follows; in ~half the runs its sweep also records a kill of the
    # already-dead process after that exit (RA-CL3d N21) — not a second kill BY END
    assert [r["event"] for r in tail] in (["exit"], ["exit", "kill"]), tail
    print("post-close", tail)
    assert tail[0]["exit_code"] in (-15, -9)          # killed by a signal: true
    assert not any(r.get("ticket") for r in _recs(bravo["path"]))
    assert "SESS None" in out and not _alive(proc)


def test_OK_bound_chain_deleted_before_exit_nothing_misfiled(tmp_path):
    """A child's ticket chain (alpha) is deleted while its process runs; END/START bravo; the
    child's kill/exit cannot be written to alpha and must not land in bravo or a session chain."""
    alpha = _start("alpha")
    pub, env = _bound_env(tmp_path)
    try:
        p = _popen(CHILD_RUN % ("10.0.0.71", "10.0.0.71", "['sleep','30']"), env)
        line = p.stdout.readline()
        assert line.startswith("STARTED"), line + p.stderr.read()
        p.send_signal(signal.SIGSTOP)
        E.end()
        for suf in (".jsonl", ".key", ".head"):
            path = os.path.splitext(alpha["path"])[0] + suf
            if os.path.exists(path):
                os.unlink(path)
        ok, why = E.start("bravo", "ROE-2", ["10.0.0.0/24"], OP)
        assert ok, why
        bravo = E.chain_info()
        p.send_signal(signal.SIGCONT)
        out, err = p.communicate(timeout=30)
    finally:
        pub.close()
    print(out, err[-400:])
    assert not any(r.get("ticket") for r in _recs(bravo["path"]))
    assert "SESS None" in out
    assert not _sessions(os.path.dirname(bravo["path"]))


# ============================================================== 4: states() fold
def test_OK_fold_does_not_hide_a_later_running_or_executed():
    c = chain.Chain.create(name="fold")
    c.record("authorize", action="net:portscan", target="10.0.0.1")
    c.record("issue", ticket="a" * 32, label="net:portscan", target="10.0.0.1")
    c.record("refuse_ticket", ticket="a" * 32, label="net:portscan", target="10.0.0.1",
             reason="engagement ended before the ticket was used — void", by="end")
    c.record("spawn", ticket="a" * 32, label="net:portscan", pid=1)
    assert [r["state"] for r in c.states()] == ["RUNNING"]
    c.record("exit", ticket="a" * 32, label="net:portscan", exit_code=0)
    assert [r["state"] for r in c.states()] == ["EXECUTED"]
    # a redeem refusal of a known ticket stays visible (folded into its row, with the reason)
    c.record("authorize", action="net:portscan", target="10.0.0.2")
    c.record("issue", ticket="b" * 32, label="net:portscan", target="10.0.0.2")
    c.record("refuse_ticket", ticket="b" * 32, label="net:portscan", target="10.0.0.2",
             reason="10.0.0.2 not in the engagement scope")
    rows = {r["target"]: (r["state"], r["detail"]) for r in c.states()}
    assert rows["10.0.0.2"] == ("REFUSED", "scope")
    # an UNKNOWN ticket's refusal is still its own row
    c.record("refuse_ticket", ticket="c" * 32, label="net:x", target="10.0.0.3", reason="stale")
    assert ("REFUSED", "stale") in [(r["state"], r["detail"]) for r in c.states()]
