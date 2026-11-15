import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"; sys.dont_write_bytecode=True
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtCore
from PySide6.QtTest import QTest
app=QtWidgets.QApplication([])
from palisade_qt import theme, shell, chrome, eventbus
import txguard, engagement
print("shell from", shell.__file__)
K=QtCore.Qt
def pump(ms=100):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.005)
hub=shell.PalisadeHub(demo=False, mode="dark"); hub.resize(1280,720); hub.show(); pump()
alerts=[]; eventbus.bus.published.connect(lambda e: alerts.append(e) if e["type"]=="alert" else None)
escaped=[]
sys.excepthook=lambda t,v,tb: escaped.append(repr(v))
def arm():
    txguard.arm(True); txguard.unlock_session(True)
    engagement.start("Op","ROE-1",["10.0.0.*"],"N0CALL"); hub.state.poll()
    hub.panic_banner.setText(""); hub.panic_banner.hide(); alerts.clear(); escaped.clear()
def press():
    direct=None
    try: QTest.keyClick(QtWidgets.QApplication.focusWidget() or hub, K.Key_F12)
    except Exception as e: direct=repr(e)
    pump(40); return direct
def rep(label, killed):
    print("%-28s armed=%s unlocked=%s eng=%s killed=%s banner_vis=%s banner=%r alerts=%d engslot=%r txslot=%r escaped=%s" % (
        label, txguard.is_armed(), txguard.session_unlocked(), engagement.is_active(), killed,
        hub.panic_banner.isVisible(), hub.panic_banner.text()[:50], len(alerts),
        hub.topbar.slots["engagement"].text(), hub.topbar.slots["tx"].text(), escaped))
def boom(*a,**k): raise RuntimeError("boom")
# baseline
k=[]; hub._list_children=lambda:[11,12,13]; hub._kill=lambda p:k.append(p) or True
arm(); press(); rep("baseline", k)
# kill raises on first
k=[]
def kk(p):
    if p==11: raise RuntimeError("kill boom")
    k.append(p); return True
hub._kill=kk; arm(); press(); rep("_kill raises on 11", k)
# realistic: PermissionError is OSError -> handled by real _terminate; but ProcessLookup etc also OSError. real _terminate with a bad arg:
# _list_children raises
k=[]; hub._kill=lambda p:k.append(p) or True; hub._list_children=boom
arm(); press(); rep("_list_children raises", k)
hub._list_children=lambda:[77]
# chrome.reset raises
o=chrome.reset; chrome.reset=boom; k=[]; arm(); press(); chrome.reset=o; rep("chrome.reset raises", k)
# page on_gate_changed raises
hub.open_callsign("RECON"); pump(150); rp=hub.pages["RECON"]; og=rp.on_gate_changed
rp.on_gate_changed=boom; k=[]; arm(); press(); rep("page.on_gate_changed raises", k); rp.on_gate_changed=og
# bus publish raises
o=eventbus.bus.publish; eventbus.bus.publish=boom; k=[]; arm(); press(); eventbus.bus.publish=o; rep("bus.publish raises", k)
# real seams: can the REAL child_pids/_terminate raise non-OSError?
import subprocess
o=subprocess.run
def fake_run(*a,**kw):
    class R: stdout="123\n456\n"
    return R()
print("real child_pids ok:", (setattr(subprocess,"run",fake_run), shell.child_pids())[1]); subprocess.run=o
hub.close(); pump(200)
