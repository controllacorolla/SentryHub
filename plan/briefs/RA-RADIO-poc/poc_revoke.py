import os, sys, time, socket, struct, threading
WT = sys.argv[1]; sys.path[:0] = [WT, os.path.join(WT, "tests")]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
import iqsource
from palisade_qt import radio_arbiter as ra
ra._make_lease = lambda n: None
from palisade_qt.iqworker import TunerWorker, FastScanWorker
from rtltcp_fake import FakeRtlTcp, FakeProc
log = []
ra.arbiter.transition.connect(lambda e, o, n: log.append((time.monotonic(), "ARB", e, o, n)))
class P(FakeProc):
    def terminate(self):
        log.append((time.monotonic(), "PROC", "terminate", self.argv[4], ""))
        super().terminate()
def pump(ms):
    t = time.time()
    while time.time() - t < ms/1000: app.processEvents(); time.sleep(0.005)

# stalled rtl_tcp: header then no samples (a wedged dongle)
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(4); port = srv.getsockname()[1]
conns = []
def serve():
    while True:
        try: c, _ = srv.accept()
        except OSError: return
        c.sendall(b"RTL0" + struct.pack(">II", 5, 29)); conns.append(c)
threading.Thread(target=serve, daemon=True).start()
for cls, kw in ((TunerWorker, {}), (FastScanWorker, {"channels": [(121.5, "g", "AM", 8330)]})):
    log.clear(); procs = []
    fac = lambda w: iqsource.RtlTcpSource(w.centre_hz, w.rate, spawn=lambda a: procs.append(P(a)) or procs[-1], port=port)
    w = cls(source="rtl", source_factory=fac, audio=False, **kw)
    w.start()
    pump(1500)
    print(cls.__name__, "held:", ra.arbiter.held_by(w.NAME), "procs:", len(procs))
    t0 = time.monotonic()
    ra.arbiter.revoke(w.NAME)
    pump(2000)
    print("  owner after revoke:", ra.arbiter.owner(), " proc terminated:", [p.terminated for p in procs])
    for e in log: print("   %+.3f" % (e[0]-t0), *e[1:])
    w.stop(); w.wait(3000)
    print("  alive after stop:", w.isRunning(), " owner:", ra.arbiter.owner())
    ra.arbiter.reset_for_tests()
