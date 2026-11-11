"""Regression tests for bugs fixed in sky_app.py during the code audit."""
import os
import queue
import threading
import time

import sky_app as sky


# ---------------------------------------------------------------- emergency field
def test_alert_kind_maps_readsb_emergency_enum():
    # readsb emits these in 'emergency' even when the squawk is ordinary (e.g. 1200)
    assert sky.alert_kind("1200", "general") == "emergency"
    assert sky.alert_kind("1200", "nordo") == "radio failure"
    assert sky.alert_kind("1200", "unlawful") == "hijack"
    assert sky.alert_kind("", "downed") == "emergency"
    assert sky.alert_kind("7500", "none") == "hijack"


# ---------------------------------------------------------------- controller
class FakeLease:
    who = "Sky airband"

    def __init__(self):
        self.released = 0

    def acquire(self, keep=()):
        pass

    def release(self):
        self.released += 1

    paused = []


def _ctl(monkeypatch, tmp_path):
    monkeypatch.setattr(sky, "STATS_PATH", str(tmp_path / "stats"))
    monkeypatch.setattr(sky, "CONF_PATH", str(tmp_path / "conf"))
    monkeypatch.setattr(sky, "file_log", lambda m: None)
    c = sky.Controller.__new__(sky.Controller)   # no background _loop thread
    c.s = sky.deepcopy(sky.DEFAULT_SETTINGS)
    c.events, c.cmds = queue.Queue(), queue.Queue()
    c.proc, c.state, c.device = None, "idle", None
    c.binary, c.record, c.record_unsupported = "/bin/false", False, False
    c.my_pids, c.lease = set(), FakeLease()
    monkeypatch.setattr(c, "choose_device", lambda: ("rtlsdr", "test"))
    monkeypatch.setattr(c, "_free", lambda d: None)
    monkeypatch.setattr(sky.time, "sleep", lambda t: None)
    return c


def test_start_releases_lease_when_popen_fails(monkeypatch, tmp_path):
    c = _ctl(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise PermissionError("exec denied")
    monkeypatch.setattr(sky.subprocess, "Popen", boom)
    c._start()
    assert c.state == "error"
    assert c.lease.released == 1, "readsb left paused after Popen failed"


def test_start_releases_lease_when_retry_free_raises(monkeypatch, tmp_path):
    c = _ctl(monkeypatch, tmp_path)
    calls = {"n": 0}

    def free(d):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("readsb is still holding the SDR")
    monkeypatch.setattr(c, "_free", free)
    c.binary = "/bin/sh"
    monkeypatch.setattr(sky, "write_rtl_conf", lambda *a, **k: None)
    orig = sky.subprocess.Popen
    monkeypatch.setattr(sky.subprocess, "Popen",
                        lambda cmd, **k: orig(["sh", "-c", "echo usb_claim_interface error -6"], **k))
    c._start()
    assert c.state == "error" and c.lease.released == 1


def test_start_never_stuck_in_starting_after_last_record_retry(monkeypatch, tmp_path):
    c = _ctl(monkeypatch, tmp_path)
    monkeypatch.setattr(sky, "write_rtl_conf", lambda *a, **k: None)
    seq = iter(["usb_claim_interface busy", "usb_claim_interface busy",
                "unknown output type"])
    orig = sky.subprocess.Popen

    def popen(cmd, **k):
        c.record = True     # record fallback is only tried while recording
        return orig(["sh", "-c", "echo %s" % next(seq)], **k)
    monkeypatch.setattr(sky.subprocess, "Popen", popen)
    c._start()
    assert c.state == "error", "left in state %r with readsb paused" % c.state
    assert c.lease.released >= 1


def test_record_retry_flag_reset_each_start(monkeypatch, tmp_path):
    c = _ctl(monkeypatch, tmp_path)
    c.record_retry_pending = True          # stale from an earlier failed start
    monkeypatch.setattr(sky, "write_rtl_conf", lambda *a, **k: None)
    orig = sky.subprocess.Popen
    monkeypatch.setattr(sky.subprocess, "Popen",
                        lambda cmd, **k: orig(["sleep", "30"], **k))
    monkeypatch.setattr(sky.time, "time", iter(range(0, 10**6, 10)).__next__)
    monkeypatch.setattr(sky.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: None})())
    c._start()
    try:
        assert c.state == "running"
        assert c.record_unsupported is False
    finally:
        c.proc.kill()
        c.proc.wait()


def test_watch_restores_before_reporting_error(monkeypatch, tmp_path):
    c = _ctl(monkeypatch, tmp_path)
    order = []
    c.lease.release = lambda: order.append("release")
    real_set = c.set_state
    c.set_state = lambda st, d="": (order.append(st), real_set(st, d))
    monkeypatch.setitem(__import__("sys").modules, "suite",
                        type("M", (), {"_lease_state": staticmethod(lambda: {})}))
    p = sky.subprocess.Popen(["true"])
    c.proc, c.state, c.device = p, "running", "rtlsdr"
    c._watch(p)
    assert order == ["release", "error"]


# ---------------------------------------------------------------- feed
def _feed(monkeypatch, files):
    f = sky.AdsbFeed.__new__(sky.AdsbFeed)
    f.sources, f.aircraft, f.receiver, f.status = ["x"], [], None, "none"
    f.source, f.updated, f.trails, f.history = None, 0.0, {}, []
    f._last_frame, f._rcv_retry, f.lock = 0.0, 0.0, threading.Lock()

    def get(base, name):
        v = files[name]
        if isinstance(v, Exception):
            raise v
        return v() if callable(v) else v
    f._get = get
    return f


def test_feed_stale_now_does_not_grow_history(monkeypatch):
    frozen = {"now": 1000.0, "aircraft": [{"hex": "abc", "lat": 39.6, "lon": -104.8,
                                           "seen": 0, "seen_pos": 0}]}
    f = _feed(monkeypatch, {"aircraft.json": frozen, "receiver.json": {"lat": 1, "lon": 2}})
    t = [5000.0]
    monkeypatch.setattr(sky.time, "time", lambda: t[0])
    for _ in range(50):
        t[0] += 3
        f._tick(["x"])
    assert len(f.history) == 1


def test_feed_retries_receiver_after_transient_failure(monkeypatch):
    files = {"aircraft.json": lambda: {"now": time.time(), "aircraft": []},
             "receiver.json": OSError("temporarily gone")}
    f = _feed(monkeypatch, files)
    f._tick(["x"])
    assert f.receiver is False
    files["receiver.json"] = {"lat": 39.6, "lon": -104.9}
    f._rcv_retry = 0          # pretend a minute has passed
    f._tick(["x"])
    assert f.receiver == (39.6, -104.9)


# ---------------------------------------------------------------- part B
def test_adsb_device_does_not_grow_sys_path():
    import sys
    sky.adsb_device()
    n = len(sys.path)
    for _ in range(50):
        sky.adsb_device()
    assert len(sys.path) == n


def test_bingo_card_always_25_squares():
    import random
    for phrases in ([], ["say again"], ["a", "b", "c", "d", "e", "f", "g", "h"],
                    [str(i) for i in range(30)]):
        card = sky.bingo_card(phrases, random.Random(1))
        assert len(card) == 25


def test_replay_frames_keep_category(monkeypatch):
    data = {"now": time.time(), "aircraft": [{"hex": "abc", "lat": 39.6, "lon": -104.8,
                                              "seen": 0, "seen_pos": 0, "category": "A7"}]}
    f = _feed(monkeypatch, {"aircraft.json": data, "receiver.json": {"lat": 1, "lon": 2}})
    f._tick(["x"])
    assert f.history[-1][1][0].get("category") == "A7"


def test_cli_stop_leaves_another_apps_lease_alone(monkeypatch, capsys):
    import suite as S
    released = []
    monkeypatch.setattr(sky, "pids_named", lambda n: [])
    monkeypatch.setattr(sky, "load_settings", lambda: sky.deepcopy(sky.DEFAULT_SETTINGS))
    monkeypatch.setattr(S, "lease_holder", lambda: ("FM radio", os.getpid()))
    monkeypatch.setattr(S.RtlLease, "release", lambda self: released.append(1))
    monkeypatch.setattr(S.RtlLease, "_write", lambda self, **k: released.append(k))
    sky.cli_stop()
    assert released == [], "sky --stop restarted readsb under FM radio"
    assert "FM radio" in capsys.readouterr().out
