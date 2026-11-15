import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
H=os.path.join(os.path.dirname(os.path.abspath(__file__)),"home"); os.makedirs(H,exist_ok=True)
os.environ["HOME"]=H; os.environ["XDG_CONFIG_HOME"]=H+"/.config"; os.environ["XDG_DATA_HOME"]=H+"/.local/share"
sys.path.insert(0,"/Users/daltonhayes/SentryHub"); sys.dont_write_bytecode=True
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
app=QtWidgets.QApplication([])
from palisade_qt import radio_arbiter, theme, panels, eventbus
class FL:
    def __init__(s,n): pass
    def release(s): pass
radio_arbiter._make_lease=lambda n: FL(n)
from palisade_qt.shell import PalisadeHub
def pump(ms=100):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(.005)
def pub(t,sev="warn"):
    eventbus.bus.publish(eventbus.alert("T",t,severity=sev)); pump(30)
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
h=PalisadeHub(demo=False,mode="dark"); h.resize(1280,720); h.show(); pump()
st=h.alerts; st.clear()
def sel(d):
    r=d.table.view.currentIndex().row(); return r, (st.items[r]["text"] if 0<=r<len(st.items) else None)
print("A: keyboard Enter")
pub("X-first"); h.open_panel("alerts"); pump(); d=h.alerts_drawer
print(" visible", d.isVisible(), "sel", sel(d))
pub("Y-critical","alert"); print(" after Y sel", sel(d))
QTest.keyClick(QtWidgets.QApplication.focusWidget() or h, QtCore.Qt.Key_Return); pump()
print(" state", [(a["text"],a["acked"]) for a in st.items], "|", d.count.text())
print("B: mouse click on row then button")
st.clear(); pump(); pub("B1"); pub("B2"); pub("B3")
v=d.table.view
idx=v.model().index(2,0); QTest.mouseClick(v.viewport(), QtCore.Qt.LeftButton, pos=v.visualRect(idx).center()); pump()
print(" clicked", sel(d))
pub("B4-new","alert"); print(" after new", sel(d))
QTest.mouseClick(d.ack_btn, QtCore.Qt.LeftButton); pump()
print(" state", [(a["text"],a["acked"]) for a in st.items])
print("C: direct widget, no hub")
s2=panels.AlertStore(); dr=panels.AlertsDrawer("dark", None, store=s2)
pub("C1"); dr.refresh(); dr.focus_first(); pub("C2","alert"); dr.ack_selected()
print(" state", [(a["text"],a["acked"]) for a in s2.items])
h.close(); pump()
