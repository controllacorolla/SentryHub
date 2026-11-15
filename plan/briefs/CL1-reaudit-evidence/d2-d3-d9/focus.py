import os, sys, json, time, collections
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
mode=sys.argv[1]
from PySide6 import QtCore, QtGui, QtWidgets
from palisade_qt import theme
theme.configure_scale(os.environ)
app=QtWidgets.QApplication([])
def pump(ms=200):
    t=0
    while t<ms:
        app.processEvents(); time.sleep(0.01); t+=10
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
from palisade_qt.shell import PalisadeHub
hub=PalisadeHub(demo=False, mode=mode); hub.resize(1280,720); hub.show(); hub.activateWindow(); pump(300)
def lum(c):
    out=[]
    for v in c:
        v/=255.0; out.append(v/12.92 if v<=0.03928 else ((v+0.055)/1.055)**2.4)
    return 0.2126*out[0]+0.7152*out[1]+0.0722*out[2]
def cr(a,b):
    x,y=sorted((lum(a),lum(b)),reverse=True); return (x+0.05)/(y+0.05)
def px(img,x,y):
    c=img.pixel(x,y); return ((c>>16)&255,(c>>8)&255,c&255)
out=[]
def probe(view):
    seen=set()
    for w in hub.findChildren(QtWidgets.QWidget):
        try:
            if not w.isVisible() or not w.isEnabled() or w.focusPolicy()==QtCore.Qt.NoFocus: continue
        except RuntimeError: continue
        if w.objectName() in("qt_spinbox_lineedit","qt_scrollarea_viewport") or isinstance(w,(QtWidgets.QScrollBar,)): continue
        if w.focusProxy() is not None: continue
        hub.setFocus(); pump(30)
        tl=w.mapTo(hub,QtCore.QPoint(0,0)); r=QtCore.QRect(tl,w.size()).intersected(hub.rect())
        a=hub.grab(r).toImage().convertToFormat(QtGui.QImage.Format_RGB32)
        w.setFocus(QtCore.Qt.TabFocusReason); pump(40)
        got=app.focusWidget() is w
        b=hub.grab(r).toImage().convertToFormat(QtGui.QImage.Format_RGB32)
        changed=0; best=0
        for y in range(a.height()):
            for x in range(a.width()):
                p,q=px(a,x,y),px(b,x,y)
                if p!=q:
                    k=cr(p,q)
                    if k>=1.5: changed+=1
                    best=max(best,k)
        t=""
        for at in ("text","currentText","placeholderText"):
            f=getattr(w,at,None)
            if f and f(): t=f()[:24]; break
        chk=isinstance(w,QtWidgets.QAbstractButton) and w.isChecked()
        key=(type(w).__name__,(w.property("class") or ""),w.objectName(),chk)
        out.append((view,)+key+(t,got,changed,round(best,2),r.width(),r.height()))
    hub.setFocus()
for name,tab in (("OPS",None),("ATLAS","MAP"),("PRISM",None),("PROWL","SCAN"),("PROWL","FM"),("RECON","WIFI"),("FORGE","RADIO"),("SYSTEM","SETTINGS"),("SYSTEM","BENCH")):
    hub.open_callsign(name,tab); pump(300); probe("%s/%s"%(name,tab))
json.dump(out,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"out2","focus_%s.json"%mode),"w"))
hub.close(); pump(100); os._exit(0)
