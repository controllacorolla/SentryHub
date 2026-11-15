from common import *
import subprocess, os, signal
def arm():
    txguard.arm(True); txguard.unlock_session(True)
    engagement.start("Op","ROE-1",["10.0.0.*"],"N0CALL")
def st(): return dict(armed=txguard.is_armed(), unlocked=txguard.session_unlocked(), eng=engagement.is_active())
def slots(hub): return {k:s.text() for k,s in hub.topbar.slots.items()}
hub=mkhub(demo=False)
def skey(*a,**k):
    try: key(*a,**k)
    except Exception as e: print('  EXC escaped:', str(e)[-60:])
killed=[]
def boom(*a,**k): raise RuntimeError("boom")
hub._list_children=lambda:[11,12,13]
def kk(p):
    if p==11: raise RuntimeError("kill boom")
    killed.append(p); return True
arm(); hub._kill=kk; hub.panic_banner.setText("")
skey(hub,K.Key_F12); print("kill raises on first ->", st(), "killed", killed, "| banner:", repr(hub.panic_banner.text()))
hub._kill=lambda p: True; hub._list_children=lambda: []
orig_reset=chrome.reset
arm(); chrome.reset=boom; hub.panic_banner.setText(""); k2=[]; hub._list_children=lambda:[77]; hub._kill=lambda p:k2.append(p) or True
try: skey(hub,K.Key_F12)
finally: chrome.reset=orig_reset
print("chrome.reset raises ->", st(), "killed", k2, "| banner:", repr(hub.panic_banner.text()))
# page on_gate_changed raising
hub.open_callsign("RECON"); pump(150)
rp=hub.pages["RECON"]; og=rp.on_gate_changed
rp.on_gate_changed=boom; arm(); hub.panic_banner.setText(""); hub.panic_banner.hide()
skey(hub,K.Key_F12); print("page.on_gate_changed raises ->", st(), "| banner visible:", hub.panic_banner.isVisible(), repr(hub.panic_banner.text()), slots(hub))
rp.on_gate_changed=og
print("== P7 truthfulness: kill returns False for all / zero children")
hub._list_children=lambda:[5,6]; hub._kill=lambda p: False; arm(); skey(hub,K.Key_F12); print(hub.panic_banner.text())
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
skey(hub,K.Key_F12); pump(700)
import bench
print("after PANIC: tx_btn enabled", b.tx_btn.isEnabled(), "gate label", b.gate.text(), "| slot TX:", slots(hub)["tx"], "| banner:", hub.panic_banner.text(), "| preflight now:", bench.preflight(b._settings(), b._band_freq()))
hub.close(); pump(300)
