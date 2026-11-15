import os, sys
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0,"/Users/daltonhayes/SentryHub"); sys.path.insert(0,"/Users/daltonhayes/SentryHub/tests")
import test_cl1_screen as T
from PySide6 import QtWidgets, QtGui
import engagement, txguard
from palisade_qt import radio_arbiter as ra, chrome, panels
engagement.reset(); txguard.reset_session(); chrome.reset()
hub=T._hub(demo=False)
out=sys.argv[1]
def show(tag):
    for k in ("radio","engagement"):
        s=hub.topbar.slots[k]; v=s.value
        fm=QtGui.QFontMetrics(v.font())
        print(tag,k,"visible=%r"%v.text(),"full=%r"%s.text(),"slotW=%d valW=%d textW(full)=%d px=%d"%(s.width(),v.width(),fm.horizontalAdvance(s.text()),v.font().pixelSize()))
for scope in (["10.0.0.*","Corp-*","AA:BB:CC:*"],["*"],["10.0.0.5"]):
    engagement.reset(); engagement.start("NightWatch","ROE-42",scope,"op1"); hub.state.poll(); T._pump(50)
    show("scope=%s"%scope)
for o in ra.OWNER_LABELS:
    ra.arbiter.changed.emit(o); T._pump(20)
    s=hub.topbar.slots["radio"]; print("owner",o,"visible=%r full=%r"%(s.value.text(),s.text()))
hub.grab().save(out+"/hub.png"); hub.topbar.grab().save(out+"/topbar.png")
tb=hub.topbar
print("topbar w",tb.width(),"stretch free px:", [ (tb.layout().itemAt(i).geometry().width()) for i in range(tb.layout().count()) if tb.layout().itemAt(i).spacerItem()])
# RECON
hub.show_page("RECON") if hasattr(hub,"show_page") else None
print("hub nav methods:",[m for m in dir(hub) if "page" in m.lower() or "goto" in m.lower()][:12])
for name,pg in getattr(hub,"pages",{}).items():
    if "RECON" in str(name).upper():
        print("RECON gate_banner:",hasattr(pg,"gate_banner"))
        labs=[l.text() for l in pg.findChildren(QtWidgets.QLabel) if any(w in l.text() for w in ("NightWatch","op1","ROE-42","ENGAGEMENT"))]
        print("RECON labels naming eng/op/auth:",labs)
        print("scope labels:",[l.text() for l in pg.findChildren(QtWidgets.QLabel) if "authorized scope" in l.text()][:3])
hub.close(); T._pump(100)
engagement.reset()
