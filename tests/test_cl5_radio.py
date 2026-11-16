"""CL5 — radio handling + worker lifecycle. One regression test (or group) per audit PoC:
A1 A2 A3 A4 A5 A6 · R1 R2 R3 R4 R5 · E2 E3 · B1 B2 B3 (+ the §15.1 "Workers" items).

Nothing here opens a radio: the arbiter's lease seam is patched, pipelines are python stand-ins,
Qt is offscreen. Real threads and real processes are used where the finding is about them.
"""
import io
import os
import signal
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


# ============================================================================ Worker (A2, Workers)
def test_worker_stop_interrupts_a_long_sleep_at_once():
    from palisade_qt.worker import Worker

    class W(Worker):
        def run(self):
            self.sleep(10_000)
    w = W(interval_ms=10)
    w.start()
    _pump(50)
    t0 = time.time()
    w.stop()
    assert w.wait(2000)
    assert time.time() - t0 < 0.5, "stop() must wake the worker, not wait out the sleep"


def test_worker_pause_and_resume():
    from palisade_qt.worker import Worker
    n = {"steps": 0}

    class W(Worker):
        def step(self):
            n["steps"] += 1
    w = W(interval_ms=5)
    w.start()
    _pump(100)
    assert n["steps"] > 3
    w.pause(True)
    _pump(50)
    a = n["steps"]
    _pump(150)
    assert n["steps"] == a, "a paused worker must not step"
    w.resume()
    _pump(100)
    assert n["steps"] > a
    w.stop()
    assert w.wait(2000)


def test_worker_backs_off_and_raises_one_fault_after_repeated_failures():
    from palisade_qt.worker import Worker
    faults, errors = [], []

    class W(Worker):
        BACKOFF_AFTER = 3
        BACKOFF_MAX_MS = 400
        fail = True

        def step(self):
            if self.fail:
                raise RuntimeError("iw scan failed")
    w = W(interval_ms=10)
    w.fault.connect(faults.append)
    w.error.connect(errors.append)
    w.start()
    _pump(300)
    assert len([f for f in faults if f.startswith("FAULT")]) == 1, faults
    assert w._current_interval() > 10, "interval must back off"
    w.fail = False
    _pump(1200)
    assert faults[-1] == "", "a successful step clears the fault"
    w.stop()
    assert w.wait(2000)


def test_a2_a_worker_that_will_not_join_is_parked_not_aborted(monkeypatch):
    """PoC: a worker outliving wait(3000) had its result ignored and reference dropped -> abort."""
    from palisade_qt import app as appmod
    from palisade_qt.app import PalisadeApp
    from palisade_qt.worker import Worker
    from palisade_qt import eventbus
    monkeypatch.setattr(appmod, "JOIN_GRACE_MS", 150)
    release = threading.Event()

    class Stuck(Worker):
        def run(self):
            release.wait(10)          # a blocking call that ignores stop()

    class A(PalisadeApp):
        TITLE = "STUCK"

        def make_worker(self):
            return Stuck()
    alerts = []
    eventbus.bus.published.connect(lambda e: alerts.append(e) if e["type"] == "alert" else None)
    a = A(demo=True)
    a.start()
    w = a._worker
    _pump(30)
    t0 = time.time()
    a.stop()                          # must return promptly and the process must survive
    assert time.time() - t0 < 1.5
    assert w in appmod.parked() and w.isRunning()
    _pump(50)
    assert any("parked" in e["payload"]["text"] for e in alerts), alerts
    release.set()
    assert w.wait(3000)
    assert appmod.parked() == []


def test_a2_stop_worker_helper_returns_true_when_it_joins():
    from palisade_qt.app import stop_worker
    from palisade_qt.worker import Worker
    w = Worker(interval_ms=10)
    w.start()
    _pump(30)
    assert stop_worker(w, "T") is True and not w.isRunning()


def test_workers_pause_while_their_page_is_hidden():
    from palisade_qt.app import PalisadeApp
    from palisade_qt.worker import Worker
    n = {"steps": 0}

    class W(Worker):
        def step(self):
            n["steps"] += 1

    class A(PalisadeApp):
        def make_worker(self):
            return W(interval_ms=5)
    a = A(demo=True)
    a.start()                         # not active yet -> starts paused
    _pump(100)
    assert n["steps"] == 0
    a.set_active(True)
    _pump(100)
    assert n["steps"] > 0
    k = n["steps"]
    a.set_active(False)
    _pump(50)
    k2 = n["steps"]
    _pump(150)
    assert n["steps"] == k2 and k2 >= k
    a.stop()


# ============================================================================ A5
def test_a5_base_class_has_no_lease_path_and_more_py_is_gone():
    from palisade_qt.app import PalisadeApp
    assert not hasattr(PalisadeApp, "_acquire_lease") and not hasattr(PalisadeApp, "_release_lease")
    assert not os.path.exists(os.path.join(SUITE_DIR, "palisade_qt", "more.py"))


# ============================================================================ A3
def test_a3_request_never_blocks_on_a_slow_acquire(monkeypatch):
    """PoC: owner() on the GUI thread blocked ~90 s while RtlLease.acquire ran under the lock."""
    from palisade_qt import radio_arbiter as ra
    gate = threading.Event()
    released = []

    class Lease:
        def release(self):
            released.append(1)

    def slow(name):
        gate.wait(5)
        return Lease()
    monkeypatch.setattr(ra, "_make_lease", slow)
    t0 = time.time()
    assert ra.arbiter.request("ATLAS-APRS") is True
    assert time.time() - t0 < 0.2
    assert ra.arbiter.state() == ("ACQUIRING", "ATLAS-APRS")
    assert ra.arbiter.owner() == "ATLAS-APRS"            # logical owner at once
    assert ra.arbiter.request("ATLAS-AIS") is False       # nobody else is granted meanwhile
    gate.set()
    assert ra.wait_held("ATLAS-APRS", 3.0)
    assert ra.arbiter.state() == ("HELD", "ATLAS-APRS")
    ra.arbiter.release("ATLAS-APRS")
    assert released == [1] and ra.arbiter.state() == ("FREE", None)


def test_a3_release_during_acquire_releases_the_late_lease(monkeypatch):
    from palisade_qt import radio_arbiter as ra
    gate = threading.Event()
    released = []

    class Lease:
        def release(self):
            released.append(1)
    monkeypatch.setattr(ra, "_make_lease", lambda n: (gate.wait(5), Lease())[1])
    ra.arbiter.request("PRISM")
    ra.arbiter.release("PRISM")                            # gave up while acquiring
    assert ra.arbiter.state() == ("FREE", None)
    gate.set()
    t0 = time.time()
    while not released and time.time() - t0 < 3:
        time.sleep(0.02)
    assert released == [1], "the lease acquired after release must be given back"
    assert ra.arbiter.state() == ("FREE", None)


def test_a3_strip_shows_acquiring_then_held(monkeypatch):
    from palisade_qt import radio_arbiter as ra, chrome
    gate = threading.Event()
    monkeypatch.setattr(ra, "_make_lease", lambda n: (gate.wait(5), None)[1])
    st = chrome.ChromeState(demo=True)
    try:
        ra.arbiter.request("ATLAS-APRS")
        _pump(20)
        assert st.radio() == ("ACQUIRING", "APRS")
        gate.set()
        assert ra.wait_held("ATLAS-APRS", 3.0)
        _pump(20)
        assert st.radio() == ("HELD", "APRS")
    finally:
        st.stop()


# ============================================================================ A1
def test_a1_revoke_asks_the_holder_and_frees_on_its_release():
    from palisade_qt import radio_arbiter as ra
    asked = []
    ra.arbiter.revoked.connect(asked.append)
    ra.arbiter.request("ATLAS-AIS")
    assert ra.wait_held("ATLAS-AIS")
    assert ra.arbiter.revoke() == "ATLAS-AIS"
    _pump(20)
    assert asked == ["ATLAS-AIS"]
    assert ra.arbiter.owner() == "ATLAS-AIS" and ra.arbiter.revoking()   # NOT freed yet
    ra.arbiter.release("ATLAS-AIS")                                     # the acknowledgement
    assert ra.arbiter.owner() is None and not ra.arbiter.revoking()


def test_a1_revoke_times_out_when_the_holder_never_answers(monkeypatch):
    from palisade_qt import radio_arbiter as ra
    ra.arbiter.request("ATLAS-AIS")
    assert ra.wait_held("ATLAS-AIS")
    assert ra.arbiter.revoke(timeout_s=0.2) == "ATLAS-AIS"
    time.sleep(0.5)
    assert ra.arbiter.owner() is None


def test_a1_lease_source_stops_its_pipeline_before_releasing():
    """CL5-fix 1/6: the pipe opens only once HELD; the revoke handler (GUI thread) only flags,
    and the worker's next poll() reaps the pipe and THEN releases."""
    from palisade_qt import atlas, radio_arbiter as ra
    stopped = []

    class FakePipe:
        stdout = io.StringIO("")

        def terminate(self):
            stopped.append(ra.arbiter.owner())      # who held the radio while we were killing

        def poll(self):
            return None

    class Src(atlas.LeaseSource):
        NAME = "ATLAS-APRS"

        def _open_pipe(self):
            return FakePipe()

        def _contacts(self):
            return []

        def feed_line(self, line):
            pass
    s = Src()
    s.start()
    s.poll()
    assert ra.wait_held("ATLAS-APRS", 3.0)
    s.poll()
    assert ra.arbiter.owner() == "ATLAS-APRS" and s._proc is not None
    t0 = time.time()
    ra.arbiter.revoke()
    assert time.time() - t0 < 0.1, "the revoke handler must not block the GUI thread"
    _pump(50)
    assert not stopped and ra.arbiter.owner() == "ATLAS-APRS"   # ack comes from the worker
    s.poll()                                                   # the worker thread's next step
    assert stopped == ["ATLAS-APRS"], "killed while still holding: kill BEFORE release"
    assert ra.arbiter.owner() is None and s.given_back
    s.stop()


# ============================================================================ A6
def test_a6_bus_copies_bounds_and_resizes():
    from palisade_qt import eventbus
    bus = eventbus.EventBus(maxlen=5)
    ev = eventbus.alert("T", "x")
    got = []
    bus.published.connect(got.append)
    bus.publish(ev)
    ev["payload"]["text"] = "MUTATED"
    _pump(20)
    assert got[0]["payload"]["text"] == "x" and bus.recent()[0]["payload"]["text"] == "x"
    # backlog: no event processing -> queued deliveries pile up; past maxlen CONTACTS are
    # dropped (kept in the log). Alerts never are (CL5-fix 8, see test_cl5_fix).
    for i in range(12):
        bus.publish(eventbus.contact("T", str(i), 47.0, -122.0))
    assert bus.pending() <= 5 and bus.dropped() >= 7
    assert len(bus.recent(100)) == 5                         # log bounded
    _pump(30)
    bus.set_retention(50)
    for i in range(20):
        bus.publish(eventbus.alert("T", "r%d" % i))
    _pump(30)
    assert len(bus.recent(100)) == 25


# ============================================================================ A4
def test_a4_pipeline_runs_in_one_session_and_terminate_reaps_every_stage():
    from palisade_qt.kit.procs import Pipeline
    p = Pipeline([[sys.executable, "-c", "import time\nwhile True:\n print('x', flush=True); time.sleep(0.05)"],
                  ["cat"]])
    try:
        assert p.stdout.readline().strip() == "x"
        for q in p.procs:
            assert os.getpgid(q.pid) == q.pid, "every stage leads its own group (killable)"
        assert set(p.sids) == {q.pid for q in p.procs}
        pids = [q.pid for q in p.procs]
        assert p.terminate(grace=0.5) is True
        for q in p.procs:
            assert q.poll() is not None                      # reaped: no zombies
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        p.terminate()


def test_a4_pipeline_kills_a_stage_that_ignores_sigterm():
    from palisade_qt.kit.procs import Pipeline
    p = Pipeline([[sys.executable, "-c",
                   "import signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                   "print('y', flush=True)\nwhile True: time.sleep(0.1)"]])
    assert p.stdout.readline().strip() == "y"
    assert p.terminate(grace=0.2, kill_after=2.0) is True
    assert p.procs[0].returncode == -signal.SIGKILL


def test_a4_decoder_argv_builders_match_the_legacy_strings():
    import aprs
    import ais
    import nwr
    from palisade_qt.kit.procs import split_shell_pipeline
    for legacy, argv in ((aprs.pipeline(10), aprs.pipeline_argv(10)),
                         (ais.pipeline(0), ais.pipeline_argv(0)),
                         (nwr.pipeline("162.400M", 20), nwr.pipeline_argv("162.400M", 20))):
        split = split_shell_pipeline(legacy)
        assert split == argv, (legacy, split, argv)


def test_a4_no_shell_true_pipelines_remain_in_the_qt_package():
    import glob
    bad = []
    for path in glob.glob(os.path.join(SUITE_DIR, "palisade_qt", "**", "*.py"), recursive=True):
        src = open(path).read()
        if "shell=True" in src:
            bad.append(os.path.relpath(path, SUITE_DIR))
    assert bad == [], bad


# ============================================================================ R1 / R2 (BABEL)
def _decoder(monkeypatch, runner=None):
    from palisade_qt import babel
    monkeypatch.setattr(babel, "_can_run", lambda m: True)
    if runner is not None:
        monkeypatch.setitem(babel._LIVE_RUNNERS, "AIS", runner)
    w = babel.DecoderWorker(demo=False, mode="AIS")
    return babel, w


def test_r1_babel_takes_no_radio_until_run_and_releases_when_hidden(monkeypatch):
    from palisade_qt import radio_arbiter as ra
    babel, w = _decoder(monkeypatch)
    w.start()
    try:
        _pump(400)
        assert ra.arbiter.owner() is None, "opening the page must not take the radio"
        w.set_running(True)
        _pump(400)
        assert ra.arbiter.owner() == babel.LEASE_NAME
        w.set_active(False)                              # page hidden
        _pump(600)
        assert ra.arbiter.owner() is None, "a hidden page must give the radio back"
        w.set_active(True)
        _pump(600)
        assert ra.arbiter.owner() == babel.LEASE_NAME
        ra.arbiter.revoke()                              # operator takes it
        _pump(600)
        assert ra.arbiter.owner() is None and not w.wants_radio()
    finally:
        w.stop()
        assert w.wait(3000)


def test_r2_early_decoder_exit_is_a_fault_with_backoff_and_no_lease_churn(monkeypatch):
    """PoC: a decoder that exited at once caused release + re-acquire every 500 ms (10 cycles in
    5 s, each restarting readsb) with the chip reading POCSAG LIVE."""
    from palisade_qt import radio_arbiter as ra
    acquires = []
    monkeypatch.setattr(ra, "_make_lease", lambda n: acquires.append(n) or None)

    class Dead:
        def poll(self):
            return 1
        errfile = io.StringIO("rtl_ais: usb_open error -3\n")

    def dies(worker):
        worker._proc = Dead()
    babel, w = _decoder(monkeypatch, runner=dies)
    faults, status = [], []
    w.fault.connect(faults.append)
    w.status.connect(status.append)
    w.set_running(True)
    w.start()
    try:
        _pump(3500)
        assert acquires == [babel.LEASE_NAME], "the lease must be held across retries, not churned"
        assert ra.arbiter.owner() == babel.LEASE_NAME
        assert any(f.startswith("FAULT") and "usb_open" in f for f in faults), faults
        assert any(s.get("sdr", {}).get("text") == "AIS FAULT" for s in status)
        assert not any(s.get("sdr", {}).get("text") == "AIS LIVE" for s in status)
    finally:
        w.stop()
        assert w.wait(3000)
    assert ra.arbiter.owner() is None


# ============================================================================ R3 / R4 (NWR)
def _held(w):
    from palisade_qt import radio_arbiter as ra
    assert ra.arbiter.request(w.NAME)
    assert ra.wait_held(w.NAME, 3.0)
    w._has_radio = True


def test_r3_dead_nwr_pipeline_shows_down_not_healthy(monkeypatch):
    from palisade_qt import prowl
    monkeypatch.setattr(prowl.shutil, "which", lambda n: "/usr/bin/" + n)

    class Dead:
        stdout = io.StringIO("")

        def poll(self):
            return 137

        def terminate(self):
            pass
    monkeypatch.setattr(prowl, "_open_nwr_pipe", lambda stages: Dead())
    w = prowl.NwrWorker(demo=False)
    status = []
    w.status.connect(status.append)
    w.set_active(True)
    _held(w)                      # CL5-fix 1: the decoder spawns only on a HELD radio
    w.step()                      # spawns
    w.step()                      # sees it dead
    texts = [s.get("sdr", {}).get("text", "") for s in status]
    assert any(t.startswith("NWR DOWN") for t in texts), texts
    assert not any(t.startswith("NWR WX2") and s.get("sdr", {}).get("ok") for s, t in zip(status, texts))


def test_r4_nwr_retune_waits_for_the_old_pipeline_to_exit(monkeypatch):
    from palisade_qt import prowl
    monkeypatch.setattr(prowl.shutil, "which", lambda n: "/usr/bin/" + n)
    order = []

    class Pipe:
        stdout = io.StringIO("")

        def __init__(self, n):
            self.n = n
            self.dead = False

        def poll(self):
            return 0 if self.dead else None

        def terminate(self, *a, **k):
            order.append("terminate-%d" % self.n)
            self.dead = True
            return True
    count = {"n": 0}

    def opener(stages):
        count["n"] += 1
        order.append("spawn-%d" % count["n"])
        return Pipe(count["n"])
    monkeypatch.setattr(prowl, "_open_nwr_pipe", opener)
    w = prowl.NwrWorker(demo=False)
    w.set_active(True)
    _held(w)
    w.step()
    w.set_channel("162.550M", "WX1")
    w.step()
    assert order == ["spawn-1", "terminate-1", "spawn-2"]


# ============================================================================ R5 (SSTV)
def test_r5_sstv_recorder_keeps_a_rolling_window_and_writes_under_cache(tmp_path, monkeypatch):
    """R5 + CL5-fix 12: the file on disk is capped (rotated at window_s, one previous window
    kept) and APPENDED to — every captured byte is written once, never the whole window again."""
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
            return b"\x01\x00" * (n // 2)

    class Proc:
        def __init__(self):
            self.stdout = Stdout(sstv.RATE * 2 * 30)       # 30 s of audio
    monkeypatch.setattr(sstv.S, "stop_group", lambda p, grace=1.0: None, raising=False)
    monkeypatch.setattr(sstv.Recorder, "FLUSH_S", 0)       # flush on every chunk: worst case
    path = str(tmp_path / "w.wav")
    rec = sstv.Recorder(path, 145.8, 40, monitor=False, window_s=4, proc=Proc())
    rec.thread.join(10)
    rec.flush()
    with wave.open(path) as w:
        secs = w.getnframes() / float(w.getframerate())
    assert 0 < secs <= 4.0, secs
    with wave.open(path[:-4] + ".prev.wav") as w:
        assert w.getnframes() / float(w.getframerate()) <= 4.0
    assert rec.window_seconds() <= 4.0
    assert os.path.getsize(path) < 2 * sstv.RATE * 5
    assert rec.bytes_written == sstv.RATE * 2 * 30, "each byte written once (append, no rewrite)"
    # the Qt worker places the capture under the cache dir, not /tmp
    import inspect
    from palisade_qt import babel
    src = inspect.getsource(babel.SstvWorker.step)
    assert "suite.CACHE" in src and "gettempdir" not in src


# ============================================================================ E2 (scan bank)
def test_e2_default_bank_is_intermittent_and_active_dwell_is_capped():
    import scanner
    assert scanner.DEFAULTS["bank"] != "NOAA Wx"
    assert scanner.DEFAULTS["max_active"] > 0
    # a channel with a continuous carrier: listen_channel must return within max_active
    loud = b"\xff\x7f" * 2048
    r, w = os.pipe()
    os.write(w, loud * 4)

    class P:
        pid = os.getpid()

        def __init__(self):
            self.stdout = os.fdopen(r, "rb", buffering=0)

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass
    writer_on = {"on": True}

    def feeder():
        while writer_on["on"]:
            try:
                os.write(w, loud)
            except OSError:
                break
            time.sleep(0.01)
    threading.Thread(target=feeder, daemon=True).start()
    s = dict(scanner.DEFAULTS, max_active=0.6, dwell=0.2, hold=5.0, squelch=10)
    scan = {"on": True, "pause": False, "idx": 0, "rms": 0.0}
    posts = []
    import suite
    stopped = []
    orig = suite.stop_group
    suite.stop_group = lambda p, grace=0.3: stopped.append(1)
    try:
        t0 = time.time()
        res = scanner.listen_channel(162.400, "am", s, scan, posts.append,
                                     popen=lambda *a, **k: P(), sink_fn=lambda: None)
        dt = time.time() - t0
    finally:
        suite.stop_group = orig
        writer_on["on"] = False
    assert res is True and ("hit", 162.400) in posts
    assert dt < 3.0, "a continuous carrier must not park the scanner (max_active)"


def test_e2_skip_locks_out_the_current_channel():
    from palisade_qt import prowl
    w = prowl.ScanWorker(demo=False)
    w._channels = [(462.5625, "1", "nfm"), (462.5875, "2", "nfm"), (462.6125, "3", "nfm")]
    w._scan = {"on": True, "pause": False, "idx": 1, "rms": 0.0}
    assert w.skip_current() == 462.5875
    assert 462.5875 in w._skip and w._scan["pause"] is True
    rows = []
    w.row.connect(rows.append)
    w._emit_state(w._channels, {}, w._scan)
    _pump(20)
    assert rows[-1]["rows"][1]["_skip"] is True and "⊘" in rows[-1]["rows"][1]["label"]
    w.clear_skips()
    assert w._skip == set()


# ============================================================================ E3 (BLE)
def test_e3_ble_scan_is_passive_opt_in_and_surfaces_failures(monkeypatch):
    from palisade_qt import atlas
    assert atlas.RidSource.scanner_kwargs(platform="darwin") == {"scanning_mode": "passive"}
    assert atlas.RidSource.scanner_kwargs(platform="linux")["scanning_mode"] == "passive"
    w = atlas.AtlasLiveWorker()
    w._ensure_sources()
    w._reconcile_rid()
    assert w._rid is None, "opening ATLAS must not start a BLE scan"
    faults = []
    w.error.connect(faults.append)
    monkeypatch.delenv("PALISADE_OFFLINE", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")      # seam: no real scan
    w.set_layer("drone", True)
    w._reconcile_rid()
    assert w._rid is not None
    w.set_layer("drone", False)
    w._reconcile_rid()
    assert w._rid is None
    # a failing scanner backend is reported, not swallowed
    src = atlas.RidSource(on_fault=faults.append)
    src._set_fault("Remote-ID BLE scan failed: adapter off")
    assert faults[-1].startswith("Remote-ID BLE scan failed") and src.state == "fault"


# ============================================================================ B1 / B2 / B3 (PROWL)
def test_b1_fm_tuner_keeps_narrow_channels():
    from palisade_qt import prowl
    p = prowl.ProwlApp(demo=True, mode="dark")
    try:
        p.switch_subtab("FM")
        assert p.fm_freq.decimals() == 3
        p.fm_freq.setValue(162.550)
        assert abs(p.fm_freq.value() - 162.550) < 1e-6, "PoC: 162.550 became 162.6"
        i = next(i for i in range(p.fm_step.count()) if p.fm_step.itemData(i) == 0.025)
        p.fm_step.setCurrentIndex(i)
        p._fm_step(p.fm_step.currentData())
        assert abs(p.fm_freq.value() - 162.575) < 1e-6
        assert p.fm_mode.currentText() == "nbfm"
    finally:
        p.stop()


def test_b2_live_squelch_is_the_engine_setting(monkeypatch):
    from palisade_qt import prowl
    p = prowl.ProwlApp(demo=False, mode="dark")
    try:
        assert p.squelch.isEnabled() and p.squelch.suffix().strip() == "-l"
        w = prowl.ScanWorker(demo=False)
        w._settings = {"nfm_squelch": 50}
        w._scan = {"on": True, "pause": False, "idx": 0, "rms": 0.0}
        p._worker = w
        p.squelch.setValue(120)
        assert w._nfm_sq == 120 and w._settings["nfm_squelch"] == 120 and w._scan["retune"]
        p._worker = None
    finally:
        p.stop()


def test_b3_hit_times_are_epochs_so_midnight_does_not_stick():
    from palisade_qt import prowl
    w = prowl.ScanWorker(demo=False)
    rows = []
    w.row.connect(rows.append)
    chans = [(162.400, "WX2", "nfm")]
    scan = {"on": True, "pause": False, "idx": 0, "rms": 0.0}
    w._emit_state(chans, {162.400: time.time() - 86400 + 10}, scan)   # "23:59:50 yesterday"
    _pump(20)
    assert rows[-1]["rows"][0]["_hot"] is False
    w._emit_state(chans, {162.400: time.time() - 5}, scan)
    _pump(20)
    assert rows[-1]["rows"][0]["_hot"] is True
    assert not hasattr(prowl, "_parse_time")
