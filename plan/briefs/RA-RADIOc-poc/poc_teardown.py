"""Teardown exception (on_source_closed raising once, e.g. a bug in a recorder close) inside
_block_fault: does the thread survive, and is the radio released?"""
import sys, os, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import test_radio_sdrpp as T
from palisade_qt import radio_arbiter as ra
T._app(); ra._make_lease = lambda n: None; ra.arbiter.reset_for_tests()
import iqsource
from palisade_qt.iqworker import TunerWorker
srv = T.FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
fac = lambda w: iqsource.RtlTcpSource(w.centre_hz, w.rate, spawn=T.FakeProc, port=srv.port)
w = TunerWorker(source="rtl", centre_hz=119_000_000, mode="AM", source_factory=fac, audio=False)
st = []; w.status.connect(st.append)
w.start()
T._until(lambda: ra.arbiter.held_by("PRISM") and w._src is not None, 5000)
n = {"c": 0}
orig = w.on_source_closed
def bad():
    n["c"] += 1
    if n["c"] == 1: raise ValueError("teardown bug")
    orig()
w.on_source_closed = bad
w.process_block = lambda raw, iq: (_ for _ in ()).throw(OSError(5, "EIO"))
T._until(lambda: w.isFinished(), 3000); T._pump(300)
print("worker running:", w.isRunning(), "| arbiter owner:", ra.arbiter.owner())
print("last status:", [(s.get("sdr") or {}).get("text") for s in st[-1:]])
srv.close()
