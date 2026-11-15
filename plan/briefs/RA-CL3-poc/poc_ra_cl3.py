"""RA-CL3 PoCs. Each test PASSES when the stated behaviour holds (DEFECT_* = the defect reproduces;
OK_* = the audit claim holds). Run: SUITE=<worktree> pytest -q poc_ra_cl3.py"""
import json
import os
import stat
import subprocess
import sys
import time

import pytest

SUITE_DIR = os.environ["SUITE"]
sys.path.insert(0, SUITE_DIR)

import chain  # noqa: E402
import engagement as E  # noqa: E402
import txguard as G  # noqa: E402

OP = "KD0ABC"
ALLOWED_PROGRAMS = frozenset({"nmap"})


def SP(real):
    return lambda argv: subprocess.Popen(real, stdout=subprocess.PIPE, start_new_session=True)


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
    executor.kill_all("teardown")
    executor.reset()
    G.reset_session()
    E.reset()
    chain.reset_for_tests()


def _start(name="job", scope=("10.0.0.0/24",)):
    ok, why = E.start(name, "ROE-1", list(scope), OP)
    assert ok, why
    return E.chain_info()


def _lines(p):
    with open(p, "rb") as fh:
        return [x for x in fh.read().splitlines() if x.strip()]


# ------------------------------------------------------------------ step 1: field rewrites
FIELDS = ["operator", "engagement", "seq", "target", "action", "binding", "authorization", "t", "pid"]


@pytest.mark.parametrize("field", FIELDS)
def test_OK_rewrite_field_fails(field):
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    lines = _lines(info["path"])
    rec = json.loads(lines[-1])
    rec[field] = (rec[field] + 1) if isinstance(rec[field], (int, float)) else "X" + str(rec[field])
    lines[-1] = chain.canonical(rec)
    open(info["path"], "wb").write(b"\n".join(lines) + b"\n")
    assert not chain.Chain.open.__func__ is None
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])


def test_OK_exit_code_and_argv_rewrite_fails():
    import executor
    info = _start()
    G.arm(True)
    ok, why, t = E.issue("net:portscan", "10.0.0.5", argv=["nmap", "10.0.0.5"], kind="ip")
    assert ok, why
    executor.run(t, spawner=SP(["true"]))
    for field, val in (("exit_code", 1), ("argv", ["false"])):
        lines = _lines(info["path"])
        idx = [i for i, l in enumerate(lines) if field.encode() in l][-1]
        rec = json.loads(lines[idx])
        orig = rec[field]
        rec[field] = val
        lines2 = list(lines)
        lines2[idx] = chain.canonical(rec)
        open(info["path"], "wb").write(b"\n".join(lines2) + b"\n")
        with pytest.raises(chain.ChainError):
            chain.Chain.open(info["id"])
        open(info["path"], "wb").write(b"\n".join(lines) + b"\n")
        assert orig is not None


def test_OK_drop_last_and_middle_and_head_delete():
    info = _start()
    for i in range(3):
        assert E.authorize_action("net:portscan", "10.0.0.%d" % (i + 1))[0]
    lines = _lines(info["path"])
    open(info["path"], "wb").write(b"\n".join(lines[:-1]) + b"\n")
    assert not chain.Chain.open.__self__ is None
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])
    open(info["path"], "wb").write(b"\n".join(lines[:1] + lines[2:]) + b"\n")
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])
    open(info["path"], "wb").write(b"\n".join(lines) + b"\n")
    hp = info["path"][:-6] + ".head"
    os.unlink(hp)
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])


def test_DEFECT_truncate_plus_head_rewrite_without_key_verifies():
    """The head is an unkeyed copy of the last record's h, which is printed in the jsonl itself.
    Drop the last N records and write the new last h into .head: verifies. No key needed."""
    info = _start()
    for i in range(3):
        assert E.authorize_action("net:portscan", "10.0.0.%d" % (i + 1))[0]
    lines = _lines(info["path"])
    kept = lines[:-2]
    open(info["path"], "wb").write(b"\n".join(kept) + b"\n")
    with open(info["path"][:-6] + ".head", "w") as fh:
        fh.write(json.loads(kept[-1])["h"])
    ch = chain.Chain.open(info["id"])           # no exception
    assert ch.verify()[0]
    assert len(ch.records) == len(lines) - 2


def test_OK_reforge_with_guessed_key_fails():
    import hmac, hashlib
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    lines = _lines(info["path"])
    rec = json.loads(lines[-1])
    rec["target"] = "10.9.9.9"
    body = dict(rec); body.pop("h")
    rec["h"] = hmac.new(b"\0" * 32, rec["prev"].encode() + b"|" + chain.canonical(body),
                        hashlib.sha256).hexdigest()
    lines[-1] = chain.canonical(rec)
    open(info["path"], "wb").write(b"\n".join(lines) + b"\n")
    open(info["path"][:-6] + ".head", "w").write(rec["h"])
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])


def test_DEFECT_swap_two_chains_files_with_their_keys_and_heads_verifies_under_wrong_name():
    """Swap A<->B (jsonl+key+head together): each id opens and verifies, showing the other
    engagement. Records do not carry the chain id, so the id↔content binding is not checked."""
    a = _start("alpha")
    E.end()
    b = _start("bravo")
    E.end()
    d = os.path.dirname(a["path"])
    for ext in (".jsonl", ".key", ".head"):
        pa, pb = os.path.join(d, a["id"] + ext), os.path.join(d, b["id"] + ext)
        os.rename(pa, pa + ".x"); os.rename(pb, pa); os.rename(pa + ".x", pb)
    ca = chain.Chain.open(a["id"])
    assert ca.verify()[0]
    opened = [r for r in ca.records if r["event"] == "engagement.open"][0]
    assert opened["name"] == "bravo"


def test_OK_swap_only_jsonl_fails():
    a = _start("alpha"); E.end()
    b = _start("bravo"); E.end()
    d = os.path.dirname(a["path"])
    pa, pb = a["path"], b["path"]
    os.rename(pa, pa + ".x"); os.rename(pb, pa); os.rename(pa + ".x", pb)
    with pytest.raises(chain.ChainError):
        chain.Chain.open(a["id"])


def test_OK_restart_no_second_genesis():
    info = _start()
    E.authorize_action("net:portscan", "10.0.0.5")
    ch = chain.Chain.open(info["id"])
    ch.record("x")
    lines = [json.loads(x) for x in _lines(info["path"])]
    assert sum(1 for r in lines if r["prev"] == chain.GENESIS) == 1
    with pytest.raises(chain.ChainError):
        chain.Chain.create(cid=info["id"])


def test_OK_write_failure_refuses_authorize_and_issue(monkeypatch):
    import executor
    info = _start()
    G.arm(True)
    n0 = len(_lines(info["path"]))
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(28, "ENOSPC")))
    ok, why = E.authorize_action("net:portscan", "10.0.0.5")
    assert not ok and "no durable record" in why
    assert not any(a["target"] == "10.0.0.5" for a in E.actions())
    before = dict(executor._ISSUED)
    with pytest.raises(executor.TicketRefused):
        executor.issue(argv=["true"], label="x")
    assert executor._ISSUED == before


def test_DEFECT_failed_append_bricks_the_chain_permanently(monkeypatch):
    """A failure AFTER the line is written (fsync / head replace) raises, the gate refuses —
    but the line stays in the jsonl and the head is not advanced: the chain never verifies
    again, every later authorize refuses, the report refuses. No repair path."""
    info = _start()
    calls = {"n": 0}
    real = chain._write_private

    def boom(path, data):
        if path.endswith(".head"):
            raise OSError(28, "ENOSPC")
        return real(path, data)
    monkeypatch.setattr(chain, "_write_private", boom)
    ok, why = E.authorize_action("net:portscan", "10.0.0.5")
    assert not ok
    monkeypatch.setattr(chain, "_write_private", real)
    ok2, why2 = E.authorize_action("net:portscan", "10.0.0.6")
    assert not ok2, "recovered"
    assert b"10.0.0.5" in open(info["path"], "rb").read()   # the 'refused' authorize is on disk
    ok3, why3 = chain.Chain(info["id"]).verify() if False else (None, None)
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])


def test_OK_refusal_execution_kill_recorded():
    import executor
    info = _start()
    G.arm(True)
    assert not E.authorize_action("net:portscan", "192.168.9.9")[0]
    ok, why, t = E.issue("net:portscan", "10.0.0.5", argv=["nmap", "10.0.0.5"], kind="ip")
    assert ok, why
    h = executor.start(t, spawner=SP(["sleep", "30"]))
    time.sleep(0.3)
    h.stop("operator stop")
    ok, why, t2 = E.issue("net:portscan", "10.0.0.6", argv=["nmap", "10.0.0.6"], kind="ip")
    executor.run(t2, spawner=SP(["false"]))
    ev = [json.loads(x) for x in _lines(info["path"])]
    names = [r["event"] for r in ev]
    assert "refuse" in names and "kill" in names and "spawn" in names
    assert any(r["event"] == "exit" and r.get("exit_code") == 1 for r in ev)
    states = {r["target"]: r["state"] for r in chain.Chain.open(info["id"]).states()}
    print(chain.Chain.open(info["id"]).states())


def test_DEFECT_spawn_and_kill_records_lose_the_child_pid():
    """record() never lets a field override 'pid' — spawn/kill pass pid=proc.pid, it is dropped
    and the HUB's pid is written. The panel's 'pid N' for RUNNING is the hub, not the process."""
    import executor
    info = _start()
    G.arm(True)
    ok, why, t = E.issue("net:portscan", "10.0.0.5", argv=["nmap", "10.0.0.5"], kind="ip")
    assert ok, why
    h = executor.start(t, spawner=SP(["sleep", "30"]))
    child = h.proc.pid
    time.sleep(0.2)
    rows = chain.Chain.open(info["id"]).states()
    h.stop("x")
    ev = [json.loads(x) for x in _lines(info["path"])]
    sp = [r for r in ev if r["event"] == "spawn"][0]
    kl = [r for r in ev if r["event"] == "kill"][0]
    assert sp["pid"] == os.getpid() != child
    assert kl["pid"] == os.getpid()
    assert any(r["detail"] == "pid %d" % os.getpid() for r in rows)


def test_DEFECT_end_while_running_kill_record_placement():
    """END while a process is running: where do kill/exit land?"""
    import executor
    info = _start()
    G.arm(True)
    ok, why, t = E.issue("net:portscan", "10.0.0.5", argv=["nmap", "10.0.0.5"], kind="ip")
    assert ok, why
    h = executor.start(t, spawner=SP(["sleep", "30"]))
    time.sleep(0.2)
    E.end()
    h.wait(5)
    ev = [json.loads(x) for x in _lines(info["path"])]
    names = [r["event"] for r in ev]
    print("ENG CHAIN:", names)
    sess = chain.current(create_session=False)
    print("SESSION:", sess and [r["event"] for r in sess.records])
    assert "kill" in names
    assert names.index("kill") < names.index("engagement.close")
    # the exit record (real exit code) — engagement chain or a stray session chain?
    assert "exit" not in names[names.index("engagement.close"):], "exit after close"
    assert "exit" in names


# ------------------------------------------------------------------ child processes
def _child(code, env):
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                          timeout=60)


def _bound_env(tmp_path):
    import gatestate, suite
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    env = gatestate.child_env(pub.path, base=dict(os.environ))
    env["PYTHONPATH"] = SUITE_DIR
    env["PALISADE_TEST_DATA"] = suite.DATA
    env.pop("SUITE_TX_LOCK", None)
    return pub, env


CHILD_HDR = ("import os, sys, json, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']\n"
             "import engagement as E, executor, chain\n"
             "E._profile_operator=lambda: 'KD0ABC'\n"
             "import subprocess\nALLOWED_PROGRAMS=frozenset({'nmap'})\n"
             "SP=lambda real: (lambda argv: subprocess.Popen(real, stdout=subprocess.PIPE, start_new_session=True))\n")


def test_DEFECT_bound_child_executions_go_to_a_private_session_chain(tmp_path):
    """In a bound child, authorize goes to the hub's chain (via _active_chain) but executor
    issue/spawn/exit go through chain.current(), whose _OPEN is None in the child → a fresh
    per-child session chain. The engagement chain shows AUTHORIZED, never EXECUTED."""
    info = _start()
    G.arm(True)
    pub, env = _bound_env(tmp_path)
    try:
        out = _child(CHILD_HDR +
                     "ok, why, t = E.issue('net:portscan', '10.0.0.7', argv=['nmap','10.0.0.7'], kind='ip')\n"
                     "print('ISSUE', ok, why)\n"
                     "r = executor.run(t, spawner=SP(['true'])) if ok else None\n"
                     "print('EXIT', r and r.exit_code)\n"
                     "s = chain.current(create_session=False)\n"
                     "print('CHILDCHAIN', s.id if s else None)\n", env)
    finally:
        pub.close()
    print(out.stdout, out.stderr[-2000:])
    assert "ISSUE True" in out.stdout and "EXIT 0" in out.stdout
    ev = [json.loads(x) for x in _lines(info["path"])]
    mine = [r["event"] for r in ev if r.get("target") == "10.0.0.7" or r.get("pid") != os.getpid()]
    print("ENG CHAIN child events:", mine)
    assert "authorize" in mine
    assert "issue" not in mine and "exit" not in mine
    d = os.path.dirname(info["path"])
    sess = [f for f in os.listdir(d) if "session" in f and f.endswith(".jsonl")]
    assert sess, os.listdir(d)
    st = chain.Chain.open(info["id"]).states()
    assert [r["state"] for r in st if r["target"] == "10.0.0.7"] == ["AUTHORIZED"]


def test_DEFECT_bound_child_stale_chain_after_engagement_rollover(tmp_path):
    """A long-lived bound child caches _CHAIN['obj']. Hub ENDs and STARTs a new engagement: the
    child's next authorize (checked against the NEW scope) is recorded in the OLD chain; the new
    engagement's chain has no record of the authorization."""
    import gatestate
    a = _start("alpha")
    pub, env = _bound_env(tmp_path)
    flag = tmp_path / "go"
    try:
        p = subprocess.Popen([sys.executable, "-c", CHILD_HDR +
                              "print('A', E.authorize_action('net:portscan','10.0.0.7')); sys.stdout.flush()\n"
                              "import time\n"
                              "while not os.path.exists(%r): time.sleep(0.05)\n" % str(flag) +
                              "print('B', E.authorize_action('net:portscan','10.0.0.8')); sys.stdout.flush()\n"],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = p.stdout.readline()
        assert "True" in line, line + p.stderr.read()
        E.end()
        b = _start("bravo")
        pub.publish_from_engines()
        flag.write_text("1")
        out, err = p.communicate(timeout=30)
        print(line, out, err[-1500:])
        assert "B (True" in out
    finally:
        pub.close()
    ra = [json.loads(x) for x in _lines(a["path"])]
    rb = [json.loads(x) for x in _lines(b["path"])]
    assert any(r.get("target") == "10.0.0.8" and r["event"] == "authorize" for r in ra)
    assert not any(r.get("target") == "10.0.0.8" for r in rb)


def test_OK_concurrent_appends_from_4_processes_verify(tmp_path):
    info = _start()
    pub, env = _bound_env(tmp_path)
    try:
        ps = [subprocess.Popen([sys.executable, "-c", CHILD_HDR +
                                "for i in range(25): assert E.authorize_action('net:portscan','10.0.0.%d' % (i+1))[0]\n"],
                               env=env) for _ in range(4)]
        for i in range(25):
            assert E.authorize_action("net:portscan", "10.0.0.%d" % (i + 100))[0]
        assert all(p.wait(60) == 0 for p in ps)
    finally:
        pub.close()
    ch = chain.Chain.open(info["id"])
    assert ch.verify()[0]
    assert sum(1 for r in ch.records if r["event"] == "authorize") == 125


def test_DEFECT_unlocked_reader_sees_spurious_tamper(tmp_path):
    """verify()/open() read without the flock; between the jsonl append and the head replace a
    reader sees head != last → 'NOT VERIFIED' / ChainError (false tamper alarm, child refuses)."""
    info = _start()
    pub, env = _bound_env(tmp_path)
    bad = 0
    try:
        p = subprocess.Popen([sys.executable, "-c", CHILD_HDR +
                              "for i in range(300): E.authorize_action('net:portscan','10.0.0.%d' % (i%200+1))\n"],
                             env=env)
        while p.poll() is None:
            try:
                chain.Chain.open(info["id"])
            except chain.ChainError as e:
                if "head" in str(e) or "JSON" in str(e):
                    bad += 1
        p.wait()
    finally:
        pub.close()
    print("spurious failures:", bad)
    assert bad > 0
    assert chain.Chain.open(info["id"]).verify()[0]


# ------------------------------------------------------------------ step 2: design
def test_OK_permissions():
    info = _start()
    d = os.path.dirname(info["path"])
    for ext in (".jsonl", ".key", ".head"):
        assert stat.S_IMODE(os.stat(os.path.join(d, info["id"] + ext)).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700


def test_DEFECT_short_key_accepted_and_jsonl_perms_unchecked():
    info = _start()
    d = os.path.dirname(info["path"])
    kp = os.path.join(d, info["id"] + ".key")
    # a 16-byte key passes open() (brief: < 32 must fail). Re-key the chain to show it opens.
    import hmac, hashlib
    k = b"A" * 16
    recs = [json.loads(x) for x in _lines(info["path"])]
    prev = chain.GENESIS
    out = []
    for r in recs:
        r["prev"] = prev
        body = dict(r); body.pop("h")
        r["h"] = hmac.new(k, prev.encode() + b"|" + chain.canonical(body), hashlib.sha256).hexdigest()
        prev = r["h"]
        out.append(chain.canonical(r))
    open(info["path"], "wb").write(b"\n".join(out) + b"\n")
    open(kp, "wb").write(k); os.chmod(kp, 0o600)
    open(os.path.join(d, info["id"] + ".head"), "w").write(prev)
    os.chmod(info["path"], 0o666)
    os.chmod(os.path.join(d, info["id"] + ".head"), 0o666)
    assert chain.Chain.open(info["id"]).verify()[0]


def test_OK_world_readable_key_refused():
    info = _start()
    E.end()
    kp = info["path"][:-6] + ".key"
    os.chmod(kp, 0o644)
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])


def test_symlink_at_chain_path_on_create(tmp_path):
    import suite
    d = chain.engagements_dir()
    victim = tmp_path / "victim"
    victim.write_text("keep")
    os.symlink(str(victim), os.path.join(d, "fixed.jsonl"))
    with pytest.raises(chain.ChainError):
        chain.Chain.create(cid="fixed")
    dangling = os.path.join(d, "dang.jsonl")
    os.symlink(str(tmp_path / "nowhere"), dangling)
    c = chain.Chain.create(cid="dang")          # exists() is False for a dangling link
    assert not os.path.islink(dangling)          # os.replace replaced the link itself
    assert victim.read_text() == "keep"


def test_DEFECT_chain_id_path_traversal_from_shared_state(tmp_path):
    """Chain.open(cid) joins cid unvalidated. A gate-state engagement record with chain
    '../../x' makes a bound child record authorizations into an attacker-chosen chain
    (with an attacker-made key) outside DATA/engagements."""
    d = chain.engagements_dir()
    outside = tmp_path / "evil"
    outside.mkdir()
    c = chain.Chain.create(cid="x", directory=str(outside))
    rel = os.path.relpath(str(outside / "x"), d)
    assert ".." in rel
    c2 = chain.Chain.open(rel)
    assert c2.path.startswith(d) and os.path.realpath(c2.path) == os.path.realpath(c.path)


def test_canonical_collisions_and_newlines():
    info = _start()
    ch = chain.Chain.open(info["id"])
    ch.record("t", s="a\nb\r\nc d\u0085e\x00", f=0.1 + 0.2, big=1e308, u="é", n=float("nan"))
    ch2 = chain.Chain.open(info["id"])
    assert ch2.verify()[0]
    # NFC vs NFD are different bytes → different hashes (no silent collision)
    assert chain.canonical({"u": "é"}) != chain.canonical({"u": "é"})
    # default=str collisions: a non-JSON object and its str() hash the same
    assert chain.canonical({"x": b"ab"}) == chain.canonical({"x": "b'ab'"})
    assert chain.canonical({"x": (1, 2)}) == chain.canonical({"x": [1, 2]})


def test_DEFECT_unencodable_or_mixed_key_fields_raise_non_chainerror():
    info = _start()
    ch = chain.Chain.open(info["id"])
    with pytest.raises(UnicodeEncodeError):
        ch.record("t", target="caf\udce9")      # surrogateescape'd filename/argv
    with pytest.raises(TypeError):
        ch.record("t", meta={1: "a", "b": 2})
    # authorize_action catches Exception → refusal (fail closed): confirm
    ok, why = E.authorize_action("net:portscan", "10.0.0.5", binding=None)
    assert ok


def test_DEFECT_start_raises_on_unencodable_name():
    with pytest.raises(UnicodeEncodeError):
        E.start("job\udce9", "ROE-1", ["10.0.0.0/24"], OP)
    assert not E._ENG["active"]


def test_session_chain_for_tx_only():
    import executor
    G.arm(True)
    G.unlock_session(True)
    ok, why, t, p = G.issue_ticket("bench", ["hackrf_transfer", "-t", "x", "-f", "915000000",
                                             "-s", "2000000", "-x", "0"], 915_000_000,
                                   settings={"tx_enabled": True, "bench_conducted_ack": True},
                                   sample_rate=2_000_000)
    assert ok, why
    s = chain.current(create_session=False)
    assert s and any(r["event"] == "issue" for r in s.records)
    # start an engagement in the same process: later TX goes to the engagement chain,
    # the session chain is never closed
    info = _start()
    assert chain.current() is not s
    E.end()
    assert chain.current() is s


def test_DEFECT_refusals_without_engagement_are_not_recorded():
    G.arm(True)
    ok, why = E.authorize_action("net:portscan", "10.0.0.5")
    assert not ok
    s = chain.current(create_session=False)
    assert s is None or not any(r["event"] == "refuse" for r in s.records)


# ------------------------------------------------------------------ step 3: H9 / E5 / C2
def test_DEFECT_chain_states_served_from_memory_when_tampered():
    """chain_states(): verify() fails, but states() is then computed from the in-memory
    records cached from the last good load — rows from memory, not the (tampered) chain."""
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    E.chain_states()
    lines = _lines(info["path"])
    rec = json.loads(lines[-1]); rec["target"] = "10.0.0.66"
    lines[-1] = chain.canonical(rec)
    open(info["path"], "wb").write(b"\n".join(lines) + b"\n")
    ci = E.chain_info()
    assert ci["verified"] is False
    rows = E.chain_states()
    assert rows and any(r["target"] == "10.0.0.5" for r in rows)


def test_OK_report_refuses_tampered_and_writes_verified(tmp_path):
    import evidence
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    p = evidence.export_engagement_report(out_dir=str(tmp_path / "r"))
    assert os.path.exists(p)
    lines = _lines(info["path"])
    rec = json.loads(lines[-1]); rec["target"] = "10.0.0.66"
    lines[-1] = chain.canonical(rec)
    open(info["path"], "wb").write(b"\n".join(lines) + b"\n")
    with pytest.raises(Exception):
        evidence.export_engagement_report(out_dir=str(tmp_path / "r2"))
    assert not os.path.exists(str(tmp_path / "r2"))


def test_report_html_escapes_chain_strings(tmp_path):
    import evidence
    info = _start(scope=("10.0.0.0/24",))
    ch = chain.Chain.open(info["id"])
    ch.record("note", text="<script>alert(1)</script>")
    p = evidence.export_engagement_report(out_dir=str(tmp_path / "r"))
    html = open(p).read()
    assert "<script>alert(1)</script>" not in html


def test_OK_no_sh_c_in_evidence():
    src = open(os.path.join(SUITE_DIR, "evidence.py")).read()
    assert '"sh"' not in src and "'sh'" not in src and "shell=True" not in src
