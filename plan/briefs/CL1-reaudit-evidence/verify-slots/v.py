import sys
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt.kit import topbar
from palisade_qt import radio_arbiter
class FakeAudio:
    available = False
    backend = "fake"

    def __getattr__(self, n): return lambda *a, **k: None
try:
    tb = topbar.TopBar(nav=(), audio=FakeAudio())
except Exception as e:
    print("fake audio failed", e); raise
for scope in ("10.0.0.0/24", "AA:BB:CC:*", "lab", "a", "Acme Q4"):
    tb.set_state("LIVE", ("FREE", ""), "OFF", ("ACTIVE", scope, "Op"))
    s = tb.slots["engagement"]
    print("scope %-12r shown %r  text() %r tip %r" % (scope, s.value.text(), s.text(), s.toolTip()))
for o in sorted(set(radio_arbiter.OWNER_LABELS.values())):
    tb.set_state("LIVE", ("HELD", o), "OFF", ("NONE", "", ""))
    s = tb.slots["radio"]
    print("owner %-11r shown %r  text() %r" % (o, s.value.text(), s.text()))
tb.set_state("LIVE", ("ACQUIRING", "APRS"), "OFF", ("NONE", "", ""))
print("acquiring shown", repr(tb.slots["radio"].value.text()))
print("len('ACTIVE · ')", len("ACTIVE · "), "max", tb.slots["engagement"]._max)
