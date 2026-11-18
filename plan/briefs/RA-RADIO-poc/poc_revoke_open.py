import os, sys, time
WT = sys.argv[1]; sys.path[:0] = [WT, os.path.join(WT, "tests")]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
import iqsource, socket
from palisade_qt import radio_arbiter as ra
ra._make_lease = lambda n: None
from palisade_qt.iqworker import TunerWorker
from rtltcp_fake import FakeProc
log = []
ra.arbiter.transition.connect(lambda e, o, n: log.append((time.monotonic(), "ARB", e, o, n)))
class P(FakeProc):
    def terminate(self):
        log.append((time.monotonic(), "PROC", "terminate", "", "")); super().terminate()
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()   # nothing listens: rtl_tcp still starting up
procs = []
w = TunerWorker(source="rtl", audio=False, source_factory=lambda w: iqsource.RtlTcpSource(w.centre_hz, w.rate, spawn=lambda a: procs.append(P(a)) or procs[-1], port=port))
w.start()
t = time.time()
while time.time() - t < 0.6: app.processEvents(); time.sleep(0.01)
t0 = time.monotonic(); ra.arbiter.revoke("PRISM")
t = time.time()
while time.time() - t < 8: app.processEvents(); time.sleep(0.01)
for e in log: print("%+.2f" % (e[0]-t0), *e[1:])
w.stop(); w.wait(3000)
