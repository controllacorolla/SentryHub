import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = sys.argv[1]
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_cl1_screen as T
from PySide6 import QtWidgets, QtCore
def cap(hub, tag):
    for w in hub.findChildren(QtWidgets.QLabel):
        t = w.text()
        if w.isVisible() and "HISTORY" in t.upper():
            fm = w.fontMetrics()
            p = w.parentWidget()
            print("  [%s] have %d need %d  card w=%d  hub=%dx%d shown=%s" % (tag, w.contentsRect().width(), fm.horizontalAdvance(t), p.width(), hub.width(), hub.height(), hub.isVisible()))
            w.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cap_%s.png" % tag))
hub = T._hub("dark", True)
T._pump(600)
cap(hub, "as_T_hub")
T._worst_case_strip(hub); T._pump(200)
cap(hub, "worst_strip")
for name, tab in T._every_view(hub):
    T._pump(120)
    if name == "OPS": cap(hub, "iter")
hub.open_callsign("OPS"); T._pump(300)
cap(hub, "after_all")
hub.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ops_full.png"))
hub.close(); T._pump(150)
