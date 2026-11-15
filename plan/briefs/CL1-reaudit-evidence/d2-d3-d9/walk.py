import os, sys, json, time, collections
os.environ["QT_QPA_PLATFORM"]="offscreen"
REPO="/Users/daltonhayes/SentryHub"; sys.path.insert(0, REPO)
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"out")
mode=sys.argv[1]; demo=sys.argv[2]=="demo"
from PySide6 import QtCore, QtGui, QtWidgets
from palisade_qt import theme
theme.configure_scale(os.environ)
app=QtWidgets.QApplication([])
import pyqtgraph as pg
def pump(ms=200):
    t=0
    while t<ms:
        app.processEvents(); time.sleep(0.01); t+=10
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
from palisade_qt.shell import PalisadeHub
from palisade_qt.ops import CALLSIGNS
hub=PalisadeHub(demo=demo, mode=mode); hub.resize(1280,720); hub.show(); pump(300)
rows=[]; heights=[]; plots=[]
def cls(w): return (w.property("class") or "")
def txt(w):
    for a in ("text","currentText","toPlainText","placeholderText"):
        f=getattr(w,a,None)
        if f:
            try:
                s=f()
                if isinstance(s,str) and s.strip(): return s.strip()[:40]
            except Exception: pass
    return ""
INTERACTIVE=(QtWidgets.QAbstractButton,QtWidgets.QLineEdit,QtWidgets.QComboBox,QtWidgets.QAbstractSpinBox,QtWidgets.QSlider)
def walk(view, root):
    for w in root.findChildren(QtWidgets.QWidget):
        if not w.isVisible(): continue
        w.ensurePolished()
        px=w.fontInfo().pixelSize()
        t=txt(w)
        name=type(w).__name__
        if isinstance(w,QtWidgets.QLabel) and w.pixmap() is not None and not w.pixmap().isNull(): t=""
        if t or isinstance(w,(QtWidgets.QTableView,QtWidgets.QHeaderView,QtWidgets.QListWidget,QtWidgets.QPlainTextEdit)):
            rows.append((view,name,cls(w),w.objectName(),t,px,w.width(),w.height()))
        if isinstance(w,INTERACTIVE) or (isinstance(w,QtWidgets.QFrame) and cls(w)=="slot"):
            heights.append((view,name,cls(w),t,w.width(),w.height(),bool(w.focusPolicy()!=QtCore.Qt.NoFocus)))
        if isinstance(w,QtWidgets.QTableView):
            vh=w.verticalHeader(); hh=w.horizontalHeader()
            n=w.model().rowCount() if w.model() else 0
            rh=sorted(set(w.rowHeight(i) for i in range(min(n,50))))
            heights.append((view,"TABLEROWS",cls(w),"rows=%d default=%d actual=%s hdr=%d hdrpx=%d"%(n,vh.defaultSectionSize(),rh,hh.height(),hh.fontInfo().pixelSize()),w.width(),w.height(),True))
        if isinstance(w,pg.GraphicsView) or isinstance(w,QtWidgets.QGraphicsView):
            try: items=w.scene().items()
            except Exception: items=[]
            for it in items:
                n=type(it).__name__
                if isinstance(it,pg.AxisItem):
                    tf=it.style.get("tickFont"); 
                    plots.append((view,n,it.orientation,"tickFont=%s"%(tf.pixelSize() if tf else None),"label=%r"%it.labelText, "labelStyle=%r"%(it.labelStyle,), "visible=%s"%it.isVisible()))
                elif isinstance(it,QtWidgets.QGraphicsTextItem):
                    par=it.parentItem()
                    f=it.font(); plots.append((view,n,type(par).__name__ if par else None,"px=%d pt=%s"%(f.pixelSize(),f.pointSizeF()),it.toPlainText()[:30],"infoPx=%d"%QtGui.QFontInfo(f).pixelSize(),"visible=%s"%it.isVisible()))
                elif isinstance(it,QtWidgets.QGraphicsSimpleTextItem):
                    f=it.font(); plots.append((view,n,"","px=%d"%QtGui.QFontInfo(f).pixelSize(),it.text()[:30],"",""))
def grab(view):
    p=hub.grab(); p.save(os.path.join(OUT,"%s_%s_%s.png"%(mode,"demo" if demo else "live",view.replace("/","_").replace(" ","_"))))
pump(800)
views=[]
for name,_ in CALLSIGNS:
    hub.open_callsign(name); pump(120)
    page=hub.pages[name]; tabs=page.subtabs()
    for t in (tabs or [None]):
        if t: page.switch_subtab(t)
        pump(700 if demo else 150)
        v="%s/%s"%(name,t); views.append(v); walk(v,hub); grab(v)
for panel in ("radios","engagement","alerts","keys","palette"):
    hub.open_panel(panel); pump(80)
    v="panel/"+panel; walk(v,hub.top_overlay()); grab(v); hub.open_panel(panel)
json.dump({"rows":rows,"heights":heights,"plots":plots,"min":[hub.minimumSizeHint().width(),hub.minimumSizeHint().height()],"topbar_h":hub.topbar.height(),"topbar_minw":hub.topbar.minimumSizeHint().width()},open(os.path.join(OUT,"walk_%s_%s.json"%(mode,"demo" if demo else "live")),"w"),indent=0)
print("views",len(views),"rows",len(rows),"heights",len(heights),"plots",len(plots))
hub.close(); pump(200)
os._exit(0)
