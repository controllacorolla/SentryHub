"""N1: every holder starts its decoder while the arbiter is still ACQUIRING (readsb not yet paused)
and reports LIVE in that window. Before CL5 request() returned only after the lease was held."""
import sys
import time

import _harness as H
from palisade_qt import radio_arbiter

ACQ = 2.0
radio_arbiter._make_lease = H.slow_make_lease(ACQ)
which = sys.argv[1] if len(sys.argv) > 1 else "babel"
A = radio_arbiter.arbiter

if which == "babel":
    from palisade_qt.babel import DecoderWorker
    w = DecoderWorker(demo=False, mode="AIS")
    w.set_running(True)
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

if w is not None:
    H.record_status(w, which)
    w.start()
else:
    src.poll()
    H.log("ATLAS AisSource.poll() returned; has_radio=%s" % src._has_radio)

for _ in range(6):
    H.pump(0.5)
    H.log("SAMPLE arbiter=%s children=%s" % (A.state(), H.children()))

if w is not None:
    w.stop()
    w.wait(5000)
else:
    src.stop()
H.pump(0.5)
H.log("END arbiter=%s children=%s" % (A.state(), H.children()))
