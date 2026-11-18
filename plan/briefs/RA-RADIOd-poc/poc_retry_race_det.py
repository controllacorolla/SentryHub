"""Deterministic interleaving of the retry_now() race: the GUI thread's retry_now() lands
between the worker's `self._fault is not None` test and its `self._fault[1]` read in _open().
Shown by having time.monotonic() (called between the two) run retry_now() once."""
import sys, os, time, threading
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import test_radio_sdrpp as T
from palisade_qt import radio_arbiter as ra, iqworker
import iqsource
T._app(); ra._make_lease = lambda n: None; ra.arbiter.reset_for_tests()
real = time.monotonic
class Clock:
    armed = False
    def monotonic(self):
        if self.armed and threading.current_thread() is not threading.main_thread():
            self.armed = False
            w.retry_now()                       # = the GUI thread's START/Enter landing here
        return real()
    def __getattr__(self, k): return getattr(time, k)
clk = Clock(); iqworker.time = clk
def fac(w): raise iqsource.SourceError("rtl_tcp exited (1)")
st = []
w = iqworker.TunerWorker(source=sys.argv[2] if len(sys.argv) > 2 else "rtl",
                         file_path="/x_1Hz_2048000sps.cu8", audio=False, source_factory=fac)
w.status.connect(st.append); w.start()
T._until(lambda: w.faulted, 3000); T._pump(100)
clk.armed = True
T._until(lambda: w.isFinished(), 3000); T._pump(200)
print("worker running: %s | owner: %s | last: %s" % (w.isRunning(), ra.arbiter.state()[1],
      [s["sdr"]["text"] for s in st][-1:]))
w.stop(); w.wait(3000)
