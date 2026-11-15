import os, sys, time
HERE=os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["HOME"]=os.path.join(HERE,"home")
sys.dont_write_bytecode=True
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore
app=QtWidgets.QApplication([])
from palisade_qt import theme, eventbus, ops
from palisade_qt.kit import tiles
def _no(*a,**k): raise OSError("blocked")
tiles.urlopen=_no
from palisade_qt.shell import PalisadeHub
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete); time.sleep(0.01)
out=os.path.join(HERE,"poc")
hub=PalisadeHub(demo=True, mode="dark"); hub.resize(1280,720); hub.show(); pump(300)
t0=time.time()
for name,_l in ops.CALLSIGNS:
    hub.open_callsign(name); pump(400)
hub.open_callsign("SWEEP"); pump(30000)
el=time.time()-t0
print("demo: %d alerts in %.0f s (%.1f/min); distinct texts: %d" % (len(hub.alerts.items), el, len(hub.alerts.items)/el*60, len({a['text'] for a in hub.alerts.items})))
from collections import Counter
for t,n in Counter((a['source'],a['text']) for a in hub.alerts.items).most_common(8): print("   ",n,t)
hub.open_panel("alerts"); pump(200)
v=hub.alerts_drawer.table.view; m=v.model(); fm=v.fontMetrics()
cw=v.columnWidth(4); el=[(str(m.data(m.index(r,4))),fm.horizontalAdvance(str(m.data(m.index(r,4))))) for r in range(m.rowCount())]
bad=[(s,w) for s,w in el if w>cw-6]
print("drawer ALERT col width %d; %d/%d rows elided; tooltip role: %r; e.g. %r needs %d" % (cw, len(bad), len(el), m.data(m.index(0,4), QtCore.Qt.ToolTipRole), bad[0][0] if bad else None, bad[0][1] if bad else 0))
hub.grab().save(os.path.join(out,"drawer_demo.png"))
hub.open_panel("alerts")
print("== cap")
hub.alerts.clear()
eventbus.bus.publish(eventbus.alert("SWEEP","FIRST: IMSI catcher",severity="alert"))
for i in range(500): eventbus.bus.publish(eventbus.alert("ATLAS","noise %d"%i,severity="info"))
pump(100)
print("   items", len(hub.alerts.items), "unacked", hub.alerts.unacked(), "FIRST still present:", any(a["text"].startswith("FIRST") for a in hub.alerts.items), "strip:", hub.topbar.alerts.value.text())
hub.close(); pump(300)
