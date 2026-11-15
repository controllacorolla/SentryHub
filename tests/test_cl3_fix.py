"""CL3-fix — close RA-CL3: B1 B2 (blocking), N1 N2 N3 N4 N5 N6 N7 N8 N10.

B1  a bound child's issue/spawn/exit went to a private session chain, never the engagement's
B2  a cached chain object outlived its engagement: a child recorded bravo's authorizations in alpha
N1  .head was an unkeyed copy of the last hash → truncate + rewrite head verified without the key
N2  chain id not bound into the HMAC → whole-file swap verified under another id
N3  an append that failed after the line was written left an orphan → chain bricked forever
N4  readers did not lock → spurious "head ≠ last" against a concurrent writer
N5  record() dropped a caller's pid → spawn/kill records named the hub's pid
N6  short key accepted; jsonl/head permissions unchecked on open
N7  engagement.start raised (UnicodeEncodeError) instead of (False, why)
N8  chain id with '/' or '..' opened a path outside DATA/engagements
N10 AUTHORIZED and its ticket were two rows; a ticket refused at redeem stayed ISSUED
"""
import json
import os
import subprocess
import sys
import threading

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


def _lines(path):
    with open(path) as fh:
        return [json.loads(x) for x in fh if x.strip()]


def _rewrite(path, lines):
    with open(path, "w") as fh:
        for rec in lines:
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")


def _child_env(pub, tmp_path):
    import gatestate
    import suite
    env = gatestate.child_env(pub.path, base=dict(os.environ))
    env["PYTHONPATH"] = SUITE_DIR
    env["PALISADE_TEST_DATA"] = suite.DATA
    env["PALISADE_OFFLINE"] = "1"
    return env


_CHILD_PRELUDE = (
    "import os, sys, subprocess, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']\n"
    "import engagement as E, executor, netpent, txguard\n")


# ============================================================================ B1
def test_b1_bound_child_executions_land_in_the_engagement_chain(tmp_path):
    """PoC: a Hub child's issue/spawn/exit went to its own session chain; the engagement chain
    showed AUTHORIZED forever."""
    import gatestate
    info = _start()
    G.arm(True)
    G.unlock_session(True)
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    try:
        code = _CHILD_PRELUDE + (
            "ok, why, t = netpent.prepare('portscan', '10.0.0.9')\n"
            "assert ok, why\n"
            "r = executor.run(t, spawner=lambda a: subprocess.Popen([sys.executable, '-c', "
            "'import sys; sys.exit(3)'], start_new_session=True, stdout=subprocess.PIPE, "
            "stderr=subprocess.STDOUT, text=True))\n"
            "print('EXIT', r.exit_code)\n")
        out = subprocess.run([sys.executable, "-c", code], env=_child_env(pub, tmp_path),
                             capture_output=True, text=True, timeout=60)
        assert out.stdout.strip().endswith("EXIT 3"), out.stdout + out.stderr
    finally:
        pub.close()
    ch = chain.Chain.open(info["id"])
    evs = [(r["event"], r.get("target")) for r in ch.records]
    assert ("authorize", "10.0.0.9") in evs and ("issue", "10.0.0.9") in evs
    assert any(r["event"] == "spawn" for r in ch.records)
    ex = [r for r in ch.records if r["event"] == "exit"]
    assert ex and ex[-1]["exit_code"] == 3 and ex[-1]["wpid"] != os.getpid()
    states = ch.states()
    assert [(r["action"], r["state"], r["detail"]) for r in states] == \
        [("net:portscan", "FAILED", "exit 3")]
    # and no private session chain was created by the child for this
    import glob
    import suite
    sessions = glob.glob(os.path.join(suite.DATA, "engagements", "*session*.jsonl"))
    assert sessions == [], sessions


# ============================================================================ B2
def test_b2_child_follows_an_engagement_rollover(tmp_path):
    """PoC: END alpha, START bravo → a running child authorized against bravo's scope but recorded
    into alpha's chain; bravo had no record."""
    import gatestate
    import time
    alpha = _start("alpha", ("10.0.0.0/24",))
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    try:
        code = _CHILD_PRELUDE + (
            "import time\n"
            "print('A', E.authorize_action('net:portscan', '10.0.0.5')[0]); sys.stdout.flush()\n"
            "open(os.environ['SYNC'] + '.ready', 'w').close()\n"
            "while not os.path.exists(os.environ['SYNC'] + '.go'): time.sleep(0.05)\n"
            "print('B', E.authorize_action('net:portscan', '10.0.1.5')[0]); sys.stdout.flush()\n")
        env = _child_env(pub, tmp_path)
        env["SYNC"] = str(tmp_path / "sync")
        p = subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        t0 = time.time()
        while not os.path.exists(str(tmp_path / "sync.ready")) and time.time() - t0 < 30:
            time.sleep(0.05)
        assert E.end() == "alpha"
        bravo = _start("bravo", ("10.0.1.0/24",))
        pub.publish_from_engines()
        open(str(tmp_path / "sync.go"), "w").close()
        out, err = p.communicate(timeout=60)
        assert out.split() == ["A", "True", "B", "True"], out + err
    finally:
        pub.close()
    a = chain.Chain.open(alpha["id"]).records
    b = chain.Chain.open(bravo["id"]).records
    assert any(r["event"] == "authorize" and r["target"] == "10.0.0.5" for r in a)
    assert not any(r["event"] == "authorize" and r["target"] == "10.0.1.5" for r in a), \
        "bravo's authorization leaked into alpha's chain"
    assert any(r["event"] == "authorize" and r["target"] == "10.0.1.5"
               and r["engagement"] == "bravo" for r in b)


def test_b2_hub_rollover_routes_executor_records_to_the_new_chain():
    import executor
    import netpent
    alpha = _start("alpha")
    G.arm(True)
    G.unlock_session(True)
    assert E.end() == "alpha"
    bravo = _start("bravo")
    ok, why, t = netpent.prepare("portscan", "10.0.0.7")
    assert ok, why
    executor.run(t, spawner=lambda a: subprocess.Popen([sys.executable, "-c", "pass"],
                                                       start_new_session=True,
                                                       stdout=subprocess.PIPE,
                                                       stderr=subprocess.STDOUT, text=True))
    assert not any(r["event"] in ("issue", "spawn", "exit")
                   for r in chain.Chain.open(alpha["id"]).records)
    assert [r["event"] for r in chain.Chain.open(bravo["id"]).records][-3:] == \
        ["issue", "spawn", "exit"]


# ============================================================================ N1 / N2
def test_n1_truncate_plus_head_rewrite_without_key_fails():
    info = _start()
    for t in ("10.0.0.5", "10.0.0.6", "10.0.0.7"):
        assert E.authorize_action("net:portscan", t)[0]
    ch = chain.Chain.open(info["id"])
    lines = _lines(ch.path)
    _rewrite(ch.path, lines[:-2])
    # the forger copies the (now) last hash into the head, as the old unkeyed format allowed
    with open(ch.head_path, "w") as fh:
        fh.write("%d %s %s" % (len(lines) - 2, lines[-3]["h"], "0" * 64))
    with pytest.raises(chain.ChainError, match="head"):
        chain.Chain.open(info["id"])


def test_n2_whole_chain_swap_fails_under_the_other_id(tmp_path):
    import shutil
    a = chain.Chain.create(cid="aaaa-1", directory=str(tmp_path))
    a.record("authorize", action="x", target="1")
    b = chain.Chain.create(cid="bbbb-2", directory=str(tmp_path))
    b.record("authorize", action="y", target="2")
    for ext in (".jsonl", ".key", ".head"):
        shutil.copy(os.path.join(str(tmp_path), "aaaa-1" + ext),
                    os.path.join(str(tmp_path), "bbbb-2" + ext))
    with pytest.raises(chain.ChainError):
        chain.Chain.open("bbbb-2", directory=str(tmp_path))


# ============================================================================ N3
def test_n3_failed_append_is_rolled_back_and_the_chain_still_verifies(monkeypatch):
    info = _start()
    ch = chain.Chain.open(info["id"])
    real = chain._write_private
    calls = {"n": 0}

    def boom(path, data):
        if path.endswith(".head"):
            raise OSError(28, "No space left on device")
        return real(path, data)
    monkeypatch.setattr(chain, "_write_private", boom)
    with pytest.raises(chain.ChainError, match="rolled back"):
        ch.record("authorize", action="x", target="y")
    monkeypatch.setattr(chain, "_write_private", real)
    assert chain.Chain.open(info["id"]).verify()[0]
    assert len(_lines(ch.path)) == 1                         # only engagement.open
    # and the gate refused, nothing in the trail, and a later authorize works again
    assert E.actions() == []
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    assert chain.Chain.open(info["id"]).verify()[0]
    assert calls == {"n": 0}


# ============================================================================ N4
def test_n4_concurrent_readers_never_see_spurious_tamper():
    info = _start()
    ch = chain.Chain.open(info["id"])
    errors = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            ok, why = chain.Chain.open(info["id"]).verify()
            if not ok:
                errors.append(why)

    ts = [threading.Thread(target=reader) for _ in range(3)]
    for t in ts:
        t.start()
    for i in range(150):
        ch.record("authorize", action="x", target=str(i))
    stop.set()
    for t in ts:
        t.join(10)
    assert errors == [], errors[:3]


# ============================================================================ N5
def test_n5_spawn_and_kill_records_carry_the_child_pid():
    import executor
    import netpent
    info = _start()
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    h = executor.start(t, spawner=lambda a: subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
    pid = h.proc.pid
    assert pid != os.getpid()
    h.stop("test")
    h.wait(5)
    recs = chain.Chain.open(info["id"]).records
    sp = [r for r in recs if r["event"] == "spawn"][-1]
    ki = [r for r in recs if r["event"] == "kill"][-1]
    assert sp["pid"] == pid and ki["pid"] == pid
    assert sp["wpid"] == os.getpid()
    assert any(r["state"] == "KILLED" for r in chain.Chain.open(info["id"]).states())


# ============================================================================ N6 / N7 / N8
def test_n6_short_key_and_loose_permissions_are_refused(tmp_path):
    c = chain.Chain.create(cid="k-1", directory=str(tmp_path))
    with open(c.key_path, "wb") as fh:
        fh.write(b"\x01" * 20)
    with pytest.raises(chain.ChainError, match="key"):
        chain.Chain.open("k-1", directory=str(tmp_path))
    c = chain.Chain.create(cid="k-2", directory=str(tmp_path))
    os.chmod(c.path, 0o666)
    with pytest.raises(chain.ChainError, match="private"):
        chain.Chain.open("k-2", directory=str(tmp_path))
    c = chain.Chain.create(cid="k-3", directory=str(tmp_path))
    os.chmod(c.head_path, 0o644)
    with pytest.raises(chain.ChainError, match="private"):
        chain.Chain.open("k-3", directory=str(tmp_path))


def test_n7_start_never_raises_on_an_unencodable_name():
    ok, why = E.start("bad\udcff", "ROE-1", ["10.0.0.0/24"], OP)
    assert isinstance(ok, bool)
    if ok:                                            # surrogatepass made it representable
        assert E.is_active() and E.chain_info()["verified"]
    else:
        assert not E.is_active()


@pytest.mark.parametrize("cid", ["../../x", "a/b", "..", "/etc/passwd", "", "x" * 120, "a b"])
def test_n8_chain_ids_with_path_or_junk_are_refused(cid):
    assert not chain.valid_id(cid)
    with pytest.raises(chain.ChainError):
        chain.for_id(cid)
    with pytest.raises(chain.ChainError):
        chain.Chain.open(cid)


def test_n8_shared_state_with_a_hostile_chain_id_fails_closed(monkeypatch):
    _start()
    e = dict(E._eng())
    e["chain"] = "../../x"
    monkeypatch.setattr(E, "_eng", lambda: e)
    assert E._active_chain() is None
    ok, why = E.authorize_action("net:portscan", "10.0.0.5")
    assert not ok and "no durable record" in why


# ============================================================================ N10
def test_n10_one_row_per_action_and_redeem_refusals_are_visible():
    import executor
    import netpent
    info = _start()
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    rows = E.chain_states()
    assert [(r["state"], r["ticket"] is not None) for r in rows] == [("ISSUED", True)]
    G.arm(False)                                      # gate closes before redeem
    G.arm(True)
    G.unlock_session(True)
    E.end()                                           # engagement gone -> ticket refused at redeem
    with pytest.raises(executor.TicketRefused):
        executor.start(t, spawner=lambda a: None)
    recs = chain.Chain.open(info["id"]).records
    assert any(r["event"] == "refuse_ticket" and r["ticket"] == t.id for r in recs) or \
        any(r["event"] == "refuse_ticket" for r in chain.current().records)
