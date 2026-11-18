import os, sys, time
WT = sys.argv[1]; sys.path[:0] = [WT, os.path.join(WT, "tests")]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
import iqsource, test_radio_sdrpp as T
from palisade_qt import radio_arbiter as ra
ra._make_lease = lambda n: None
from palisade_qt.iqworker import FastScanWorker
from rtltcp_fake import FakeRtlTcp, FakeProc
srv = FakeRtlTcp(signals=[], realtime=True)
w = FastScanWorker(source="rtl", channels=T.AIR, audio=False, dwell_s=0.15,
    source_factory=lambda w: iqsource.RtlTcpSource(w.centre_hz, w.rate, spawn=FakeProc, port=srv.port))
rows = []; w.row.connect(rows.append)
w.start(); t0 = time.time()
passes = []
while time.time() - t0 < 15:
    app.processEvents(); time.sleep(0.01)
    if w.pass_s and (not passes or passes[-1] != w.pass_s): passes.append(w.pass_s); print("wall %.1f s  pass_s=%.2f" % (time.time()-t0, w.pass_s))
w.stop(); w.wait(3000); srv.close()
