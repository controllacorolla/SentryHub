"""RA-CL5c: hidden ATLAS (AtlasLiveWorker now never paused; while hidden it steps only its lease
layers). Real hub, real rtl_ais fake, real threads; only radio_arbiter._make_lease is patched.
Scenarios (argv[1]): hidden_revoke · hidden_forced · hidden_panic · hidden_acquiring ·
hidden_cost · toggle_panic (tick AIS, PANIC before the worker's next 1 s step)."""
import sys
import threading
import time
import _harness as H
from PySide6 import QtCore
from palisade_qt import radio_arbiter, shell

which = sys.argv[1]
ACQ = 2.0 if which == "hidden_acquiring" else 0.0


def mk(name):
    if ACQ:
        H.log("LEASE.acquire start", name)
        time.sleep(ACQ)
        H.log("LEASE.acquire done", name, "children:", H.children())
    return H.FakeLease(name)


radio_arbiter._make_lease = mk
A = radio_arbiter.arbiter
A.transition.connect(lambda e, o, n: H.log("ARBITER %s %s %s" % (e, o, n)), QtCore.Qt.DirectConnection)
hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720); hub.show(); H.pump(0.5)
hub.open_callsign("ATLAS"); H.pump(0.8)
from palisade_qt.atlas import AtlasApp  # noqa: E402
atlas = hub.pages["ATLAS"].child(AtlasApp)
w = atlas._worker


def ais():
    return [p for p in H.procs_named("rtl_ais") if ":Z" not in p]


def samp(tag):
    H.log("%s arbiter=%s rtl_ais=%s layers=%s wanted=%s srcs=%s" % (
        tag, A.state(), ais(), sorted(atlas._layers), sorted(w._wanted), sorted(w._lease_srcs)))


if which == "toggle_panic":
    viol = 0
    for it in range(10):
        H.pump(0.137 * it % 1.0)                       # vary the phase against the 1 s step
        atlas._layer_btns["vessel"].click()
        pre = A.state()
        H.log("iter %d: AIS ticked (arbiter at PANIC=%s); PANIC in the same event-loop turn" % (it, pre))
        H.log("PANIC banner: " + " · ".join(hub.panic()))
        bad = 0
        for i in range(6):
            H.pump(0.5)
            bad += A.state()[0] != "FREE" or bool(ais())
        samp("iter %d after 3 s" % it)
        viol += bad > 0
        if A.state()[0] != "FREE":
            H.log("iter %d VIOLATION: radio %s after PANIC" % (it, A.state()))
        if "vessel" in atlas._layers:
            atlas._layer_btns["vessel"].click()          # untick; the worker releases
        H.pump(1.5)
    H.log("RESULT toggle_panic: %d of 10 iterations held the radio / ran rtl_ais after PANIC" % viol)
    hub.close(); H.pump(1.0)
    sys.exit(0)

atlas._layer_btns["vessel"].click()
if which == "hidden_acquiring":
    H.pump(0.3)
    samp("ACQUIRING")
    hub.show_page("OPS")
    for i in range(8):
        H.pump(0.5)
        samp("hidden t+%.1f" % ((i + 1) * 0.5))
    H.log("revoke while hidden ->", A.revoke())
    for i in range(6):
        H.pump(0.5)
        samp("after revoke t+%.1f" % ((i + 1) * 0.5))
    hub.close(); H.pump(1.0)
    sys.exit(0)
H.pump(3.0)
samp("FRONT, AIS on")
th_front = threading.active_count()
hub.show_page("OPS"); H.pump(2.0)
samp("HIDDEN")
H.log("cost: threads front=%d hidden=%d; adsb=%s rid=%s; children=%s" % (
    th_front, threading.active_count(), type(w._adsb).__name__, w._rid, H.children()))
if which == "hidden_cost":
    a0 = (w._adsb, w._rid, w._adsb_tried)
    H.pump(5.0)
    H.log("RESULT hidden_cost: after 5 s hidden threads=%d children=%s adsb/rid unchanged=%s" % (
        threading.active_count(), H.children(), (w._adsb, w._rid, w._adsb_tried) == a0))
    hub.close(); H.pump(1.0)
    sys.exit(0)
t0 = time.monotonic()
if which == "hidden_revoke":
    A.revoke()
elif which == "hidden_forced":
    A.revoke(timeout_s=0.05)
elif which == "hidden_panic":
    H.log("PANIC banner: " + " · ".join(hub.panic()))
H.log("call returned in %.3f s" % (time.monotonic() - t0))
bad = 0
for i in range(16):
    H.pump(0.5)
    samp("t+%.1f" % ((i + 1) * 0.5))
    bad += A.state()[0] == "FREE" and bool(ais())
    bad += A.state()[0] != "FREE"
rp = hub.panels.get("radios") if hasattr(hub, "panels") else None
H.log("RESULT %s: %d bad samples (FREE with rtl_ais alive, or not FREE)" % (which, bad))
hub.open_panel("radios"); H.pump(0.5)
try:
    rp = hub.radios_panel
    H.log("RADIOS history:", [(r["event"], r["owner"]) for r in rp._history[:6]])
except Exception as e:
    H.log("RADIOS history unavailable:", e)
hub.close(); H.pump(1.0)
H.log("END arbiter=%s children=%s" % (A.state(), H.children()))
