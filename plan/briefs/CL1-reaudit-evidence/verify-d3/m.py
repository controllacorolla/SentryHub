import os, sys
os.environ["QT_QPA_PLATFORM"]="offscreen"
REPO="/Users/daltonhayes/SentryHub"
sys.path.insert(0, REPO); sys.path.insert(0, REPO+"/tests")
import test_cl1_screen as T
from PySide6 import QtWidgets, QtCore
import pyqtgraph as pg
from palisade_qt.kit.feed import FeedTable
from palisade_qt.kit.subtabs import SubTabRail
OUT=os.path.dirname(os.path.abspath(__file__))
def g(w, hub):
    p=w.mapTo(hub, QtCore.QPoint(0,0)); return (p.x(),p.y(),w.width(),w.height())
for demo in (True, False):
    hub=T._hub("dark", demo=demo)
    print("=== demo",demo,"hub",hub.width(),hub.height())
    print("topbar",g(hub.topbar,hub),"stack",g(hub.stack,hub))
    print("nav_rail",hub.findChild(QtWidgets.QFrame,"nav_rail"),"foot_bar",hub.findChild(QtWidgets.QFrame,"foot_bar"))
    for name,tab in T._every_view(hub):
        T._pump(1500 if name=='OPS' else 400)
        page=hub.pages[name]
        vis=[f for f in hub.findChildren(QtWidgets.QFrame,"page_status") if f.isVisible()]
        st=[(g(f,hub),[l.text() for l in f.findChildren(QtWidgets.QLabel) if l.isVisible()]) for f in vis]
        rails=[g(r,hub) for r in hub.findChildren(SubTabRail) if r.isVisible()]
        tabs=[]
        for t in hub.findChildren(QtWidgets.QAbstractItemView):
            if t.isVisible():
                vh=t.viewport().height(); m=t.model(); n=m.rowCount() if m else 0
                rh=t.rowHeight(0) if n and hasattr(t,'rowHeight') else (t.verticalHeader().defaultSectionSize() if hasattr(t,'verticalHeader') else -1)
                tabs.append((type(t).__name__,g(t,hub),"vp_h",vh,"rowh",rh,"rows_fit",round(vh/rh,1) if rh>0 else None,"rowcount",n))
        print(name,tab,"| status",st,"| rails",rails)
        for x in tabs: print("    table",x)
        for pw in hub.findChildren(pg.PlotWidget):
            if pw.isVisible():
                vb=pw.getViewBox(); st_=vb.state
                print("    plot",g(pw,hub),"aspect",st_["aspectLocked"],"range",[[round(a,1) for a in r] for r in vb.viewRange()])
        if (name,tab) in (("OPS",None),("RECON","WIFI"),("ATLAS","MAP")) or name in("SWEEP",):
            hub.grab().save(f"{OUT}/{'demo' if demo else 'live'}_{name}_{tab}.png")
    hub.close(); T._pump(200)
