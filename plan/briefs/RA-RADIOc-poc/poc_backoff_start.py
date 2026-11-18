"""B2 side effect: after a few open faults the retry wait grows to 60 s and the operator's
STOP/START (hold_off + set_active, what PRISM's button does) does not retry sooner.
FAULT_RETRY_S scaled to 0.2 s (x25 faster): 5/10/20/40/60 s -> 0.2/0.4/0.8/1.6/2.4 s."""
import sys, os, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import test_radio_sdrpp as T
from palisade_qt import radio_arbiter as ra, iqworker
T._app(); ra._make_lease = lambda n: None; ra.arbiter.reset_for_tests()
iqworker.FAULT_RETRY_S = 0.2
import iqsource
srv = T.FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
plugged = {"v": False}; opens = []
def fac(w):
    opens.append(time.monotonic())
    if not plugged["v"]:
        raise iqsource.SourceError("rtl_tcp exited (1) — is the SDR plugged in and free?")
    return iqsource.RtlTcpSource(w.centre_hz, w.rate, spawn=T.FakeProc, port=srv.port)
w = iqworker.TunerWorker(source="rtl", centre_hz=119_000_000, mode="AM", source_factory=fac, audio=False)
w.start()
T._until(lambda: len(opens) >= 6, 15000)
plugged["v"] = True                      # operator replugs the dongle
t0 = time.monotonic()
w.hold_off("stopped by operator"); T._pump(300); w.set_active(True)    # STOP, START
T._until(lambda: w._src is not None, 10000)
el = time.monotonic() - t0
print("faults before replug: %d | STOP/START pressed right after replug | live again after %.2f s (scaled retry wait %.2f s)" % (len(opens), el, w._retry_s() if w._fault else 0))
print("real-time equivalent: retry wait = min(60, 5*2^(n-1)) = 60 s for n>=5 faults; START does not shorten it")
w.stop(); w.wait(3000); srv.close()
