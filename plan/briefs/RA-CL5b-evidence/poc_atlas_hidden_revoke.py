"""ATLAS AIS layer holds the radio; the operator leaves ATLAS (page hidden -> its worker is PAUSED,
PAUSE_WHEN_HIDDEN defaults True) and frees the radio from the RADIOS panel (arbiter.revoke()).
CL5-fix 6 moved ATLAS's revoke ack from the GUI thread into LeaseSource.poll() on the worker
thread. Does a hidden ATLAS still acknowledge, or is the radio force-freed with rtl_ais alive?"""
import time
import _harness as H
from PySide6 import QtCore
from palisade_qt import radio_arbiter, shell

radio_arbiter._make_lease = lambda name: H.FakeLease(name)
A = radio_arbiter.arbiter
A.changed.connect(lambda o: H.log("ARBITER.changed -> %r" % o), QtCore.Qt.DirectConnection)
hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720); hub.show(); H.pump(0.5)
hub.open_callsign("ATLAS"); H.pump(0.8)
from palisade_qt.atlas import AtlasApp
atlas = hub.pages["ATLAS"].child(AtlasApp)
atlas._layer_btns["vessel"].click()          # operator ticks AIS
H.pump(3.0)
H.log("ATLAS front, AIS on: arbiter=%s children=%s" % (A.state(), H.children()))
hub.show_page("OPS"); H.pump(1.5)                    # operator leaves ATLAS
w = atlas._worker
H.log("ATLAS hidden: worker paused=%s arbiter=%s children=%s" % (
    getattr(w, "_paused", None), A.state(), H.children()))
t0 = time.monotonic()
A.revoke()                                            # RADIOS panel: FREE THE RADIO
H.log("revoke() returned in %.3f s" % (time.monotonic() - t0))
forced = None
for _ in range(14):
    H.pump(0.5)
    st, kids = A.state(), H.children()
    H.log("SAMPLE arbiter=%s revoking=%s children=%s" % (st, A.revoking(), kids))
    if st[0] == "FREE" and kids and forced is None:
        forced = kids
H.log("RESULT radio FREE while rtl_ais alive (ATLAS hidden): %s" % (forced or "no"))
H.log("next request('PROWL-FM') -> %s ; children=%s" % (A.request("PROWL-FM"), H.children()))
A.release("PROWL-FM")
hub.show_page("ATLAS"); H.pump(2.0)
H.log("ATLAS fronted again: arbiter=%s children=%s" % (A.state(), H.children()))
hub.close(); H.pump(1.0)
H.log("END arbiter=%s children=%s" % (A.state(), H.children()))
