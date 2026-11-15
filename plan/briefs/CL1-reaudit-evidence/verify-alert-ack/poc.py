import sys, os
sys.path.insert(0, "/Users/daltonhayes/SentryHub"); sys.path.insert(0, "/Users/daltonhayes/SentryHub/tests")
import test_cl1_screen as T
from palisade_qt import eventbus
from PySide6 import QtCore, QtWidgets
hub = T._hub(demo=False)
def st(): return [(a["text"], "acked" if a["acked"] else "NEW") for a in hub.alerts.items]
eventbus.bus.publish(eventbus.alert("SENTINEL", "A: IMSI catcher suspected", severity="alert")); T._pump(30)
T._key(hub, None, "a"); T._pump(30)
v = hub.alerts_drawer.table.view
print("drawer visible", hub.alerts_drawer.isVisible(), "row", v.currentIndex().row(), hub.alerts_drawer.table.model.rows[v.currentIndex().row()]["text"])
eventbus.bus.publish(eventbus.alert("SENTINEL", "B: GNSS jamming detected", severity="alert")); T._pump(30)
print("after B: row", v.currentIndex().row(), hub.alerts_drawer.table.model.rows[v.currentIndex().row()]["text"])
T._key(hub, QtCore.Qt.Key_Return); T._pump(30)
print(st(), "unacked", hub.alerts.unacked(), "topbar", hub.topbar.alerts.text())
# variant: cursor on row 2 of 3, then arrival
hub.alerts.clear() if hasattr(hub.alerts,"clear") else None
for t in "XYZ": eventbus.bus.publish(eventbus.alert("T", t)); 
T._pump(30); v.selectRow(2); print("sel", hub.alerts_drawer.table.model.rows[2]["text"])
eventbus.bus.publish(eventbus.alert("T", "W")); T._pump(30)
hub.alerts_drawer.ack_selected(); print(st())
hub.close(); T._pump(150)
