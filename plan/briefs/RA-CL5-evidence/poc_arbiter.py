"""A3 / A1 arbiter races with real threads (only _make_lease patched).
1 release during ACQUIRING   2 revoke timer vs a re-grant to ANOTHER owner
3 revoke timer vs the SAME owner re-requesting (stale timer frees the new grant?)
4 owner()/state() latency on the main thread while a 3 s acquire runs
5 GUI-thread block when a holder acknowledges a revoke on the GUI thread (ATLAS) and the
  lease release is slow (stand-in for `sudo systemctl start readsb`)"""
import os
import sys
import threading
import time

import _harness as H
from palisade_qt import radio_arbiter
from palisade_qt.radio_arbiter import RadioArbiter


class L:
    def __init__(self, name, rel_s=0.0):
        self.name, self.rel_s, self.released = name, rel_s, False

    def release(self):
        time.sleep(self.rel_s)
        self.released = True


# 1
leases = []
radio_arbiter._make_lease = lambda n: (time.sleep(0.5), leases.append(L(n)), leases[-1])[2]
a = RadioArbiter()
a.request("A")
time.sleep(0.1)
a.release("A")
time.sleep(0.8)
H.log("1 release during ACQUIRING: state=%s stale-lease-released=%s" % (
    a.state(), [x.released for x in leases]))

# 2
radio_arbiter._make_lease = lambda n: L(n)
a = RadioArbiter()
a.request("A"); time.sleep(0.05)
a.revoke("A", timeout_s=0.3)
a.release("A"); a.request("B"); time.sleep(0.6)
H.log("2 revoke timer after re-grant to B: state=%s (B must still hold)" % (a.state(),))

# 3
sys.stderr = open(os.devnull, "w")       # the '[radio] … forcing free' print sits in the window
hits = 0
N = 400
for i in range(N):
    a = RadioArbiter()
    a.request("A")
    while a.state()[0] != "HELD":
        time.sleep(0.0005)
    a.revoke("A", timeout_s=0.002)
    time.sleep(0.0019)
    a.release("A")                     # the holder acknowledges right at the deadline …
    a.request("A")                     # … and the operator immediately starts it again
    time.sleep(0.01)
    if a.owner() != "A":
        hits += 1
sys.stderr = sys.__stderr__
H.log("3 stale revoke timer freed the SAME owner's new grant in %d/%d runs" % (hits, N))

# 4
radio_arbiter._make_lease = lambda n: (time.sleep(3.0), L(n))[1]
a = RadioArbiter()
a.request("A")
worst = 0.0
end = time.monotonic() + 3.2
while time.monotonic() < end:
    t0 = time.perf_counter(); a.owner(); a.state(); worst = max(worst, time.perf_counter() - t0)
H.log("4 worst owner()+state() latency during a 3 s acquire: %.6f s" % worst)

# 5
radio_arbiter._make_lease = lambda n: L(n, rel_s=2.0)
from palisade_qt.atlas import AisSource  # noqa: E402
A = radio_arbiter.arbiter
src = AisSource(); src.start(); src.poll()
H.pump(1.0)
t0 = time.monotonic()
A.revoke("ATLAS-AIS")
H.log("5 ATLAS: arbiter.revoke() blocked the calling (GUI) thread for %.2f s" % (time.monotonic() - t0))
src.stop()
