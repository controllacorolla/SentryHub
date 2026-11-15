"""RA-CL3b PoCs — attacks on the CL3-fix routing, head MAC, rollback and readers (tip 13c04a4).
OK_* = the fix holds. DEFECT_* = the defect reproduces (the test PASSES when it does).
Run: SUITE=<worktree> pytest -q poc_ra_cl3b.py"""
import json
import os
import shutil
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
    return E.chain_info()


def _recs(path):
    with open(path, "rb") as fh:
        return [json.loads(x) for x in fh.read().splitlines() if x.strip()]


def _sessions(d):
    return sorted(f for f in os.listdir(d) if "-session-" in f and f.endswith(".jsonl"))


def _bound_env(tmp_path):
    import gatestate
    import suite
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    env = gatestate.child_env(pub.path, base=dict(os.environ))
    env["PYTHONPATH"] = SUITE_DIR
    env["PALISADE_TEST_DATA"] = suite.DATA
    env.pop("SUITE_TX_LOCK", None)
    return pub, env


HDR = ("import os, sys, json, time, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']\n"
       "import engagement as E, executor, chain\n"
       "E._profile_operator=lambda: 'KD0ABC'\n"
       "import subprocess\nALLOWED_PROGRAMS=frozenset({'nmap'})\n"
       "SP=lambda real: (lambda argv: subprocess.Popen(real, stdout=subprocess.PIPE, start_new_session=True))\n"
       "def wait(p):\n"
       "    while not os.path.exists(p): time.sleep(0.02)\n"
       "def say(*a):\n"
       "    print(*a); sys.stdout.flush()\n")


def _popen(code, env):
    return subprocess.Popen([sys.executable, "-c", HDR + textwrap.dedent(code)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


# ============================================================== step 2: routing
def test_OK_bound_child_across_END_START_START(tmp_path):
    """alpha → END → (child refused, refusal to child's session chain) → START bravo → START
    charlie (refused, bravo open) → child authorizes into bravo only."""
    a = _start("alpha")
    pub, env = _bound_env(tmp_path)
    try:
        p = _popen("""
            say('A', E.authorize_action('net:portscan','10.0.0.7')[0])
            wait(%r); say('N', E.authorize_action('net:portscan','10.0.0.8')[0])
            wait(%r); say('B', E.authorize_action('net:portscan','10.0.0.9')[0])
        """ % (str(tmp_path / "f1"), str(tmp_path / "f2")), env)
        assert "A True" in p.stdout.readline()
        E.end()
        (tmp_path / "f1").write_text("1")
        assert "N False" in p.stdout.readline()
        b = _start("bravo")
        ok, why = E.start("charlie", "ROE-1", ["10.0.0.0/24"], OP)
        assert not ok
        (tmp_path / "f2").write_text("1")
        out, err = p.communicate(timeout=30)
        assert "B True" in out, err
    finally:
        pub.close()
    ra, rb = _recs(a["path"]), _recs(b["path"])
    assert [r["target"] for r in ra if r["event"] == "authorize"] == ["10.0.0.7"]
    assert [r["target"] for r in rb if r["event"] == "authorize"] == ["10.0.0.9"]
    assert not any(r.get("target") == "10.0.0.8" for r in ra + rb)
    assert chain.Chain.open(a["id"]).verify()[0] and chain.Chain.open(b["id"]).verify()[0]


def test_OK_child_started_before_the_engagement(tmp_path):
    """A child bound while NO engagement is open, then the hub starts one: the child's
    issue/spawn/exit go to the engagement chain."""
    pub, env = _bound_env(tmp_path)
    G.arm(True)
    try:
        p = _popen("""
            say('PRE', E.authorize_action('net:portscan','10.0.0.7')[0])
            wait(%r)
            ok, why, t = E.issue('net:portscan','10.0.0.7', argv=['nmap','10.0.0.7'], kind='ip')
            say('ISSUE', ok, why)
            r = executor.run(t, spawner=SP(['true']))
            say('EXIT', r.exit_code, chain.current().id)
        """ % str(tmp_path / "go"), env)
        assert "PRE False" in p.stdout.readline()
        info = _start("late")
        pub.publish_from_engines()
        (tmp_path / "go").write_text("1")
        out, err = p.communicate(timeout=30)
    finally:
        pub.close()
    assert "ISSUE True" in out and ("EXIT 0 %s" % info["id"]) in out, out + err
    ev = [r["event"] for r in _recs(info["path"])]
    assert ev.count("authorize") == 1 and "issue" in ev and "spawn" in ev and "exit" in ev


def test_DEFECT_ticket_from_before_START_exits_into_the_engagement_chain():
    """A TX-only bench ticket issued with no engagement (session chain) whose process is still
    running when an engagement STARTs: its exit lands in the ENGAGEMENT chain; the session chain
    never gets it. states() then shows an EXECUTED row the engagement never authorized."""
    import executor
    G.arm(True); G.unlock_session(True)
    ok, why, t, _p = G.issue_ticket("bench", ["hackrf_transfer", "-t", "x", "-f", "915000000",
                                              "-s", "2000000", "-x", "0"], 915_000_000,
                                    settings={"tx_enabled": True, "bench_conducted_ack": True},
                                    sample_rate=2_000_000)
    assert ok, why
    sess = chain.current(create_session=False)
    h = executor.start(t, spawner=lambda a: subprocess.Popen(["sleep", "0.8"],
                                                               stdout=subprocess.PIPE,
                                                               start_new_session=True))
    info = _start("eng")
    h.wait(5)
    eng = _recs(info["path"])
    print("ENG:", [(r["event"], r.get("label")) for r in eng])
    print("SESSION:", [r["event"] for r in _recs(sess.path)])
    assert any(r["event"] == "exit" and r.get("ticket") == t.id for r in eng)
    assert not any(r["event"] == "exit" for r in _recs(sess.path))
    rows = chain.Chain.open(info["id"]).states()
    print(rows)
    assert any(r.get("ticket") == t.id and r["state"] == "EXECUTED" for r in rows)


def test_OK_shared_state_names_an_unopenable_chain_child_refuses_no_session_fallback(tmp_path):
    """Hub publishes an engagement whose chain id the child cannot open (missing / bad key perms /
    tampered / hostile id). Child: authorize refuses, issue refuses, executor records raise,
    and NO session chain is created."""
    info = _start()
    G.arm(True)
    pub, env = _bound_env(tmp_path)
    d = os.path.dirname(info["path"])
    try:
        for case in ("missing", "keyperm", "tamper", "hostile"):
            st = E.export_state()
            if case == "missing":
                st["chain"] = "20990101-000000-deadbeef-nope"
            elif case == "hostile":
                st["chain"] = "../../x"
            elif case == "keyperm":
                os.chmod(os.path.join(d, info["id"] + ".key"), 0o644)
            elif case == "tamper":
                os.chmod(os.path.join(d, info["id"] + ".key"), 0o600)
                L = open(info["path"], "rb").read().splitlines()
                r = json.loads(L[0]); r["name"] = "evil"; L[0] = chain.canonical(r)
                bak = open(info["path"], "rb").read()
                open(info["path"], "wb").write(b"\n".join(L) + b"\n")
            pub.publish(True, False, st)
            p = _popen("""
                say('AUTH', E.authorize_action('net:portscan','10.0.0.7'))
                say('ISSUE', E.issue('net:portscan','10.0.0.7', argv=['nmap','10.0.0.7'], kind='ip')[:2])
                try:
                    chain.record('spawn', pid=1); say('REC ok')
                except Exception as e:
                    say('REC raised', type(e).__name__)
                say('SESS', chain._SESSION['chain'])
            """, env)
            out, err = p.communicate(timeout=30)
            print(case, out, err[-600:])
            assert "AUTH (False" in out and "ISSUE (False" in out, (case, out, err)
            assert "REC raised" in out and "SESS None" in out, (case, out)
            assert not _sessions(d), (case, _sessions(d))
            if case == "tamper":
                open(info["path"], "wb").write(bak)
    finally:
        pub.close()


def test_DEFECT_end_while_a_bound_childs_process_runs_kill_exit_leave_the_engagement_chain(tmp_path):
    """Hub END while a bound child's gated process runs. The hub's end() publishes 'expired' and
    then 'none' back-to-back; the child's executor sweeps every 250 ms, sees no engagement, and
    its kill + exit records route to a NEW per-child session chain. The engagement chain ends
    ... spawn, engagement.close — the row stays RUNNING forever."""
    info = _start()
    G.arm(True)
    pub, env = _bound_env(tmp_path)
    try:
        p = _popen("""
            ok, why, t = E.issue('net:portscan','10.0.0.7', argv=['nmap','10.0.0.7'], kind='ip')
            h = executor.start(t, spawner=SP(['sleep','30']))
            say('STARTED', ok, h.proc.pid)
            h.wait(10)
            time.sleep(0.3)
            s = chain._SESSION['chain']
            say('STOPPED', h.stopped, 'EXIT', h.exit_code, 'SESS', s.id if s else None)
        """, env)
        line = p.stdout.readline()
        assert "STARTED True" in line, line + p.stderr.read()
        time.sleep(0.3)
        E.end()
        out, err = p.communicate(timeout=30)
    finally:
        pub.close()
    print(line, out, err[-800:])
    eng = _recs(info["path"])
    names = [r["event"] for r in eng]
    print("ENG CHAIN:", names)
    d = os.path.dirname(info["path"])
    sess = _sessions(d)
    print("SESSIONS:", sess)
    assert "spawn" in names
    assert "kill" not in names and "exit" not in names
    assert sess
    sev = [r["event"] for r in _recs(os.path.join(d, sess[0]))]
    print("CHILD SESSION:", sev)
    assert "kill" in sev and "exit" in sev
    rows = chain.Chain.open(info["id"]).states()
    assert [r["state"] for r in rows if r["target"] == "10.0.0.7"] == ["RUNNING"]


def test_OK_end_while_a_hub_process_runs_kill_exit_before_close():
    import executor
    info = _start()
    G.arm(True)
    ok, why, t = E.issue("net:portscan", "10.0.0.5", argv=["nmap", "10.0.0.5"], kind="ip")
    h = executor.start(t, spawner=lambda a: subprocess.Popen(["sleep", "30"], stdout=subprocess.PIPE,
                                                               start_new_session=True))
    time.sleep(0.2)
    E.end()
    h.wait(5)
    names = [r["event"] for r in _recs(info["path"])]
    assert names.index("kill") < names.index("exit") < names.index("engagement.close")
    assert not _sessions(os.path.dirname(info["path"]))


HUB2 = """
import os, sys, json, time, subprocess, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']
import engagement as E, gatestate, chain
E._profile_operator=lambda: 'KD0ABC'
ok, why = E.start('bravo', 'ROE-2', ['10.0.0.0/24'], 'KD0ABC'); assert ok, why
pub = gatestate.Publisher(os.environ['HUB2_GATE'])
env = gatestate.child_env(pub.path, base=dict(os.environ))
code = os.environ['CHILD_CODE']
ps = [subprocess.Popen([sys.executable, '-c', code], env=env) for _ in range(3)]
rc = [p.wait(60) for p in ps]
print('HUB2', E.chain_info()['id'], rc); sys.stdout.flush()
pub.close()
"""


def test_OK_two_hubs_children_on_one_data_dir(tmp_path):
    """Hub 1 (this process, 'alpha') and hub 2 (subprocess, 'bravo'), same DATA dir, 3 bound
    children each, 20 authorizes per child. Each child's records land in its own hub's chain;
    both chains verify; no session chains."""
    a = _start("alpha")
    pub, env = _bound_env(tmp_path)
    child = HDR + ("for i in range(20): assert E.authorize_action('net:portscan','10.0.0.%d' % (i+1))[0]\n"
                   "say('CHILD', os.getpid(), chain.current().id)\n")
    env2 = dict(env)
    env2.pop("PALISADE_GATE_STATE", None); env2.pop("PALISADE_GATE_NONCE", None)
    env2["HUB2_GATE"] = str(tmp_path / "gate2.json")
    env2["CHILD_CODE"] = child
    try:
        h2 = subprocess.Popen([sys.executable, "-c", HUB2], env=env2, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
        mine = [subprocess.Popen([sys.executable, "-c", child], env=env, stdout=subprocess.PIPE,
                                 text=True) for _ in range(3)]
        outs = [m.communicate(timeout=90)[0] for m in mine]
        o2, e2 = h2.communicate(timeout=90)
    finally:
        pub.close()
    assert all(m.returncode == 0 for m in mine), outs
    assert "HUB2" in o2 and "[0, 0, 0]" in o2, o2 + e2
    bid = [l for l in o2.splitlines() if l.startswith("HUB2")][0].split()[1]
    d = os.path.dirname(a["path"])
    ra = _recs(a["path"]); rb = _recs(os.path.join(d, bid + ".jsonl"))
    assert sum(r["event"] == "authorize" for r in ra) == 60
    assert sum(r["event"] == "authorize" for r in rb) == 60
    assert all(r.get("engagement") == "alpha" for r in ra if r["event"] == "authorize")
    assert all(r.get("engagement") == "bravo" for r in rb if r["event"] == "authorize")
    assert chain.Chain.open(a["id"]).verify()[0] and chain.Chain.open(bid).verify()[0]
    assert not _sessions(d)


# ============================================================== step 3: head / rollback
def test_DEFECT_snapshot_rollback_without_the_key_verifies():
    """Copy jsonl+head at N records; later restore both. The head MAC binds (id,n,h) but not
    freshness, so the older snapshot verifies — every record after the snapshot is gone and
    nothing on the device notices. No key needed (only read access to two 0600 files)."""
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    hp = info["path"][:-6] + ".head"
    snap = (open(info["path"], "rb").read(), open(hp, "rb").read())
    for i in range(5):
        assert E.authorize_action("net:portscan", "10.0.0.%d" % (i + 10))[0]
    open(info["path"], "wb").write(snap[0]); open(hp, "wb").write(snap[1])
    ch = chain.Chain.open(info["id"])
    assert ch.verify()[0]
    assert not any(r.get("target") == "10.0.0.10" for r in ch.records)
    # and the running hub keeps appending on the rolled-back chain without complaint
    assert E.authorize_action("net:portscan", "10.0.0.99")[0]
    assert E.chain_info()["verified"]


def test_OK_fsync_of_the_jsonl_fails_rolled_back(monkeypatch):
    info = _start()
    real = os.fsync
    n0 = len(_recs(info["path"]))
    calls = {"n": 0}

    def boom(fd):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(28, "ENOSPC")
        return real(fd)
    monkeypatch.setattr(os, "fsync", boom)
    assert not E.authorize_action("net:portscan", "10.0.0.5")[0]
    monkeypatch.setattr(os, "fsync", real)
    assert len(_recs(info["path"])) == n0
    assert E.authorize_action("net:portscan", "10.0.0.6")[0]
    assert E.chain_info()["verified"]


def test_DEFECT_directory_fsync_failure_after_head_replace_bricks_the_chain(monkeypatch):
    """_write_private os.replace()s the new head, THEN fsyncs the directory. If that dir fsync
    fails, record() rolls the jsonl back — but the head on disk already says n+1. Every later
    open/append fails: the engagement is bricked (the N3 hazard, one step later)."""
    info = _start()
    real = os.fsync
    import stat as _st

    def boom(fd):
        if _st.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(5, "EIO")
        return real(fd)
    monkeypatch.setattr(os, "fsync", boom)
    ok, why = E.authorize_action("net:portscan", "10.0.0.5")
    assert not ok
    monkeypatch.setattr(os, "fsync", real)
    ok2, why2 = E.authorize_action("net:portscan", "10.0.0.6")
    print(why2)
    assert not ok2
    with pytest.raises(chain.ChainError, match="head says"):
        chain.Chain.open(info["id"])


KILLER = """
import os, sys, signal, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']
import chain
c = chain.Chain.open(sys.argv[1])
real = chain._write_private
def die(path, data):
    if path.endswith('.head'):
        os.kill(os.getpid(), signal.SIGKILL)
    return real(path, data)
chain._write_private = die
c.record('authorize', action='net:portscan', target='10.0.0.77')
"""


def test_DEFECT_sigkill_between_line_fsync_and_head_write_bricks_the_chain(tmp_path):
    """A writer SIGKILLed after its line is fsynced but before the head is replaced (power loss,
    OOM-kill, PANIC kill -9 of an app) leaves an orphan line. Reopen → ChainError forever: every
    authorize in every process refuses, the report refuses. No rollback runs (the process is
    dead) and there is no recovery path on open."""
    import suite
    info = _start()
    env = dict(os.environ, PYTHONPATH=SUITE_DIR, PALISADE_TEST_DATA=suite.DATA)
    p = subprocess.run([sys.executable, "-c", KILLER, info["id"]], env=env, capture_output=True)
    assert p.returncode == -signal.SIGKILL
    assert b"10.0.0.77" in open(info["path"], "rb").read()
    chain.reset_for_tests()
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])
    ok, why = E.authorize_action("net:portscan", "10.0.0.5")
    print(why)
    assert not ok


def test_sigkill_random_points_under_load(tmp_path):
    """SIGKILL a busy writer at random moments, 12 times; count how often the chain is left
    unopenable. (Measurement; asserts only that it ran.)"""
    import random
    import suite
    info = _start()
    env = dict(os.environ, PYTHONPATH=SUITE_DIR, PALISADE_TEST_DATA=suite.DATA)
    loop = ("import os,suite; suite.DATA=os.environ['PALISADE_TEST_DATA']\nimport chain,sys\n"
            "c=chain.Chain.open(sys.argv[1])\nwhile True: c.record('note', x='y'*200)\n")
    bricked = 0
    for i in range(12):
        p = subprocess.Popen([sys.executable, "-c", loop, info["id"]], env=env)
        time.sleep(0.25 + random.random() * 0.2)
        p.send_signal(signal.SIGKILL); p.wait()
        try:
            chain.Chain.open(info["id"])
        except chain.ChainError as e:
            bricked += 1
            print("bricked:", e)
            break
    print("bricked after", i + 1, "kills:", bricked)


def test_OK_readers_and_three_writer_processes(tmp_path):
    info = _start()
    pub, env = _bound_env(tmp_path)
    bad = 0
    n = 0
    try:
        ps = [_popen("for i in range(100): E.authorize_action('net:portscan','10.0.0.%d' % (i%200+1))\n",
                     env) for _ in range(3)]
        while any(p.poll() is None for p in ps):
            ci = E.chain_info(); n += 1
            if not ci["verified"]:
                bad += 1; print(ci["why"])
            E.chain_states()
        for p in ps:
            p.communicate()
    finally:
        pub.close()
    print("reads", n, "spurious", bad)
    assert bad == 0
    ch = chain.Chain.open(info["id"])
    assert sum(r["event"] == "authorize" for r in ch.records) == 300


def test_DEFECT_malformed_head_or_line_raises_non_chainerror_out_of_the_gate(tmp_path):
    """A head of '² h m' (str.isdigit() accepts it, int() does not) or a jsonl line that is
    valid JSON but not an object ('1') raises ValueError / AttributeError, not ChainError.
    _active_chain() catches only ChainError → in a process that has not cached the chain (a bound
    child, or after reset), authorize_action RAISES instead of returning (False, why)."""
    info = _start()
    hp = info["path"][:-6] + ".head"
    good_head = open(hp, "rb").read()
    open(hp, "w").write("² %s %s" % ("a" * 64, "b" * 64))
    chain.reset_for_tests()
    with pytest.raises(ValueError):
        E.authorize_action("net:portscan", "10.0.0.5")
    open(hp, "wb").write(good_head)
    raw = open(info["path"], "rb").read()
    open(info["path"], "wb").write(b"1\n" + raw)
    chain.reset_for_tests()
    with pytest.raises(AttributeError):
        E.authorize_action("net:portscan", "10.0.0.5")
    # chain_info (the panel) raises too → panel shows its UNKNOWN row, not NOT VERIFIED
    with pytest.raises(AttributeError):
        E.chain_info()
    open(info["path"], "wb").write(raw)          # restore so teardown's end() can run


def test_OK_id_binding_rename_under_another_valid_id_fails():
    a = _start("alpha")
    E.end()
    d = os.path.dirname(a["path"])
    for ext in (".jsonl", ".key", ".head"):
        shutil.copy2(os.path.join(d, a["id"] + ext), os.path.join(d, "renamed-id" + ext))
    with pytest.raises(chain.ChainError):
        chain.Chain.open("renamed-id")


def test_folding_cross_process_interleave_misattributes(tmp_path):
    """N10 folding keys on (label, target). Two authorizes of the same action+target before
    either ticket: the first ticket folds into the SECOND authorize row; the first authorize
    row stays AUTHORIZED although its ticket ran. (Measurement — printed.)"""
    import executor
    info = _start()
    G.arm(True)
    ch = chain.for_id(info["id"])
    ch.record("authorize", action="net:portscan", target="10.0.0.5", binding="scoped")
    ok, why, t = E.issue("net:portscan", "10.0.0.5", argv=["nmap", "10.0.0.5"], kind="ip")
    executor.run(t, spawner=lambda a: subprocess.Popen(["true"], stdout=subprocess.PIPE,
                                                         start_new_session=True))
    rows = chain.Chain.open(info["id"]).states()
    print([(r["seq"], r["state"]) for r in rows if r["target"] == "10.0.0.5"])
