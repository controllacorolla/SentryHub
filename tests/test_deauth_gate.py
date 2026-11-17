"""DEAUTH — targeted Wi-Fi deauth is a gated capability (owner decision 2026-11-17).

`aireplay-ng --deauth` (wifipent action `deauth`, RECON -> WIFI) runs ONLY when:
  * an engagement is active,
  * the AP BSSID AND the client MAC are both in the engagement scope (no broadcast form),
  * the TX kill switch is armed (txguard.emit_allowed — it is an RF emitter),
and the issue, spawn and exit are recorded in the engagement's evidence chain.

It runs on its own pane, so it can fire while the handshake capture it exists for keeps running.
Nothing here transmits: the spawner is injected and runs a harmless Python child.
"""
import json
import os
import subprocess
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from PySide6 import QtWidgets  # noqa: E402

import chain  # noqa: E402
import engagement as E  # noqa: E402
import txguard as G  # noqa: E402
import wifipent as W  # noqa: E402

OP = "KD0ABC"
AP = "AA:BB:CC:11:22:33"
CL = "DE:AD:BE:EF:00:01"
OOS_AP = "99:88:77:66:55:44"
OOS_CL = "12:34:56:78:9A:BC"
SCOPE = [AP, CL]


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _wait(pred, s=6.0):
    app, t = _app(), time.time()
    while time.time() - t < s:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    app.processEvents()
    return pred()


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    import suite
    import executor
    from palisade_qt import chrome
    monkeypatch.setattr(suite, "DATA", str(tmp_path / "data"))
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    monkeypatch.delenv("PALISADE_GATE_STATE", raising=False)
    monkeypatch.setattr(E, "_profile_operator", lambda: OP, raising=False)
    G.reset_session()
    E.reset()
    executor.reset()
    chain.reset_for_tests()
    chrome.reset()
    yield
    executor.kill_all("test teardown")
    executor.reset()
    G.reset_session()
    E.reset()
    chain.reset_for_tests()
    chrome.reset()


class Spawns:
    """Records every argv; runs a harmless child instead (a long sleep for the capture tool, a
    short print for everything else)."""

    def __init__(self):
        self.calls = []
        self.procs = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        code = ("import time; print('CH  6 ][ capturing'); time.sleep(30)"
                if argv[0] == "airodump-ng" else
                "print('Sending 64 directed DeAuth (code 7)')")
        p = subprocess.Popen([sys.executable, "-u", "-c", code], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.procs.append(p)
        return p


def _recon(monkeypatch, spawns):
    from palisade_qt import recon
    monkeypatch.setattr(recon.ReconApp, "_spawner", lambda self: spawns)
    _app()
    p = recon.ReconApp(demo=False)
    _app().processEvents()
    return p


def _close(p):
    p.stop()
    p.deleteLater()
    _app().processEvents()


def _start(scope=SCOPE):
    ok, why = E.start("job", "ROE-1", list(scope), OP)
    assert ok, why
    return E.chain_info()


def _recs(path):
    with open(path, "rb") as fh:
        return [json.loads(x) for x in fh.read().splitlines() if x.strip()]


def _press(card, action):
    i = [b.text() for b in card._btns].index(action.upper())
    card._btns[i].click()
    _app().processEvents()


def _deauth(p, ap=AP, client=CL, iface="wlan1mon"):
    p.wifi_gated.target.setText(ap)
    p.wifi_client.setText(client)
    p.wifi_iface.setText(iface)
    p.wifi_gated._authorize("deauth")          # direct: also reachable when the button is off
    _app().processEvents()


# ============================================================ refusals: nothing is spawned

def test_deauth_with_no_engagement_is_refused_and_nothing_spawns(monkeypatch):
    G.arm(True)
    ok, why, t = W.prepare("deauth", AP, client=CL)
    assert not ok and t is None and "engagement" in why.lower(), why
    sp = Spawns()
    p = _recon(monkeypatch, sp)
    try:
        btn = p.wifi_gated._btns[[b.text() for b in p.wifi_gated._btns].index("DEAUTH")]
        assert not btn.isEnabled()                 # the card is off with no engagement
        _deauth(p)
        assert "DENIED" in p.wifi_gated.result.text()
        assert sp.calls == [] and not p.wifi_deauth_run.running()
    finally:
        _close(p)


def test_deauth_out_of_scope_bssid_is_refused_and_nothing_spawns(monkeypatch):
    info = _start([OOS_CL, CL])                    # client in scope, AP not
    G.arm(True)
    ok, why, t = W.prepare("deauth", OOS_AP, client=CL)
    assert not ok and t is None, why
    sp = Spawns()
    p = _recon(monkeypatch, sp)
    try:
        _deauth(p, ap=OOS_AP)
        assert "DENIED" in p.wifi_gated.result.text()
        assert sp.calls == []
        assert not [r for r in _recs(info["path"]) if r["event"] in ("issue", "spawn")]
    finally:
        _close(p)


def test_deauth_out_of_scope_client_is_refused_and_nothing_spawns(monkeypatch):
    info = _start([AP])                            # AP in scope, client not
    G.arm(True)
    ok, why, t = W.prepare("deauth", AP, client=OOS_CL)
    assert not ok and t is None and why.startswith("client:"), why
    sp = Spawns()
    p = _recon(monkeypatch, sp)
    try:
        _deauth(p, client=OOS_CL)
        assert "DENIED" in p.wifi_gated.result.text()
        assert sp.calls == []
        assert not [r for r in _recs(info["path"]) if r["event"] in ("issue", "spawn")]
    finally:
        _close(p)


@pytest.mark.parametrize("client", ["", "FF:FF:FF:FF:FF:FF", "not-a-mac"])
def test_deauth_has_no_broadcast_or_clientless_form(client):
    _start([AP, CL])
    G.arm(True)
    ok, why, t = W.prepare("deauth", AP, client=client)
    assert not ok and t is None, why


def test_deauth_with_the_tx_kill_switch_off_is_refused(monkeypatch):
    _start()                                       # in scope, but not armed
    ok, why, t = W.prepare("deauth", AP, client=CL)
    assert not ok and t is None and "kill switch" in why.lower(), why
    sp = Spawns()
    p = _recon(monkeypatch, sp)
    try:
        _deauth(p)
        assert "DENIED" in p.wifi_gated.result.text() and sp.calls == []
    finally:
        _close(p)


# ============================================================ in scope: it runs and is recorded

def test_in_scope_deauth_runs_and_issue_spawn_exit_are_in_the_engagement_chain(monkeypatch):
    info = _start()
    G.arm(True)
    sp = Spawns()
    p = _recon(monkeypatch, sp)
    try:
        _deauth(p)
        assert len(sp.calls) == 1, p.wifi_gated.result.text()
        assert sp.calls[0] == ["aireplay-ng", "--deauth", "3", "-a", AP, "-c", CL, "wlan1mon"]
        assert _wait(lambda: not p.wifi_deauth_run.running()
                     and not p.wifi_deauth_run.state.text().startswith("RUNNING"))
        _wait(lambda: "[exit 0]" in p.wifi_deauth_run.out.toPlainText())
        assert "DeAuth" in p.wifi_deauth_run.out.toPlainText()
        assert p.wifi_deauth_run.state.text() == "DONE · exit 0"
        assert not p.wifi_run.running() and p.wifi_run.out.toPlainText() == ""   # its own pane
        recs = _recs(info["path"])
        ev = [r["event"] for r in recs]
        issue = [r for r in recs if r["event"] == "issue"]
        spawn = [r for r in recs if r["event"] == "spawn"]
        exit_ = [r for r in recs if r["event"] == "exit"]
        assert len(issue) == 1 and issue[0]["label"] == "wifi:deauth"
        assert issue[0]["argv"] == sp.calls[0] and issue[0]["emitter"] == "wifi"
        assert len(spawn) == 1 and spawn[0]["pid"] == sp.procs[0].pid and spawn[0]["pstart"]
        assert spawn[0]["argv"] == sp.calls[0]
        assert len(exit_) == 1 and exit_[0]["exit_code"] == 0
        assert ev.index("issue") < ev.index("spawn") < ev.index("exit")
        assert [r["state"] for r in chain.Chain.open(info["id"]).states()] == ["EXECUTED"]
    finally:
        _close(p)


def test_deauth_count_is_capped_in_the_issued_argv():
    _start()
    G.arm(True)
    ok, why, t = W.prepare("deauth", AP, client=CL, count=10_000)
    assert ok, why
    assert t.argv[t.argv.index("--deauth") + 1] == str(W.DEAUTH_MAX)


def test_deauth_runs_while_the_handshake_capture_keeps_running(monkeypatch):
    info = _start()
    G.arm(True)
    sp = Spawns()
    p = _recon(monkeypatch, sp)
    try:
        p._wifi_pick({"bssid": AP, "ch": "6"})
        p.wifi_iface.setText("wlan1mon")
        _press(p.wifi_gated, "handshake")
        assert p.wifi_run.running() and sp.calls[0][0] == "airodump-ng"
        btn = {b.text(): b for b in p.wifi_gated._btns}
        assert not btn["HANDSHAKE"].isEnabled() and not btn["PMKID"].isEnabled()
        assert btn["DEAUTH"].isEnabled()           # the capture does not block the deauth
        p.wifi_client.setText(CL)
        _press(p.wifi_gated, "deauth")
        assert len(sp.calls) == 2 and sp.calls[1][0] == "aireplay-ng", p.wifi_gated.result.text()
        assert _wait(lambda: not p.wifi_deauth_run.running()
                     and p.wifi_deauth_run.state.text() == "DONE · exit 0")
        assert p.wifi_run.running()                # capture still up after the deauth ended
        spawns = [r for r in _recs(info["path"]) if r["event"] == "spawn"]
        assert [s["argv"][0] for s in spawns] == ["airodump-ng", "aireplay-ng"]
    finally:
        _close(p)


def test_closing_recon_and_end_kill_a_running_deauth(monkeypatch):
    info = _start()
    G.arm(True)

    class Slow(Spawns):
        def __call__(self, argv, **kw):
            self.calls.append(list(argv))
            p = subprocess.Popen([sys.executable, "-u", "-c", "import time; time.sleep(30)"],
                                 start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.procs.append(p)
            return p

    sp = Slow()
    p = _recon(monkeypatch, sp)
    _deauth(p)
    assert p.wifi_deauth_run.running()
    assert p.wifi_deauth_run in p.run_panes()
    _close(p)
    assert _wait(lambda: sp.procs[0].poll() is not None)
    assert "kill" in [r["event"] for r in _recs(info["path"])]


def test_disarm_kills_a_running_deauth_from_the_card(monkeypatch):
    _start()
    G.arm(True)

    class Slow(Spawns):
        def __call__(self, argv, **kw):
            self.calls.append(list(argv))
            p = subprocess.Popen([sys.executable, "-u", "-c", "import time; time.sleep(30)"],
                                 start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.procs.append(p)
            return p

    sp = Slow()
    p = _recon(monkeypatch, sp)
    try:
        _deauth(p)
        assert p.wifi_deauth_run.running()
        G.arm(False)
        assert _wait(lambda: sp.procs[0].poll() is not None)
    finally:
        _close(p)
