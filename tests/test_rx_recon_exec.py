"""RX — RECON NET (nmap) and RECON Wi-Fi (wifipent) actually execute (owner decision 2026-11-17).

Before: the gate authorized, RECON showed a single-use ticket, and nothing ran ("Execution of the
argv is device-only; nothing is spawned here"). After: the ticket goes to executor.start() through
the card's RunPane, which streams the tool's output; the executor records spawn (pid + start
time) and exit (real exit code) in the engagement chain, and END / PANIC / STOP / closing RECON
kill the process group with a recorded kill.

Gate tests: an out-of-scope target, no engagement, an iface that looks like an option, and an
engagement that ended between authorize and run are all refused with NOTHING spawned. BLEPENT and
PASSAUDIT stay authorize-only (v0.2).
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

OP = "KD0ABC"


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
    """A spawner that records every argv it was asked to run and runs a harmless Python child in
    its own session instead of the real tool."""

    def __init__(self, code="print('ok')"):
        self.code = code
        self.calls = []
        self.procs = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        p = subprocess.Popen([sys.executable, "-u", "-c", self.code], start_new_session=True,
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


def _start(scope):
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


# ============================================================ the gate still refuses first

def test_rx_out_of_scope_nmap_target_is_refused_and_nothing_is_spawned(monkeypatch):
    sp = Spawns()
    info = _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        p.net_gated.target.setText("192.168.1.5")
        for act in ("discover", "portscan", "services"):
            _press(p.net_gated, act)
            assert "DENIED" in p.net_gated.result.text(), p.net_gated.result.text()
        assert sp.calls == [], "an out-of-scope target reached the spawner"
        assert not p.net_run.running()
        events = [r["event"] for r in _recs(info["path"])]
        assert "spawn" not in events and "issue" not in events
    finally:
        _close(p)


def test_rx_out_of_scope_bssid_is_refused_and_nothing_is_spawned(monkeypatch):
    sp = Spawns()
    info = _start(["AA:BB:CC:*"])
    p = _recon(monkeypatch, sp)
    try:
        p.wifi_gated.target.setText("99:99:99:99:99:99")
        _press(p.wifi_gated, "handshake")
        assert "DENIED" in p.wifi_gated.result.text()
        assert sp.calls == []
        assert "spawn" not in [r["event"] for r in _recs(info["path"])]
    finally:
        _close(p)


def test_rx_without_an_engagement_nothing_is_spawned(monkeypatch):
    sp = Spawns()
    p = _recon(monkeypatch, sp)
    try:
        assert not any(b.isEnabled() for b in p.net_gated._btns + p.wifi_gated._btns)
        p.net_gated.target.setText("10.0.0.5")
        p.net_gated._authorize("portscan")           # even a direct call: the ENGINE refuses
        assert "DENIED" in p.net_gated.result.text()
        assert sp.calls == []
    finally:
        _close(p)


def test_rx_a_ticket_whose_engagement_ended_before_run_is_refused_at_spawn(monkeypatch):
    import netpent
    from palisade_qt.runpane import RunPane
    from palisade_qt import theme
    sp = Spawns()
    _start(["10.0.0.0/24"])
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    assert ok, why
    E.end()
    _app()
    pane = RunPane("NETPENT", theme.tokens("dark"))
    started, msg = pane.run(t, spawner=sp)
    assert not started and "refused" in msg and pane.state.text() == "REFUSED"
    assert sp.calls == []


def test_rx_wifi_iface_that_looks_like_an_option_is_refused_by_the_engine():
    import wifipent
    _start(["AA:BB:CC:*"])
    for bad in ("-w", "--write", "../x", "wlan0 x", ""):
        ok, why, t = wifipent.prepare("handshake", "AA:BB:CC:11:22:33", iface=bad, out="cap")
        assert not ok and t is None, bad
    ok, why, t = wifipent.prepare("handshake", "AA:BB:CC:11:22:33", iface="wlan0mon",
                                  out="-oops")
    assert not ok and t is None


def test_rx_blepent_and_passaudit_stay_authorize_only(monkeypatch):
    p = _recon(monkeypatch, Spawns())
    try:
        assert p.ble_gated._runner is None and p.pass_gated._runner is None
        assert p.net_gated._runner is p.net_run and p.wifi_gated._runner is p.wifi_run
    finally:
        _close(p)


# ============================================================ it really runs

def test_rx_in_scope_nmap_runs_streams_output_and_records_spawn_and_exit(monkeypatch):
    sp = Spawns("print('Starting Nmap'); print('\\x1b[1mHost is up\\x1b[0m'); print('Nmap done')")
    info = _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        p.net_gated.target.setText("10.0.0.5")
        _press(p.net_gated, "portscan")
        assert len(sp.calls) == 1 and sp.calls[0][0] == "nmap" and sp.calls[0][-1] == "10.0.0.5"
        assert _wait(lambda: not p.net_run.running() and not p.net_run.state.text().startswith("RUNNING"))
        _wait(lambda: "[exit 0]" in p.net_run.out.toPlainText())
        text = p.net_run.out.toPlainText()
        assert "Starting Nmap" in text and "Host is up" in text and "\x1b" not in text
        assert p.net_run.state.text() == "DONE · exit 0"
        assert all(b.isEnabled() for b in p.net_gated._btns)       # free again after exit
        recs = _recs(info["path"])
        spawn = [r for r in recs if r["event"] == "spawn"]
        exit_ = [r for r in recs if r["event"] == "exit"]
        assert len(spawn) == 1 and spawn[0]["pid"] == sp.procs[0].pid and spawn[0]["pstart"]
        assert len(exit_) == 1 and exit_[0]["exit_code"] == 0
        assert [r["state"] for r in chain.Chain.open(info["id"]).states()] == ["EXECUTED"]
    finally:
        _close(p)


def test_rx_a_failing_tool_shows_its_real_exit_code(monkeypatch):
    sp = Spawns("import sys; print('You requested a scan type which requires root'); sys.exit(1)")
    info = _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        p.net_gated.target.setText("10.0.0.5")
        _press(p.net_gated, "services")
        assert _wait(lambda: not p.net_run.running() and not p.net_run.state.text().startswith("RUNNING"))
        assert p.net_run.state.text() == "FAILED · exit 1"
        assert "requires root" in p.net_run.out.toPlainText()
        assert [r["state"] for r in chain.Chain.open(info["id"]).states()] == ["FAILED"]
    finally:
        _close(p)


def test_rx_one_process_per_card(monkeypatch):
    sp = Spawns("import time; time.sleep(30)")
    _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        p.net_gated.target.setText("10.0.0.5")
        _press(p.net_gated, "portscan")
        assert p.net_run.running()
        assert not any(b.isEnabled() for b in p.net_gated._btns)
        p.net_gated._authorize("discover")
        assert len(sp.calls) == 1
    finally:
        _close(p)


def test_rx_wifi_handshake_runs_with_the_card_inputs_and_a_capture_path_under_data(monkeypatch):
    import suite
    sp = Spawns("print('CH  6 ][ Elapsed: 0 s')")
    info = _start(["AA:BB:CC:*"])
    p = _recon(monkeypatch, sp)
    try:
        p._wifi_pick({"bssid": "AA:BB:CC:11:22:33", "ch": "6"})
        p.wifi_iface.setText("wlan1mon")
        _press(p.wifi_gated, "handshake")
        assert len(sp.calls) == 1, p.wifi_gated.result.text()
        argv = sp.calls[0]
        assert argv[0] == "airodump-ng" and argv[-1] == "wlan1mon"
        assert argv[argv.index("--bssid") + 1] == "AA:BB:CC:11:22:33"
        assert argv[argv.index("--channel") + 1] == "6"
        out = argv[argv.index("--write") + 1]
        assert out.startswith(os.path.join(suite.DATA, "captures") + os.sep)
        assert _wait(lambda: not p.wifi_run.state.text().startswith("RUNNING"))
        assert "spawn" in [r["event"] for r in _recs(info["path"])]
    finally:
        _close(p)


def test_rx_wifi_deauth_still_needs_a_client_and_the_tx_gate(monkeypatch):
    sp = Spawns()
    _start(["AA:BB:CC:*"])
    p = _recon(monkeypatch, sp)
    try:
        p.wifi_gated.target.setText("AA:BB:CC:11:22:33")
        _press(p.wifi_gated, "deauth")                       # no client: never a broadcast
        assert "DENIED" in p.wifi_gated.result.text()
        p.wifi_client.setText("AA:BB:CC:00:00:01")
        _press(p.wifi_gated, "deauth")                       # TX kill switch not armed: refused
        assert "DENIED" in p.wifi_gated.result.text()
        assert sp.calls == []
    finally:
        _close(p)


def test_rx_unprivileged_portscan_is_a_connect_scan(monkeypatch):
    import netpent
    _start(["10.0.0.0/24"])
    monkeypatch.setattr(netpent, "_is_root", lambda: False)
    ok, _w, t = netpent.prepare("portscan", "10.0.0.5")
    assert ok and "-sT" in t.argv and "-sS" not in t.argv
    monkeypatch.setattr(netpent, "_is_root", lambda: True)
    ok, _w, t = netpent.prepare("portscan", "10.0.0.6")
    assert ok and "-sS" in t.argv


def test_rx_a_missing_tool_is_not_spawned_and_says_so(monkeypatch):
    import netpent
    from palisade_qt import runpane, theme
    info = _start(["10.0.0.0/24"])
    monkeypatch.setattr(runpane.shutil, "which", lambda name: None)
    ok, _w, t = netpent.prepare("discover", "10.0.0.0/24")
    _app()
    pane = runpane.RunPane("NETPENT", theme.tokens("dark"))
    started, msg = pane.run(t, spawner=None)
    assert not started and "not installed" in msg and pane.state.text() == "NOT INSTALLED"
    assert "spawn" not in [r["event"] for r in _recs(info["path"])]


# ============================================================ END / PANIC / STOP / close kill it

def _running(monkeypatch, scope=("10.0.0.0/24",)):
    sp = Spawns("import time; print('scanning', flush=True); time.sleep(60)")
    info = _start(list(scope))
    p = _recon(monkeypatch, sp)
    p.net_gated.target.setText("10.0.0.5")
    _press(p.net_gated, "portscan")
    assert p.net_run.running()
    assert _wait(lambda: "scanning" in p.net_run.out.toPlainText())
    return sp, info, p


def _gone(proc):
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return False
    return True


def test_rx_end_kills_the_running_tool_and_records_kill_before_close(monkeypatch):
    sp, info, p = _running(monkeypatch)
    try:
        E.end()
        assert _gone(sp.procs[0])
        assert _wait(lambda: not p.net_run.running() and not p.net_run.state.text().startswith("RUNNING"))
        assert p.net_run.state.text().startswith("STOPPED (gate closed")
        names = [r["event"] for r in _recs(info["path"])]
        assert names.index("spawn") < names.index("kill") < names.index("exit") \
            < names.index("engagement.close")
        assert [r["state"] for r in chain.Chain.open(info["id"]).states()] == ["KILLED"]
    finally:
        _close(p)


def test_rx_panic_kills_the_running_tool(monkeypatch):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_cl1_screen import _hub, _pump
    sp = Spawns("import time; print('scanning', flush=True); time.sleep(60)")
    from palisade_qt import recon
    monkeypatch.setattr(recon.ReconApp, "_spawner", lambda self: sp)
    info = _start(["10.0.0.0/24"])
    hub = _hub(demo=False)
    try:
        hub._list_children = lambda: []
        hub.open_callsign("RECON")
        _pump(60)
        page = hub.pages["RECON"]
        page.switch_subtab("NET")
        page.net_gated.target.setText("10.0.0.5")
        _press(page.net_gated, "portscan")
        assert page.net_run.running()
        hub.panic()
        assert _gone(sp.procs[0])
        assert _wait(lambda: not page.net_run.state.text().startswith("RUNNING"))
        assert page.net_run.state.text().startswith("STOPPED")
        assert [r["state"] for r in chain.Chain.open(info["id"]).states()] == ["KILLED"]
    finally:
        hub.close()
        _pump(150)


def test_rx_stop_button_kills_and_records_it(monkeypatch):
    sp, info, p = _running(monkeypatch)
    try:
        p.net_run.stop_btn.click()
        assert _gone(sp.procs[0])
        assert _wait(lambda: not p.net_run.running() and not p.net_run.state.text().startswith("RUNNING"))
        assert "operator STOP" in p.net_run.state.text()
        kills = [r for r in _recs(info["path"]) if r["event"] == "kill"]
        assert len(kills) == 1 and kills[0]["reason"] == "operator STOP"
    finally:
        _close(p)


def test_rx_closing_recon_kills_the_running_tool(monkeypatch):
    sp, info, p = _running(monkeypatch)
    _close(p)
    assert _gone(sp.procs[0])
    kills = [r for r in _recs(info["path"]) if r["event"] == "kill"]
    assert len(kills) == 1 and kills[0]["reason"] == "RECON closed"


def test_rx_offscreen_default_never_spawns(monkeypatch):
    """Without a test spawner RECON under offscreen refuses to spawn (the BENCH seam)."""
    from palisade_qt import recon
    _app()
    p = recon.ReconApp(demo=False)
    try:
        _start(["10.0.0.0/24"])
        p.net_gated.target.setText("10.0.0.5")
        import executor
        _press(p.net_gated, "discover")
        assert p.net_run.state.text() == "FAILED TO START"
        assert executor.running() == []
    finally:
        _close(p)


# ============================================================ RA-RX fixes

def _targets(argv):
    """The non-option tokens after the last option value: what nmap is asked to scan."""
    toks = list(argv[1:])
    out, skip = [], False
    for tok in toks:
        if skip:
            skip = False
            continue
        if tok in ("-p", "-oG", "-oN"):
            skip = True
            continue
        if tok.startswith("-"):
            continue
        out.append(tok)
    return out


@pytest.mark.parametrize("target", ["10.0.0.250-10.0.0.255", "ip:10.0.0.5", "IP:10.0.0.0/28",
                                    "host:10.0.0.7", "10.0.0.5", "10.0.0.0/24",
                                    "10.0.0.1-10.0.0.200"])
def test_rx_h1_nmap_only_ever_gets_address_literals_and_never_resolves(target):
    import ipaddress
    import netpent
    _start(["10.0.0.0/24"])
    for action in ("discover", "portscan", "services"):
        ok, why, t = netpent.prepare(action, target)
        assert ok, (target, why)
        assert "-n" in t.argv, "nmap must never resolve a name itself"
        tg = _targets(t.argv)
        assert tg, t.argv
        for tok in tg:
            net = ipaddress.ip_network(tok, strict=False)        # raises if not a literal
            assert net.subnet_of(ipaddress.ip_network("10.0.0.0/24")), (target, tok)


def test_rx_h1_a_range_becomes_exactly_its_cidr_cover():
    import ipaddress
    import netpent
    _start(["10.0.0.0/24"])
    ok, _w, t = netpent.prepare("discover", "10.0.0.250-10.0.0.255")
    nets = [ipaddress.ip_network(x) for x in _targets(t.argv)]
    covered = {int(a) for n in nets for a in n}
    want = set(range(int(ipaddress.ip_address("10.0.0.250")),
                     int(ipaddress.ip_address("10.0.0.255")) + 1))
    assert covered == want


def test_rx_h1_out_of_scope_range_and_prefixed_targets_are_still_refused():
    import netpent
    _start(["10.0.0.0/24"])
    for target in ("10.0.0.250-10.0.1.5", "ip:192.168.1.5", "host:192.168.1.5", "IP:8.8.8.0/24"):
        ok, _w, t = netpent.prepare("portscan", target)
        assert not ok and t is None, target


def test_rx_m1_an_endless_line_is_read_in_bounded_pieces(monkeypatch):
    import executor
    import netpent
    _start(["10.0.0.0/24"])
    ok, _w, t = netpent.prepare("discover", "10.0.0.5")
    code = "import sys\nfor _ in range(200): sys.stdout.write('x' * 10000); sys.stdout.flush()"
    got = []
    h = executor.start(t, spawner=Spawns(code), on_line=got.append)
    h.wait(20)
    assert h.exit_code == 0
    assert got and max(len(x) for x in got) <= executor.LINE_MAX
    assert sum(len(x) for x in got) == 200 * 10000


def test_rx_m1_the_pane_batches_and_truncates_a_flood(monkeypatch):
    from palisade_qt import runpane
    sp = Spawns("import sys\nfor i in range(20000): print('line %d ' % i + 'y' * 3000)")
    _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        p.net_gated.target.setText("10.0.0.5")
        _press(p.net_gated, "discover")
        assert _wait(lambda: not p.net_run.state.text().startswith("RUNNING"), 30)
        doc = p.net_run.out.document()
        assert doc.blockCount() <= runpane.MAX_LINES
        longest = max(len(doc.findBlockByNumber(i).text()) for i in range(doc.blockCount()))
        assert longest <= runpane.LINE_SHOWN + 10
    finally:
        _close(p)


def test_rx_l4_a_refused_capture_creates_no_directory(monkeypatch):
    import suite
    sp = Spawns()
    _start(["AA:BB:CC:*"])
    p = _recon(monkeypatch, sp)
    try:
        p.wifi_gated.target.setText("99:99:99:99:99:99")
        _press(p.wifi_gated, "pmkid")
        assert "DENIED" in p.wifi_gated.result.text()
        assert not os.path.exists(os.path.join(suite.DATA, "captures"))
    finally:
        _close(p)


def test_rx_l2_the_monitor_note_follows_the_adapter(monkeypatch):
    from palisade_qt import recon
    p = _recon(monkeypatch, Spawns())
    try:
        monkeypatch.setattr(recon, "monitor_iface", lambda: None)
        p._switch("BLE")
        p._switch("WIFI")
        assert "NO MONITOR-MODE" in p.wifi_hw.text()
        monkeypatch.setattr(recon, "monitor_iface", lambda: "wlan1")
        p._switch("BLE")
        p._switch("WIFI")
        assert p.wifi_hw.text() == "monitor-mode interface: wlan1"
    finally:
        _close(p)


# ============================================================ RX-fix2 (planner backcheck before the device test)

class ArgvSpawns(Spawns):
    """Like Spawns, but the child gets the real argv, so it can act like nmap -oN."""

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        p = subprocess.Popen([sys.executable, "-u", "-c", self.code] + list(argv),
                             start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.procs.append(p)
        return p


_FAKE_NMAP = ("import sys\na = sys.argv[1:]\nprint('Nmap scan report for 10.0.0.5')\n"
              "if '-oN' in a:\n    open(a[a.index('-oN') + 1], 'w').write('# Nmap done\\n')\n")


def test_rx_fix2_scan_results_are_saved_as_evidence_and_the_path_is_in_the_chain(monkeypatch):
    import suite
    sp = ArgvSpawns(_FAKE_NMAP)
    info = _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        p.net_gated.target.setText("10.0.0.5")
        _press(p.net_gated, "portscan")
        argv = sp.calls[0]
        path = argv[argv.index("-oN") + 1]
        assert path.startswith(os.path.join(suite.DATA, "captures") + os.sep) and path.endswith(".txt")
        assert argv[-1] == "10.0.0.5"
        assert _wait(lambda: "[results saved" in p.net_run.out.toPlainText())
        assert p.net_run.saved == path and open(path).read() == "# Nmap done\n"
        spawn = [r for r in _recs(info["path"]) if r["event"] == "spawn"][0]
        assert path in spawn["argv"], "the evidence file is named in the chain"
    finally:
        _close(p)


def test_rx_fix2_a_scan_that_wrote_no_results_says_so(monkeypatch):
    sp = Spawns("print('nmap died')")
    _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        p.net_gated.target.setText("10.0.0.5")
        _press(p.net_gated, "discover")
        assert _wait(lambda: "[results file NOT written" in p.net_run.out.toPlainText())
        assert p.net_run.saved is None
    finally:
        _close(p)


def test_rx_fix2_out_path_cannot_be_an_option():
    import netpent
    _start(["10.0.0.0/24"])
    for bad in ("-oX", "--script=x", ""):
        ok, _w, t = netpent.prepare("discover", "10.0.0.5", out=bad)
        assert not ok and t is None, bad


def test_rx_fix2_ipv6_targets_get_dash_6():
    import netpent
    _start(["fd00::/64"])
    ok, why, t = netpent.prepare("portscan", "fd00::5")
    assert ok, why
    assert "-6" in t.argv and t.argv[-1] == "fd00::5"
    ok, _w, t = netpent.prepare("discover", "fd00::/120")
    assert ok and "-6" in t.argv


def test_rx_fix2_ipv4_targets_never_get_dash_6():
    import netpent
    _start(["10.0.0.0/24"])
    ok, _w, t = netpent.prepare("services", "10.0.0.5")
    assert ok and "-6" not in t.argv


def test_rx_fix2_a_dual_stack_name_is_refused_with_both_addresses(monkeypatch):
    import netpent
    _start(["10.0.0.0/24", "fd00::/64"])
    monkeypatch.setattr(E, "_resolve", lambda h: ["10.0.0.9", "fd00::9"])
    ok, why, t = netpent.prepare("portscan", "nas.lan")
    assert not ok and t is None
    assert "mixes IPv4 and IPv6" in why and "10.0.0.9" in why and "fd00::9" in why


def test_rx_fix2_a_single_word_name_gets_an_honest_refusal():
    import netpent
    _start(["10.0.0.0/24"])
    for name in ("router", "host:nas", "localhost"):
        ok, why, t = netpent.prepare("portscan", name)
        assert not ok and t is None
        assert "single-word name" in why and "use its IP address" in why, why


def test_rx_fix2_nmap_that_scanned_nothing_is_not_done(monkeypatch):
    sp = Spawns("print('setup_target: failed to determine route to ::1'); "
                "print('WARNING: No targets were specified, so 0 hosts scanned.')")
    _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        p.net_gated.target.setText("10.0.0.5")
        _press(p.net_gated, "discover")
        assert _wait(lambda: not p.net_run.state.text().startswith("RUNNING"))
        assert p.net_run.state.text() == "NOTHING SCANNED · exit 0"
    finally:
        _close(p)


# ============================================================ RA-RXc N4 N5 N6

def test_rx_n4_two_scans_in_one_second_never_share_a_results_file(monkeypatch):
    from palisade_qt import recon
    monkeypatch.setattr(recon.time, "strftime", lambda *a: "20261117T000000Z")
    p = _recon(monkeypatch, Spawns())
    try:
        a = p._net_extra("portscan")[0]["out"]
        b = p._net_extra("portscan")[0]["out"]
        assert a != b
        assert p._wifi_extra("pmkid")[0]["out"] != p._wifi_extra("pmkid")[0]["out"]
    finally:
        _close(p)


def test_rx_n5_results_path_must_be_in_the_captures_folder():
    import suite
    import netpent
    _start(["10.0.0.0/24"])
    cap = os.path.join(suite.DATA, "captures")
    for bad in ("/etc/cron.d/x", "/dev/sda", os.path.join(cap, "..", "x.txt"),
                os.path.join(cap, "sub", "x.txt"), "x.txt"):
        ok, _w, t = netpent.prepare("discover", "10.0.0.5", out=bad)
        assert not ok and t is None, bad
    ok, why, t = netpent.prepare("discover", "10.0.0.5", out=os.path.join(cap, "ok.txt"))
    assert ok, why


def test_rx_n6_nothing_scanned_never_claims_results_saved(monkeypatch):
    sp = ArgvSpawns("import sys\na = sys.argv[1:]\n"
                    "open(a[a.index('-oN') + 1], 'w').write('# Nmap header only\\n')\n"
                    "print('WARNING: No targets were specified, so 0 hosts scanned.')\n")
    _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        p.net_gated.target.setText("10.0.0.5")
        _press(p.net_gated, "discover")
        assert _wait(lambda: "[nothing scanned" in p.net_run.out.toPlainText())
        assert "[results saved" not in p.net_run.out.toPlainText()
        assert p.net_run.saved is None and p.net_run.state.text() == "NOTHING SCANNED · exit 0"
    finally:
        _close(p)


# ============================================================ Wi-Fi select-and-act (device ask 2026-11-17)

def _menu_items(menu):
    return [(a.text(), a.isEnabled()) for a in menu.actions() if not a.isSeparator()]


def _find(menu, prefix):
    for a in menu.actions():
        if a.text().startswith(prefix):
            return a
    raise AssertionError("no menu item starting %r in %s" % (prefix, [a.text() for a in menu.actions()]))


def test_wifi_act_button_enables_only_with_a_selection(monkeypatch):
    p = _recon(monkeypatch, Spawns())
    try:
        assert not p.wifi_act_btn.isEnabled()
        p._wifi_pick({"bssid": "AA:BB:CC:11:22:33", "ch": "6", "ssid": "x", "sig": "-50", "sec": "WPA2"})
        assert p.wifi_act_btn.isEnabled()
        p._wifi_pick({})                                  # a header/blank row
        assert not p.wifi_act_btn.isEnabled()
    finally:
        _close(p)


def test_wifi_menu_greys_gated_items_with_the_engine_reason_when_no_engagement(monkeypatch):
    from palisade_qt import recon
    monkeypatch.setattr(recon, "monitor_iface", lambda: "wlan1mon")
    p = _recon(monkeypatch, Spawns())
    try:
        p._wifi_pick({"bssid": "AA:BB:CC:11:22:33", "ch": "6", "ssid": "Cafe", "sig": "-50", "sec": "WPA2"})
        menu = p._build_wifi_menu()
        for label in ("Capture WPA handshake", "Capture PMKID", "Deauth a client"):
            a = _find(menu, label)
            assert not a.isEnabled()
            assert "no active engagement" in a.text()
    finally:
        _close(p)


def test_wifi_menu_greys_everything_out_of_scope(monkeypatch):
    from palisade_qt import recon
    monkeypatch.setattr(recon, "monitor_iface", lambda: "wlan1mon")
    _start(["AA:BB:CC:*"])
    p = _recon(monkeypatch, Spawns())
    try:
        p._wifi_pick({"bssid": "99:99:99:99:99:99", "ch": "1", "ssid": "x", "sig": "-60", "sec": "WPA2"})
        menu = p._build_wifi_menu()
        a = _find(menu, "Capture WPA handshake")
        assert not a.isEnabled() and "not in the engagement scope" in a.text()
    finally:
        _close(p)


def test_wifi_menu_greys_capture_when_no_monitor_interface(monkeypatch):
    from palisade_qt import recon
    monkeypatch.setattr(recon, "monitor_iface", lambda: None)
    _start(["AA:BB:CC:*"])
    p = _recon(monkeypatch, Spawns())
    try:
        p._wifi_pick({"bssid": "AA:BB:CC:11:22:33", "ch": "6", "ssid": "x", "sig": "-50", "sec": "WPA2"})
        menu = p._build_wifi_menu()
        a = _find(menu, "Capture WPA handshake")
        assert not a.isEnabled() and "no monitor-mode interface" in a.text()
    finally:
        _close(p)


def test_wifi_menu_handshake_runs_through_the_gate(monkeypatch):
    from palisade_qt import recon
    monkeypatch.setattr(recon, "monitor_iface", lambda: "wlan1mon")
    sp = Spawns("print('CH 6')")
    info = _start(["AA:BB:CC:*"])
    p = _recon(monkeypatch, sp)
    try:
        p._wifi_pick({"bssid": "AA:BB:CC:11:22:33", "ch": "6", "ssid": "x", "sig": "-50", "sec": "WPA2"})
        menu = p._build_wifi_menu()
        a = _find(menu, "Capture WPA handshake")
        assert a.isEnabled()
        a.trigger()
        assert len(sp.calls) == 1 and sp.calls[0][0] == "airodump-ng"
        assert "AA:BB:CC:11:22:33" in sp.calls[0]
        assert _wait(lambda: not p.wifi_run.state.text().startswith("RUNNING"))
        assert "spawn" in [r["event"] for r in _recs(info["path"])]
    finally:
        _close(p)


def test_wifi_menu_gateway_scan_only_when_associated(monkeypatch):
    from palisade_qt import recon
    monkeypatch.setattr(recon, "monitor_iface", lambda: None)
    _start(["AA:BB:CC:*", "192.168.1.0/24"])
    p = _recon(monkeypatch, Spawns())
    try:
        p._wifi_pick({"bssid": "AA:BB:CC:11:22:33", "ch": "6", "ssid": "x", "sig": "-50", "sec": "WPA2"})
        # not associated -> disabled
        monkeypatch.setattr(p, "_associated_bssid", lambda: None)
        monkeypatch.setattr(p, "_default_gateway", lambda: "192.168.1.1")
        a = _find(p._build_wifi_menu(), "Port-scan the gateway")
        assert not a.isEnabled() and "not associated" in a.text()
        # associated + gateway -> enabled
        monkeypatch.setattr(p, "_associated_bssid", lambda: "aa:bb:cc:11:22:33")
        a = _find(p._build_wifi_menu(), "Port-scan the gateway")
        assert a.isEnabled() and "192.168.1.1" in a.text()
    finally:
        _close(p)


def test_wifi_menu_gateway_scan_runs_on_net_and_is_scope_checked(monkeypatch):
    from palisade_qt import recon
    monkeypatch.setattr(recon, "monitor_iface", lambda: None)
    sp = Spawns("print('Nmap done')")
    _start(["AA:BB:CC:*", "192.168.1.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        monkeypatch.setattr(p, "_associated_bssid", lambda: "aa:bb:cc:11:22:33")
        monkeypatch.setattr(p, "_default_gateway", lambda: "192.168.1.1")
        p._wifi_pick({"bssid": "AA:BB:CC:11:22:33", "ch": "6", "ssid": "x", "sig": "-50", "sec": "WPA2"})
        _find(p._build_wifi_menu(), "Port-scan the gateway").trigger()
        assert p._subtab == "NET"
        assert len(sp.calls) == 1 and sp.calls[0][0] == "nmap" and "192.168.1.1" in sp.calls[0]
    finally:
        _close(p)


def test_wifi_menu_gateway_out_of_scope_is_refused_not_spawned(monkeypatch):
    from palisade_qt import recon
    monkeypatch.setattr(recon, "monitor_iface", lambda: None)
    sp = Spawns()
    _start(["AA:BB:CC:*"])                             # gateway NOT in scope
    p = _recon(monkeypatch, sp)
    try:
        monkeypatch.setattr(p, "_associated_bssid", lambda: "aa:bb:cc:11:22:33")
        monkeypatch.setattr(p, "_default_gateway", lambda: "192.168.1.1")
        p._wifi_pick({"bssid": "AA:BB:CC:11:22:33", "ch": "6", "ssid": "x", "sig": "-50", "sec": "WPA2"})
        _find(p._build_wifi_menu(), "Port-scan the gateway").trigger()
        assert sp.calls == []
        assert "DENIED" in p.net_gated.result.text()
    finally:
        _close(p)
