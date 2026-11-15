from common import *
hub=mkhub(demo=True)
print("== M1 Up/Down with a non-primary table focused")
for name,tab in (("ATLAS","SKY DOME"),("PROWL","SCAN"),("RECON","WIFI"),("FORGE","SENSORS"),("SYSTEM","MESH"),("SYSTEM","BENCH"),("ATLAS","MAP"),("PROWL","DECODE")):
    hub.open_callsign(name,tab); pump(700)
    pg=hub.pages[name]
    from palisade_qt.kit.feed import FeedTable
    tabs=[t for t in pg.findChildren(FeedTable) if t.isVisible()]
    prim=pg.primary_list()
    info=[(len(t.model.rows)) for t in tabs]
    line="%s/%s visible tables=%d rows=%s"%(name,tab,len(tabs),info)
    if len(tabs)>1:
        other=[t for t in tabs if t is not prim][0]
        other.view.setFocus(); pump(30)
        r0=(prim.view.currentIndex().row(), other.view.currentIndex().row())
        key(hub,K.Key_Down); key(hub,K.Key_Down)
        r1=(prim.view.currentIndex().row(), other.view.currentIndex().row())
        line+=" | focus on 2nd table, Down x2: (primary,other) rows %s -> %s ; focus now on primary: %s"%(r0,r1, QtWidgets.QApplication.focusWidget() is prim.view)
    print(line)
print("== M2 Tab out of an open overlay")
hub.open_callsign("PROWL","SCAN"); pump(200)
hub.open_panel("keys"); pump(50)
seq=[]
for i in range(6):
    key(hub,K.Key_Tab); f=QtWidgets.QApplication.focusWidget(); seq.append((type(f).__name__, hub.keymap.isAncestorOf(f) if f else None))
print("keys overlay, Tab x6 focus chain (type, inside overlay?):", seq)
s0=state(hub); key(hub,text="3"); print("digit 3 with overlay open & focus outside it:", s0,"->",state(hub))
key(hub,K.Key_Escape)
hub.open_panel("radios"); pump(50); seq=[]
for i in range(8):
    key(hub,K.Key_Tab); f=QtWidgets.QApplication.focusWidget(); seq.append((type(f).__name__, hub.radios_panel.isAncestorOf(f) if f else None))
print("radios overlay Tab x8:", seq); key(hub,K.Key_Escape)
print("== M3 mouse click on nav key under/with overlay open")
hub.open_panel("engagement"); pump(50)
QTest.mouseClick(hub.topbar.nav_keys["FORGE"], K.LeftButton); pump(80); print("click FORGE nav with ENGAGEMENT open ->", state(hub), fw())
key(hub,K.Key_Escape); print("after esc", state(hub))
print("== M4 Tab reach from hub focus")
hub.open_callsign("RECON"); pump(200)
seen=[]; 
for i in range(60):
    key(hub,K.Key_Tab); f=QtWidgets.QApplication.focusWidget()
    lab=type(f).__name__+":"+((f.text() if hasattr(f,"text") and callable(f.text) else "") or getattr(f,"caption","") or getattr(f,"callsign","") or f.objectName())[:22]
    if lab in seen: break
    seen.append(lab)
print(len(seen), seen)
print("== M5 Enter/Space on focused StatusSlot and NavKey")
hub.topbar.slots["engagement"].setFocus(); key(hub,K.Key_Return); print("Enter on ENGAGE slot ->", state(hub)); key(hub,K.Key_Escape)
hub.topbar.slots["radio"].setFocus(); key(hub,K.Key_Space); print("Space on RADIO slot ->", state(hub)); key(hub,K.Key_Escape)
hub.topbar.nav_keys["PRISM"].setFocus(); key(hub,K.Key_Return); print("Enter on PRISM nav ->", state(hub), fw())
print("== M6 palette")
for q in ("5","sweep","bench","babel","overwatch","engage","panic","146.52","more","counter","mesh"):
    hub.open_panel("palette"); pump(30); QTest.keyClicks(hub.palette.input,q); pump(30)
    top=hub.palette.list.item(0).text() if hub.palette.list.count() else None
    print("  %r -> top hit: %s (%d hits)"%(q,top,hub.palette.list.count())); key(hub,K.Key_Escape)
hub.open_panel("palette"); QTest.keyClicks(hub.palette.input,"recon rf"); key(hub,K.Key_Return); print("palette 'recon rf'+Enter ->", state(hub), fw())
print("== M7 folded callsigns")
for n in ("OVERWATCH","BABEL","BENCH","MORE"):
    hub.open_callsign(n); pump(100); print(n,"->",state(hub), type(hub.pages[n]).__name__)
print("== M8 slot text")
engagement.start("Op","ROE-1",["10.0.0.0/24"],"N0CALL"); hub.state.poll(); pump(50)
from palisade_qt import radio_arbiter
print("ENGAGE slot shown:", repr(hub.topbar.slots["engagement"].value.text()), "full:", hub.topbar.slots["engagement"].text())
engagement.reset()
hub.close(); pump(300)
