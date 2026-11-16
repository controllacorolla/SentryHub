"""RA-CL5d: attack the N-k fix (revoke / forced free / PANIC during a pending switch) through the
real hub. Real processes and threads; only radio_arbiter._make_lease is patched (SlowLease: release
takes REL s). TRAP stages (SIGTERM-ignoring rtl_fm / multimon-ng / rtl_ais) are on PATH so the
retiring worker's kill takes time, as on a real wedged dongle.

  python3 poc_d_swap.py <scenario> [<at>]
  at = seconds after the switch to fire (0 = same GUI turn)
Scenarios:
  revoke_at    PROWL NWR -> FM, RADIOS revoke at <at>
  forced_at    PROWL NWR -> FM, revoke with a 0.3 s timeout at <at> (forced free before the ack)
  panic_at     PROWL NWR -> FM, hub.panic() at <at>
  revoke_free  PROWL NWR -> FM, revoke the instant the retiring worker's release makes it FREE
  panic_new    PROWL NWR -> FM, PANIC the instant the NEW worker requests (ACQUIRING)
  revoke_new   PROWL NWR -> FM, revoke the instant the NEW worker requests (ACQUIRING)
  chain_revoke PROWL SCAN -> FM -> SCAN within 0.05 s, revoke at <at>
  chain_panic  PROWL SCAN -> FM -> SCAN within 0.05 s, PANIC at <at>
  babel_chain_revoke  BABEL AIS(RUN) -> SSTV -> POCSAG within 0.05 s, revoke at <at>
  babel_chain_panic   BABEL AIS(RUN) -> SSTV -> POCSAG within 0.05 s, PANIC at <at>
  babel_revoke_at     BABEL AIS(RUN) -> SSTV, revoke at <at>
  babel_forced_at     BABEL AIS(RUN) -> SSTV, revoke timeout 0.3 s at <at>
  babel_rerun         BABEL AIS(RUN) -> SSTV, revoke at 0.2, operator re-ticks RUN at 0.6
  panic_atlas  ATLAS AIS layer ticked (RADIO BUSY, PROWL NWR holds), ATLAS hidden; PROWL NWR -> FM;
               PANIC at <at>: the radio must stay FREE (hidden ATLAS must not grab it after PANIC)
  other_page   PROWL NWR -> FM; 0.2 s later the operator opens DECODE and ticks BABEL RUN
Verdict per run: final arbiter state, dongle openers, and whether the page shows a state it lacks
(RUN ticked without a worker; a page/strip claim with the radio FREE; "press Enter" while HELD)."""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "RA-CL5c-evidence"))
import _harness as H  # noqa: E402
from PySide6 import QtCore  # noqa: E402
from palisade_qt import radio_arbiter, shell  # noqa: E402

which = sys.argv[1]
AT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2
REL = float(os.environ.get("REL", "3.5"))
EV = os.path.join(HERE, "..", "RA-CL5b-evidence")
os.environ["PATH"] = os.pathsep.join([os.path.join(EV, "fakebin_trap"),
                                      os.path.join(EV, "fakebin_trap_mm"), os.environ["PATH"]])


class SlowLease(H.FakeLease):
    def release(self):
        H.log("LEASE.release %s start (%.1f s)" % (self.name, REL))
        time.sleep(REL)
        H.log("LEASE.release %s done" % self.name)


radio_arbiter._make_lease = lambda name: SlowLease(name)
A = radio_arbiter.arbiter
HOOK = {"on_free": None, "on_acq": None}
FIRED = []


class _Gui(QtCore.QObject):
    go = QtCore.Signal(object)


GUI = _Gui()
GUI.go.connect(lambda f: f(), QtCore.Qt.QueuedConnection)   # run f on the GUI thread, next turn


def _tr(e, o, n):
    H.log("ARBITER %s %s %s [thread %s]" % (e, o, n, threading.current_thread().name))
    if e == "RELEASE" and HOOK["on_free"]:
        f, HOOK["on_free"] = HOOK["on_free"], None
        GUI.go.emit(f)                     # GUI thread, next turn (the operator's click)
    if e == "ACQUIRING" and HOOK["on_acq"] and o == HOOK["on_acq"][0]:
        f, HOOK["on_acq"] = HOOK["on_acq"][1], None
        GUI.go.emit(f)


A.transition.connect(_tr, QtCore.Qt.DirectConnection)
from palisade_qt.prowl import ProwlApp  # noqa: E402
from palisade_qt.babel import BabelApp  # noqa: E402

hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720); hub.show(); H.pump(0.5)


def openers():
    mine = {k.split(":")[0] for k in H.children() if "(Z)" not in k}
    return [p for p in H.procs_named("rtl_fm", "rtl_power", "rtl_ais", "multimon-ng", "rtl_sdr")
            if p.split(":")[0] in mine]


def snap(tag, pg):
    H.log("%s arbiter=%s openers=%s page_worker=%s retiring=%s busy=%r chip=%r%s" % (
        tag, A.state(), openers(), type(pg._worker).__name__ if pg._worker else None,
        [type(w).__name__ for w in (getattr(pg, "_retiring", None) or [])], pg.busy.text()[:80],
        (pg._last_status.get("sdr") or {}).get("text"),
        (" RUN=%s" % pg.run_btn.isChecked()) if hasattr(pg, "run_btn") else ""))


def fire(kind):
    if kind == "revoke":
        r = A.revoke()
        FIRED.append(r)
        H.log("RADIOS revoke ->", r)
    elif kind == "forced":
        r = A.revoke(timeout_s=0.3)
        FIRED.append(r)
        H.log("RADIOS revoke (timeout 0.3 s) ->", r)
    elif kind == "panic":
        FIRED.append("PANIC")
        H.log("PANIC banner: " + " · ".join(hub.panic()))


def at(seconds, kind):
    if seconds <= 0:
        fire(kind)
    else:
        H.pump(seconds)
        fire(kind)


def verdict(pg, held_ok_names=(), expect_free=True):
    """After the dust settles: radio FREE and no openers (unless the operator resumed)."""
    H.pump(REL + 6)
    snap("FINAL", pg)
    st, o = A.state()
    bad = []
    if expect_free and (o is not None or openers()):
        bad.append("radio %s %s / openers %s after the revoke/PANIC" % (st, o, openers()))
    if hasattr(pg, "run_btn"):
        if pg.run_btn.isChecked() and pg._worker is None:
            bad.append("RUN ticked with no worker")
        if pg.run_btn.isChecked() and o is None and not pg.swapping():
            bad.append("RUN ticked but radio FREE")
    if o is not None and "press Enter" in pg.busy.text():
        bad.append("'press Enter' while %s %s" % (st, o))
    chip = (pg._last_status.get("sdr") or {}).get("text") or ""
    if o is None and any(k in chip for k in ("LIVE", "capturing", "NWR WX", "FM ", "SCAN ")) \
            and "OFF" not in chip and "BUSY" not in chip:
        bad.append("chip %r claims the radio while FREE" % chip)
    if o is not None and o not in held_ok_names:
        bad.append("held by %s" % o)
    if not FIRED:
        H.log("RESULT %s %s: NOT FIRED (PoC hook)" % (which, AT)); return
    if FIRED == [None]:
        H.log("RESULT %s %s: N/A — revoke returned None (radio already FREE: the old mode had "
              "released; the new mode starting is not a lost revoke). Final %s" % (which, AT, A.state()))
        return
    H.log("RESULT %s %s: %s" % (which, AT, "FAIL: " + "; ".join(bad) if bad else "clean"))


hub.open_callsign("PROWL"); H.pump(0.5)
page = hub.pages["PROWL"]
prowl = page.child(ProwlApp)

if which.startswith("babel"):
    page.switch_subtab("DECODE"); H.pump(REL + 1.5)
    b = page.child(BabelApp)
    b.mode_combo.setCurrentText("AIS"); H.pump(0.5)
    b.run_btn.setChecked(True); H.pump(3.0)
    snap("BABEL AIS RUN", b)
    if which.startswith("babel_chain"):
        b.mode_combo.setCurrentText("SSTV")
        if AT >= 0:
            H.pump(0.05)
        b.mode_combo.setCurrentText("POCSAG")
        at(max(AT, 0), "revoke" if which == "babel_chain_revoke" else "panic")
        verdict(b)
    elif which == "babel_revoke_at":
        b.mode_combo.setCurrentText("SSTV")
        at(AT, "revoke"); verdict(b)
    elif which == "babel_forced_at":
        b.mode_combo.setCurrentText("SSTV")
        at(AT, "forced"); verdict(b)
    elif which == "babel_rerun":
        b.mode_combo.setCurrentText("SSTV")
        at(0.2, "revoke"); H.pump(0.4)
        b.run_btn.setChecked(True); H.log("operator re-ticks RUN")
        snap("after re-RUN", b)
        H.pump(REL + 6); snap("FINAL", b)
        st, o = A.state()
        ok = o == "BABEL-SSTV" and b.run_btn.isChecked() and b._worker is not None
        H.log("RESULT babel_rerun: %s (operator resumed: expect HELD BABEL-SSTV, RUN on, worker)"
              % ("clean" if ok else "FAIL arbiter=%s RUN=%s worker=%s" % (
                  (st, o), b.run_btn.isChecked(), b._worker)))
else:
    if which.startswith("chain"):
        H.pump(REL + 3.0); snap("SCAN live", prowl)
        page.switch_subtab("FM")
        if AT >= 0:
            H.pump(0.05)
        page.switch_subtab("SCAN")                 # AT < 0: FM, SCAN and the revoke in one GUI turn
        at(max(AT, 0), "revoke" if which == "chain_revoke" else "panic")
        verdict(prowl)
    else:
        page.switch_subtab("NWR"); H.pump(REL + 3.5)
        snap("NWR live", prowl)
        if which == "revoke_at":
            page.switch_subtab("FM"); at(AT, "revoke"); verdict(prowl)
        elif which == "forced_at":
            page.switch_subtab("FM"); at(AT, "forced"); verdict(prowl)
        elif which == "panic_at":
            page.switch_subtab("FM"); at(AT, "panic"); verdict(prowl)
        elif which == "revoke_free":
            HOOK["on_free"] = lambda: fire("revoke")
            page.switch_subtab("FM"); verdict(prowl, held_ok_names=("PROWL-FM",), expect_free=False)
        elif which == "revoke_new":
            HOOK["on_acq"] = ("PROWL-FM", lambda: fire("revoke"))
            page.switch_subtab("FM"); verdict(prowl)
        elif which == "panic_new":
            HOOK["on_acq"] = ("PROWL-FM", lambda: fire("panic"))
            page.switch_subtab("FM"); verdict(prowl)
        elif which == "panic_atlas":
            hub.open_callsign("ATLAS"); H.pump(0.8)
            from palisade_qt.atlas import AtlasApp
            atlas = hub.pages["ATLAS"].child(AtlasApp)
            atlas._layer_btns["vessel"].click(); H.pump(1.5)
            H.log("ATLAS AIS ticked; arbiter", A.state())
            hub.open_callsign("PROWL"); H.pump(0.5)
            page.switch_subtab("FM"); at(AT, "panic")
            bad = 0
            for i in range(int((REL + 8) / 0.5)):
                H.pump(0.5)
                if A.state()[0] != "FREE" or openers():
                    bad += 1
                    H.log("t VIOLATION arbiter=%s openers=%s" % (A.state(), openers()))
            snap("FINAL", prowl)
            H.log("RESULT panic_atlas %s: %s; ATLAS layers=%s" % (
                AT, "clean" if not bad else "FAIL %d samples not FREE" % bad, sorted(atlas._layers)))
        elif which == "other_page":
            page.switch_subtab("FM"); H.pump(0.2)
            page.switch_subtab("DECODE")
            b = page.child(BabelApp)
            b.mode_combo.setCurrentText("AIS"); b.run_btn.setChecked(True)
            H.log("operator: DECODE, BABEL AIS RUN while PROWL is still switching")
            for _ in range(int((REL + 8) / 1.0)):
                H.pump(1.0); snap("t", b)
            st, o = A.state()
            bad = []
            if o != "BABEL":
                bad.append("arbiter %s %s (expect BABEL)" % (st, o))
            if prowl._worker is not None and getattr(prowl._worker, "_has_radio", False):
                bad.append("hidden PROWL FM worker holds the radio")
            H.log("RESULT other_page: %s; prowl worker=%s busy=%r" % (
                "FAIL: " + "; ".join(bad) if bad else "clean",
                type(prowl._worker).__name__ if prowl._worker else None, prowl.busy.text()))
hub.close(); H.pump(REL + 1.5)
H.log("END arbiter=%s children=%s" % (A.state(), H.children()))
