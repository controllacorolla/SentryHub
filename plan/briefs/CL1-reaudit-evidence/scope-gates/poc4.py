import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.dont_write_bytecode = True
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore, QtTest
app = QtWidgets.QApplication([])
pump = QtTest.QTest.qWait
import engagement, txguard
engagement.reset(); txguard.reset_session()
from palisade_qt.shell import PalisadeHub
from palisade_qt import radio_arbiter as ra
ra._make_lease = lambda n: None
hub = PalisadeHub(demo=False, mode="dark"); hub._list_children = lambda: []
hub.show(); pump(100)
ra.arbiter.request("ATLAS-APRS"); pump(100)
print("owner before:", ra.arbiter.owner(), "| slot visible:", repr(hub.topbar.slots["radio"].value.text()), "full:", hub.topbar.slots["radio"].text())
def key(k, text=""):
    w = QtWidgets.QApplication.focusWidget() or hub
    QtTest.QTest.keyClick(w, k)
    pump(50)
key(QtCore.Qt.Key_R); print("focus after R:", type(QtWidgets.QApplication.focusWidget()).__name__, getattr(QtWidgets.QApplication.focusWidget(), "text", lambda: "")())
key(QtCore.Qt.Key_Space)
print("owner after R, Space:", ra.arbiter.owner())
key(QtCore.Qt.Key_Escape)
# keyboard can reach engine state only through engine API: E panel with empty form
key(QtCore.Qt.Key_E); hub.engage_panel.eng_operator.setText(""); hub.engage_panel._activate()
print("activate with empty form ->", hub.engage_panel.eng_msg.text(), "| active:", engagement.is_active())
key(QtCore.Qt.Key_Escape)
# UI cannot set TX state: slot click/Enter on TX slot
hub.topbar.slots["tx"].clicked.emit(); pump(50)
print("TX slot click -> armed:", txguard.is_armed(), "overlay:", type(hub.top_overlay()).__name__)
key(QtCore.Qt.Key_Escape)
# RECON gated tool, no engagement, via Enter on focused action button
hub.open_callsign("RECON"); pump(300)
from palisade_qt.recon import GatedTool
g = hub.pages["RECON"].findChildren(GatedTool)
print("gated tools:", len(g))
btns = g[0].findChildren(QtWidgets.QPushButton)
print(" buttons enabled w/o engagement:", [b.isEnabled() for b in btns])
g[0].target.setEnabled(True); g[0].target.setText("10.0.0.5")
for b in btns: b.setEnabled(True)
btns[0].click(); print(" forced click w/o engagement ->", g[0].result.text()[:70])
engagement.start("N", "A", ["10.0.0.*"], "op"); hub.state.poll(); pump(50)
g[0].target.setText("8.8.8.8"); btns[0].click(); print(" out-of-scope ->", g[0].result.text()[:80])
print(" card state after poll:", g[0].state.text())
engagement.end(); hub.state.poll(); pump(50)
print(" card state after end+poll:", g[0].state.text(), "| btn enabled:", [b.isEnabled() for b in btns])
hub.close()
