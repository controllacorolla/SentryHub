"""CL3-fix2 — close RA-CL3b B3 (blocking) and N14.

B3  Hub END while a bound child's gated process runs: the child's kill + exit went to a fresh
    per-child session chain; the engagement chain ended `... spawn, engagement.close` and the row
    stayed RUNNING forever.
N14 A ticket issued before START (session chain) that exited after START wrote its exit into the
    engagement chain: a phantom EXECUTED row the engagement never authorized.

Fix: a ticket is bound to the chain it was ISSUED under (executor entry["chain"]); every later
record for it goes there by id. END waits (bounded) for every running ticket's kill/exit, then
records a kill (RUNNING) or a void refuse_ticket (ISSUED) for anything still open — all BEFORE
engagement.close. An engagement ticket is void once the engagement it was issued under is gone,
even if a new engagement covers the same target.
"""
import json
import os
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
import txguard as G  # noqa: E402

OP = "KD0ABC"


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
    return E.chain_info()


def _recs(path):
    with open(path, "rb") as fh:
        return [json.loads(x) for x in fh.read().splitlines() if x.strip()]


def _sessions(d):
    return sorted(f for f in os.listdir(d) if "-session-" in f and f.endswith(".jsonl"))


def _sleeper(secs):
    return lambda argv: subprocess.Popen([sys.executable, "-c", "import time; time.sleep(%s)"
                                          % secs], start_new_session=True,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True)


_CHILD = (
    "import os, sys, time, subprocess, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']\n"
    "import engagement as E, executor, chain\n"
    "E._profile_operator = lambda: 'KD0ABC'\n"
    "ALLOWED_PROGRAMS = frozenset({'nmap'})\n"
    "def say(*a):\n"
    "    print(*a); sys.stdout.flush()\n")


def _bound_child(tmp_path, code):
    import gatestate
    import suite
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    env = gatestate.child_env(pub.path, base=dict(os.environ))
    env["PYTHONPATH"] = SUITE_DIR
    env["PALISADE_TEST_DATA"] = suite.DATA
    env["PALISADE_OFFLINE"] = "1"
    env.pop("SUITE_TX_LOCK", None)
    p = subprocess.Popen([sys.executable, "-c", _CHILD + textwrap.dedent(code)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return pub, p


# ============================================================================ B3 (the PoC)
def test_b3_end_while_a_bound_childs_process_runs_records_kill_and_exit_before_close(tmp_path):
    """RA-CL3b PoC `test_DEFECT_end_while_a_bound_childs_process_runs_...`, inverted."""
    info = _start()
    G.arm(True)
    pub, p = _bound_child(tmp_path, """
        ok, why, t = E.issue('net:portscan', '10.0.0.7', argv=['nmap', '10.0.0.7'], kind='ip')
        assert ok, why
        h = executor.start(t, spawner=lambda a: subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(30)'], stdout=subprocess.PIPE,
            start_new_session=True))
        say('STARTED', h.proc.pid)
        h.wait(15)
        s = chain._SESSION['chain']
        say('STOPPED', h.stopped, 'EXIT', h.exit_code, 'SESS', s.id if s else None)
    """)
    try:
        line = p.stdout.readline()
        assert line.startswith("STARTED"), line + p.stderr.read()
        child_proc = int(line.split()[1])
        time.sleep(0.3)
        assert E.end() == "job"
        out, err = p.communicate(timeout=30)
    finally:
        pub.close()
    assert "SESS None" in out, out + err[-800:]
    recs = _recs(info["path"])
    names = [r["event"] for r in recs]
    assert "kill" in names and "exit" in names, names
    close = names.index("engagement.close")
    kill = next(r for r in recs if r["event"] == "kill")
    ex = next(r for r in recs if r["event"] == "exit")
    # recorded by the CHILD (its own kill + real exit code), in the engagement chain, before close
    assert kill["seq"] < close and ex["seq"] < close, names
    assert kill["wpid"] == p.pid and ex["wpid"] == p.pid
    assert kill["pid"] == child_proc
    assert ex["exit_code"] is not None and ex["exit_code"] != 0 and ex["stopped"]
    assert not any(r.get("by") == "end" for r in recs)          # nothing had to be papered over
    rows = chain.Chain.open(info["id"]).states()
    assert [r["state"] for r in rows if r["target"] == "10.0.0.7"] == ["KILLED"]
    assert not _sessions(os.path.dirname(info["path"]))


def test_b3_end_leaves_no_ticket_running_or_issued_even_without_confirmation(monkeypatch):
    """A child that died hard (SIGKILL, power) never records its exit; a ticket that was issued and
    never used never records anything. END still gives each an outcome, before engagement.close."""
    import netpent
    monkeypatch.setattr(E, "END_DRAIN_S", 0.3)
    info = _start()
    G.arm(True)
    G.unlock_session(True)
    ch = chain.for_id(info["id"])
    # a running ticket whose process will never report (simulates a SIGKILLed bound child)
    ch.record("issue", ticket="dead" * 8, label="net:portscan", target="10.0.0.8",
              issuer="engagement")
    ch.record("spawn", ticket="dead" * 8, label="net:portscan", pid=999999)
    # a ticket issued here and never redeemed
    ok, why, t = netpent.prepare("portscan", "10.0.0.9")
    assert ok, why
    states = {r["target"]: r["state"] for r in ch.states()}
    assert states == {"10.0.0.8": "RUNNING", "10.0.0.9": "ISSUED"}
    t0 = time.monotonic()
    E.end()
    assert time.monotonic() - t0 < 2.0                        # bounded wait
    recs = _recs(info["path"])
    names = [r["event"] for r in recs]
    assert names[-1] == "engagement.close"
    by_end = [r for r in recs if r.get("by") == "end"]
    assert sorted((r["event"], r["target"]) for r in by_end) == \
        [("refuse_ticket", "10.0.0.9"), ("unconfirmed", "10.0.0.8")]
    # RA-CL3c N16: END signalled nothing, so the orphan is UNCONFIRMED — never a false KILLED
    assert not any(r["event"] == "kill" for r in by_end)
    rows = chain.Chain.open(info["id"]).states()
    assert sorted((r["target"], r["state"]) for r in rows) == \
        [("10.0.0.8", "UNCONFIRMED"), ("10.0.0.9", "REFUSED")]  # one row each, none open
    assert not any(r["state"] in ("RUNNING", "ISSUED") for r in rows)


def test_b3_end_while_a_hub_process_runs_still_closes_last():
    import executor
    import netpent
    info = _start()
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    h = executor.start(t, spawner=_sleeper(30))
    E.end()
    h.wait(5)
    names = [r["event"] for r in _recs(info["path"])]
    assert names.index("kill") < names.index("exit") < names.index("engagement.close")
    assert names[-1] == "engagement.close"
    assert [r["state"] for r in chain.Chain.open(info["id"]).states()] == ["KILLED"]


def test_b3_a_ticket_from_alpha_is_void_under_bravo():
    """A ticket is bound to the engagement it was issued under. END alpha + START bravo with the
    same scope, inside the ticket TTL: redeeming it is refused, the refusal is in alpha's chain,
    and bravo's chain never sees the ticket."""
    import executor
    import netpent
    alpha = _start("alpha")
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    assert ok, why
    E.end()
    bravo = _start("bravo")
    with pytest.raises(executor.TicketRefused):
        executor.start(t, spawner=_sleeper(30))
    a = _recs(alpha["path"])
    assert [r["event"] for r in a if r.get("ticket") == t.id] == \
        ["issue", "refuse_ticket", "refuse_ticket"]               # voided at END, refused at redeem
    assert not any(r.get("ticket") == t.id for r in _recs(bravo["path"]))


def test_b3_a_rollover_the_child_never_saw_still_kills_the_process():
    """If a bound child's sweep misses the END→START gap, the process must not keep running under
    the new engagement: the re-check is bound to the chain the ticket was issued under."""
    import executor
    import netpent
    _start("alpha")
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    entry = executor._ISSUED[t.id]
    assert entry["recheck"]()[0]
    E._ENG["chain"] = "20990101-000000-deadbeef-bravo"          # same scope, another engagement
    ok, why = entry["recheck"]()
    assert not ok and "engagement changed" in why


def test_b3_end_does_not_claim_to_kill_a_txguard_ticket_it_does_not_end(monkeypatch):
    """END kills engagement tickets only. A bench TX ticket (txguard's gate, not the engagement's)
    issued while the engagement was open keeps running; END must not write a false `kill` for it,
    and its real exit still lands in the chain it was issued under."""
    import executor
    monkeypatch.setattr(E, "END_DRAIN_S", 0.3)
    info = _start()
    G.arm(True)
    G.unlock_session(True)
    ok, why, t, _p = G.issue_ticket("bench", ["hackrf_transfer", "-t", "x", "-f", "915000000",
                                              "-s", "2000000", "-x", "0"], 915_000_000,
                                    settings={"tx_enabled": True, "bench_conducted_ack": True},
                                    sample_rate=2_000_000)
    assert ok, why
    h = executor.start(t, spawner=_sleeper(0.8))
    E.end()
    assert h.running()
    h.wait(10)
    recs = [r for r in _recs(info["path"]) if r.get("ticket") == t.id]
    assert [r["event"] for r in recs] == ["issue", "spawn", "exit"]
    assert not any(r.get("by") == "end" for r in recs)


# ============================================================================ RA-CL3c
def _orphan(start_new_session=True):
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            start_new_session=start_new_session, stdout=subprocess.DEVNULL)


def test_n16_end_kills_an_orphan_whose_pid_and_start_time_match(monkeypatch):
    """Owner decision (N16 option B): a bound child died after spawning (SIGKILL) and never
    reported. Its gated process is still running in its own session. pid + start time match the
    spawn record -> END kills it, verifies it gone, and records `kill` "orphan at END"."""
    import gatestate
    monkeypatch.setattr(E, "END_DRAIN_S", 0.2)
    info = _start()
    ch = chain.for_id(info["id"])
    p = _orphan()
    try:
        ps = gatestate.proc_start(p.pid)
        assert ps
        ch.record("issue", ticket="o1", label="net:portscan", target="10.0.0.6",
                  issuer="engagement")
        ch.record("spawn", ticket="o1", label="net:portscan", pid=p.pid, pstart=ps)
        E.end()
        assert p.wait(5) is not None                         # really gone
        recs = [r for r in _recs(info["path"]) if r.get("ticket") == "o1"]
        k = recs[-1]
        assert (k["event"], k["reason"], k["by"], k["pid"], k["verified_gone"]) == \
            ("kill", "orphan at END", "end", p.pid, True)
        names = [r["event"] for r in _recs(info["path"])]
        assert names[-1] == "engagement.close" and k["seq"] < names.index("engagement.close")
        assert [r["state"] for r in chain.Chain.open(info["id"]).states()] == ["KILLED"]
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(5)


def test_n16_end_never_signals_a_pid_whose_start_time_does_not_match(monkeypatch):
    """Same orphan, but the logged start time does not match the live pid (a recycled pid): END
    sends NO signal and records UNCONFIRMED — never KILLED."""
    monkeypatch.setattr(E, "END_DRAIN_S", 0.2)
    info = _start()
    ch = chain.for_id(info["id"])
    p = _orphan()
    try:
        ch.record("issue", ticket="o2", label="net:portscan", target="10.0.0.6",
                  issuer="engagement")
        ch.record("spawn", ticket="o2", label="net:portscan", pid=p.pid, pstart="linux:1")
        E.end()
        time.sleep(0.3)
        assert p.poll() is None                               # untouched
        recs = [r for r in _recs(info["path"]) if r.get("ticket") == "o2"]
        assert [r["event"] for r in recs] == ["issue", "spawn", "unconfirmed"]
        assert "does not match" in recs[-1]["reason"]
        assert [r["state"] for r in chain.Chain.open(info["id"]).states()] == ["UNCONFIRMED"]
    finally:
        p.kill()
        p.wait(5)


def test_n16_spawn_records_the_process_start_time():
    import executor
    import gatestate
    import netpent
    info = _start()
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    h = executor.start(t, spawner=_sleeper(30))
    try:
        sp = [r for r in _recs(info["path"]) if r["event"] == "spawn"][-1]
        assert sp["pid"] == h.proc.pid and sp["pstart"] == gatestate.proc_start(h.proc.pid)
        assert sp["pstart"]
    finally:
        h.stop("test")


def test_n16_a_late_exit_overrides_unconfirmed():
    """If the orphan does report after END, its real outcome replaces UNCONFIRMED."""
    ch = chain.Chain.create(cid="n16-1")
    ch.record("issue", ticket="t1", label="x", target="y", issuer="engagement")
    ch.record("spawn", ticket="t1", label="x", pid=4242)
    ch.record("unconfirmed", ticket="t1", label="x", reason="engagement ended", by="end")
    assert [r["state"] for r in ch.states()] == ["UNCONFIRMED"]
    ch.record("exit", ticket="t1", label="x", exit_code=0, stopped=None)
    assert [(r["state"], r["detail"]) for r in ch.states()] == [("EXECUTED", "exit 0")]


def test_n17_end_never_voids_a_ticket_used_after_it_looked(monkeypatch):
    """PoC: END read the chain, a device write landed, END then wrote its void anyway and the trail
    showed REFUSED for bytes that were sent. The void is now conditional under the exclusive lock,
    and a refusal can never replace an outcome in the trail."""
    monkeypatch.setattr(E, "END_DRAIN_S", 0.1)
    info = _start()
    ch = chain.for_id(info["id"])
    ch.record("issue", ticket="w1", label="hid:type", target="10.0.0.3", issuer="engagement")
    real = E._open_tickets

    def stale_then_write(c):
        snap = real(c)                                # END's view: w1 unused ...
        c.record("write", ticket="w1", bytes=12)       # ... then the write lands
        return snap
    monkeypatch.setattr(E, "_open_tickets", stale_then_write)
    E.end()
    recs = _recs(info["path"])
    assert [r["event"] for r in recs if r.get("ticket") == "w1"] == ["issue", "write"]
    assert [(r["state"], r["detail"]) for r in chain.Chain.open(info["id"]).states()] == \
        [("EXECUTED", "12 bytes")]


def test_n17_a_refusal_never_hides_an_outcome_in_the_trail():
    ch = chain.Chain.create(cid="n17-2")
    ch.record("issue", ticket="t2", label="x", target="y")
    ch.record("write", ticket="t2", label="x", bytes=3)
    ch.record("refuse_ticket", ticket="t2", label="x", reason="engagement ended")
    assert [r["state"] for r in ch.states()] == ["EXECUTED"]


def test_n19_end_writes_nothing_for_a_process_its_child_already_killed(monkeypatch):
    """The child recorded its kill but its exit is slow: END must not add a second kill."""
    monkeypatch.setattr(E, "END_DRAIN_S", 0.2)
    info = _start()
    ch = chain.for_id(info["id"])
    ch.record("issue", ticket="k1", label="net:portscan", target="10.0.0.4", issuer="engagement")
    ch.record("spawn", ticket="k1", label="net:portscan", pid=4243)
    ch.record("kill", ticket="k1", label="net:portscan", reason="gate closed", pid=4243)
    E.end()
    recs = [r for r in _recs(info["path"]) if r.get("ticket") == "k1"]
    assert [r["event"] for r in recs] == ["issue", "spawn", "kill"]
    assert [r["state"] for r in chain.Chain.open(info["id"]).states()] == ["KILLED"]


# ============================================================================ N14
def test_n14_a_ticket_from_before_start_keeps_its_exit_in_the_session_chain():
    """RA-CL3b PoC `test_DEFECT_ticket_from_before_START_exits_into_the_engagement_chain`,
    inverted: a bench TX ticket (no engagement) whose process ends after START records its exit in
    the session chain it was issued under; the engagement chain never sees it."""
    import executor
    G.arm(True)
    G.unlock_session(True)
    ok, why, t, _p = G.issue_ticket("bench", ["hackrf_transfer", "-t", "x", "-f", "915000000",
                                              "-s", "2000000", "-x", "0"], 915_000_000,
                                    settings={"tx_enabled": True, "bench_conducted_ack": True},
                                    sample_rate=2_000_000)
    assert ok, why
    sess = chain.current(create_session=False)
    assert sess is not None
    h = executor.start(t, spawner=_sleeper(0.8))
    info = _start("eng")
    h.wait(10)
    assert h.exit_code == 0
    eng = _recs(info["path"])
    assert not any(r.get("ticket") == t.id for r in eng), [r["event"] for r in eng]
    assert not any(r.get("ticket") == t.id for r in chain.Chain.open(info["id"]).states())
    s = [r for r in _recs(sess.path) if r.get("ticket") == t.id]
    assert [r["event"] for r in s] == ["issue", "spawn", "exit"]
    assert s[-1]["exit_code"] == 0
    assert [(r["state"], r["detail"]) for r in chain.Chain.open(sess.id).states()
            if r["ticket"] == t.id] == [("EXECUTED", "exit 0")]


def test_executor_never_falls_back_to_another_chain_when_the_bound_one_is_gone(monkeypatch):
    """A ticket's later records go to ITS chain or nowhere — never misfiled into whatever chain is
    current (that is how N14 produced phantom rows)."""
    import executor
    import netpent
    info = _start("alpha")
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    cid = executor._ISSUED[t.id]["chain"]
    assert cid == info["id"]

    def gone(c):
        raise chain.ChainError("gone")
    monkeypatch.setattr(chain, "for_id", gone)
    assert executor.record("exit", chain_id=cid, ticket=t.id, exit_code=0) is None
    assert chain._SESSION["chain"] is None
