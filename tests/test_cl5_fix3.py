"""CL5-fix3 — one regression test per RA-CL5c finding (plan/briefs/RA-CL5c-report.md §7).

Same rules as test_cl5_fix.py / test_cl5_fix2.py (helpers and fixtures reused): real processes
(fake rtl_fm / multimon-ng on PATH), real worker threads, only the arbiter's lease seam patched.
"""
import os
import sys
import threading
import time

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
for d in (SUITE_DIR, TESTS_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import test_cl5_fix as _H  # noqa: E402
import test_cl5_fix2 as _H2  # noqa: E402

_pump, _until, decoders = _H._pump, _H._until, _H.decoders
_SlowLease = _H2._SlowLease
_reset = _H._reset           # autouse: fresh arbiter + bus per test
live = _H.live               # fake radio binaries on PATH, decoder seams open


# stages that ignore SIGTERM (RA-CL5b's trap fakes): their kill takes the full SIGTERM grace, so
# the retiring mode still HOLDS the radio when the operator presses FREE THE RADIO
_TRAP_RTL = """#!/bin/sh
trap '' TERM
while :; do echo '!AIVDM,1,1,,A,15M67FC000G?ufbE`FepT@3n00Sa,0*5C'; sleep 0.2; done
# FAKE_rtl_fm
"""
_TRAP_MM = """#!/bin/sh
trap '' TERM
while :; do sleep 0.1; done
# FAKE_multimon-ng
"""


def _replace_fake(binz, name, body):
    (binz / name).write_text(body % {"py": sys.executable})


# ============================================================================ N-k
def test_nk_a_revoke_during_a_prowl_switch_sticks(monkeypatch, live):
    """RA-CL5c N-k: FREE THE RADIO while NWR -> FM was pending was acknowledged by the retiring
    NWR worker, then the new FM worker took the radio straight back. Now the revoke cancels the
    pending switch: the radio stays FREE until the operator asks again."""
    from palisade_qt import prowl, radio_arbiter as ra
    _replace_fake(live, "rtl_fm", _TRAP_RTL)       # the old mode still holds the radio while
    _replace_fake(live, "multimon-ng", _TRAP_MM)   # it is being reaped (SIGTERM grace)
    lease = _SlowLease(3.5)
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    p = prowl.ProwlApp(demo=False, mode="dark")
    p.set_active(True)
    p.switch_subtab("NWR")
    p.start()
    try:
        assert _until(lambda: ra.arbiter.held_by("PROWL-NWR") and decoders(("rtl_fm",)), 5000)
        old = p._worker
        p.switch_subtab("FM")
        _pump(100)
        assert ra.arbiter.owner() == "PROWL-NWR", "precondition: the old mode still holds it"
        ra.arbiter.revoke()                        # the operator frees the radio mid-switch
        assert _until(lambda: not old.isRunning(), 6000)
        _pump(2000)
        assert ra.arbiter.owner() is None, "the new sub-mode took the radio back after a revoke"
        assert p._worker is None and decoders() == []
        assert "Enter" in p.busy.text(), p.busy.text()
        assert p._resume_radio()                   # the operator asks again
        assert _until(lambda: ra.arbiter.held_by("PROWL-FM"), 4000)
    finally:
        p.stop()
        _pump(200)
    assert decoders() == []


def test_nk_a_revoke_during_a_babel_switch_sticks_and_unticks_run(monkeypatch, live):
    from palisade_qt import babel, radio_arbiter as ra
    _replace_fake(live, "rtl_fm", _TRAP_RTL)
    lease = _SlowLease(2.0)
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    import ais
    monkeypatch.setattr(ais, "pipeline", lambda gain=0: [["rtl_fm", "-f", "162.0M", "-"]])
    b = babel.BabelApp(demo=False, mode="dark")
    b.set_active(True)
    b.start()
    try:
        b.mode_combo.setCurrentText("AIS")
        b.run_btn.setChecked(True)
        assert _until(lambda: ra.arbiter.held_by("BABEL") and decoders(("rtl_fm",)), 5000)
        old = b._worker
        b.mode_combo.setCurrentText("SSTV")
        _pump(100)
        assert ra.arbiter.owner() == "BABEL", "precondition: the old decoder still holds it"
        ra.arbiter.revoke()
        assert _until(lambda: not old.isRunning(), 6000)
        _pump(1500)
        assert ra.arbiter.owner() is None, ra.arbiter.state()
        assert not b.run_btn.isChecked(), "RUN must untick when the radio is taken back"
        assert decoders() == []
    finally:
        b.stop()
        _pump(200)


# ============================================================================ N-l
_STDERR_ONLY = """#!/bin/sh
exec "%(py)s" -c '
import sys, time
while True:
    sys.stderr.write("usb_claim_interface error -6\\n" * 50); sys.stderr.flush()
    time.sleep(0.05)
' FAKE_rtl_fm "$@" 2>/dev/null
"""
_NEVER_READS = """#!/bin/sh
exec "%(py)s" -c '
import time
while True:
    time.sleep(1)
' FAKE_multimon-ng "$@"
"""


def _never_live(p, secs):
    seen = set()
    t0 = time.time()
    while time.time() - t0 < secs:
        _pump(100)
        seen.add(p.nwr_state.text().split(" ")[0])
    return seen


def _nwr_page():
    from palisade_qt import prowl
    p = prowl.ProwlApp(demo=False, mode="dark")
    p.set_active(True)
    p.switch_subtab("NWR")
    p.start()
    return p


def test_nl_rtl_fm_that_only_writes_stderr_never_reads_live(live):
    """RA-CL5c N-l: the heartbeat counted rtl_fm's writes, stderr included; an rtl_fm that only
    printed errors read LIVE 248 of 250 samples. LIVE now follows what the decoder reads."""
    _replace_fake(live, "rtl_fm", _STDERR_ONLY)
    p = _nwr_page()
    try:
        seen = _never_live(p, 5.0)
        assert "LIVE" not in seen and "NOT" in seen, seen
    finally:
        p.stop()
        _pump(200)


def test_nl_a_decoder_that_never_reads_never_reads_live(live):
    """N-l: multimon-ng stuck (not reading) read LIVE ~3 s per restart while rtl_fm filled the
    pipe."""
    _replace_fake(live, "multimon-ng", _NEVER_READS)
    p = _nwr_page()
    try:
        seen = _never_live(p, 5.0)
        assert "LIVE" not in seen and "NOT" in seen, seen
    finally:
        p.stop()
        _pump(200)


def test_nl_flapping_decoder_never_reports_live(live):
    """The flapping test now asserts on `live` (RA-CL5c weak-test note)."""
    from palisade_qt import prowl
    _replace_fake(live, "rtl_fm", _H2._FLAPPING)
    w = prowl.NwrWorker(demo=False)
    faults, lv = [], []
    w.fault.connect(faults.append)
    w.status.connect(lambda s: lv.append(s.get("live")))
    w.set_active(True)
    w.start()
    try:
        assert _until(lambda: any(f and "keeps failing" in f for f in faults), 8000), faults
    finally:
        w.stop()
        assert w.wait(4000)
    assert True not in lv, "a decoder that dies every 0.6 s reported LIVE"


# ============================================================================ N-m
def test_nm_a_frame_decoded_after_stop_is_still_shown_once():
    """RA-CL5c N-m: a complete frame whose decode finished just after STOP was thrown away
    (shown at 510359e). It is shown, with one decode event; only the clock write is dropped."""
    import numpy as np
    import sstv
    from palisade_qt import babel, eventbus
    fs = sstv.RATE
    w = babel.SstvWorker(demo=False)
    go = threading.Event()
    rows, events = [], []
    w.row.connect(rows.append)
    eventbus.bus.published.connect(events.append)

    class Rec:
        n = 300 * fs

        def total_samples(self):
            return self.n

        def samples_since(self, a):
            return b"\0\0" * (200 * fs), self.n - 200 * fs

        def stop(self):
            pass
    img = np.zeros((4, 4, 3), np.uint8)

    def decode(x, f):
        go.wait(5)
        return {"image": img, "mode": "PD120", "lines": 496, "slant_ppm": 0,
                "start": fs, "t0": fs, "period": 0.508 * fs}
    w._decode = decode
    old = Rec()
    w._rec = old
    t = threading.Thread(target=w._decode_job, args=(old, fs))
    t.start()
    w._stop_rec()                                  # STOP while the decode is running
    go.set()
    t.join(5)
    _pump(50)
    assert [r["lines"] for r in rows] == [496], rows
    decs = [e for e in events if e["type"] == "decode" and e["source"] == "BABEL-SSTV"]
    assert len(decs) == 1
    assert w._decoded_upto == 0 and w._scan_from == 0, "the clock must still not leak"


# ============================================================================ N-n
def test_nn_a_retired_workers_late_status_is_ignored(monkeypatch, live):
    """RA-CL5c N-n: a status the retiring worker had already queued could overwrite "SDR —
    switching modes" with its old green chip."""
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _SlowLease(2.0)
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    p = _nwr_page()
    try:
        assert _until(lambda: ra.arbiter.held_by("PROWL-NWR"), 5000)
        old = p._worker
        # queued from another thread BEFORE the switch cuts the connection (the N-n race)
        t = threading.Thread(target=lambda: old.status.emit(
            {"src": "NWR", "live": True, "sdr": {"text": "NWR WX2 162.400M", "ok": True}}))
        t.start()
        t.join()
        p.switch_subtab("FM")
        _pump(100)
        assert "NWR WX2" not in " ".join(p.page_status().values()), p.page_status()
        assert isinstance(p, prowl.ProwlApp)
    finally:
        p.stop()
        _pump(200)


# ============================================================================ N-q
def test_nq_nwr_emits_alerts_parsed_before_a_stop():
    """RA-CL5c N-q: SAME headers parsed in the last poll interval before a stop were dropped."""
    from palisade_qt import prowl
    import nwr
    w = prowl.NwrWorker(demo=False)
    rows = []
    w.row.connect(rows.append)
    line = "EAS: ZCZC-WXR-TOR-029095+0030-1051700-KEAX/NWS-"
    a = nwr.parse_same(line)
    assert a, "fixture SAME header must parse"
    w._handle_line(line)
    w._kill()                                      # the stop path, before any _drain()
    _pump(50)
    assert rows and rows[0]["code"] == "TOR", rows
