import sys, os, tempfile
os.environ["HOME"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.environ["HOME"]; os.environ["XDG_DATA_HOME"] = os.environ["HOME"]
sys.path.insert(0, "/Users/daltonhayes/SentryHub"); sys.path.insert(0, "/Users/daltonhayes/SentryHub/tests")
from PySide6 import QtWidgets, QtCore
import test_cl1_screen as T
from palisade_qt import radio_arbiter as ra
import engagement
hub = T._hub(demo=False)
tb = hub.topbar
print("strip width", tb.width(), "minHint", tb.minimumSizeHint().width(), "sizeHint", tb.sizeHint().width())
for lease, lbl in ra.OWNER_LABELS.items():
    ra.arbiter.changed.emit(lease); T._pump(20)
    s = tb.slots["radio"]
    print("%-11s full=%-20r shown=%-14r slotw=%d valw=%d" % (lease, s.text(), s.value.text(), s.width(), s.value.width()))
ra.arbiter.changed.emit("PRISM"); T._pump(20)
print("PRISM shown=%r" % tb.slots["radio"].value.text())
ra.arbiter.changed.emit(""); T._pump(20)
for scope in (["10.0.0.*"], ["10.0.0.0/24"], ["192.168.1.0/24", "corp-wifi"], ["a"]):
    engagement.start("Op", "ROE-1", scope, "N0CALL"); hub.state.poll(); T._pump(20)
    s = tb.slots["engagement"]
    print("scope %-32r full=%-36r shown=%r" % (scope, s.text(), s.value.text()))
    engagement.end() if hasattr(engagement, "end") else None
    hub.state.poll()
tb.set_state("LIVE", ("ACQUIRING", "PROWL scan"), "PERMITTED", ("NONE", "", ""))
print("ACQ shown=%r tx shown=%r" % (tb.slots["radio"].value.text(), tb.slots["tx"].value.text()))
# worst-case free space
tb.set_state("DEMO", ("HELD", "PROWL scan"), "PERMITTED", ("ACTIVE", "10.0.0.0/24", "Op")); tb.set_alerts(3); T._pump(30)
print("worst: minHint", tb.minimumSizeHint().width(), "of", tb.width())
fm = tb.slots["radio"].value.fontMetrics()
for t in ("HELD · PROWL scan", "HELD · BABEL SSTV", "ACTIVE · 10.0.0.0/24"):
    print("needed px for %r: %d" % (t, fm.horizontalAdvance(t)))
tb.grab().save("strip.png")
# keyboard reachability of full text: focus slot, any non-tooltip surface?
print("tooltip:", tb.slots["radio"].toolTip(), "|", tb.slots["engagement"].toolTip())
hub.close()
