from common import *
import subprocess, os, signal
def arm():
    txguard.arm(True); txguard.unlock_session(True)
    engagement.start("Op","ROE-1",["10.0.0.*"],"N0CALL")
def st(): return dict(armed=txguard.is_armed(), unlocked=txguard.session_unlocked(), eng=engagement.is_active())
def slots(hub): return {k:s.text() for k,s in hub.topbar.slots.items()}
hub=mkhub(demo=False)
print("== P1 baseline F12"); arm(); hub.state.poll(); print(slots(hub)); key(hub,K.Key_F12); print(st(), slots(hub), hub.panic_banner.text())

print("== P2 modifiers")
for name,mod in (("Shift",K.ShiftModifier),("Ctrl",K.ControlModifier),("Alt",K.AltModifier),("Meta",K.MetaModifier)):
    arm(); key(hub,K.Key_F12,mod=mod); print(name+"+F12 ->", st())
print("== P3 each overlay open")
for w in ("radios","engagement","alerts","keys","palette"):
    arm(); hub.open_panel(w); pump(60); f=fw(); key(hub,K.Key_F12); print(w, "focus",f,"->",st(), "overlay still:", state(hub)[2]); key(hub,K.Key_Escape)
print("== P4 combo popup open")
hub.open_callsign("PROWL"); pump(200)
cb=[c for c in hub.pages["PROWL"].findChildren(QtWidgets.QComboBox) if c.isVisible() and c.isEnabled()][0]
arm(); cb.setFocus(); cb.showPopup(); pump(100)
pop=QtWidgets.QApplication.activePopupWidget(); tgt=QtWidgets.QApplication.focusWidget()
print("popup:",type(pop).__name__, "focus:",type(tgt).__name__, "focus.window() is hub:", tgt.window() is hub if tgt else None)
QTest.keyClick(tgt or pop, K.Key_F12); pump(60); print("F12 with combo popup ->", st())
QTest.keyClick(pop.findChild(QtWidgets.QAbstractItemView) or pop, K.Key_F12); pump(60); print("F12 sent to popup view ->", st())
cb.hidePopup(); pump(50)
print("== P5 context menu open on a line edit")
le=[e for e in hub.pages["PROWL"].findChildren(QtWidgets.QLineEdit) if e.isVisible() and e.isEnabled()]
if le:
    le=le[0]; le.setFocus(); menu=le.createStandardContextMenu(); menu.popup(le.mapToGlobal(QtCore.QPoint(5,5))); pump(100)
    arm(); QTest.keyClick(menu, K.Key_F12); pump(60); print("F12 with QMenu ->", st()); menu.close(); pump(30)
print("== P6 steps raising")
orig_arm=txguard.arm
def boom(*a,**k): raise RuntimeError("arm boom")
arm(); txguard.arm=boom
try: key(hub,K.Key_F12); print("arm raises ->", st(), "|", hub.panic_banner.text())
finally: txguard.arm=orig_arm
txguard.reset_session()
orig_end=engagement.end
arm(); engagement.end=boom
try: key(hub,K.Key_F12); print("end raises ->", st(), "|", hub.panic_banner.text())
finally: engagement.end=orig_end
engagement.reset()
killed=[]
def lc(): raise RuntimeError("pgrep boom")
arm(); hub._list_children=lc; hub.panic_banner.setText("")
try: key(hub,K.Key_F12)
except Exception as e: print("EXC escaped", e)
print("list_children raises ->", st(), "| banner:", repr(hub.panic_banner.text()), "slots", slots(hub))
hub._list_children=lambda:[11,12,13]
def kk(p):
    if p==11: raise RuntimeError("kill boom")
    killed.append(p); return True
arm(); hub._kill=kk; hub.panic_banner.setText("")
key(hub,K.Key_F12); print("kill raises on first ->", st(), "killed", killed, "| banner:", repr(hub.panic_banner.text()))
hub._kill=lambda p: True; hub._list_children=lambda: []
orig_reset=chrome.reset
arm(); chrome.reset=boom; hub.panic_banner.setText(""); k2=[]; hub._list_children=lambda:[77]; hub._kill=lambda p:k2.append(p) or True
try: key(hub,K.Key_F12)
finally: chrome.reset=orig_reset
print("chrome.reset raises ->", st(), "killed", k2, "| banner:", repr(hub.panic_banner.text()))
# page on_gate_changed raising
hub.open_callsign("RECON"); pump(150)
rp=hub.pages["RECON"]; og=rp.on_gate_changed
rp.on_gate_changed=boom; arm(); hub.panic_banner.setText(""); hub.panic_banner.hide()
key(hub,K.Key_F12); print("page.on_gate_changed raises ->", st(), "| banner visible:", hub.panic_banner.isVisible(), repr(hub.panic_banner.text()), slots(hub))
rp.on_gate_changed=og
print("== P7 truthfulness: kill returns False for all / zero children")
hub._list_children=lambda:[5,6]; hub._kill=lambda p: False; arm(); key(hub,K.Key_F12); print(hub.panic_banner.text())
print("== P8 autorepeat")
hub._list_children=lambda:[]; n0=len(hub.alerts.items)
for i in range(5):
    ev=QtGui.QKeyEvent(QtCore.QEvent.KeyPress, K.Key_F12, K.NoModifier, "", True); QtWidgets.QApplication.sendEvent(QtWidgets.QApplication.focusWidget() or hub, ev)
pump(50); print("5 auto-repeat F12 -> alerts added", len(hub.alerts.items)-n0)
print("== P9 BENCH permit vs slot after PANIC")
hub.open_callsign("BENCH"); pump(200)
b=hub.pages["BENCH"]; print("bench type", type(b).__name__)
b.ack.setChecked(True); pump(50)
for i in range(b.band.count()):
    b.band.setCurrentIndex(i); pump(30)
    if b.tx_btn.isEnabled(): break
hub.state.poll(); pump(50)
print("before: band", b.band.currentText(), "tx_btn enabled", b.tx_btn.isEnabled(), "gate", b.gate.text(), "slot", slots(hub)["tx"], "armed", txguard.is_armed())
key(hub,K.Key_F12); pump(700)
import bench
print("after PANIC: tx_btn enabled", b.tx_btn.isEnabled(), "gate label", b.gate.text(), "| slot TX:", slots(hub)["tx"], "| banner:", hub.panic_banner.text(), "| preflight now:", bench.preflight(b._settings(), b._band_freq()))
hub.close(); pump(300)
