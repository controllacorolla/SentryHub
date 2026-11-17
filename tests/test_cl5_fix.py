"""CL5-fix — one regression test per item of RA-CL5's fix list (plan/briefs/RA-CL5-report.md).

Derived from the auditor's PoCs: real processes (shell stand-ins for rtl_fm / rtl_ais /
multimon-ng on PATH) and real worker threads; only the arbiter's lease seam
(radio_arbiter._make_lease) is patched. The decoder seams check QT_QPA_PLATFORM at call time,
so a test that needs a real pipeline sets it to "minimal" for the seam only (the QApplication
is already up on offscreen).
"""
import io
import os
import signal
import stat
import sys
import threading
import time

import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _pump(ms):
    app = _app()
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents()
        time.sleep(0.005)


def _until(pred, ms, step_ms=10):
    t = time.time()
    while time.time() - t < ms / 1000:
        _app().processEvents()
        v = pred()
        if v:
            return v
        time.sleep(step_ms / 1000)
    return pred()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _app()
    from palisade_qt import radio_arbiter as ra, eventbus
    ra.arbiter.reset_for_tests()
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    eventbus.bus.clear()
    yield
    ra.arbiter.reset_for_tests()
    eventbus.bus.clear()


# ------------------------------------------------------------------ real-process helpers
FAKES = {
    # loud NFM audio forever (int16 ±16384); FAKE_STUBBORN=1 ignores SIGTERM
    "rtl_fm": """#!/bin/sh
exec "%(py)s" -c '
import os, signal, sys, time
if os.environ.get("FAKE_STUBBORN"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
b = bytes([0, 0x40, 0, 0xC0]) * 1200
while True:
    try:
        sys.stdout.buffer.write(b); sys.stdout.buffer.flush()
    except (BrokenPipeError, OSError):
        break
    time.sleep(0.05)
' FAKE_rtl_fm "$@"
""",
    "multimon-ng": """#!/bin/sh
exec "%(py)s" -c '
import sys
while sys.stdin.buffer.read(4096):
    pass
' FAKE_multimon-ng "$@"
""",
    "aplay": """#!/bin/sh
exec cat > /dev/null
""",
    "pacat": """#!/bin/sh
exec cat > /dev/null
""",
    "rtl_ais": """#!/bin/sh
while :; do echo '!AIVDM,1,1,,A,15M67FC000G?ufbE`FepT@3n00Sa,0*5F'; sleep 0.2; done
""",
}


@pytest.fixture
def live(monkeypatch, tmp_path):
    """Fake radio binaries on PATH and the decoder seams opened (they check the env at call
    time). HOME is a temp dir so no settings file of the operator's is read."""
    binz = tmp_path / "fakebin"
    binz.mkdir()
    for name, body in FAKES.items():
        p = binz / name
        p.write_text(body % {"py": sys.executable})
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(binz) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PALISADE_OFFLINE", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "minimal")      # seams only; the app stays offscreen
    yield binz
    _reap_strays()


def _procs():
    """{pid: (ppid, state, comm)} from /proc."""
    out = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % d) as f:
                st = f.read()
        except OSError:
            continue
        comm = st[st.index("(") + 1:st.rindex(")")]
        rest = st[st.rindex(")") + 2:].split()
        out[int(d)] = (int(rest[1]), rest[0], comm)
    return out


def _cmdline(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return f.read().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def decoders(names=("rtl_fm", "rtl_ais", "multimon-ng")):
    """Live (non-zombie) descendants of this test process that are fake radio programs."""
    ps = _procs()
    kids, todo, seen = [], [os.getpid()], set()
    while todo:
        p = todo.pop()
        for c, (pp, state, _comm) in ps.items():
            if pp == p and c not in seen:
                seen.add(c)
                todo.append(c)
                cmd = _cmdline(c)
                if state != "Z" and any(("fakebin/" + n) in cmd or ("FAKE_" + n) in cmd
                                        for n in names):
                    kids.append(c)
    return kids


def _reap_strays():
    for pid in decoders():
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass


class _GateLease:
    """Stands in for suite.RtlLease: acquire waits on a gate (readsb being stopped); release is
    recorded with the decoder processes still alive at that moment."""
    def __init__(self):
        self.gate = threading.Event()
        self.released = []

    def make(self, name):
        self.gate.wait(10)
        lease = self

        class L:
            def release(self_inner):
                lease.released.append((name, decoders()))
        return L()


# ============================================================================ 1 — HELD before decode
def test_fix1_no_decoder_starts_before_the_arbiter_says_held(monkeypatch, live):
    """N1 PoC: BABEL showed AIS LIVE and ran rtl_ais (NWR, PRISM, ATLAS-AIS likewise) through the
    whole 2 s ACQUIRING, while readsb still held the dongle. Now nothing spawns until HELD, the
    page says ACQUIRING meanwhile, and only then does LIVE appear."""
    from palisade_qt import babel, radio_arbiter as ra
    gate = _GateLease()
    monkeypatch.setattr(ra, "_make_lease", gate.make)
    w = babel.DecoderWorker(demo=False, mode="AIS")
    status, rows = [], []
    w.status.connect(status.append)
    w.row.connect(rows.append)
    w.set_running(True)
    w.start()
    try:
        _pump(1200)
        assert ra.arbiter.state() == ("ACQUIRING", babel.LEASE_NAME)
        assert decoders() == [], "a decoder ran while the arbiter was still ACQUIRING"
        assert rows == []
        texts = [(s.get("sdr") or {}).get("text", "") for s in status]
        assert any("ACQUIRING" in t for t in texts), texts
        assert not any("LIVE" in t for t in texts), texts
        gate.gate.set()
        assert _until(lambda: decoders(), 3000), "the decoder starts once HELD"
        assert _until(lambda: any("AIS LIVE" in (s.get("sdr") or {}).get("text", "")
                                  for s in status), 2000)
    finally:
        w.stop()
        assert w.wait(4000)
    assert decoders() == [] and ra.arbiter.owner() is None


@pytest.mark.parametrize("holder", ["nwr", "fm", "prism", "atlas", "sstv"])
def test_fix1_every_other_holder_waits_for_held(monkeypatch, holder):
    """The same rule for the other six holders' spawn seams: record the arbiter state at the
    moment each one opens its decoder — it must always be HELD."""
    from palisade_qt import radio_arbiter as ra, prowl, prism, atlas, babel
    gate = _GateLease()
    monkeypatch.setattr(ra, "_make_lease", gate.make)
    spawned = []

    class Pipe:
        stdout = io.StringIO("")
        stderr = None

        def poll(self):
            return None

        def terminate(self, *a, **k):
            return True

        def stop(self):
            pass

    def opener(*a, **k):
        spawned.append(ra.arbiter.state())
        return Pipe()
    monkeypatch.setattr(prowl.shutil, "which", lambda b: "/usr/bin/" + b)
    if holder == "nwr":
        monkeypatch.setattr(prowl, "_open_nwr_pipe", opener)
        w = prowl.NwrWorker(demo=False)
    elif holder == "fm":
        monkeypatch.setattr(prowl, "_open_fm_pipe", opener)
        w = prowl.FmWorker(demo=False)
    elif holder == "prism":
        monkeypatch.setattr(prism, "_open_rtl_power", opener)
        w = prism.SweepWorker(demo=False)
        w.set_active(True)
    elif holder == "sstv":
        monkeypatch.setattr(babel.shutil, "which", lambda b: "/usr/bin/" + b)
        w = babel.SstvWorker(demo=False)
        w._make_recorder = lambda path: (opener(), None)[1]
        w.set_running(True)
    else:
        monkeypatch.setattr(atlas, "_open_ais_pipe", opener)
        w = atlas.AtlasLiveWorker()
        w._adsb_tried = True
        w.set_layer("vessel", True)
    w.start()
    try:
        _pump(900)
        assert spawned == [], "%s opened its decoder during ACQUIRING: %s" % (holder, spawned)
        gate.gate.set()
        assert _until(lambda: spawned, 3000), "%s never started once HELD" % holder
        assert all(st == "HELD" for st, _o in spawned), spawned
    finally:
        w.stop()
        assert w.wait(4000)
    assert ra.arbiter.owner() is None


# ============================================================================ 2 — kill, wait, release
@pytest.mark.parametrize("kind", ["nwr-hide", "nwr-revoke", "fm-hide", "fm-stop"])
def test_fix2_prowl_kills_and_waits_before_it_releases(monkeypatch, live, kind):
    """N4 PoC (poc_release_order): NWR on revoke, NWR on hide and FM on hide released the radio
    while the decoder was still alive (3 of 3). Now the decoder is gone at the moment of release,
    and the release comes from the worker thread."""
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _GateLease()
    lease.gate.set()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    w = prowl.NwrWorker(demo=False) if kind.startswith("nwr") else \
        prowl.FmWorker(demo=False, freq=162.4, mode="nbfm")
    w.set_active(True)
    w.start()
    try:
        assert _until(lambda: decoders(("rtl_fm",)), 4000), "decoder never started"
        if kind.endswith("hide"):
            w.set_active(False)
        elif kind.endswith("revoke"):
            ra.arbiter.revoke()
        else:
            w.stop()
        assert _until(lambda: lease.released, 4000), "never released"
        name, alive = lease.released[0]
        assert alive == [], "released while the decoder still ran: %s" % alive
        assert ra.arbiter.owner() is None
    finally:
        w.stop()
        assert w.wait(4000)


def test_fix2_scan_stop_never_releases_while_listen_channel_runs(monkeypatch):
    """N4: ScanWorker.stop() released from the GUI thread while listen_channel's rtl_fm was
    alive. Now stop() only flags; the release follows listen_channel's return."""
    from palisade_qt import prowl, radio_arbiter as ra
    import scanner
    order = []

    def listen(freq, mode, s, scan, post, **k):
        order.append("listen")
        while scan["on"] and not scan["pause"]:
            time.sleep(0.02)
        time.sleep(0.3)                           # stop_group(rtl_fm) waiting for the exit
        order.append("listen-exit owner=%s" % ra.arbiter.owner())
        return False
    monkeypatch.setattr(scanner, "listen_channel", listen)
    monkeypatch.setattr(prowl, "_offscreen", lambda: False)
    monkeypatch.setattr(prowl.shutil, "which", lambda b: "/usr/bin/" + b)
    w = prowl.ScanWorker(demo=False, bank="GMRS/FRS")
    w.set_active(True)
    w.start()
    try:
        assert _until(lambda: order, 3000)
        w.stop()
        assert ra.arbiter.owner() == "PROWL-SCAN", "stop() must not release on the GUI thread"
    finally:
        assert w.wait(4000)
    assert order[-1] == "listen-exit owner=PROWL-SCAN", order
    assert ra.arbiter.owner() is None


# ============================================================================ 3 — SSTV RUN / hide / revoke
def test_fix3_sstv_takes_the_radio_only_on_run_and_gives_it_back(monkeypatch):
    """R1 PoC: SstvWorker took the radio with RUN off, kept it while hidden (paused worker,
    Recorder still running) and ignored a revoke until the forced free."""
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setattr(babel.shutil, "which", lambda b: "/usr/bin/" + b)
    stops = []

    class Rec:
        err, level = "", 0.0

        def seconds(self):
            return 1.0

        def total_samples(self):
            return 0

        def stop(self):
            stops.append(ra.arbiter.owner())          # who held it while capture stopped
    w = babel.SstvWorker(demo=False)
    w._make_recorder = lambda path: Rec()
    status = []
    w.status.connect(status.append)
    assert w.PAUSE_WHEN_HIDDEN is False
    w.start()
    try:
        _pump(600)
        assert ra.arbiter.owner() is None, "SSTV took the radio with RUN off"
        w.set_running(True)
        assert _until(lambda: w._rec is not None, 3000)
        w.set_active(False)                                # page hidden
        assert _until(lambda: ra.arbiter.owner() is None, 2000), "hidden SSTV kept the radio"
        assert stops == ["BABEL-SSTV"], "capture stopped BEFORE release: %s" % stops
        w.set_active(True)
        assert _until(lambda: w._rec is not None, 3000)
        t0 = time.time()
        ra.arbiter.revoke()
        assert time.time() - t0 < 0.1
        assert _until(lambda: ra.arbiter.owner() is None, 2500), "revoke not acknowledged"
        assert not ra.arbiter.revoking(), "acknowledged by release, not by the forced timeout"
        _pump(1200)
        assert ra.arbiter.owner() is None, "SSTV re-took the radio after the revoke"
        assert any(s.get("run_off") for s in status), "the page must untick RUN"
    finally:
        w.stop()
        assert w.wait(4000)


# ============================================================================ 4 — SCAN revoke
def test_fix4_scan_revoke_breaks_an_active_listen(monkeypatch, live):
    """A1 PoC (poc_revoke, scan): on an active channel PROWL-SCAN acked a revoke only after
    max_active (20 s), so the arbiter force-freed with rtl_fm alive. Now the revoke breaks the
    real listen_channel at once and rtl_fm is gone when the radio is released."""
    from palisade_qt import prowl, radio_arbiter as ra
    import scanner
    lease = _GateLease()
    lease.gate.set()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    monkeypatch.setattr(prowl, "_offscreen", lambda: False)
    monkeypatch.setattr(scanner, "sink_cmd", lambda: None)
    w = prowl.ScanWorker(demo=False, bank="GMRS/FRS")
    w.set_active(True)
    w.start()
    try:
        assert _until(lambda: decoders(("rtl_fm",)), 4000)
        _pump(1500)                                        # the channel is active (loud audio)
        t0 = time.time()
        ra.arbiter.revoke(timeout_s=5.0)
        assert _until(lambda: lease.released, 3000), "SCAN never acknowledged the revoke"
        assert time.time() - t0 < 2.0
        assert lease.released[0][1] == [], "released with rtl_fm alive"
        assert not ra.arbiter.revoking()
        _pump(800)
        assert ra.arbiter.owner() is None and decoders(("rtl_fm",)) == []
    finally:
        w.stop()
        assert w.wait(4000)


# ============================================================================ 5 — PANIC
def test_fix5_panic_frees_the_radio_and_nothing_respawns(monkeypatch, live):
    """N3 PoC (poc_panic): after PANIC the arbiter stayed HELD and BABEL respawned rtl_ais ~2 s
    later (NWR ~0.5 s). Now PANIC frees the arbiter, the banner says so, RUN is unticked and no
    decoder comes back."""
    from palisade_qt import radio_arbiter as ra, shell
    import txguard
    import engagement
    monkeypatch.setattr(txguard, "arm", lambda on: None, raising=False)
    monkeypatch.setattr(engagement, "end", lambda: None, raising=False)
    hub = shell.PalisadeHub(demo=False, mode="dark")
    hub.resize(1280, 720)
    hub.show()
    try:
        _pump(300)
        hub.open_callsign("BABEL")
        _pump(400)
        page = hub.page_app("BABEL")
        page.mode_combo.setCurrentText("AIS")
        _pump(200)
        page.run_btn.setChecked(True)
        assert _until(lambda: decoders(("rtl_ais",)), 4000), "BABEL never started rtl_ais"
        assert ra.arbiter.state() == ("HELD", "BABEL")
        did = hub.panic()
        assert any(d.startswith("radio released") for d in did), did
        assert ra.arbiter.state() == ("FREE", None)
        assert not page.run_btn.isChecked(), "PANIC must untick RUN"
        for _ in range(6):                                 # 3 s: it must STAY free
            _pump(500)
            assert ra.arbiter.state() == ("FREE", None), "a page re-took the radio after PANIC"
            assert decoders(("rtl_ais",)) == [], "a decoder respawned after PANIC"
    finally:
        hub.close()
        _pump(500)


def test_fix5_panic_holds_nwr_off_until_the_operator_resumes(live):
    from palisade_qt import radio_arbiter as ra, prowl
    p = prowl.ProwlApp(demo=False, mode="dark")
    p.set_active(True)
    p.switch_subtab("NWR")
    p.start()
    try:
        assert _until(lambda: decoders(("rtl_fm",)), 4000)
        assert p.on_panic() == []
        ra.arbiter.panic_free()                            # (the shell kills the tree between)
        assert ra.arbiter.state() == ("FREE", None)
        assert _until(lambda: not decoders(("rtl_fm",)), 3000)
        _pump(1500)
        assert ra.arbiter.owner() is None and decoders(("rtl_fm",)) == [], "NWR respawned"
        assert "NOT MONITORING" in p.nwr_state.text()
        assert p.primary_action() is True                  # Enter resumes
        assert _until(lambda: decoders(("rtl_fm",)), 4000), "resume must restart the receiver"
    finally:
        p.stop()
        _pump(300)


# ============================================================================ 6 — no GUI-thread blocks
def test_fix6_stop_hide_and_revoke_never_block_the_gui_thread(monkeypatch, live):
    """poc_gui_block: BABEL hide, STOP and revoke each blocked the GUI thread 1.00 s when a stage
    ignored SIGTERM; ATLAS acked a revoke synchronously (2.00 s). Every GUI-thread entry point is
    now a flag + a non-blocking kill, and the release still waits for the stubborn stage."""
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setenv("FAKE_STUBBORN", "1")
    lease = _GateLease()
    lease.gate.set()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    import ais
    monkeypatch.setattr(ais, "pipeline_argv", lambda gain=0: [["rtl_fm", "-f", "162.0M", "-"]])
    w = babel.DecoderWorker(demo=False, mode="AIS")
    w.set_running(True)
    w.start()
    try:
        for action in ("stop", "hide", "revoke"):
            lease.released.clear()
            assert _until(lambda: decoders(("rtl_fm",)), 4000), action
            t0 = time.time()
            if action == "stop":
                w.set_running(False)
            elif action == "hide":
                w.set_active(False)
            else:
                ra.arbiter.revoke()
            took = time.time() - t0
            assert took < 0.1, "%s blocked the GUI thread %.2f s" % (action, took)
            assert _until(lambda: lease.released, 4000), action
            assert lease.released[0][1] == [], "%s released before the stubborn stage died" % action
            w.set_active(True)
            w.set_running(True)
    finally:
        w.stop()
        assert w.wait(4000)


def test_fix6_atlas_revoke_ack_is_off_the_gui_thread(monkeypatch):
    from palisade_qt import atlas, radio_arbiter as ra

    class SlowPipe:
        stdout = io.StringIO("")

        def terminate(self):
            time.sleep(1.0)                    # a stage that ignores SIGTERM
            return True
    monkeypatch.setattr(atlas, "_open_ais_pipe", lambda gain: SlowPipe())
    s = atlas.AisSource()
    s.start()
    s.poll()
    assert ra.wait_held("ATLAS-AIS", 3.0)
    s.poll()
    t0 = time.time()
    ra.arbiter.revoke()
    _pump(20)
    assert time.time() - t0 < 0.2, "the revoke ack ran on the GUI thread"
    s.poll()                                   # the worker thread acks (and may take its time)
    assert ra.arbiter.owner() is None
    s.stop()


# ============================================================================ 7 — honest give-back
def test_fix7_nwr_never_reads_monitoring_after_the_radio_is_given_back(live):
    """N2 (Critical) PoC: after a revoke / forced free the NWR page kept MONITORING, a green
    'NWR WX2 162.400M' chip and NO ALERTS with the radio FREE and no decoder. Now it reads LIVE
    only while PROWL-NWR holds the radio with a running decoder, and NOT MONITORING otherwise."""
    from palisade_qt import radio_arbiter as ra, prowl
    p = prowl.ProwlApp(demo=False, mode="dark")
    p.set_active(True)
    p.switch_subtab("NWR")
    p.start()
    try:
        assert "NOT MONITORING" in p.nwr_state.text()             # nothing yet: not monitoring
        assert _until(lambda: p.nwr_state.text().startswith("LIVE"), 5000), p.nwr_state.text()
        assert p.nwr_monitoring()
        ra.arbiter.revoke()
        assert _until(lambda: "NOT MONITORING" in p.nwr_state.text(), 3000), p.nwr_state.text()
        _pump(600)
        assert ra.arbiter.owner() is None and decoders(("rtl_fm",)) == []
        assert "NOT MONITORING" in p.nwr_state.text()
        sdr = p._last_status.get("sdr") or {}
        assert not sdr.get("ok") and "NWR WX" not in (sdr.get("text") or ""), sdr
        assert "NOT MONITORING" in p.nwr_detail.hero.text() + " " + \
            " ".join(lbl.text() for lbl in p.nwr_detail.findChildren(QtWidgets.QLabel))
    finally:
        p.stop()
        _pump(300)


def test_fix7_a_silent_or_forced_free_receiver_goes_not_monitoring(monkeypatch):
    """The page does not trust a stale LIVE: no healthy status for NWR_STALE_S, or the arbiter
    not holding PROWL-NWR (a forced free), flips it to NOT MONITORING on its own timer."""
    from palisade_qt import radio_arbiter as ra, prowl
    p = prowl.ProwlApp(demo=False, mode="dark")
    p._submode = "NWR"
    p._worker = prowl.NwrWorker(demo=False)
    ra.arbiter.request("PROWL-NWR")
    assert ra.wait_held("PROWL-NWR")
    p.on_status({"src": "NWR", "live": True, "sdr": {"text": "NWR WX2 162.400M", "ok": True}})
    assert p.nwr_state.text().startswith("LIVE")
    ra.arbiter.release("PROWL-NWR")                         # forced free under the page
    p._sync_nwr_state()
    assert "NOT MONITORING" in p.nwr_state.text()
    ra.arbiter.request("PROWL-NWR")
    assert ra.wait_held("PROWL-NWR")
    p.on_status({"src": "NWR", "live": True, "sdr": {"text": "NWR WX2 162.400M", "ok": True}})
    assert p.nwr_state.text().startswith("LIVE")
    p._live_ts -= p.NWR_STALE_S + 1                          # the worker went silent
    p._sync_nwr_state()
    assert "NOT MONITORING" in p.nwr_state.text() and "silent" in p.nwr_state.text()
    p._worker = None
    p.stop()


@pytest.mark.parametrize("cls", ["ScanWorker", "FmWorker", "NwrWorker"])
def test_fix7_every_prowl_give_back_says_off(cls):
    from palisade_qt import prowl, radio_arbiter as ra
    w = getattr(prowl, cls)(demo=False)
    status = []
    w.status.connect(status.append)
    ra.arbiter.request(w.NAME)
    assert ra.wait_held(w.NAME)
    w._has_radio = True
    w._on_revoked(w.NAME)
    w._ensure_lease()
    assert ra.arbiter.owner() is None
    off = [s for s in status if s.get("off")]
    assert off and off[-1]["live"] is False and "OFF" in off[-1]["sdr"]["text"]
    assert off[-1]["sdr"]["ok"] is False


def test_fix7_prism_says_off_when_it_gives_the_radio_back():
    from palisade_qt import prism, radio_arbiter as ra
    w = prism.SweepWorker(demo=False)
    status = []
    w.status.connect(status.append)
    w.set_active(True)
    w.step()
    assert ra.wait_held("PRISM")
    w.step()
    w._on_revoked("PRISM")
    w.step()
    assert ra.arbiter.owner() is None
    assert any(s.get("off") and "SDR OFF" in s["sdr"]["text"] for s in status), status


# ============================================================================ 8 — alerts never dropped
def test_fix8_a_warning_during_a_gui_stall_reaches_the_alert_store():
    """N5 PoC (poc_alert_drop): a Tornado Warning published during a GUI stall under 300
    contacts/s never reached the AlertStore (only the log). Alerts are never dropped now."""
    from palisade_qt import eventbus, panels
    store = panels.AlertStore()
    bus = eventbus.bus
    n0 = len(store.items)
    for i in range(bus._maxlen + 200):                       # GUI stalled: nothing delivered
        bus.publish(eventbus.contact("ATLAS", "c%d" % i, 47.0, -122.0))
    bus.publish(eventbus.alert("PROWL", "Tornado Warning — King", severity="alert", event="TOR"))
    for i in range(300):
        bus.publish(eventbus.contact("ATLAS", "d%d" % i, 47.0, -122.0))
    assert bus.dropped() > 0, "the contact backlog is still bounded"
    _pump(200)
    texts = [it["text"] for it in store.items[: len(store.items) - n0]]
    assert any("Tornado Warning" in t for t in texts), "the alert was dropped"


# ============================================================================ 9 — Pipeline
def _alive(pid):
    st = _procs().get(pid)
    return st is not None and st[1] != "Z"


def test_fix9_pipeline_kills_a_child_that_ignores_sigterm(tmp_path):
    """poc_pipeline (a): a stage's child that ignored SIGTERM survived, and terminate() still
    returned True."""
    from palisade_qt.kit.procs import Pipeline
    pidf = tmp_path / "child.pid"
    child = ("import signal,time,os; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
             "open(%r,'w').write(str(os.getpid())); time.sleep(60)" % str(pidf))
    stage = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',%r]); " \
            "time.sleep(60)" % child
    p = Pipeline([[sys.executable, "-c", stage]])
    assert _until(lambda: pidf.exists() and pidf.read_text(), 3000)
    cpid = int(pidf.read_text())
    assert p.terminate(grace=0.3) is True
    assert not _alive(cpid), "the stage's SIGTERM-ignoring child survived"


def test_fix9_pipeline_kills_the_child_of_a_stage_that_forked_and_exited(tmp_path):
    """poc_pipeline (c): _signal skipped groups whose leader had exited, so the grandchild lived."""
    from palisade_qt.kit.procs import Pipeline
    pidf = tmp_path / "gc.pid"
    child = "import time,os; open(%r,'w').write(str(os.getpid())); time.sleep(60)" % str(pidf)
    stage = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',%r])" % child
    p = Pipeline([[sys.executable, "-c", stage]])
    assert _until(lambda: pidf.exists() and pidf.read_text(), 3000)
    gpid = int(pidf.read_text())
    assert _until(lambda: p.procs[0].poll() is not None, 3000)     # the leader is gone
    assert p.terminate(grace=0.3) is True
    assert not _alive(gpid), "the forked grandchild survived"


def test_fix9_a_failed_later_stage_does_not_leak_stage_one(tmp_path):
    """poc_pipeline (e): stage N's binary missing left stage 1 (rtl_fm) running on the dongle."""
    from palisade_qt.kit.procs import Pipeline
    pidf = tmp_path / "s1.pid"
    s1 = "import time,os; open(%r,'w').write(str(os.getpid())); time.sleep(60)" % str(pidf)
    with pytest.raises(FileNotFoundError):
        Pipeline([[sys.executable, "-c", s1], ["/nonexistent/multimon-ng-missing"]])
    if pidf.exists() and pidf.read_text():
        assert _until(lambda: not _alive(int(pidf.read_text())), 3000), "stage 1 leaked"
    assert not [pid for pid, (pp, st, c) in _procs().items()
                if pp == os.getpid() and st != "Z" and s1[:20] in _cmdline(pid)]


# ============================================================================ 10 — E3 on BlueZ
def test_fix10_passive_ble_scan_has_bluez_or_patterns():
    """poc_e3_bleak: bleak/BlueZ refuses passive mode without or_patterns, so DRONES never
    scanned on the uConsole."""
    from palisade_qt import atlas
    kw = atlas.RidSource.scanner_kwargs(platform="linux")
    assert kw["scanning_mode"] == "passive"
    pats = kw["bluez"]["or_patterns"]
    assert pats and int(pats[0][1]) == 0x16 and pats[0][2] == b"\xfa\xff" and pats[0][0] == 0
    if not sys.platform.startswith("linux"):
        return
    try:
        from bleak import BleakScanner
    except Exception:
        pytest.skip("bleak is not installed")
    with pytest.raises(Exception, match="or_patterns"):
        BleakScanner(scanning_mode="passive")              # the PoC: refused on BlueZ
    BleakScanner(**kw)                                     # accepted with our patterns


def test_fix10_atlas_shows_a_source_fault_on_the_page():
    from palisade_qt import atlas
    p = atlas.AtlasApp(demo=False, mode="dark")
    p.on_error("Remote-ID BLE scan failed: adapter off")
    assert "Remote-ID BLE scan failed" in p.page_status().get("fault", "")
    p.stop()


# ============================================================================ 11 — B2 retune
def test_fix11_a_squelch_retune_is_not_a_hit(monkeypatch):
    """poc_b2_retune: listen_channel's "retune" (a squelch change) was recorded as a hit, so an
    empty channel showed ACTIVE for 30 s and the scanner moved on."""
    from palisade_qt import prowl, radio_arbiter as ra
    import scanner
    calls = []

    def listen(freq, mode, s, scan, post, **k):
        calls.append(freq)
        if len(calls) == 1:
            return "retune"
        scan["on"] = False
        return False
    monkeypatch.setattr(scanner, "listen_channel", listen)
    monkeypatch.setattr(prowl, "_offscreen", lambda: False)
    monkeypatch.setattr(prowl.shutil, "which", lambda b: "/usr/bin/" + b)
    w = prowl.ScanWorker(demo=False, bank="GMRS/FRS")
    rows = []
    w.row.connect(rows.append)
    ra.arbiter.request(w.NAME)
    assert ra.wait_held(w.NAME)
    w._has_radio = True
    w._run_live()
    assert len(calls) == 2 and calls[0] == calls[1], "a retune re-listens the SAME channel"
    _pump(50)
    assert not any(r.get("_hot") for msg in rows for r in msg["rows"]), "retune made a hit"
    w._finish()


# ============================================================================ 12 — SSTV new audio only
def test_fix12_sstv_decodes_only_new_audio_and_publishes_one_event_per_frame(monkeypatch):
    """N9: the whole 240 s window (11.5 MB) was decoded every 12 s and re-emitted the same
    frame (and decode event) each pass. Now a decode reads only the new audio (plus a short
    overlap, or the frame being received) and a frame produces one decode event."""
    import numpy as np
    import sstv
    from palisade_qt import babel, eventbus
    fs = sstv.RATE
    w = babel.SstvWorker(demo=False)
    seen = []

    class Rec:
        n = 0

        def total_samples(self):
            return self.n

        def samples_since(self, a):
            a = max(0, int(a), self.n - 240 * fs)
            return b"\0\0" * (self.n - a), a
    rec = Rec()
    w._rec = rec               # the live recorder (CL5-fix2 N-e: a job for any other is dropped)
    result = {"r": None}

    def decode(x, f):
        seen.append(len(x) / fs)
        if result["r"] is None:
            raise ValueError("no SSTV header found - nothing was being sent")
        return dict(result["r"])
    w._decode = decode
    events = []
    eventbus.bus.published.connect(events.append)
    # 200 s of nothing: each decode sees only ~12 s new + 2 s overlap, never the window
    for _ in range(15):
        rec.n += 13 * fs
        w._decode_job(rec, fs)
    assert max(seen[1:]) <= 13 + w.OVERLAP_S + 0.01, seen
    # a frame starts: refinements re-read it but publish ONE event; complete -> move on
    base_n = rec.n
    rec.n += 13 * fs
    img = np.zeros((4, 4, 3), np.uint8)
    rel = (rec.n - 13 * fs) - w._scan_from + fs           # image starts 1 s into the new audio
    result["r"] = {"image": img, "mode": "PD120", "lines": 40, "slant_ppm": 0,
                   "start": rel, "t0": rel, "period": 0.508 * fs}
    w._decode_job(rec, fs)
    first_from = w._scan_from
    rec.n += 13 * fs
    r2 = dict(result["r"])
    r2["start"] = r2["t0"] = (base_n + fs) - first_from
    r2["lines"] = 496
    result["r"] = r2
    w._decode_job(rec, fs)
    _pump(50)
    decs = [e for e in events if e["type"] == "decode" and e["source"] == "BABEL-SSTV"]
    assert len(decs) == 1, "one decode event per frame, not one per pass"
    assert w._frame is None and w._scan_from > base_n, "a complete frame moves the scan on"


def test_fix12_recorder_appends_and_never_rewrites(tmp_path, monkeypatch):
    """N9: flush() rewrote the full 11.5 MB window every 5 s (~8 GB/h of flash writes). Bytes
    written to disk must equal bytes captured (each written once)."""
    import sstv
    import wave

    class Stdout:
        def __init__(self, total):
            self.left = total

        def read(self, n):
            if self.left <= 0:
                return b""
            n = min(n, self.left)
            self.left -= n
            time.sleep(0.0005)
            return b"\x01\x00" * (n // 2)

    class Proc:
        stdout = Stdout(sstv.RATE * 2 * 20)                 # 20 s of audio
    monkeypatch.setattr(sstv.Recorder, "FLUSH_S", 0.01)
    monkeypatch.setattr(sstv.S, "stop_group", lambda p, grace=1.0: None, raising=False)
    path = str(tmp_path / "a.wav")
    rec = sstv.Recorder(path, 145.8, 40, monitor=False, window_s=60, proc=Proc())
    rec.thread.join(15)
    assert rec.bytes_written == sstv.RATE * 2 * 20
    with wave.open(path) as w:
        assert w.getnframes() == sstv.RATE * 20                # one valid, complete WAV
    data, start = rec.samples_since(rec.total_samples() - sstv.RATE)
    assert start == rec.total_samples() - sstv.RATE and len(data) == 2 * sstv.RATE
