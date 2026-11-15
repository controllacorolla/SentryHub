import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
from palisade_qt.kit.topbar import NavKey
def pump(ms=150):
    t = 0
    while t < ms:
        app.processEvents(); time.sleep(0.01); t += 10
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
hub = PalisadeHub(demo=True, mode="dark"); hub.resize(1280,720); hub.show(); hub.activateWindow(); pump(200)
hub.open_callsign("ATLAS"); pump(200)
seen = []
for i in range(80):
    QTest.keyClick(QtWidgets.QApplication.focusWidget() or hub, QtCore.Qt.Key_Tab); pump(20)
    w = QtWidgets.QApplication.focusWidget()
    d = "%s/%s/%s" % (type(w).__name__, w.property("class") if w else None, getattr(w, "callsign", ""))
    if d in seen: 
        pass
    seen.append(d)
print("navkey_on reached by Tab:", any("navkey_on" in s for s in seen))
print("combo reached by Tab:", any(s.startswith("QComboBox") for s in seen))
print(sorted(set(seen)))
hub.close(); pump(100)
