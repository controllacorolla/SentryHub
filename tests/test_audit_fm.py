"""Regression tests for bugs fixed in fm.py during the code audit."""
import time

import pytest

import fm


def test_pipe_stops_producer_when_sink_cannot_start():
    started = []
    real = fm.subprocess.Popen

    def popen(cmd, **k):
        p = real(cmd, **k)
        started.append(p)
        return p
    fm.subprocess.Popen, saved = popen, fm.subprocess.Popen
    try:
        with pytest.raises(OSError):
            fm.Pipe(["sleep", "30"], ["/nonexistent/sink-binary"])
    finally:
        fm.subprocess.Popen = saved
    assert started and all(p.poll() is not None for p in started), \
        "rtl_fm stand-in left running after the sink failed to exec"


def test_pipe_stop_kills_survivor_after_sink_died():
    p = fm.Pipe(["sleep", "30"], ["true"])        # sink exits at once, producer lives
    deadline = time.time() + 3
    while p.sink.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    assert p.poll() is not None                    # the pipe looks "dead"...
    p.stop()
    assert p.rtl.poll() is not None, "producer (rtl_fm) left holding the dongle"
