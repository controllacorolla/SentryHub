import os, sys, time
HERE=os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["HOME"]=os.path.join(HERE,"home")
sys.dont_write_bytecode=True
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtCore
app=QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.kit import tiles
def _no(*a,**k): raise OSError("blocked")
tiles.urlopen=_no
from palisade_qt.shell import PalisadeHub
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete); time.sleep(0.01)
hub=PalisadeHub(demo=True, mode="dark"); hub.resize(1280,720); hub.show(); pump(300)
def tables(tag):
    for v in hub.findChildren(QtWidgets.QTableView):
        if not v.isVisibleTo(hub) or not v.isVisible(): continue
        m=v.model(); fm=v.fontMetrics(); res=[]
        for c in range(m.columnCount()):
            head=m.headerData(c, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole)
            ws=[fm.horizontalAdvance(str(m.data(m.index(r,c)) or "")) for r in range(min(m.rowCount(),30))]
            ex=str(m.data(m.index(0,c)) or "") if m.rowCount() else ""
            res.append("%s: col=%d need=%d%s eg=%r" % (head, v.columnWidth(c), max(ws) if ws else 0, " ELIDED" if ws and max(ws)>v.columnWidth(c)-6 else "", ex[:30]))
        print("  ", tag, "rows", m.rowCount(), "font px", v.font().pixelSize(), "|", " ; ".join(res))
for cs, sub in sys.argv[2:] and [a.split(":") for a in sys.argv[2:]]:
    hub.open_callsign(cs); pump(300)
    p=hub.pages.get(cs)
    if sub and hasattr(p,"switch_subtab"): p.switch_subtab(sub)
    pump(2500)
    tables(cs+"/"+sub)
hub.close(); pump(300)
