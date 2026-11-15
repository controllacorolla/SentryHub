import os, sys, json, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
tree=sys.argv[1]; sys.path.insert(0, tree)
from PySide6 import QtWidgets, QtCore
app=QtWidgets.QApplication([])
from palisade_qt import theme, shell
from palisade_qt.ops import CALLSIGNS
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
hub=shell.PalisadeHub(demo=True, mode="dark"); hub.resize(1280,720); hub.show()
def pump(ms=150):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.01)
inv={}
def collect(w):
    out=set()
    for b in w.findChildren(QtWidgets.QAbstractButton):
        if b.text(): out.add("BTN:"+b.text())
    for t in w.findChildren(QtWidgets.QTableView):
        m=t.model()
        if m: out.add("TBL:"+"|".join(str(m.headerData(i,QtCore.Qt.Horizontal)) for i in range(m.columnCount())))
    for c in w.findChildren(QtWidgets.QComboBox):
        out.add("CMB:"+"|".join(c.itemText(i) for i in range(c.count())))
    for e in w.findChildren(QtWidgets.QLineEdit):
        if e.placeholderText(): out.add("EDT:"+e.placeholderText())
    for l in w.findChildren(QtWidgets.QLabel):
        if l.property("class") in ("micro",) and l.text(): out.add("CAP:"+l.text())
    return out
for name,_ in CALLSIGNS:
    hub.open_callsign(name); pump()
    pg=hub.pages[name]
    if hasattr(pg,"subtabs"):
        for t in pg.subtabs():
            pg.switch_subtab(t); pump(80)
    inv[name]=sorted(x for x in collect(pg) if not x.startswith("CAP:"))
if hasattr(hub,"_overlays"):
    for o in hub._overlays:
        inv["OVERLAY:"+o.TITLE]=sorted(collect(o))
    inv["TOPBAR"]=sorted(collect(hub.topbar))
json.dump(inv, open(sys.argv[2],"w"), indent=1, ensure_ascii=False)
hub.close(); pump(300)
