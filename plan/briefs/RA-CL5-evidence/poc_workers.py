"""A2 / Workers: close a page mid-sleep, mid-retry (backoff), and with a worker stuck in an
uninterruptible call; then quit. Each scenario runs in its own interpreter so the exit code and
stderr ("QThread: Destroyed while thread is still running" / SIGABRT 134) are real."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = r'''
import os, sys, time
sys.path.insert(0, %(here)r)
import _harness as H
from PySide6 import QtCore, QtWidgets
from palisade_qt.app import PalisadeApp, parked
from palisade_qt.worker import Worker
kind = %(kind)r

class W(Worker):
    def step(self):
        if kind == "sleep":
            return                       # normal: waits the interval on the condition
        if kind == "retry":
            raise RuntimeError("device gone")   # backs off (interval doubles)
        if kind == "stuck":
            time.sleep(8)                # an uninterruptible blocking call (iw scan / read)

class P(PalisadeApp):
    TITLE = "POC"
    def make_worker(self):
        return W(demo=False, interval_ms=20000 if kind == "sleep" else 200)

p = P(demo=False)
p.set_active(True)
p.resize(1280, 720)
p.show()
H.pump(2.5 if kind == "retry" else 0.6)
t0 = time.monotonic()
p.close()
H.log("close() took %%.2fs ; parked=%%d ; running=%%s" %% (time.monotonic() - t0, len(parked()), [w.isRunning() for w in parked()]))
QtCore.QTimer.singleShot(100, H.APP.quit)
H.APP.exec()
H.log("event loop left; exiting")
'''


def run(kind):
    code = SCEN % {"here": HERE, "kind": kind}
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                       cwd=HERE)
    err = [ln for ln in r.stderr.splitlines() if "QStandardPaths" not in ln and "propagateSize" not in ln]
    print("== %s: rc=%s wall=%.1fs" % (kind, r.returncode, time.monotonic() - t0))
    print("   stdout:", " | ".join(r.stdout.strip().splitlines()))
    print("   stderr:", " | ".join(err)[:600] or "-")


for k in ("sleep", "retry", "stuck"):
    run(k)
