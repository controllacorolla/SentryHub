"""Radio handoffs off the UI thread (2026-11-09): stopping readsb can take ~45 s and used
to freeze RF Explorer, Sensors, Signals and Scout for that long."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import suite as S  # noqa: E402


class FakeRoot:
    """Stands in for Tk: runs after() callbacks on a pump we drive from the test."""

    def __init__(self):
        self.jobs, self.thread = [], threading.current_thread()

    def after(self, ms, fn):
        assert threading.current_thread() is self.thread, "Tk touched from a worker thread"
        self.jobs.append((time.time() + ms / 1000.0, fn))

    def pump(self, until):
        end = time.time() + until
        while time.time() < end:
            now = time.time()
            due = [j for j in self.jobs if j[0] <= now]
            self.jobs = [j for j in self.jobs if j[0] > now]
            for _, fn in due:
                fn()
            time.sleep(0.01)


class SlowLease:
    def __init__(self, delay=0.5, fail=False):
        self.delay, self.fail, self.log = delay, fail, []

    def acquire(self):
        self.log.append("acquire-start")
        time.sleep(self.delay)
        self.log.append("acquire-end")
        if self.fail:
            raise RuntimeError("readsb wedged")

    def release(self):
        self.log.append("release")


def test_acquire_does_not_block_the_ui_thread():
    root, lease, got = FakeRoot(), SlowLease(0.6), []
    t0 = time.time()
    S.acquire_bg(root, lease, lambda ok, v: got.append(ok))
    assert time.time() - t0 < 0.1                  # returned immediately
    root.pump(1.5)
    assert got == [True]


def test_failed_acquire_releases_and_reports():
    root, lease, got = FakeRoot(), SlowLease(0.1, fail=True), []
    S.acquire_bg(root, lease, lambda ok, v: got.append((ok, str(v))))
    root.pump(1.0)
    assert got == [(False, "readsb wedged")]
    assert lease.log[-1] == "release"              # readsb isn't left paused


def test_stop_during_start_releases_after_acquire_lands():
    root, lease = FakeRoot(), SlowLease(0.5)
    S.acquire_bg(root, lease, lambda ok, v: None)
    time.sleep(0.05)
    S.release_bg(root, lease)                       # user hit Stop mid-acquire
    root.pump(1.5)
    assert lease.log == ["acquire-start", "acquire-end", "release"]


def test_release_now_waits_for_inflight_handoff():
    root, lease = FakeRoot(), SlowLease(0.4)
    S.acquire_bg(root, lease, lambda ok, v: None)
    time.sleep(0.05)
    S.release_now(lease)                            # quitting mid-acquire
    assert lease.log == ["acquire-start", "acquire-end", "release"]
