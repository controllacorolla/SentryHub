from common import *
hub=mkhub()
# 1. digits + right-arrow walk
for d in "12345678":
    key(hub, text=d)
    pg=hub.current_page(); tabs=pg.subtabs()
    seen=[pg.current_subtab()]
    for _ in range(len(tabs)):
        key(hub, K.Key_Right); seen.append(pg.current_subtab())
    back=[]
    for _ in range(len(tabs)):
        key(hub, K.Key_Left); back.append(pg.current_subtab())
    print(d, hub._current, "tabs", tabs, "walkR", seen, "focus", fw())
    assert set(tabs)<=set(seen) or not tabs, (tabs, seen)
# 9, 0 keys
for d in "90":
    before=state(hub); key(hub,text=d); print("key",d,before,"->",state(hub))
# Esc
key(hub, text="6"); key(hub, K.Key_Escape); print("Esc from RECON ->", state(hub))
# keypad digit
key(hub, K.Key_3, mod=K.KeypadModifier); print("keypad 3 ->", state(hub))
# shift+digit
tgt=QtWidgets.QApplication.focusWidget() or hub
QTest.keyClick(tgt, K.Key_4, K.ShiftModifier); pump(); print("shift+4 ->", state(hub))
# Ctrl+digit
QTest.keyClick(tgt, K.Key_5, K.ControlModifier); pump(); print("ctrl+5 ->", state(hub))
# overlays keys
for ch,name in (("/","COMMAND"),("?","KEYS"),("r","RADIOS"),("e","ENGAGEMENT"),("a","ALERTS")):
    key(hub, K.Key_Escape); key(hub, text="3")
    key(hub, text=ch); s1=state(hub); f1=fw()
    key(hub, text=ch); s2=state(hub)   # same key again: toggle?
    print("overlay key %r -> %s focus=%s ; again -> %s"%(ch,s1,f1,s2))
    key(hub, K.Key_Escape); print("   esc ->", state(hub), fw())
hub.close(); pump(300)
