"""RA-CL5c PoC harness (copy of RA-CL5b _harness.py; fakebin from RA-CL5-evidence): real processes and real threads; only radio_arbiter._make_lease is patched.

Run from the repo root:  QT_QPA_PLATFORM=minimal python3 plan/briefs/RA-CL5-evidence/<poc>.py
"""
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "RA-CL5-evidence")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, REPO)
os.environ["PATH"] = os.path.join(HERE, "fakebin") + os.pathsep + os.environ["PATH"]
os.environ["HOME"] = tempfile.mkdtemp(prefix="racl5home")
os.environ.pop("PALISADE_OFFLINE", None)
if os.environ.get("QT_QPA_PLATFORM") in (None, "", "offscreen"):
    os.environ["QT_QPA_PLATFORM"] = "minimal"          # live paths are skipped under 'offscreen'

from PySide6 import QtCore, QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from palisade_qt import radio_arbiter  # noqa: E402

T0 = time.monotonic()
LOG = []


def t():
    return round(time.monotonic() - T0, 2)


def log(*a):
    LOG.append((t(),) + a)
    print("%6.2f" % t(), *a, flush=True)


class FakeLease:
    """Stands in for suite.RtlLease: acquire takes ACQ_S (readsb stop); release is recorded."""
    def __init__(self, name):
        self.name = name

    def release(self):
        log("LEASE.release", self.name, "children-at-release:", children())


def slow_make_lease(acq_s):
    def _mk(name):
        log("LEASE.acquire start", name, "(readsb would still hold the dongle)")
        time.sleep(acq_s)
        log("LEASE.acquire done", name, "children-at-HELD:", children())
        return FakeLease(name)
    return _mk


def children(pid=None):
    """Every live (non-zombie) descendant of this process: pid, comm, pgid, sid."""
    out = subprocess.run(["ps", "-eo", "pid=,ppid=,pgid=,sid=,stat=,comm="], capture_output=True,
                         text=True).stdout
    rows = [ln.split(None, 5) for ln in out.splitlines() if ln.strip()]
    kids, todo, me = [], [pid or os.getpid()], set()
    by_ppid = {}
    for r in rows:
        by_ppid.setdefault(int(r[1]), []).append(r)
    while todo:
        p = todo.pop()
        for r in by_ppid.get(p, []):
            c = int(r[0])
            if c in me:
                continue
            me.add(c)
            todo.append(c)
            if r[5] in ("ps",):
                continue
            kids.append("%s:%s%s" % (r[0], r[5], "(Z)" if r[4].startswith("Z") else ""))
    return kids


def procs_named(*names):
    out = subprocess.run(["ps", "-eo", "pid=,stat=,comm=,args="], capture_output=True,
                         text=True).stdout
    hits = []
    for ln in out.splitlines():
        parts = ln.split(None, 3)
        if len(parts) >= 3 and any(n in ln for n in names) and "ps -eo" not in ln \
                and "pytest" not in ln and "_harness" not in ln and "poc_" not in ln:
            hits.append("%s:%s:%s" % (parts[0], parts[1], parts[2]))
    return hits


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents(QtCore.QEventLoop.AllEvents, 20)
        time.sleep(0.01)


def record_status(worker, name):
    def on(st):
        state = radio_arbiter.arbiter.state()
        log("STATUS", name, st.get("sdr", {}).get("text") if isinstance(st, dict) else st,
            "| arbiter:", state)
    worker.status.connect(on, QtCore.Qt.DirectConnection)
    if hasattr(worker, "fault"):
        worker.fault.connect(lambda m: log("FAULT", name, m), QtCore.Qt.DirectConnection)
