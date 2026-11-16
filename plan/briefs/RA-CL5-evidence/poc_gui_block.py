"""GUI-thread time spent in BABEL's hide / STOP / revoke handlers when the decoder is slow to die
(a stage that ignores SIGTERM, e.g. rtl_* wedged in a USB transfer)."""
import os
import time

import _harness as H
from palisade_qt import radio_arbiter

d = os.path.join(H.HERE, "fakebin_noterm")
os.makedirs(d, exist_ok=True)
p = os.path.join(d, "rtl_ais")
with open(p, "w") as f:
    f.write("#!/bin/sh\ntrap '' TERM\nwhile :; do echo '!AIVDM,1,1,,A,15M67FC000G?ufbE`FepT@3n00Sa,0*5C'; "
            "sleep 0.2; done\n")
os.chmod(p, 0o755)
os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
radio_arbiter._make_lease = lambda n: H.FakeLease(n)
from palisade_qt.babel import DecoderWorker  # noqa: E402

for label, act in (("set_active(False) [page hidden]", lambda w: w.set_active(False)),
                   ("set_running(False) [STOP]", lambda w: w.set_running(False)),
                   ("revoked [FREE THE RADIO]", lambda w: radio_arbiter.arbiter.revoke("BABEL"))):
    w = DecoderWorker(demo=False, mode="AIS")
    w.set_running(True)
    w.set_active(True)
    w.start()
    H.pump(1.5)
    t0 = time.monotonic()
    act(w)
    H.log("BABEL %s blocked the GUI thread %.2f s" % (label, time.monotonic() - t0))
    w.stop()
    w.wait(5000)
    radio_arbiter.arbiter.reset_for_tests()
