import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtCore, QtGui, QtWidgets
from palisade_qt import theme
theme.configure_scale(os.environ)
app=QtWidgets.QApplication([])
def pump(ms=200):
    t=0
    while t<ms:
        app.processEvents(); time.sleep(0.01); t+=10
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app,"dark"); app.setStyleSheet(theme.qss("dark"))
from palisade_qt.shell import PalisadeHub
from palisade_qt.ops import CALLSIGNS
import pyqtgraph as pg
for demo in (False,True):
    hub=PalisadeHub(demo=demo, mode="dark"); hub.resize(1280,720); hub.show(); pump(500)
    print("== demo",demo,"topbar",hub.topbar.geometry().getRect(),"stack",hub.stack.geometry().getRect())
    for name,_ in CALLSIGNS:
        hub.open_callsign(name); pump(150); page=hub.pages[name]
        for t in (page.subtabs() or [None]):
            if t: page.switch_subtab(t)
            pump(300)
            ps=[f for f in hub.findChildren(QtWidgets.QFrame,"page_status") if f.isVisible()]
            rail=[f for f in hub.findChildren(QtWidgets.QFrame,"subtab_rail") if f.isVisible()]
            line="%s/%s status_row_h=%s rail_w=%s"%(name,t,[f.height() for f in ps],[f.width() for f in rail])
            for tv in hub.findChildren(QtWidgets.QTableView):
                if tv.isVisible(): line+=" table viewport %dx%d => %d rows of 40"%(tv.viewport().width(),tv.viewport().height(),tv.viewport().height()//40)
            for pw in hub.findChildren(pg.PlotWidget):
                if pw.isVisible():
                    vb=pw.getPlotItem().getViewBox(); 
                    locked=vb.state.get("aspectLocked")
                    (x0,x1),(y0,y1)=vb.viewRange(); sr=vb.sceneBoundingRect()
                    line+=" plot %dx%d aspectLocked=%s viewRange x[%.0f..%.0f] y[%.0f..%.0f]"%(pw.width(),pw.height(),locked,x0,x1,y0,y1)
            print(line)
    hub.close(); pump(200)
sys.stdout.flush(); os._exit(0)
