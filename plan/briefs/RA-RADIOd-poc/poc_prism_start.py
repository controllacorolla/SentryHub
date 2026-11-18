"""C1 end to end through PRISM's own START button (real FAULT_RETRY_S = 5 s):
(a) faulted deep in the back-off (60 s), replug, START -> live within ~1 s;
(b) the same while the page is hidden -> START does not take the radio;
(c) START while held off (STOP pressed) + faulted -> retries."""
import sys, os, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import test_radio_sdrpp as T
from palisade_qt import radio_arbiter as ra, iqworker
import iqsource
T._app(); ra._make_lease = lambda n: None; ra.arbiter.reset_for_tests()
srv = T.FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
plugged = {"v": False}; opens = []; owners = []
def mk(self):
    opens.append(time.monotonic())
    if not plugged["v"]:
        raise iqsource.SourceError("rtl_tcp exited (1)")
    return iqsource.RtlTcpSource(self.centre_hz, self.rate, spawn=T.FakeProc, port=srv.port)
iqworker.IqWorker._make_source = mk
ra.arbiter.changed.connect(lambda *a: owners.append(ra.arbiter.state()[1])) if hasattr(ra.arbiter, "changed") else None
from palisade_qt.prism import PrismApp
p = PrismApp(demo=False, mode="dark"); p.start(); p.set_active(True)
T._until(lambda: p._worker is not None and p._worker.faulted, 4000)
w = p._worker
def case(name, hidden, stop_first):
    plugged["v"] = False
    T._until(lambda: w.faulted, 8000)
    w._fault_n = 6                           # back-off 60 s
    w._fault = (w._fault[0], time.monotonic())
    plugged["v"] = True
    if hidden: p.set_active(False); T._pump(300)
    if stop_first and p._running(): p.run_btn.click(); T._pump(200)
    n0 = len(opens); t0 = time.monotonic()
    p._set_running(True)                     # what the START button / Enter does
    ok = T._until(lambda: w._src is not None, 3000)
    held = ra.arbiter.state()[1]
    print("%s: live=%s after %.2fs | opens=%d | arbiter owner=%s | button=%s" % (
        name, bool(ok), time.monotonic() - t0, len(opens) - n0, held, p.run_btn.text()))
    if hidden: p.set_active(True)
    if ok:  # break it again for the next case
        w.queue(); w._block_fault(iqsource.SourceError("unplugged")); 
case("a visible START", False, False)
case("b hidden START", True, False)
case("c STOP then START", False, True)
p.stop(); srv.close()
