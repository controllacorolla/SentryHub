"""B2 side effect: changing the live squelch mid-listen returns "retune" from scanner.listen_channel;
ScanWorker treats that truthy string as a hit, so an EMPTY channel is shown ACTIVE (hot) with a
fresh 'last' time, and the scanner moves on instead of re-listening at the new level."""
import os

import _harness as H
from PySide6 import QtCore
from palisade_qt import radio_arbiter

d = os.path.join(H.HERE, "fakebin_silent")
os.makedirs(d, exist_ok=True)
p = os.path.join(d, "rtl_fm")
with open(p, "w") as f:
    f.write("#!/bin/sh\n# fake rtl_fm on an empty channel: hardware squelch sends nothing\n"
            "exec sleep 600\n")
os.chmod(p, 0o755)
os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
radio_arbiter._make_lease = lambda n: H.FakeLease(n)
from palisade_qt.prowl import ScanWorker  # noqa: E402

rows = []
w = ScanWorker(demo=False)
w.set_active(True)
w.row.connect(lambda r: rows.append(r), QtCore.Qt.DirectConnection)
w.start()
H.pump(0.4)
before = [r["freq"] for r in (rows[-1]["rows"] if rows else []) if r["_hot"]]
w.set_nfm_squelch(80)                       # operator nudges the squelch spinbox
H.pump(0.8)
hot = [(r["freq"], r["last"]) for r in rows[-1]["rows"] if r["_hot"]]
H.log("hot channels before=%s ; after one squelch change on a silent band: %s" % (before, hot))
w.stop()
w.wait(5000)
