"""CL5-fix2 — one regression test per RA-CL5b finding (plan/briefs/RA-CL5b-report.md §3/§6).

Same rules as test_cl5_fix.py (whose helpers and fixtures this reuses): real processes (fake
rtl_fm / rtl_ais / multimon-ng on PATH), real worker threads, and only the arbiter's lease seam
patched.
"""
import os
import sys
import threading
import time
import wave

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
for d in (SUITE_DIR, TESTS_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import test_cl5_fix as _H  # noqa: E402

_GateLease, _pump, _until, decoders = _H._GateLease, _H._pump, _H._until, _H.decoders
_reset = _H._reset           # autouse: fresh arbiter + bus per test
live = _H.live               # fake radio binaries on PATH, decoder seams open


class _SlowLease(_GateLease):
    """A lease whose release takes `slow` seconds (readsb restarting), recording the decoders
    still alive when it was asked to release."""
    def __init__(self, slow):
        super().__init__()
        self.gate.set()
        self.slow = slow

    def make(self, name):
        lease = self

        class L:
            def release(self_inner):
                lease.released.append((name, decoders()))
                time.sleep(lease.slow)
        return L()


# ============================================================================ N-a
def test_na_hidden_atlas_answers_a_revoke_and_reaps_before_release(monkeypatch, live):
    """RA-CL5b N-a: with ATLAS hidden and AIS on, a revoke was never acknowledged (the worker
    was paused), the arbiter forced the radio free after 5 s with rtl_ais still on the dongle,
    and RADIOS read FREE. Now the hidden worker acknowledges: rtl_ais reaped, THEN released, well
    inside the revoke timeout, and never a forced free."""
    from palisade_qt import atlas, radio_arbiter as ra
    lease = _GateLease()
    lease.gate.set()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    monkeypatch.setattr(ra, "REVOKE_TIMEOUT_S", 4.0)
    notes = []
    if hasattr(ra.arbiter, "transition"):
        ra.arbiter.transition.connect(lambda e, o, n: notes.append((e, o, n)))
    app = atlas.AtlasApp(demo=False, mode="dark")
    app.set_active(True)
    app.start()
    try:
        app._worker.set_layer("vessel", True)
        assert _until(lambda: decoders(("rtl_ais",)), 5000), "AIS layer never started"
        app.set_active(False)                       # the operator leaves ATLAS
        _pump(300)
        assert not app._worker.paused, "a radio holder must not be paused while hidden"
        t0 = time.time()
        ra.arbiter.revoke()
        assert _until(lambda: ra.arbiter.owner() is None, 3000), "hidden ATLAS never acked"
        assert time.time() - t0 < 3.0
        assert lease.released and lease.released[0][1] == [], \
            "released with rtl_ais still running: %r" % lease.released
        _pump(100)
        assert not any("FORCED" in n for _e, _o, n in notes), notes
        assert decoders(("rtl_ais",)) == []
        _pump(1500)                                 # and it does not come back while hidden
        assert decoders(("rtl_ais",)) == [] and ra.arbiter.owner() is None
    finally:
        app.stop()
    assert decoders() == []


def test_na_hidden_atlas_starts_its_decoder_once_held(monkeypatch, live):
    """N-a (related): ATLAS hidden while ACQUIRING kept the radio HELD with no decoder until it
    was fronted. A hidden lease layer now finishes starting (or gives the radio back)."""
    from palisade_qt import atlas, radio_arbiter as ra
    gate = _GateLease()
    monkeypatch.setattr(ra, "_make_lease", gate.make)
    app = atlas.AtlasApp(demo=False, mode="dark")
    app.set_active(True)
    app.start()
    try:
        app._worker.set_layer("vessel", True)
        assert _until(lambda: ra.arbiter.state() == ("ACQUIRING", "ATLAS-AIS"), 3000)
        app.set_active(False)
        gate.gate.set()
        assert _until(lambda: decoders(("rtl_ais",)), 5000), "HELD with no decoder while hidden"
    finally:
        app.stop()
    assert decoders() == [] and ra.arbiter.owner() is None


# ============================================================================ N-c
def test_nc_prowl_submode_switch_never_waits_on_the_gui_thread(monkeypatch, live):
    """RA-CL5b N-c: _switch_submode waited up to 3 s on the GUI thread and then dropped a still
    running QThread (SIGABRT with a 3.5 s release). Now the switch returns at once, the old
    worker is kept until it has finished (kill -> wait -> release), and only then does the new
    sub-mode take the radio — never two decoders on the dongle."""
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _SlowLease(3.5)
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    p = prowl.ProwlApp(demo=False, mode="dark")
    p.set_active(True)
    p.switch_subtab("NWR")
    p.start()
    try:
        assert _until(lambda: ra.arbiter.held_by("PROWL-NWR") and decoders(("rtl_fm",)), 5000)
        old = p._worker
        t0 = time.time()
        p.switch_subtab("FM")
        took = time.time() - t0
        assert took < 0.2, "sub-mode switch blocked the GUI thread %.2f s" % took
        assert old.isRunning(), "the 3.5 s release is still in progress"
        assert p._worker is None and p.swapping(), "no new worker while the old one releases"
        _pump(200)
        assert "NWR WX" not in " ".join(p.page_status().values()), \
            "the old sub-mode's chip still claims the radio: %r" % p.page_status()
        assert ra.arbiter.owner() is None, "FREE is announced before the slow lease release"
        assert "NOT MONITORING" in p.nwr_state.text() or p._submode != "NWR"
        assert _until(lambda: not old.isRunning(), 6000), "old worker never finished"
        assert lease.released[0] == ("PROWL-NWR", []), "released before the decoder died"
        assert _until(lambda: isinstance(p._worker, prowl.FmWorker)
                      and ra.arbiter.held_by("PROWL-FM"), 5000), "FM never started"
        assert len(decoders(("rtl_fm",))) <= 1
    finally:
        p.stop()
        _pump(200)
    assert decoders() == []


def test_nc_panic_during_a_pending_switch_starts_nothing(monkeypatch, live):
    """A switch waiting on the old worker must not start a decoder after PANIC."""
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _SlowLease(1.0)
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    p = prowl.ProwlApp(demo=False, mode="dark")
    p.set_active(True)
    p.switch_subtab("NWR")
    p.start()
    try:
        assert _until(lambda: decoders(("rtl_fm",)), 5000)
        old = p._worker
        p.switch_subtab("FM")
        p.on_panic()
        ra.arbiter.panic_free()
        assert _until(lambda: not old.isRunning(), 5000)
        _pump(1500)
        assert p._worker is None and decoders() == [] and ra.arbiter.owner() is None
        assert "Enter" in p.busy.text()
        assert p._resume_radio()                  # the operator asks again: FM starts
        assert _until(lambda: ra.arbiter.held_by("PROWL-FM"), 4000)
    finally:
        p.stop()
        _pump(200)


def test_nc_babel_decoder_switch_never_waits_on_the_gui_thread(monkeypatch, live):
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setenv("FAKE_STUBBORN", "1")       # a stage that ignores SIGTERM
    lease = _SlowLease(2.2)
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    import ais
    monkeypatch.setattr(ais, "pipeline", lambda gain=0: [["rtl_fm", "-f", "162.0M", "-"]])
    b = babel.BabelApp(demo=False, mode="dark")
    b.set_active(True)
    b.start()
    try:
        b.mode_combo.setCurrentText("AIS")
        b.run_btn.setChecked(True)
        assert _until(lambda: decoders(("rtl_fm",)), 5000)
        old = b._worker
        t0 = time.time()
        b.mode_combo.setCurrentText("SSTV")
        took = time.time() - t0
        assert took < 0.2, "BABEL decoder switch blocked the GUI thread %.2f s" % took
        assert _until(lambda: not old.isRunning(), 8000)
        assert lease.released[0][1] == [], "released before the stubborn stage died"
        assert _until(lambda: isinstance(b._worker, babel.SstvWorker), 2000)
    finally:
        b.stop()
        _pump(200)
    assert decoders() == []


# ============================================================================ N-b
def test_nb_decoder_fault_shows_its_stderr_through_the_real_runner(monkeypatch, live, tmp_path):
    """RA-CL5b N-b: _stop_proc closed the stderr file before the runner read its tail, so the
    FAULT lost its reason. Real _run_ais, a decoder that writes to stderr and exits at once."""
    from palisade_qt import babel, radio_arbiter as ra
    lease = _GateLease()
    lease.gate.set()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    import ais
    monkeypatch.setattr(ais, "pipeline", lambda gain=0: [
        ["sh", "-c", "echo 'usb_claim_interface error -6' >&2; exit 1"]])
    w = babel.DecoderWorker(demo=False, mode="AIS")
    faults = []
    w.fault.connect(faults.append)
    w.set_running(True)
    w.start()
    try:
        assert _until(lambda: any(f for f in faults), 5000), "no FAULT"
        assert "usb_claim_interface error -6" in [f for f in faults if f][0], faults
    finally:
        w.stop()
        assert w.wait(4000)


# ============================================================================ N-e
def test_ne_a_decode_that_outlives_its_recorder_cannot_stall_the_next_run():
    """RA-CL5b N-e: a decode finishing after the recorder stopped wrote its old clock back, and
    the next RUN waited ~2400 s before decoding. A job for a recorder that is no longer live is
    dropped."""
    import sstv
    from palisade_qt import babel
    fs = sstv.RATE
    w = babel.SstvWorker(demo=False)
    go = threading.Event()

    class Rec:
        n = 2400 * fs

        def total_samples(self):
            return self.n

        def samples_since(self, a):
            return b"\0\0" * (12 * fs), self.n - 12 * fs

        def stop(self):
            pass

    def slow_decode(x, f):
        go.wait(5)
        raise ValueError("no SSTV header found")
    w._decode = slow_decode
    old = Rec()
    w._rec = old
    w._decoding = True
    t = threading.Thread(target=w._decode_job, args=(old, fs))
    t.start()
    w._stop_rec()                           # RUN off while the decode is running
    w._rec = Rec()                          # the next RUN's recorder
    go.set()
    t.join(5)
    assert w._decoded_upto == 0 and w._scan_from == 0, (w._decoded_upto, w._scan_from)
    assert not w._decoding


# ============================================================================ N-f
def test_nf_tk_recorder_leaves_one_contiguous_last_window(tmp_path, monkeypatch):
    """RA-CL5b N-f: rotation split a frame across .prev.wav and .wav, so the Tk app (which
    decodes the file at STOP) lost frames that decoded at ed4694a. At the end of a recording the
    file is the last window, contiguous, and the .prev file is gone."""
    import array
    import sstv

    class Stdout:
        def __init__(self, total):
            self.i, self.total = 0, total

        def read(self, n):
            n = min(n // 2, self.total - self.i)
            if n <= 0:
                return b""
            a = array.array("h", [(self.i + k) % 30000 for k in range(n)])
            self.i += n
            return a.tobytes()

    class Proc:
        def __init__(self):
            self.stdout = Stdout(sstv.RATE * 10)           # 10 s, a counter per sample
    monkeypatch.setattr(sstv.S, "stop_group", lambda p, grace=1.0: None, raising=False)
    monkeypatch.setattr(sstv.Recorder, "FLUSH_S", 0)
    path = str(tmp_path / "pass.wav")
    rec = sstv.Recorder(path, 145.8, 40, monitor=False, window_s=3, proc=Proc())
    rec.thread.join(10)
    assert rec.rotations >= 2
    assert not os.path.exists(path[:-4] + ".prev.wav")
    with wave.open(path) as wf:
        n = wf.getnframes()
        a = array.array("h")
        a.frombytes(wf.readframes(n))
    assert 2.5 * sstv.RATE <= n <= 3 * sstv.RATE
    total = sstv.RATE * 10
    assert list(a) == [(k % 30000) for k in range(total - n, total)], "not the contiguous tail"


def test_nf_qt_worker_does_not_pay_for_the_tk_rewrite():
    import inspect
    from palisade_qt import babel
    assert "keep_last_window=False" in inspect.getsource(babel.SstvWorker)


# ============================================================================ N-d
_WEDGED = """#!/bin/sh
exec "%(py)s" -c '
import time
while True:
    time.sleep(1)
' FAKE_rtl_fm "$@"
"""
_FLAPPING = """#!/bin/sh
exec "%(py)s" -c '
import sys, time
sys.stdout.buffer.write(bytes(8820)); sys.stdout.buffer.flush()
time.sleep(0.6)
' FAKE_rtl_fm "$@"
"""


def _replace_fake(binz, name, body):
    p = binz / name
    p.write_text(body % {"py": sys.executable})


def test_nd_a_wedged_rtl_fm_never_reads_live(monkeypatch, live):
    """RA-CL5b N-d (owner: fix now): a wedged rtl_fm (alive, no samples) read LIVE · NO ALERTS
    forever. LIVE now needs audio flowing; a receiver with no audio reads NOT MONITORING and is
    restarted after AUDIO_RESPAWN_S."""
    from palisade_qt import prowl, radio_arbiter as ra
    _replace_fake(live, "rtl_fm", _WEDGED)
    monkeypatch.setattr(prowl.NwrWorker, "AUDIO_RESPAWN_S", 1.5, raising=False)
    p = prowl.ProwlApp(demo=False, mode="dark")
    p.set_active(True)
    p.switch_subtab("NWR")
    p.start()
    seen, pids = set(), set()
    try:
        t0 = time.time()
        while time.time() - t0 < 5.0:
            _pump(100)
            seen.add(p.nwr_state.text().split(" ")[0])
            pids.update(decoders(("rtl_fm",)))
        assert ra.arbiter.held_by("PROWL-NWR"), "the radio is held (the process is alive)"
        assert "LIVE" not in seen, seen
        assert "NOT" in seen
        assert "no alerts" not in p.nwr_detail.hero.text() + " ".join(
            lb.text() for lb in p.nwr_detail.findChildren(type(p.nwr_state)))
        assert len(pids) >= 2, "a wedged receiver is restarted"
    finally:
        p.stop()
        _pump(200)
    assert decoders() == []


def test_nd_a_flapping_decoder_escalates_and_never_reads_live(monkeypatch, live):
    """A decoder that died every 2 s never reached the back-off (_down reset on each respawn)
    and read LIVE ~80 % of the time. Exits are now counted over a window -> FAULT."""
    from palisade_qt import prowl
    _replace_fake(live, "rtl_fm", _FLAPPING)
    w = prowl.NwrWorker(demo=False)
    faults, live_st = [], []
    w.fault.connect(faults.append)
    w.status.connect(lambda s: live_st.append(s.get("live")))
    w.set_active(True)
    w.start()
    try:
        assert _until(lambda: any(f and "keeps failing" in f for f in faults), 8000), faults
    finally:
        w.stop()
        assert w.wait(4000)
    assert decoders() == []


def test_nd_flowing_audio_reads_live(live):
    """Control: the normal fake rtl_fm (audio flowing) still reads LIVE."""
    from palisade_qt import prowl
    p = prowl.ProwlApp(demo=False, mode="dark")
    p.set_active(True)
    p.switch_subtab("NWR")
    p.start()
    try:
        assert _until(lambda: p.nwr_state.text().startswith("LIVE"), 5000), p.nwr_state.text()
    finally:
        p.stop()
        _pump(200)


# ============================================================================ low items
def test_ng_atlas_busy_line_before_the_first_status():
    """N-g: _update_busy raised TypeError (tuple & set) until the first worker status."""
    from palisade_qt import atlas
    app = atlas.AtlasApp(demo=False, mode="dark")
    app._update_busy()                         # must not raise


def test_n11_radios_history_logs_each_transition_and_marks_a_forced_free(monkeypatch):
    """N11: a fast acquire logged HELD, HELD; a forced free looked like a normal release."""
    from palisade_qt import panels, radio_arbiter as ra
    monkeypatch.setattr(ra, "REVOKE_TIMEOUT_S", 0.2)
    panel = panels.RadiosPanel(mode="dark")
    try:
        ra.arbiter.request("ATLAS-AIS")
        assert ra.wait_held("ATLAS-AIS", 3.0)
        _pump(50)
        ra.arbiter.revoke()                    # nobody acknowledges
        assert _until(lambda: ra.arbiter.owner() is None, 2000)
        _pump(50)
        events = [r["event"] for r in panel.hist_feed.model.rows]
        assert events[1:3] == ["HELD", "ACQUIRING"], events      # newest first
        assert events[0].startswith("RELEASE") and "FORCED FREE" in events[0], events
    finally:
        panel.stop()


def test_nh_panic_banner_counts_what_the_pages_stopped(monkeypatch):
    """N-h: the banner said "no child processes were running" / "radio was free" when the
    page's own kill or release won the race."""
    from palisade_qt import shell, radio_arbiter as ra, procs
    hub = shell.PalisadeHub(demo=False)
    try:
        ra.arbiter.request("BABEL")
        assert ra.wait_held("BABEL", 3.0)
        calls = {"n": 0}

        def kids():
            calls["n"] += 1
            return [999999] if calls["n"] == 1 else []      # gone by the second look
        hub._list_children = kids
        monkeypatch.setattr(procs, "alive", lambda pid, run=None: False)
        page = hub.page_app("BABEL")
        monkeypatch.setattr(page, "on_panic", lambda: (ra.arbiter.release("BABEL"), [])[1])
        texts = []
        monkeypatch.setattr(hub, "_show_banner", texts.append)
        hub.panic()
        assert texts and "stopped by their pages" in texts[0], texts
        assert "radio released (was BABEL)" in texts[0], texts
    finally:
        hub.close()
        _pump(100)
