import os, sys, subprocess, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0, "/Users/daltonhayes/SentryHub"); sys.path.insert(0, "/Users/daltonhayes/SentryHub/tests")
import test_cl1_screen as T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
import txguard, engagement
from palisade_qt import chrome, shell
K=QtCore.Qt
def fresh(demo=True):
    engagement.reset(); txguard.reset_session(); chrome.reset()
    h=T._hub(demo=demo); h._list_children=lambda: []; return h
def key(h,k=None,text="",mod=K.NoModifier):
    tgt=QtWidgets.QApplication.focusWidget() or h
    QTest.keyClicks(tgt,text) if text else QTest.keyClick(tgt,k,mod)
    T._pump(40)

# A. basic routing
h=fresh()
for i,(n,_l) in enumerate(shell.CALLSIGNS,1):
    key(h,text=str(i)); assert h._current==n,(i,n,h._current)
print("A digits 1-8 OK", [n for n,_ in shell.CALLSIGNS])
key(h,text="2"); p=h.current_page(); s0=p.current_subtab(); key(h,K.Key_Right); s1=p.current_subtab(); key(h,K.Key_Left)
print("A left/right", h._current, s0,"->",s1,"->",p.current_subtab())
key(h,text="/"); print("A / palette", h.palette.isVisible()); key(h,K.Key_Escape); print("  esc closes", not h.palette.isVisible())
key(h,text="?"); print("A ? keymap", h.keymap.isVisible()); key(h,K.Key_Escape)
for t,attr in (("r","radios"),("e","engagement"),("a","alerts")):
    key(h,text=t); o=h.top_overlay(); print("A",t,"->",type(o).__name__ if o else None); key(h,K.Key_Escape)
m0=h.topbar.is_muted() if hasattr(h.topbar,"is_muted") else getattr(h.topbar,"muted",None)
key(h,text="m"); m1=h.topbar.is_muted() if hasattr(h.topbar,"is_muted") else getattr(h.topbar,"muted",None)
print("A m mute",m0,"->",m1)
key(h,text="3"); key(h,K.Key_Escape); print("A esc home", h._current)
# typing guard
h.open_callsign("PROWL"); T._pump(100); le=h.page_app("PROWL").fdb_input; le.setFocus(); T._pump(30); le.clear()
key(h,text="5 /?ream[+"); print("A typing guard: page",h._current,"text",repr(le.text()),"overlay",h.top_overlay())
h.close(); T._pump(100)

# B. PANIC with modifiers
for mod,name in ((K.ControlModifier,"Ctrl"),(K.AltModifier,"Alt"),(K.MetaModifier,"Meta"),(K.ShiftModifier,"Shift")):
    h=fresh(); txguard.arm(True); key(h,K.Key_F12,mod=mod); print("B PANIC+%s -> armed after: %s"%(name,txguard.is_armed())); h.close(); T._pump(80)

# B2. combo popup open
h=fresh(); 
found=None
for n,_ in shell.CALLSIGNS:
    h.open_callsign(n); T._pump(80)
    for c in h.findChildren(QtWidgets.QComboBox):
        if c.isVisible() and not c.isEditable() and c.count()>1: found=(n,c); break
    if found: break
print("B2 combo on", found[0], found[1].objectName())
c=found[1]; c.setFocus(); T._pump(30); c.showPopup(); T._pump(100)
txguard.arm(True)
tgt=QtWidgets.QApplication.focusWidget(); print("  focus while popup:", type(tgt).__name__, "window is hub:", tgt.window() is h, "activePopup:", type(QtWidgets.QApplication.activePopupWidget()).__name__)
pop=QtWidgets.QApplication.activePopupWidget() or c.view()
QTest.keyClick(pop,K.Key_F12); T._pump(60); print("  F12 sent to popup -> armed:",txguard.is_armed())
QTest.keyClick(c.view(),K.Key_F12); T._pump(60); print("  F12 sent to combo view -> armed:",txguard.is_armed())
c.hidePopup(); T._pump(50)
# B3 context menu
menu=QtWidgets.QMenu(h); menu.addAction("x"); menu.popup(h.mapToGlobal(QtCore.QPoint(100,100))); T._pump(100)
QTest.keyClick(menu,K.Key_F12); T._pump(60); print("B3 F12 with QMenu open -> armed:",txguard.is_armed()); menu.close()
key(h,K.Key_F12); print("   control: plain F12 -> armed:",txguard.is_armed())
h.close(); T._pump(80)

# C. exception after first two steps
for what in ("chrome.reset","_list_children","_kill","publish"):
    h=fresh(); txguard.arm(True); killed=[]
    h._list_children=lambda: [11,12]; h._kill=lambda p: killed.append(p) or True
    def boom(*a,**k): raise RuntimeError("boom")
    saved=None
    if what=="chrome.reset": saved=chrome.reset; chrome.reset=boom
    elif what=="_list_children": h._list_children=boom
    elif what=="_kill":
        def k1(p):
            killed.append(p)
            if p==11: raise RuntimeError("boom")
            return True
        h._kill=k1
    elif what=="publish":
        from palisade_qt import eventbus; saved=eventbus.bus.publish; eventbus.bus.publish=boom
    try:
        h.panic(); r="no raise"
    except Exception as e: r="RAISED %r"%e
    if what=="chrome.reset": chrome.reset=saved
    if what=="publish": eventbus.bus.publish=saved
    print("C %s raises -> %s; killed=%s banner=%s armed=%s"%(what,r,killed,h.panic_banner.isVisible(),txguard.is_armed()))
    h.close(); T._pump(80)

# D. grandchildren + kills reported as kills
p=subprocess.Popen(["sh","-c","sleep 300 | sleep 301; true"])
time.sleep(0.5)
direct=shell.child_pids()
out=subprocess.run(["pgrep","-f","sleep 30[01]"],capture_output=True,text=True).stdout.split()
print("D direct children:",direct,"popen pid",p.pid,"grandchildren sleeps:",out)
h=fresh(); h._list_children=lambda: [x for x in shell.child_pids() if x==p.pid]
did=h.panic(); time.sleep(0.5)
out2=subprocess.run(["pgrep","-f","sleep 30[01]"],capture_output=True,text=True).stdout.split()
print("D panic said:",did[-1],"| sh alive:",p.poll() is None,"| surviving sleeps:",out2)
for x in out2: os.kill(int(x),15)
p.wait(timeout=5)
# SIGTERM-ignoring child
q=subprocess.Popen([sys.executable,"-c","import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(300)"]); time.sleep(0.7)
h._list_children=lambda:[q.pid]; did=h.panic(); time.sleep(0.5)
print("D TERM-ignoring child: panic said:",did[-1],"| still alive:",q.poll() is None); q.kill(); q.wait()
h.close(); T._pump(80)

# E. BENCH
h=fresh(demo=False)
h.open_callsign("SYSTEM","BENCH"); T._pump(150)
b=h.page_app("SYSTEM") if not hasattr(h.pages["SYSTEM"],"child") else None
from palisade_qt.bench_app import BenchApp
b=h.findChild(BenchApp)
b.ack.setChecked(True); T._pump(80); b._refresh_gate(); h.state.poll(); T._pump(50)
print("E before: slot",h.topbar.slots["tx"].text(),"| tx_btn enabled",b.tx_btn.isEnabled(),"| gate",b.gate.text())
key(h,K.Key_F12); T._pump(700)
import bench
print("E after PANIC: slot",h.topbar.slots["tx"].text(),"| tx_btn enabled",b.tx_btn.isEnabled(),"| gate",b.gate.text(),"| ack",b.ack.isChecked(),"| preflight",bench.preflight(b._settings(),b._band_freq())[0])
b._tx(); print("E after PANIC clicking TX: hero rows ->", b.card.findChildren(QtWidgets.QLabel)[0].text() if b.card.findChildren(QtWidgets.QLabel) else None, [l.text() for l in b.card.findChildren(QtWidgets.QLabel)][:8])
h.close(); T._pump(80)
