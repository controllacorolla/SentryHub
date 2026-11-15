import os, sys
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0, "/Users/daltonhayes/SentryHub"); sys.path.insert(0, "/Users/daltonhayes/SentryHub/tests")
import test_cl1_screen as T
from PySide6 import QtCore, QtGui, QtWidgets
from palisade_qt.kit.topbar import NavKey
def diff(a,b):
    return sum(a.pixel(x,y)!=b.pixel(x,y) for y in range(a.height()) for x in range(a.width()))
for mode in T.THEMES:
    h=T._hub(mode=mode); h.open_callsign("PRISM"); T._pump(150)
    for b in h.findChildren(NavKey):
        print(repr(b.call.text()))
        if b.callsign not in ("PRISM","OPS"): continue
        h.setFocus(); T._pump(60); a=b.grab().toImage()
        b.setFocus(QtCore.Qt.TabFocusReason); T._pump(60); c=b.grab().toImage()
        print(mode, b.call.text(), b.property("class"), "hasFocus",b.hasFocus(),"diff px",diff(a,c), "of", a.width()*a.height())
    h.close(); T._pump(100)
