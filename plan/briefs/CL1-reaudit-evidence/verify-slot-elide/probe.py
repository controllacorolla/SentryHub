import sys, os
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
os.environ["QT_QPA_PLATFORM"]="offscreen"
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication([])
from palisade_qt import theme, radio_arbiter as ra
from palisade_qt.shell import PalisadeHub
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
hub = PalisadeHub(demo=True, mode="dark"); hub.resize(1280,720); hub.show()
def pump(n=20):
    for _ in range(n): app.processEvents()
pump()
tb = hub.topbar
seen = {}
for k, lab in ra.OWNER_LABELS.items():
    tb.set_state("LIVE", ("HELD", lab), "OFF", ("NONE","",""))
    pump(3)
    s = tb.slots["radio"]
    fm = s.value.fontMetrics()
    print("%-11s full=%-20r painted=%-13r slotW=%d lblW=%d fullPx=%d font=%dpx" % (k, s.text(), s.value.text(), s.width(), s.value.width(), fm.horizontalAdvance(s.text()), s.value.font().pixelSize()))
    seen.setdefault(s.value.text(), []).append(k)
print("collisions:", {k:v for k,v in seen.items() if len(v)>1})
for sc in ("10.0.0.*", "192.168.1.0/24", "aa:*", "lab", "x"):
    tb.set_state("LIVE", ("FREE",""), "OFF", ("ACTIVE", sc, "x"))
    pump(3)
    s = tb.slots["engagement"]
    print("scope %-15s full=%-26r painted=%r tip=%r" % (sc, s.text(), s.value.text(), s.toolTip()))
tb.set_state("LIVE", ("HELD", "PROWL NWR"), "ARMED", ("ACTIVE", "10.0.0.*", "x")); pump()
tb.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "strip.png"))
print("strip width", tb.width(), "minHint", tb.minimumSizeHint().width(), "hub w", hub.width())
print("focus policy", tb.slots["radio"].focusPolicy())
