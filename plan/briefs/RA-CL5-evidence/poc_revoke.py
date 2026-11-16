"""A1 re-derived per holder: grant, run a (fake) decoder, revoke from the GUI thread like FREE THE
RADIO does, then watch: how long revoke() blocks the GUI thread, whether the holder acknowledges
(release) before REVOKE_TIMEOUT_S, whether the arbiter force-frees while the decoder still runs, and
what the holder's last status says afterwards."""
import sys
import time

import _harness as H
from PySide6 import QtCore
from palisade_qt import radio_arbiter

radio_arbiter._make_lease = lambda name: H.FakeLease(name)
A = radio_arbiter.arbiter
which = sys.argv[1]
src = None
if which == "babel":
    from palisade_qt.babel import DecoderWorker
    w = DecoderWorker(demo=False, mode="AIS")
    w.set_running(True)
    w.set_active(True)
elif which == "sstv":
    from palisade_qt.babel import SstvWorker
    w = SstvWorker(demo=False)
elif which == "scan":
    from palisade_qt.prowl import ScanWorker
    w = ScanWorker(demo=False)
    w.set_active(True)
elif which == "fm":
    from palisade_qt.prowl import FmWorker
    w = FmWorker(demo=False)
    w.set_active(True)
elif which == "nwr":
    from palisade_qt.prowl import NwrWorker
    w = NwrWorker(demo=False)
    w.set_active(True)
elif which == "prism":
    from palisade_qt.prism import SweepWorker
    w = SweepWorker(demo=False)
    w.set_active(True)
elif which == "atlas":
    from palisade_qt.atlas import AisSource
    w = None
    src = AisSource()
    src.start()
    src.poll()

if w is not None:
    H.record_status(w, which)
    w.start()
A.changed.connect(lambda o: H.log("ARBITER.changed -> %r" % o), QtCore.Qt.DirectConnection)
H.pump(3.0)
H.log("BEFORE REVOKE arbiter=%s children=%s" % (A.state(), H.children()))
t0 = time.monotonic()
asked = A.revoke()
H.log("revoke() returned %r after %.3f s on the GUI thread" % (asked, time.monotonic() - t0))
forced_with_live = None
for _ in range(16):
    H.pump(0.5)
    st, kids = A.state(), H.children()
    H.log("SAMPLE arbiter=%s revoking=%s children=%s" % (st, A.revoking(), kids))
    if st[0] == "FREE" and kids and forced_with_live is None:
        forced_with_live = kids
H.log("RESULT radio FREE while decoder alive: %s" % (forced_with_live or "no"))
# the next requester is granted immediately
H.log("next request('OTHER') -> %s ; children=%s" % (A.request("OTHER"), H.children()))
A.release("OTHER")
if w is not None:
    w.stop()
    w.wait(5000)
else:
    src.stop()
H.pump(0.5)
H.log("END arbiter=%s children=%s" % (A.state(), H.children()))
