import sys, os, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
import iqsource
from palisade_qt import radio_arbiter
from palisade_qt.iqworker import TunerWorker
import test_radio_sdrpp as T
radio_arbiter.arbiter.reset_for_tests()
srv = T.FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
log = []; t0 = time.monotonic()
radio_arbiter.arbiter.transition.connect(lambda e, o, n: log.append(("%.2f" % (time.monotonic() - t0), e)))
opens = []
def factory(w):
    opens.append(time.monotonic() - t0)
    return iqsource.RtlTcpSource(w.centre_hz, w.rate, spawn=lambda av: T.FakeProc(av), port=srv.port)
w = TunerWorker(source="rtl", centre_hz=119_000_000, mode="AM", source_factory=factory, audio=False)
def bad(raw, iq): raise ValueError("deterministic bug")
w.process_block = bad
held_idle = []
w.start()
end = time.monotonic() + 16
while time.monotonic() < end:
    app.processEvents(); time.sleep(0.05)
    held_idle.append(radio_arbiter.arbiter.held_by("PRISM") and w._src is None)
w.stop(); w.wait(4000); srv.close()
print("source opens:", ["%.1f" % x for x in opens])
print("arbiter transitions in 16 s:", len(log), log)
print("fraction of time radio HELD by PRISM with no source open (faulted):", round(sum(held_idle)/len(held_idle), 2))
