"""PROWL Enter order on a FAST scanner: faulted; faulted+held off (PANIC); hidden; finished+held."""
import sys, os, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import test_radio_sdrpp as T
from palisade_qt import radio_arbiter as ra, iqworker
import iqsource
T._app(); ra._make_lease = lambda n: None; ra.arbiter.reset_for_tests()
opens = []
def mk(self):
    opens.append(1); raise iqsource.SourceError("rtl_tcp exited (1)")
iqworker.IqWorker._make_source = mk
p = T._prowl(demo=False, engine="fast"); p.start(); p.set_active(True)
T._until(lambda: p._worker is not None and p._worker.faulted, 4000)
w = p._worker
def deep():
    T._until(lambda: w.faulted, 3000); w._fault_n = 6; T._pump(400)
def enter(name):
    n0 = len(opens); r = p.primary_action(); T._pump(1200)
    print("%-28s Enter->%s | opens in 1.2s: %d | held_off=%s faulted=%s owner=%s hold=%s" % (
        name, r, len(opens) - n0, w.held_off, w.faulted, ra.arbiter.state()[1],
        p._held(w)))
deep(); enter("faulted, visible")
deep(); w.hold_off("PANIC"); T._pump(300); enter("faulted + held off (PANIC)")
enter("  second Enter")
deep(); p.set_active(False); T._pump(300); enter("faulted, page hidden")
p.set_active(True); T._pump(200)
p.stop()
