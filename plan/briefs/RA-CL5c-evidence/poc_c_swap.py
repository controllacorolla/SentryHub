"""RA-CL5c: attack PalisadeApp.swap_worker (non-blocking sub-mode / decoder switch) through the real
hub. Real processes and threads; only radio_arbiter._make_lease is patched (a FakeLease whose
release() takes REL s = `systemctl start readsb`). TRAP=1 puts SIGTERM-ignoring rtl_fm / rtl_ais /
multimon-ng stages on PATH. A 5 ms QTimer heartbeat measures the longest GUI-thread stall.
Scenarios (argv[1]):
  same_name    SCAN -> FM -> SCAN within 0.1 s (same lease name), then audit ownership
  babel_same   BABEL text -> SSTV -> text within 0.1 s with RUN on
  gui_block    NWR -> FM, FM -> SCAN, BABEL AIS -> SSTV, with TRAP and REL 3.5
  close        close the hub 0.3 s into a slow switch
  never        lease release blocks 40 s (stuck readsb restart): what does PROWL/RADIOS say?
  revoke       NWR -> FM, then RADIOS revoke 0.2 s later: does FM take the radio afterwards?
  babel_revoke BABEL AIS (RUN) -> SSTV, revoke 0.2 s later: does SSTV take the radio?
  panic        NWR -> FM, PANIC 0.2 s later (old worker still releasing)
  babel_panic  BABEL AIS (RUN) -> SSTV, PANIC 0.2 s later"""
import os
import sys
import threading
import time
import _harness as H
from PySide6 import QtCore
from palisade_qt import radio_arbiter, shell, app as papp

which = sys.argv[1]
REL = float(os.environ.get("REL", "3.5"))
TRAP = os.environ.get("TRAP") == "1" or which in ("gui_block", "revoke", "panic", "babel_revoke",
                                                   "babel_panic", "close")
EV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "RA-CL5b-evidence")
if TRAP:
    os.environ["PATH"] = os.pathsep.join([os.path.join(EV, "fakebin_trap"),
                                          os.path.join(EV, "fakebin_trap_mm"), os.environ["PATH"]])


class SlowLease(H.FakeLease):
    def release(self):
        H.log("LEASE.release %s start (%.1f s) children=%s" % (self.name, REL, H.children()))
        time.sleep(40.0 if which == "never" else REL)
        H.log("LEASE.release %s done" % self.name)


radio_arbiter._make_lease = lambda name: SlowLease(name)
A = radio_arbiter.arbiter
A.transition.connect(lambda e, o, n: H.log("ARBITER %s %s %s [thread %s]" % (
    e, o, n, threading.current_thread().name)), QtCore.Qt.DirectConnection)
from palisade_qt.prowl import ProwlApp  # noqa: E402
from palisade_qt.babel import BabelApp  # noqa: E402

hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720); hub.show(); H.pump(0.5)
gap = {"last": time.monotonic(), "max": 0.0}


def beat():
    now = time.monotonic()
    gap["max"] = max(gap["max"], now - gap["last"])
    gap["last"] = now


hb = QtCore.QTimer(); hb.timeout.connect(beat); hb.start(5)


def openers():
    """Dongle openers that are OUR descendants (other audits may run on this machine)."""
    mine = {k.split(":")[0] for k in H.children() if "(Z)" not in k}
    return [p for p in H.procs_named("rtl_fm", "rtl_power", "rtl_ais", "multimon-ng", "rtl_sdr")
            if p.split(":")[0] in mine]


def snap(tag, prowl=None, babel=None):
    pg = prowl or babel
    extra = ""
    if pg is not None:
        extra = " page_worker=%s retiring=%s busy=%r chip=%r" % (
            type(pg._worker).__name__ if pg._worker else None,
            [type(w).__name__ for w in (getattr(pg, "_retiring", None) or [])],
            pg.busy.text()[:70], (pg._last_status.get("sdr") or {}).get("text"))
    H.log("%s arbiter=%s openers=%s%s" % (tag, A.state(), openers(), extra))


def watch(seconds, prowl=None, babel=None, every=0.5):
    n = int(seconds / every)
    for i in range(n):
        H.pump(every)
        snap("t+%.1f" % ((i + 1) * every), prowl, babel)


def timed(label, fn):
    gap["max"] = 0.0; gap["last"] = time.monotonic()
    t0 = time.monotonic()
    fn()
    call = time.monotonic() - t0
    H.pump(REL + 4.5)
    H.log("GUI-THREAD %-34s call %.3f s; longest event-loop stall during the switch %.3f s"
          % (label, call, gap["max"]))


hub.open_callsign("PROWL"); H.pump(0.5)
page = hub.pages["PROWL"]
prowl = page.child(ProwlApp)
if which.startswith("babel"):
    page.switch_subtab("DECODE"); H.pump(REL + 1.5)    # PROWL SCAN gives the radio back
    b = page.child(BabelApp)
    b.mode_combo.setCurrentText("AIS"); H.pump(0.5)
    b.run_btn.setChecked(True); H.pump(2.5)
    snap("BABEL AIS RUN", babel=b)
    if which == "babel_same":
        b.mode_combo.setCurrentText("SSTV"); H.pump(0.05)
        b.mode_combo.setCurrentText("POCSAG")
        watch(REL + 6, babel=b)
        st = A.state()
        H.log("RESULT babel_same: arbiter=%s openers=%s RUN=%s (expected HELD BABEL + a decoder)"
              % (st, openers(), b.run_btn.isChecked()))
    elif which == "babel_revoke":
        b.mode_combo.setCurrentText("SSTV"); H.pump(0.2)
        H.log("RADIOS revoke ->", A.revoke())
        watch(REL + 8, babel=b)
        H.log("RESULT babel_revoke: arbiter=%s openers=%s RUN=%s" % (A.state(), openers(),
                                                                     b.run_btn.isChecked()))
    elif which == "babel_panic":
        b.mode_combo.setCurrentText("SSTV"); H.pump(0.2)
        H.log("PANIC banner: " + " · ".join(hub.panic()))
        watch(REL + 8, babel=b)
        H.log("RESULT babel_panic: arbiter=%s openers=%s children=%s RUN=%s" % (
            A.state(), openers(), H.children(), b.run_btn.isChecked()))
else:
    page.switch_subtab("NWR"); H.pump(REL + 3.5)       # the default SCAN releases first
    snap("NWR live", prowl)
    if which == "same_name":
        page.switch_subtab("SCAN"); H.pump(2.5); snap("SCAN live", prowl)
        page.switch_subtab("FM"); H.pump(0.05); page.switch_subtab("SCAN")
        watch(REL + 6, prowl)
        H.log("RESULT same_name: arbiter=%s worker=%s openers=%s" % (
            A.state(), type(prowl._worker).__name__, openers()))
    elif which == "gui_block":
        timed("PROWL NWR -> FM", lambda: page.switch_subtab("FM"))
        snap("after NWR->FM", prowl)
        timed("PROWL FM -> SCAN", lambda: page.switch_subtab("SCAN"))
        snap("after FM->SCAN", prowl)
        page.switch_subtab("DECODE"); H.pump(REL + 2)
        b = page.child(BabelApp)
        b.mode_combo.setCurrentText("AIS"); H.pump(0.5)
        b.run_btn.setChecked(True); H.pump(3.0)
        snap("BABEL AIS RUN", babel=b)
        timed("BABEL AIS -> SSTV", lambda: b.mode_combo.setCurrentText("SSTV"))
        snap("after AIS->SSTV", babel=b)
    elif which == "close":
        page.switch_subtab("FM"); H.pump(0.3)
        snap("mid-switch", prowl)
        t0 = time.monotonic()
        hub.close()
        H.log("hub.close() took %.2f s; parked=%s" % (time.monotonic() - t0, papp.parked()))
        H.pump(REL + 3)
        H.log("RESULT close: arbiter=%s openers=%s children=%s" % (A.state(), openers(), H.children()))
        sys.exit(0)
    elif which == "never":
        page.switch_subtab("FM"); watch(6, prowl, every=1.0)
        page.switch_subtab("SCAN"); watch(4, prowl, every=1.0)
        H.log("RESULT never: arbiter=%s page=%r strip-owner=%r" % (
            A.state(), prowl.busy.text(), radio_arbiter.owner_label()))
    elif which == "revoke":
        page.switch_subtab("FM"); H.pump(0.2)
        H.log("RADIOS revoke ->", A.revoke())
        watch(REL + 8, prowl)
        H.log("RESULT revoke: arbiter=%s openers=%s" % (A.state(), openers()))
    elif which == "panic":
        page.switch_subtab("FM"); H.pump(0.2)
        H.log("PANIC banner: " + " · ".join(hub.panic()))
        watch(REL + 8, prowl)
        H.log("RESULT panic: arbiter=%s openers=%s children=%s" % (A.state(), openers(), H.children()))
hub.close(); H.pump(REL + 1.5)
H.log("END arbiter=%s children=%s" % (A.state(), H.children()))
