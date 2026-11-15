import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"; sys.dont_write_bytecode=True
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtCore
from PySide6.QtTest import QTest
app=QtWidgets.QApplication([])
from palisade_qt import shell
import txguard, engagement
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.005)
hub=shell.PalisadeHub(demo=False, mode="dark"); hub.resize(1280,720); hub.show(); pump(100)
def boom(*a): raise RuntimeError("boom")
hub._list_children=boom
txguard.arm(True); engagement.start("Op","ROE-1",["10.0.0.*"],"N0CALL"); hub.state.poll()
try: QTest.keyClick(hub, QtCore.Qt.Key_F12)
except Exception as e: print("raised to caller", e)
s=lambda:(hub.topbar.slots["engagement"].text(), hub.topbar.slots["tx"].text(), hub.panic_banner.isVisible())
print("t+0", s()); pump(900); print("t+900ms", s())
hub.close(); pump(100)
