"""retry_now() (GUI thread) clears self._fault while the worker thread is between
`self._fault is not None` and `self._fault[1]` / `_fault_text()` / `self._fault[0]`
in _open() or _ensure_radio(). Those reads are outside run()'s per-block try, so a
TypeError reaches the BaseException handler and the worker thread ends."""
import sys, os, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import test_radio_sdrpp as T
from palisade_qt import radio_arbiter as ra, iqworker
import iqsource
T._app(); ra._make_lease = lambda n: None; ra.arbiter.reset_for_tests()
sys.setswitchinterval(float(sys.argv[2]) if len(sys.argv) > 2 else 1e-6)
src_kind = sys.argv[3] if len(sys.argv) > 3 else "rtl"
def fac(w):
    raise iqsource.SourceError("rtl_tcp exited (1)")
st = []
w = iqworker.TunerWorker(source=src_kind, file_path="/x_121500000Hz_2048000sps.cu8",
                         audio=False, source_factory=fac)
w.status.connect(st.append)
w.start()
T._until(lambda: w.faulted, 3000)
t0 = time.monotonic(); n = 0
while time.monotonic() - t0 < float(os.environ.get("SECS", "20")) and w.isRunning():
    if w._fault is not None:
        w.retry_now(); n += 1
    if n % 200 == 0:
        T._app().processEvents()
T._pump(200)
dead = [s["sdr"]["text"] for s in st if "stopped" in s["sdr"]["text"]]
print("retry_now calls: %d | worker running: %s | owner: %s | %s" %
      (n, w.isRunning(), ra.arbiter.state()[1], dead[:1]))
w.stop(); w.wait(3000)
