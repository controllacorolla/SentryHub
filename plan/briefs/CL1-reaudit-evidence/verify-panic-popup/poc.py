import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.dont_write_bytecode=True
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtTest import QTest
app=QtWidgets.QApplication([])
from palisade_qt import theme, shell
import txguard, engagement
K=QtCore.Qt
def pump(ms=100):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.005)
def arm():
    txguard.arm(True); txguard.unlock_session(True)
    if not engagement.is_active(): engagement.start("Op","ROE-1",["10.0.0.*"],"N0CALL")
def st(): return (txguard.is_armed(), txguard.session_unlocked(), engagement.is_active())
hub=shell.PalisadeHub(demo=False, mode="dark"); hub.resize(1280,720); hub.show(); hub.activateWindow(); pump(150)
hub._list_children=lambda: []; hub._kill=lambda p: True
calls=[]; orig=hub.panic
def spy(): calls.append(1); return orig()
hub.panic=spy
def press(tgt, mod=K.NoModifier):
    n=len(calls); QTest.keyClick(tgt, K.Key_F12, mod); pump(50); return len(calls)-n
arm(); print("A baseline: panic calls", press(QtWidgets.QApplication.focusWidget() or hub), st())
for name,mod in (("Shift",K.ShiftModifier),("Ctrl",K.ControlModifier),("Alt",K.AltModifier),("Meta",K.MetaModifier)):
    arm(); print("B %s+F12: calls"%name, press(QtWidgets.QApplication.focusWidget() or hub, mod), st())
hub.open_callsign("PROWL"); pump(200)
cbs=[c for c in hub.pages["PROWL"].findChildren(QtWidgets.QComboBox) if c.isVisible() and c.isEnabled()]
print("visible combos on PROWL:", len(cbs))
cb=cbs[0]; cb.setFocus(); cb.showPopup(); pump(120)
pop=QtWidgets.QApplication.activePopupWidget(); f=QtWidgets.QApplication.focusWidget()
print("C popup", type(pop).__name__, "focus", type(f).__name__, "focus.window() is hub:", f.window() is hub, "popup.window() is hub:", pop.window() is hub)
arm(); print("C F12 -> focus widget: calls", press(f), st(), "popup still open:", pop.isVisible())
print("C F12 -> popup container: calls", press(pop), st())
# real-path dispatch: synthesize window-system key event to the popup's window handle
wh=pop.windowHandle()
if wh:
    n=len(calls); QTest.keyClick(wh, K.Key_F12); pump(50); print("C F12 -> popup QWindow: calls", len(calls)-n, st())
print("C second F12 (popup still open?)", pop.isVisible(), "calls", press(QtWidgets.QApplication.focusWidget()), st())
cb.hidePopup(); pump(80)
print("C after closing popup: calls", press(QtWidgets.QApplication.focusWidget() or hub), st())
les=[e for e in hub.pages["PROWL"].findChildren(QtWidgets.QLineEdit) if e.isVisible() and e.isEnabled()]
le=les[0]; le.setFocus(); m=le.createStandardContextMenu(); m.popup(le.mapToGlobal(QtCore.QPoint(5,5))); pump(120)
arm(); print("D context menu: active popup", type(QtWidgets.QApplication.activePopupWidget()).__name__, "calls", press(m), st()); m.close(); pump(50)
# E: control - is there any QShortcut/other route for F12?
print("E shortcuts on hub:", [s.key().toString() for s in hub.findChildren(QtGui.QShortcut)])
# F: count combos/context-capable inputs across all pages
tot=0
for n,p in hub.pages.items(): tot+=len(p.findChildren(QtWidgets.QComboBox))
print("F combos across instantiated pages:", tot, "pages:", len(hub.pages))
txguard.arm(False)
if engagement.is_active(): engagement.end()
hub.close(); pump(200)
