"""NFM squelch (2026-11-09): an FM discriminator turns an EMPTY channel into full-scale
noise, so the old RMS gate (rtl_fm -l 0) stopped on empty NFM channels - 7 of the 9
banks. NFM now uses rtl_fm's own power squelch; these drive listen_channel() with a fake
rtl_fm that behaves like the real one."""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scanner  # noqa: E402

FAKE = r'''
import sys, os, time, math, random, struct
mode, cmd = sys.argv[1], sys.argv[2]
out = sys.stdout.buffer
def write(samples):
    out.write(struct.pack("<%dh" % len(samples), *samples)); out.flush()
end = time.time() + 10
if mode == "exit":
    sys.exit(0)
if mode == "empty_fm":
    # real rtl_fm: squelch off -> discriminator noise; squelch on -> nothing at all
    while time.time() < end:
        if " -l 0 " in cmd:
            write([random.randint(-30000, 30000) for _ in range(1024)])
        time.sleep(0.04)
elif mode == "voice_then_quiet":
    t0 = time.time()
    while time.time() < end:
        if time.time() - t0 < 0.6:
            write([int(9000 * math.sin(i / 3.0)) for i in range(1024)])
        time.sleep(0.04)
elif mode == "am_quiet":
    while time.time() < end:
        write([random.randint(-300, 300) for _ in range(1024)])   # AM: empty is quiet
        time.sleep(0.04)
'''


def fake_popen(behavior, seen):
    def popen(cmd, **k):
        seen.append(cmd)
        return subprocess.Popen([sys.executable, "-c", FAKE, behavior, " %s " % " ".join(cmd)],
                                **k)
    return popen


def settings(**kw):
    s = dict(scanner.DEFAULTS, dwell=0.3, hold=0.3)
    s.update(kw)
    return s


def run(behavior, mode, s, scan=None):
    seen, posts = [], []
    scan = scan if scan is not None else {"on": True, "pause": False, "rms": 0.0}
    t0 = time.time()
    res = scanner.listen_channel(146.52, mode, s, scan, posts.append,
                                 popen=fake_popen(behavior, seen), sink_fn=lambda: None)
    return res, posts, seen, time.time() - t0


def test_empty_nfm_channel_is_not_held():
    res, posts, seen, dt = run("empty_fm", "nfm", settings())
    assert res is False, "scanner stopped on an empty NFM channel"
    assert not any(p[0] == "hit" for p in posts)
    assert dt < scanner.TUNE_SETTLE + 0.3 + 1.0      # dwelt, then moved on


def test_nfm_hands_squelch_to_rtl_fm():
    _, _, seen, _ = run("empty_fm", "nfm", settings(nfm_squelch=50))
    cmd = seen[0]
    assert cmd[cmd.index("-l") + 1] == "50"


def test_old_gate_would_have_held_the_empty_channel():
    # the bug, pinned: with rtl_fm's squelch off, empty-channel noise clears the RMS gate
    res, posts, _, _ = run("empty_fm", "nfm", settings(nfm_squelch=0))
    assert res is True and any(p[0] == "hit" for p in posts)


def test_active_nfm_channel_holds_then_releases():
    res, posts, _, dt = run("voice_then_quiet", "nfm", settings())
    assert res is True and ("hit", 146.52) in posts
    assert dt < 0.6 + 0.3 + 1.5                      # let go after the hold time


def test_am_keeps_rms_gate_and_open_rtl_squelch():
    res, posts, seen, _ = run("am_quiet", "am", settings())
    assert res is False
    cmd = seen[0]
    assert cmd[cmd.index("-l") + 1] == "0"


def test_retune_returns_for_same_channel():
    scan = {"on": True, "pause": False, "rms": 0.0, "retune": True}
    res, _, _, _ = run("empty_fm", "nfm", settings(), scan)
    assert res == "retune" and scan["retune"] is False


def test_immediate_exit_backs_off_with_status():
    res, posts, _, dt = run("exit", "nfm", settings())
    assert res is False
    assert any(p[0] == "status" and "SDR free" in p[1] for p in posts)
    assert dt >= 1.0                                  # backed off instead of tight-looping


def test_rf_explorer_manual_listen_stays_unsquelched():
    # RF Explorer reuses rtl_cmd for click-to-listen: no squelch argument -> -l 0
    cmd = scanner.rtl_cmd(146.52, "nfm", 32)
    assert cmd[cmd.index("-l") + 1] == "0"


def test_gate_open_by_mode():
    s = settings(squelch=8000, nfm_squelch=50)
    assert scanner.gate_open(1500, "nfm", s) is True     # NFM ignores the AM RMS threshold
    assert scanner.gate_open(0, "nfm", s) is False
    assert scanner.gate_open(1500, "am", s) is False
    assert scanner.gate_open(9000, "am", s) is True
