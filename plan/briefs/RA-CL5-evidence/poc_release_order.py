"""A1 contract ("stop the pipeline, wait for exit, THEN release"): for each holder and each give-back
path, is the holder's decoder still alive at the moment the lease is released (i.e. when real
RtlLease.release would restart readsb)?  The fake lease snapshots this process's live children
inside release()."""
import time

import _harness as H
from palisade_qt import radio_arbiter

radio_arbiter._make_lease = lambda name: H.FakeLease(name)
A = radio_arbiter.arbiter


def trial(label, make, give_back):
    w = make()
    w.start()
    H.pump(1.5)
    before = H.children()
    n0 = len(H.LOG)
    give_back(w)
    H.pump(1.5)
    rel = [e for e in H.LOG[n0:] if e[1] == "LEASE.release"]
    at = rel[0][4] if rel else "NO RELEASE"
    print("RESULT %-34s decoder before=%s | alive at release=%s" % (label, before, at), flush=True)
    w.stop()
    w.wait(5000)
    A.reset_for_tests()
    H.pump(0.3)


from palisade_qt.prowl import NwrWorker, FmWorker, ScanWorker  # noqa: E402
from palisade_qt.babel import DecoderWorker  # noqa: E402


def mk(cls, **k):
    def f():
        w = cls(demo=False, **k)
        w.set_active(True)
        if hasattr(w, "set_running"):
            w.set_running(True)
        return w
    return f


for i in range(3):
    trial("NWR hidden (set_active False)", mk(NwrWorker), lambda w: w.set_active(False))
    trial("NWR revoked", mk(NwrWorker), lambda w: A.revoke("PROWL-NWR"))
    trial("FM hidden (set_active False)", mk(FmWorker), lambda w: w.set_active(False))
    trial("SCAN stop() (sub-tab switch/close)", mk(ScanWorker), lambda w: w.stop())
    trial("BABEL stop()", mk(DecoderWorker, mode="AIS"), lambda w: w.stop())
