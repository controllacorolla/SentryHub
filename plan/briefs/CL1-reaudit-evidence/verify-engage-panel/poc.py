import os, sys, time
HERE=os.path.dirname(os.path.abspath(__file__))
tree, tag = sys.argv[1], sys.argv[2]
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["HOME"]=os.path.join(HERE,"home")
sys.dont_write_bytecode=True
sys.path.insert(0, tree)
from PySide6 import QtWidgets, QtCore, QtGui
app=QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.kit import tiles
def _no(*a,**k): raise OSError("blocked")
if hasattr(tiles,"urlopen"): tiles.urlopen=_no
from palisade_qt.shell import PalisadeHub
import engagement
print("engagement from", engagement.__file__)
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.01)
hub=PalisadeHub(demo=False, mode="dark"); hub.resize(1280,720); hub.show(); pump(300)
print("hub size", hub.size().toTuple())
branch = hasattr(hub,"open_panel")
def panel():
    if branch:
        if not hub.engage_panel.isVisible(): hub.open_panel("engagement")
        return hub.engage_panel
    hub.open_callsign("RECON"); p=hub.pages["RECON"]; p._switch("ENGAGE"); return p
def refresh(p):
    for n in ("refresh","_refresh_gate"):
        if hasattr(p,n): getattr(p,n)(); return
cases={"short":("ACME Q4","SOW-114",["192.168.1.0/24"],"K7"),
 "realistic":("ACME HQ wireless assessment","SOW-2026-114 J.Doe CISO",["192.168.10.0/24","AA:BB:CC:*","ACME-Guest-*","ACME-Corp"],"K7ABC"),
 "many-scope":("ACME Q4","SOW-114",["10.0.%d.0/24"%i for i in range(12)],"K7"),
 "name87":("A"*20+" "+"wireless assessment for the headquarters campus phase two retest window Q4"[:66],"SOW-2026-114 J.Doe CISO",["192.168.10.0/24","AA:BB:CC:*"],"K7ABC")}
for k,(n,a,s,o) in cases.items():
    engagement.reset(); print(k, engagement.start(n,a,s,o), "namelen", len(n))
    for t in s[:3]: engagement.authorize_action("deauth", t.replace("*","1") if "*" in t and not "/" in t else t)
    if hasattr(hub,"state"): hub.state.poll()
    pump(30); p=panel(); refresh(p); pump(200)
    c=p.eng_detail; tb=p.eng_actions
    for lab in c.findChildren(QtWidgets.QLabel):
        if lab.isVisible() and lab.wordWrap():
            need=lab.heightForWidth(lab.width())
            # visible region inside card
            top=lab.mapTo(c,QtCore.QPoint(0,0)).y(); vis=min(lab.height(), c.height()-top)
            flag = "CLIPPED" if need>lab.height()+1 or vis<need-1 else "ok"
            print("   label %-32r w=%d h=%d need=%d visible_h=%d %s" % (lab.text()[:32], lab.width(), lab.height(), need, vis, flag))
    v=tb.view; nrows=tb.model.rowCount()
    vp=v.viewport().height(); rh=v.rowHeight(0) if nrows else -1
    print("   card %dx%d  table h=%d viewport_h=%d rows=%d row_h=%d -> fully visible rows=%s" % (c.width(), c.height(), tb.height(), vp, nrows, rh, (vp//rh if rh>0 else "n/a")))
    hub.grab().save(os.path.join(HERE,"out","%s_%s.png"%(tag,k)))
    if branch: hub.open_panel("engagement"); pump(30)
engagement.reset()
p=panel(); pump(100)
e=p.eng_scope; fm=e.fontMetrics()
print("placeholder needs", fm.horizontalAdvance(e.placeholderText()), "field w", e.width(), "contents", e.contentsRect().width())
e.grab().save(os.path.join(HERE,"out","%s_placeholder.png"%tag))
hub.close(); pump(200)
