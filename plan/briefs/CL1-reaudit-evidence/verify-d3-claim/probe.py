import os, sys
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
import test_cl1_screen as T
from PySide6 import QtWidgets, QtCore, QtGui
import palisade_qt
print("module:", palisade_qt.__file__)
hub = T._hub()
hub.open_callsign("RECON"); T._pump(200)
page = hub.pages["RECON"]; rail = page._rail
print("rail geom", rail.geometry().getRect(), "layout", type(rail.layout()).__name__, "page", page.width(), page.height())
bs = list(rail.buttons.values())
print("btn geoms", [b.geometry().getRect() for b in bs[:3]])
on = bs[0]; off = bs[1]
def img(w): return w.grab().toImage().convertToFormat(QtGui.QImage.Format_RGB32)
def diff(a, b):
    n = 0
    for y in range(min(a.height(), b.height())):
        for x in range(min(a.width(), b.width())):
            if a.pixel(x, y) != b.pixel(x, y): n += 1
    return n
# checked vs unchecked appearance on the same button (same text)
a = img(off); off.setChecked(True); T._pump(50); b = img(off); off.setChecked(False); T._pump(50)
print("checked-vs-unchecked differing px:", diff(a, b), "of", a.width()*a.height())
# focus vs no-focus
hub.activateWindow(); a = img(off); off.setFocus(QtCore.Qt.TabFocusReason); T._pump(50)
print("hasFocus", off.hasFocus()); b = img(off)
print("focus-vs-nofocus differing px:", diff(a, b))
hub.close(); T._pump(150)
