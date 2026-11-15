import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
from palisade_qt.kit.topbar import NavKey

def pump(ms=150):
    t = 0
    while t < ms:
        app.processEvents(); time.sleep(0.01); t += 10

def diff(a, b):
    a = a.convertToFormat(QtGui.QImage.Format_RGB32); b = b.convertToFormat(QtGui.QImage.Format_RGB32)
    n = 0
    w, h = a.width(), a.height()
    pa, pb = a.constBits().tobytes(), b.constBits().tobytes()
    if pa == pb: return 0
    for i in range(0, len(pa), 4):
        if pa[i:i+4] != pb[i:i+4]: n += 1
    return n

def probe(hub, w):
    """grab only the widget's own rect (so page animation elsewhere doesn't pollute)"""
    hub.setFocus(); pump(80)
    r = QtCore.QRect(w.mapTo(hub, QtCore.QPoint(0, 0)), w.size())
    before = hub.grab(r).toImage()
    before2 = hub.grab(r).toImage()
    w.setFocus(QtCore.Qt.TabFocusReason); pump(80)
    has = w.hasFocus()
    after = hub.grab(r).toImage()
    return has, diff(before, before2), diff(before, after)

for mode in ("dark", "light", "sun"):
    theme.load_fonts(); theme.set_app_font(app)
    app.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=True, mode=mode)
    hub.resize(1280, 720); hub.show(); hub.activateWindow(); pump(200)
    keys = hub.findChildren(NavKey)
    for target in ("PRISM", "ATLAS", "RECON"):
        hub.open_callsign(target); pump(150)
        for k in keys:
            if not k.isVisible(): continue
            has, noise, d = probe(hub, k)
            cls = k.property("class")
            if cls == "navkey_on" or k is keys[0] or d == 0:
                print(mode, "page=%s" % target, k.callsign, cls, "hasFocus=%s noise=%d changed=%d" % (has, noise, d))
    hub.open_callsign("ATLAS"); pump(200)
    for c in hub.findChildren(QtWidgets.QComboBox):
        if c.isVisible():
            has, noise, d = probe(hub, c)
            print(mode, "COMBO", [c.itemText(i) for i in range(c.count())], "policy=%s hasFocus=%s noise=%d changed=%d styled=%s" % (c.focusPolicy(), has, noise, d, bool(c.styleSheet())))
    for name in ("PRISM", "ATLAS"):
        hub.open_callsign(name); pump(200)
        for p in hub.findChildren(pg.PlotWidget):
            if p.isVisible():
                has, noise, d = probe(hub, p)
                print(mode, "PLOT on", name, type(p).__name__, "policy=%s hasFocus=%s noise=%d changed=%d" % (p.focusPolicy(), has, noise, d))
    hub.close(); pump(150)
