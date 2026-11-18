import os, sys, time, socket, struct
WT = sys.argv[1]; sys.path[:0] = [WT, os.path.join(WT, "tests")]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
import numpy as np, iqsource
from palisade_qt import radio_arbiter as ra
ra._make_lease = lambda n: None
from palisade_qt.iqworker import TunerWorker
from rtltcp_fake import FakeRtlTcp, FakeProc

# (1) unit: a peer that stops reading control bytes -> set_freq raises what?
a, b = socket.socketpair()
b.sendall(b"RTL0" + struct.pack(">II", 5, 29))
src = iqsource.RtlTcpSource(121_500_000, 2048000, spawn=FakeProc, port=1, connect=lambda p: a)
src.open()
try:
    for n in range(200000):
        src.set_freq(118_000_000 + n)
    print("(1) no error")
except iqsource.SourceError as e:
    print("(1) SourceError", e)
except OSError as e:
    print("(1) set_freq after %d cmds raised %s (NOT SourceError)" % (n, type(e).__name__))

# (2) worker: rtl_tcp dies between blocks, then a retune is queued
srv = FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
procs = []
class Src(iqsource.RtlTcpSource):
    def set_freq(self, hz):
        if getattr(self, "dead", False):
            raise BrokenPipeError(32, "Broken pipe")
        super().set_freq(hz)
holder = {}
def factory(w):
    s = Src(w.centre_hz, w.rate, spawn=lambda av: procs.append(FakeProc(av)) or procs[-1], port=srv.port)
    holder["s"] = s
    return s
w = TunerWorker(source="rtl", centre_hz=119_000_000, mode="AM", source_factory=factory, audio=False)
rows, status, faults, errs = [], [], [], []
w.row.connect(rows.append); w.status.connect(status.append); w.fault.connect(faults.append); w.error.connect(errs.append)
w.start()
t = time.time()
while time.time() - t < 3 and not rows:
    app.processEvents(); time.sleep(0.01)
print("(2) running, held_by PRISM:", ra.arbiter.held_by("PRISM"))
holder["s"].dead = True
w.queue(centre_hz=120_000_000)
t = time.time()
while time.time() - t < 3:
    app.processEvents(); time.sleep(0.01)
print("(2) worker thread running after the retune:", w.isRunning(),
      "| arbiter owner:", ra.arbiter.owner(), "| rtl_tcp terminated:", procs[0].terminated,
      "| OFF/fault status emitted:", any(s.get("off") or s.get("fault") for s in status),
      "| fault signal:", [f for f in faults if f], "| errors:", errs)
srv.close()
