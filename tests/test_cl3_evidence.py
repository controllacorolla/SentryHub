"""CL3 — evidence chain. One regression test (or group) per audit PoC: G6 G7 H9 E5 C2.

G6  an action was authorized even when it could not be logged (chain optional, failure swallowed)
G7  chain not tamper-evident / durable / shared: hash covered 4 fields (rewrite operator,
    engagement, file, seq → still verifies), dropping the last record verifies, unkeyed, no reload
    (restart appends a second genesis), silent write errors, authorizations only (no executions)
H9  the UI listed authorizations for commands that never ran, as if executed
C2  the vault built `sh -c` strings from paths and the recipient
E5  the report generator had no callers
"""
import json
import os
import subprocess
import sys

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


def _start(scope=("10.0.0.0/24", "BADGE-7")):
    ok, why = E.start("job", "ROE-1", list(scope), OP)
    assert ok, why
    return E.chain_info()


def _lines(path):
    with open(path) as fh:
        return [json.loads(x) for x in fh if x.strip()]


def _rewrite(path, lines):
    with open(path, "w") as fh:
        for rec in lines:
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")


# ============================================================================ G7: tamper-evident
def test_g7_rewriting_any_field_breaks_verification_poc():
    """PoC: operator / engagement / file / seq could be rewritten and the chain still verified."""
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    ch = chain.Chain.open(info["id"])
    assert ch.verify()[0]
    for field, value in (("operator", "MALLORY"), ("engagement", "other"), ("target", "10.9.9.9"),
                         ("seq", 7), ("t", 1.0), ("action", "net:nothing"), ("authorization", "X")):
        lines = _lines(ch.path)
        idx = next(i for i, r in enumerate(lines) if r["event"] == "authorize")
        lines[idx][field] = value
        _rewrite(ch.path, lines)
        with pytest.raises(chain.ChainError):
            chain.Chain.open(info["id"])
        # restore
        _rewrite(ch.path, _lines(ch.path)[:idx] + [ch.records[idx]] + _lines(ch.path)[idx + 1:])
        assert chain.Chain.open(info["id"]).verify()[0], field


def test_g7_dropping_the_last_record_is_detected_poc():
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    ch = chain.Chain.open(info["id"])
    lines = _lines(ch.path)
    _rewrite(ch.path, lines[:-1])
    with pytest.raises(chain.ChainError, match="head"):
        chain.Chain.open(info["id"])


def test_g7_dropping_a_middle_record_is_detected():
    info = _start()
    for t in ("10.0.0.5", "10.0.0.6", "10.0.0.7"):
        assert E.authorize_action("net:portscan", t)[0]
    ch = chain.Chain.open(info["id"])
    lines = _lines(ch.path)
    del lines[2]
    _rewrite(ch.path, lines)
    with pytest.raises(chain.ChainError):
        chain.Chain.open(info["id"])


def test_g7_unkeyed_reforge_fails_poc():
    """PoC: the old chain was unkeyed, so a forger could recompute every hash. Now the HMAC key is
    needed: re-forging with a wrong key (or no key) fails verification."""
    import hashlib
    import hmac as _hmac
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    ch = chain.Chain.open(info["id"])
    lines = _lines(ch.path)
    lines[1]["target"] = "10.9.9.9"
    prev = chain.GENESIS
    wrong = b"\x00" * 32
    for rec in lines:                       # forger recomputes the whole chain with a guessed key
        body = {k: v for k, v in rec.items() if k != "h"}
        rec["h"] = _hmac.new(wrong, prev.encode() + b"|" + chain.canonical(body),
                             hashlib.sha256).hexdigest()
        prev = rec["h"]
    _rewrite(ch.path, lines)
    with open(ch.head_path, "w") as fh:
        fh.write(prev)
    with pytest.raises(chain.ChainError, match="HMAC"):
        chain.Chain.open(info["id"])


def test_g7_reopen_continues_the_chain_no_second_genesis_poc():
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    n = len(_lines(chain.Chain.open(info["id"]).path))
    # "restart": a fresh Chain object on the same id continues from the head
    ch2 = chain.Chain.open(info["id"])
    ch2.record("authorize", action="x", target="10.0.0.6")
    lines = _lines(ch2.path)
    assert len(lines) == n + 1
    assert lines[-1]["prev"] == lines[-2]["h"] and lines[-1]["seq"] == n
    assert sum(1 for r in lines if r["prev"] == chain.GENESIS) == 1
    assert chain.Chain.open(info["id"]).verify()[0]


def test_g7_write_errors_raise_not_silent_poc(monkeypatch):
    info = _start()
    ch = chain.Chain.open(info["id"])

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(chain.ChainError):
        ch.record("authorize", action="x", target="y")


def test_g7_records_executions_with_exit_code_and_kills():
    """PoC: the old chain recorded authorizations, not executions."""
    import executor
    import netpent
    info = _start()
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    assert ok, why
    r = executor.run(t, spawner=lambda argv: subprocess.Popen(
        [sys.executable, "-c", "import sys; print('x'); sys.exit(3)"], start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
    assert r.exit_code == 3
    events = [x["event"] for x in chain.Chain.open(info["id"]).records]
    assert events[:2] == ["engagement.open", "authorize"]
    assert "issue" in events and "spawn" in events and "exit" in events
    ex = [x for x in chain.Chain.open(info["id"]).records if x["event"] == "exit"][-1]
    assert ex["exit_code"] == 3 and ex["ticket"] == t.id
    # END records close and kills registered processes (kill is recorded)
    ok, why, t2 = netpent.prepare("portscan", "10.0.0.6")
    h = executor.start(t2, spawner=lambda argv: subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
    E.end()
    h.wait(5)
    recs = chain.Chain.open(info["id"]).records
    assert any(x["event"] == "kill" and x["ticket"] == t2.id for x in recs)
    assert recs[-1]["event"] in ("engagement.close", "exit", "kill")
    assert any(x["event"] == "engagement.close" for x in recs)


def test_g7_open_records_scope_in_force_and_files_are_private():
    info = _start(("10.0.0.0/24", "AA:BB:CC:*"))
    ch = chain.Chain.open(info["id"])
    o = ch.records[0]
    assert o["event"] == "engagement.open" and o["scope"] == ["10.0.0.0/24", "AA:BB:CC:*"]
    assert o["operator"] == OP and o["authorization"] == "ROE-1" and o["expires"] > o["started"]
    for p in (ch.path, ch.key_path, ch.head_path):
        assert os.stat(p).st_mode & 0o077 == 0, p
    assert "mono_ns" in o and "wpid" in o and o["seq"] == 0


def test_g7_one_chain_shared_by_recon_and_forge_pages():
    """PoC: RECON and FORGE each held a separate in-memory chain."""
    import inspect
    import palisade_qt.recon as recon
    import palisade_qt.forge as forge
    for mod in (recon, forge):
        src = inspect.getsource(mod)
        assert "EvidenceChain()" not in src, mod.__name__
    _start()
    assert E.authorize_action("wifi:pmkid", "AA:BB:CC:DD:EE:FF", kind="mac")[0] is False  # out of scope
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    rows = E.chain_states()
    assert [r["state"] for r in rows] == ["AUTHORIZED", "REFUSED"]
    assert rows[1]["detail"] == "scope"


# ============================================================================ G6: fail closed
def test_g6_no_durable_record_no_authorization_poc(monkeypatch):
    info = _start()
    ch = E._active_chain()
    assert ch is not None and ch.id == info["id"]

    def boom(*a, **k):
        raise chain.ChainError("disk gone")
    monkeypatch.setattr(ch, "record", boom)
    ok, why = E.authorize_action("net:portscan", "10.0.0.5")
    assert not ok and "no durable record" in why
    assert E.actions() == []
    ok, why, t = E.issue("net:portscan", "10.0.0.5", argv=["nmap", "10.0.0.5"], kind="ip")
    assert not ok and t is None


def test_g6_engagement_cannot_start_without_a_chain(monkeypatch):
    monkeypatch.setattr(chain.Chain, "create", classmethod(
        lambda cls, **k: (_ for _ in ()).throw(chain.ChainError("read-only filesystem"))))
    ok, why = E.start("job", "ROE-1", ["10.0.0.0/24"], OP)
    assert not ok and "evidence chain" in why and not E.is_active()


def test_g6_ticket_issue_fails_closed_when_the_record_fails(monkeypatch):
    import executor
    _start()
    ch = E._active_chain()
    real = ch.record

    def flaky(event, **f):
        if event == "issue":
            raise chain.ChainError("disk gone")
        return real(event, **f)
    monkeypatch.setattr(ch, "record", flaky)
    ok, why, t = E.issue("net:portscan", "10.0.0.5", argv=["nmap", "10.0.0.5"], kind="ip")
    assert not ok and t is None and "evidence" in why
    assert executor._ISSUED == {}                     # nothing was minted


# ============================================================================ H9: states
def test_h9_authorized_and_executed_are_different_states_poc():
    import executor
    import netpent
    _start()
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    assert ok
    rows = E.chain_states()
    # RA-CL3 N10: the ticket folds into its AUTHORIZED row — one row per action, now ISSUED
    assert [(r["action"], r["state"]) for r in rows] == [("net:portscan", "ISSUED")]
    assert not any(r["state"] == "EXECUTED" for r in rows)       # nothing ran yet
    executor.run(t, spawner=lambda argv: subprocess.Popen(
        [sys.executable, "-c", "pass"], start_new_session=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True))
    rows = E.chain_states()
    done = [r for r in rows if r["state"] == "EXECUTED"]
    assert len(done) == 1 and done[0]["detail"] == "exit 0"
    # a failing run is FAILED, not EXECUTED
    ok, why, t2 = netpent.prepare("portscan", "10.0.0.6")
    executor.run(t2, spawner=lambda argv: subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(2)"], start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
    assert any(r["state"] == "FAILED" and r["detail"] == "exit 2" for r in E.chain_states())


def test_h9_engagement_panel_shows_state_column_from_the_chain(monkeypatch):
    import os as _os
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    import palisade_qt.panels as panels
    _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    p = panels.EngagePanel("dark")
    p.render_actions()
    m = p.eng_actions.model
    rows = list(m.rows)
    assert any(r.get("state") == "AUTHORIZED" for r in rows)
    assert "VERIFIED" in p.eng_chain.text()
    app.processEvents()


# ============================================================================ C2: vault argv
def test_c2_vault_uses_argv_lists_and_a_pipe_not_sh_c():
    import evidence
    v = evidence.Vault("/tmp/eng.age")
    stages = v.lock_argv("/tmp/find ings; rm -rf /", "age1key; touch /tmp/pwn")
    assert stages[0][0] == "tar" and stages[1][0] == "age"
    assert all(a[0] != "sh" for a in stages)
    assert "/tmp/find ings; rm -rf /" in stages[0] and "age1key; touch /tmp/pwn" in stages[1]
    ran = []

    class _Out:
        def close(self):
            pass

    class P:
        def __init__(self, argv, stdin=None, stdout=None):
            ran.append((list(argv), stdin is not None, stdout is not None))
            self.stdout = _Out() if stdout is not None else None
            self.returncode = 0

        def wait(self):
            return 0
    assert evidence.Vault.run_pipeline(stages, popen=P) == 0
    assert ran[0][0][0] == "tar" and ran[0][2] is True and ran[1][0][0] == "age" and ran[1][1]


# ============================================================================ E5: report has a caller
def test_e5_report_is_written_from_the_verified_chain(tmp_path):
    import evidence
    import inspect
    import palisade_qt.panels as panels
    assert "export_engagement_report" in inspect.getsource(panels)
    info = _start()
    assert E.authorize_action("net:portscan", "10.0.0.5")[0]
    path = evidence.export_engagement_report(out_dir=str(tmp_path / "reports"))
    doc = open(path).read()
    assert info["id"] in doc and "AUTHORIZED" in doc and OP in doc and "ROE-1" in doc
    # a chain that does not verify yields no report
    ch = chain.Chain.open(info["id"])
    lines = _lines(ch.path)
    lines[1]["target"] = "10.9.9.9"
    _rewrite(ch.path, lines)
    with pytest.raises(Exception):
        evidence.export_engagement_report(out_dir=str(tmp_path / "reports2"))


# ============================================================================ cross-process
def test_chain_is_shared_with_a_bound_child_process(tmp_path):
    """A hub child (gatestate) appends to the SAME chain by id; the parent sees it and it verifies."""
    import gatestate
    import suite
    info = _start()
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    try:
        env = gatestate.child_env(pub.path, base=dict(os.environ))
        env["PYTHONPATH"] = SUITE_DIR
        env["PALISADE_TEST_DATA"] = suite.DATA
        code = (
            "import os, sys, suite; suite.DATA=os.environ['PALISADE_TEST_DATA']\n"
            "import engagement as E\n"
            "ok, why = E.authorize_action('net:portscan', '10.0.0.9')\n"
            "print('OK' if ok else 'NO ' + why)\n")
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                             timeout=30)
        assert out.stdout.strip() == "OK", out.stdout + out.stderr
    finally:
        pub.close()
    recs = chain.Chain.open(info["id"]).records
    child = [r for r in recs if r["event"] == "authorize" and r["target"] == "10.0.0.9"]
    assert child and child[0]["wpid"] != os.getpid()
    assert chain.Chain.open(info["id"]).verify()[0]
    # and the parent continues after the child's append without a fork in the chain
    assert E.authorize_action("net:portscan", "10.0.0.8")[0]
    assert chain.Chain.open(info["id"]).verify()[0]


def test_tx_without_engagement_goes_to_a_session_chain(tmp_path):
    """A conducted bench run (txguard only, no engagement) is still evidence."""
    import executor
    import txguard
    G.arm(True)
    G.unlock_session(True)
    ok, why, t, p = txguard.issue_ticket("bench", ["hackrf_transfer", "-t", "x", "-f", "915000000",
                                                   "-s", "2000000", "-x", "0"], 915_000_000,
                                         settings={"tx_enabled": True, "bench_conducted_ack": True},
                                         sample_rate=2_000_000)
    assert ok, why
    ch = chain.current(create_session=False)
    assert ch is not None and "session-%d" % os.getpid() in ch.id
    events = [r["event"] for r in ch.records]
    assert "session.open" in events and "issue" in events
    assert executor._ISSUED[t.id]
