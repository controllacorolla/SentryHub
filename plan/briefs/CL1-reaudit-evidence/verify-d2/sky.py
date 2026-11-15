import sys, os
sys.path.insert(0, sys.argv[1]); os.chdir(sys.argv[1])
from PySide6 import QtWidgets, QtGui, QtCore
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.overwatch import SkyDome
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
d = SkyDome(theme.tokens("dark")); d.resize(400, 400); d.show(); app.processEvents()
d.ensurePolished()
fm = QtGui.QFontMetrics(d.font())
print("dome font px", d.fontInfo().pixelSize(), "fm.height", fm.height(), "ascent", fm.ascent(), "tightBoundingRect('ISS (ZARYA)Qg')", fm.tightBoundingRect("ISS (ZARYA)Qg"))
print("label rect h 16; cardinal rect 20x16; 'N' width", fm.horizontalAdvance("N"), "W width", fm.horizontalAdvance("W"))
# direct reproduction of the draw call
img = QtGui.QImage(200, 60, QtGui.QImage.Format_ARGB32); img.fill(QtGui.QColor("black"))
p = QtGui.QPainter(img); p.setFont(d.font()); p.setPen(QtGui.QColor("white"))
p.drawText(QtCore.QRectF(10, 20, 120, 16), QtCore.Qt.AlignLeft, "ISS Qgy"); p.end()
ys = [y for y in range(60) if any(img.pixelColor(x, y).lightness() > 60 for x in range(200))]
print("clipped ink rows", min(ys), max(ys), "rect rows 20..35")
img2 = QtGui.QImage(200, 60, QtGui.QImage.Format_ARGB32); img2.fill(QtGui.QColor("black"))
p = QtGui.QPainter(img2); p.setFont(d.font()); p.setPen(QtGui.QColor("white"))
p.drawText(QtCore.QRectF(10, 20, 120, 40), QtCore.Qt.AlignLeft, "ISS Qgy"); p.end()
ys = [y for y in range(60) if any(img2.pixelColor(x, y).lightness() > 60 for x in range(200))]
print("unclipped ink rows", min(ys), max(ys))
