import os, sys, json, time, collections
os.environ["QT_QPA_PLATFORM"]="offscreen"
REPO="/Users/daltonhayes/SentryHub"; sys.path.insert(0, REPO)
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"out2")
mode=sys.argv[1]; armed=len(sys.argv)>2 and sys.argv[2]=="armed"
from PySide6 import QtCore, QtGui, QtWidgets
from palisade_qt import theme
theme.configure_scale(os.environ)
app=QtWidgets.QApplication([])
def pump(ms=200):
    t=0
    while t<ms:
        app.processEvents(); time.sleep(0.01); t+=10
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
import engagement, txguard
if armed:
    engagement.start("Op","ROE-1",["10.0.0.*","aa:*"],"N0CALL"); txguard.arm(True); txguard.unlock_session(True)
from palisade_qt.shell import PalisadeHub
from palisade_qt.ops import CALLSIGNS
hub=PalisadeHub(demo=True, mode=mode); hub.resize(1280,720); hub.show(); pump(900)
def lum(c):
    out=[]
    for v in c:
        v/=255.0; out.append(v/12.92 if v<=0.03928 else ((v+0.055)/1.055)**2.4)
    return 0.2126*out[0]+0.7152*out[1]+0.0722*out[2]
def cr(a,b):
    x,y=sorted((lum(a),lum(b)),reverse=True); return (x+0.05)/(y+0.05)
def measure(img, rect, inset=4):
    r=rect.adjusted(inset,inset,-inset,-inset).intersected(img.rect())
    if r.width()<4 or r.height()<4: return None
    cnt=collections.Counter()
    for y in range(r.top(), r.bottom()+1):
        for x in range(r.left(), r.right()+1):
            c=img.pixel(x,y); cnt[((c>>16)&255,(c>>8)&255,c&255)]+=1
    bg=cnt.most_common(1)[0][0]
    best=None
    for c,n in cnt.items():
        if n>=3 and c!=bg:
            k=cr(c,bg)
            if best is None or k>best[0]: best=(k,c)
    if best is None: return None
    return bg,best[1],best[0],cnt
def hexc(c): return "#%02X%02X%02X"%c
TEXTY=(QtWidgets.QLabel,QtWidgets.QAbstractButton,QtWidgets.QLineEdit,QtWidgets.QComboBox,QtWidgets.QAbstractSpinBox)
res=[]; nongray=collections.Counter(); green=[]
G=theme.tokens(mode)["live"].lstrip("#"); GREEN=(int(G[0:2],16),int(G[2:4],16),int(G[4:6],16))
def survey(view, root):
    img=hub.grab().toImage().convertToFormat(QtGui.QImage.Format_RGB32)
    img.save(os.path.join(OUT,"%s_%s_%s.png"%(mode,"armed" if armed else "idle",view.replace("/","_").replace(" ","_"))))
    for w in root.findChildren(QtWidgets.QWidget):
        if not w.isVisible() or not isinstance(w,TEXTY): continue
        if w.objectName()=="qt_spinbox_lineedit": continue
        if isinstance(w,QtWidgets.QLabel) and (not w.text().strip() or (w.pixmap() is not None and not w.pixmap().isNull())): continue
        t=""
        for a in ("text","currentText","placeholderText"):
            f=getattr(w,a,None)
            if f and f(): t=f(); break
        if not t.strip(): continue
        tl=w.mapTo(hub,QtCore.QPoint(0,0)); rect=QtCore.QRect(tl,w.size())
        inset=0 if isinstance(w,QtWidgets.QLabel) else 5
        m=measure(img,rect,inset)
        if not m: continue
        bg,fg,k,cnt=m
        kind=type(w).__name__
        st=[]
        if not w.isEnabled(): st.append("disabled")
        if isinstance(w,QtWidgets.QAbstractButton) and w.isChecked(): st.append("checked")
        if isinstance(w,QtWidgets.QLineEdit) and not w.text() and w.placeholderText(): st.append("placeholder")
        res.append((view,kind,(w.property("class") or ""),",".join(st),t[:40].replace("\n"," "),hexc(bg),hexc(fg),round(k,2)))
        if cnt.get(GREEN,0)>=3 and mode!="sun": green.append((view,kind,(w.property("class") or ""),t[:50]))
    # tables: every visible cell
    for tv in root.findChildren(QtWidgets.QTableView):
        if not tv.isVisible() or tv.model() is None: continue
        mdl=tv.model(); vp=tv.viewport()
        for r in range(min(mdl.rowCount(),8)):
            for c in range(mdl.columnCount()):
                idx=mdl.index(r,c); vr=tv.visualRect(idx)
                if not vr.isValid() or not vp.rect().intersects(vr): continue
                txt=str(mdl.data(idx) or "")
                if not txt.strip(): continue
                rect=QtCore.QRect(vp.mapTo(hub,vr.topLeft()),vr.size())
                m=measure(img,rect,2)
                if not m: continue
                bg,fg,k,cnt=m
                sel=tv.selectionModel().isRowSelected(r,QtCore.QModelIndex())
                res.append((view,"CELL","col=%s"%mdl.headerData(c,QtCore.Qt.Horizontal),"selected" if sel else "",txt[:40],hexc(bg),hexc(fg),round(k,2)))
                if cnt.get(GREEN,0)>=3 and mode!="sun": green.append((view,"CELL",str(mdl.headerData(c,QtCore.Qt.Horizontal)),txt[:50]))
        hh=tv.horizontalHeader()
        if hh.isVisible():
            rect=QtCore.QRect(hh.mapTo(hub,QtCore.QPoint(0,0)),hh.size()); m=measure(img,rect,2)
            if m: res.append((view,"HEADER","","",str(mdl.headerData(0,QtCore.Qt.Horizontal)),hexc(m[0]),hexc(m[1]),round(m[2],2)))
    if mode=="sun":
        for y in range(0,img.height()):
            for x in range(0,img.width()):
                c=img.pixel(x,y); r_,g_,b_=(c>>16)&255,(c>>8)&255,c&255
                if max(r_,g_,b_)-min(r_,g_,b_)>24: nongray[(view,hexc((r_,g_,b_)))]+=1
for name,_ in CALLSIGNS:
    hub.open_callsign(name); pump(120)
    page=hub.pages[name]; tabs=page.subtabs()
    for t in (tabs or [None]):
        if t: page.switch_subtab(t)
        pump(700)
        v="%s/%s"%(name,t)
        survey(v,hub)
        # select first row of the primary table and re-survey cells
        tvs=[x for x in hub.findChildren(QtWidgets.QTableView) if x.isVisible() and x.model() is not None and x.model().rowCount()>0]
        if tvs:
            tvs[0].selectRow(0); tvs[0].setFocus(); pump(60)
            survey(v+"+sel",hub)
            tvs[0].clearSelection(); hub.setFocus()
for panel in ("radios","engagement","alerts","keys","palette"):
    hub.open_panel(panel); pump(100)
    survey("panel/"+panel,hub.top_overlay()); hub.open_panel(panel)
json.dump({"res":res,"green":green,"nongray":[(k[0],k[1],n) for k,n in nongray.most_common(60)]},open(os.path.join(OUT,"contrast_%s_%s.json"%(mode,"armed" if armed else "idle")),"w"))
print("done",len(res))
if armed: engagement.reset(); txguard.reset_session()
hub.close(); pump(100); os._exit(0)
