"""A4 attack: kit.procs.Pipeline.terminate() against hostile stages (real processes).

a  a stage whose CHILD ignores SIGTERM (the stage itself exits on SIGTERM)
b  a stage that ignores SIGTERM itself
c  a stage that forks a grandchild into its group and then exits on its own
d  a grandchild that calls setsid() (leaves the group)
e  Pipeline() where stage 2's binary is missing (stage 1 already started)
"""
import os
import signal
import subprocess
import sys
import time

import _harness as H
from palisade_qt.kit.procs import Pipeline

PY = sys.executable
CHILD_IGNORES_TERM = ("import os,signal,time\n"
                      "pid=os.fork()\n"
                      "if pid==0:\n"
                      "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                      "    os.execlp('sleep','sleep','301')\n"
                      "time.sleep(300)\n")
IGNORES_TERM = "import signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(302)\n"
FORK_AND_EXIT = ("import os,time\n"
                 "if os.fork()==0:\n"
                 "    os.execlp('sleep','sleep','303')\n"
                 "time.sleep(0.2)\n")
SETSID_CHILD = ("import os,time\n"
                "if os.fork()==0:\n"
                "    os.setsid(); os.execlp('sleep','sleep','304')\n"
                "time.sleep(300)\n")


def survivors(tag):
    out = subprocess.run(["pgrep", "-af", "sleep 30%s" % tag], capture_output=True, text=True).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def case(label, stages, tag, settle=0.5):
    p = Pipeline(stages)
    time.sleep(settle)
    t0 = time.monotonic()
    ok = p.terminate()
    dt = time.monotonic() - t0
    time.sleep(0.3)
    left = survivors(tag)
    H.log("%s: terminate() -> %s in %.2fs ; survivors: %s" % (label, ok, dt, left or "none"))
    for ln in left:
        try:
            os.kill(int(ln.split()[0]), signal.SIGKILL)
        except Exception:
            pass
    return left


case("a child-ignores-SIGTERM", [[PY, "-c", CHILD_IGNORES_TERM]], "1")
case("b stage-ignores-SIGTERM", [[PY, "-c", IGNORES_TERM]], "2")
case("c fork-then-exit", [[PY, "-c", FORK_AND_EXIT], ["cat"]], "3", settle=1.0)
case("d grandchild-setsid", [[PY, "-c", SETSID_CHILD]], "4")
try:
    Pipeline([["sleep", "305"], ["no-such-decoder-binary"]])
except Exception as e:
    time.sleep(0.2)
    H.log("e missing stage-2 binary: %s: %s ; survivors: %s" % (type(e).__name__, e,
                                                                 survivors("5") or "none"))
    for ln in survivors("5"):
        os.kill(int(ln.split()[0]), signal.SIGKILL)
