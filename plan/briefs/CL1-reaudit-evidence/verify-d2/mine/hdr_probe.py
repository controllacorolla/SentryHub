import sys, os
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtGui, QtCore
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.kit import FeedTable
theme.load_fonts(); theme.set_app_font(app)
app.setStyleSheet(theme.qss("dark") if hasattr(theme, "qss") else theme.stylesheet("dark"))
t = FeedTable([("a", "CALLSIGN"), ("b", "BEARING")])
t.resize(600, 200); t.show(); app.processEvents()
h = t.view.horizontalHeader(); h.ensurePolished()
print("fontInfo px:", h.fontInfo().pixelSize(), "header height:", h.height())
img = h.grab().toImage()
# measure glyph ink height: rows containing pixels notably different from background
bg = img.pixelColor(1, 1)
rows = [y for y in range(img.height()) if any(abs(img.pixelColor(x, y).lightness() - bg.lightness()) > 40 for x in range(img.width()))]
print("ink rows:", (min(rows), max(rows)) if rows else None, "ink height:", (max(rows) - min(rows) + 1) if rows else 0)
