"""RA-MAIN-1 PoC: PANIC with everything live at once on merged main."""
import os, subprocess, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
WT = os.environ["WT"]
for p in (WT, os.path.join(WT, "tests")):
    sys.path.insert(0, p)
import pytest
from test_cl1_screen import _pump, _hub, _isolate  # noqa
from test_cl2_gates import _clean, _sleeper_spawner, OP  # noqa
import engagement as E, txguard as G
_isolate = _isolate; _clean = _clean

def _dead(proc, t=6.0):
    end = time.time() + t
    while proc.poll() is None and time.time() < end:
        _pump(20)
    return proc.poll() is not None

def _stubborn():
    # child tree member that ignores SIGTERM (needs the SIGKILL fallback)
    return subprocess.Popen(["sh", "-c", "trap '' TERM; sleep 60 & wait"], start_new_session=True)

def _setup_bench(hub, monkeypatch, tmp_path):
    import bench
    monkeypatch.setattr(bench, "TX_LOG", str(tmp_path / "bench.log"), raising=False)
    iq = tmp_path / "s.iq"; iq.write_bytes(b"\0" * 64)
    monkeypatch.setattr(bench, "saved_settings",
                        lambda: {"tx_enabled": True, "callsign": OP, "iq_file": str(iq)})
    hub.open_callsign("BENCH"); _pump(80)
    page = hub.pages["BENCH"]
    page._spawner = lambda: _sleeper_spawner([])
    return page

def test_panic_everything_live(monkeypatch, tmp_path):
    import executor, netpent
    hub = _hub(demo=False)
    kids = []
    try:
        page = _setup_bench(hub, monkeypatch, tmp_path)
        G.arm(True); G.unlock_session(True)
        page.ack.setChecked(True); _pump(40)
        assert page.tx_btn.isEnabled(), page.gate.text()
        page._tx(); _pump(40)
        assert page._handle is not None and page._handle.running(), "bench did not key"
        bench_proc = page._handle.proc
        E.start("job", "ROE-1", ["10.0.0.0/24"], OP)
        ok, why, t = netpent.prepare("portscan", "10.0.0.5"); assert ok, why
        h2 = executor.start(t, spawner=_sleeper_spawner([]))
        kid = _stubborn(); kids.append(kid)
        hub._list_children = lambda: [kid.pid]
        hub.state.poll(); _pump(40)
        before = (hub.topbar.slots["tx"].text(), len(executor.running()))
        did = hub.panic(); _pump(100)
        banner = hub.panic_banner.text()
        print("BEFORE", before); print("BANNER", banner)
        assert before[0] == "UNLOCKED" and before[1] == 2
        assert _dead(bench_proc) and _dead(h2.proc) and _dead(kid)
        assert executor.running() == []
        assert not page.ack.isChecked() and not page.tx_btn.isEnabled() or page._handle is None
        from palisade_qt import chrome
        assert chrome.read_tx() == "OFF" == hub.topbar.slots["tx"].text()
        assert chrome.tx_permit_sources() == []
        assert "TX OFF" in banner and "BENCH ack revoked" in banner
        assert chrome.read_engagement()[0] == "NONE"
        assert not G.is_armed() and not G.session_unlocked()
    finally:
        for k in kids:
            try: os.killpg(k.pid, 9)
            except Exception: pass
        hub.close(); _pump(150)

def test_stale_permitted_after_plain_disarm_while_keyed(monkeypatch, tmp_path):
    """Is PERMITTED reachable under CL2? Disarm (not PANIC) while BENCH is keyed."""
    from palisade_qt import chrome
    hub = _hub(demo=False)
    try:
        page = _setup_bench(hub, monkeypatch, tmp_path)
        G.arm(True); G.unlock_session(True)
        page.ack.setChecked(True); _pump(40)
        page._tx(); _pump(40)
        assert page._handle.running()
        G.arm(False)
        seen = []
        t0 = time.time()
        while time.time() - t0 < 1.5:
            seen.append((round(time.time() - t0, 2), hub.topbar.slots["tx"].text(), chrome.read_tx()))
            _pump(10)
        words = [s[1] for s in seen]
        print("TIMELINE", [s for i, s in enumerate(seen) if i == 0 or s[1:] != seen[i-1][1:]])
        assert words[-1] == "OFF"
        print("PERMITTED_SEEN", "PERMITTED" in words)
    finally:
        hub.close(); _pump(150)
