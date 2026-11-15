import sys, os
root, tag, out = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
os.chdir(root)
from PySide6 import QtWidgets, QtGui, QtCore
app = QtWidgets.QApplication([])
from palisade_qt import theme
print("theme file", theme.__file__)
if hasattr(theme, "load_fonts"): theme.load_fonts()
host = QtWidgets.QWidget()
try:
    theme.apply(app, "dark")
except Exception as e:
    print("apply(app) failed", e); theme.apply(host, "dark")
from palisade_qt.overwatch import SkyDome
lay = QtWidgets.QVBoxLayout(host)
d = SkyDome(theme.tokens("dark")); lay.addWidget(d)
host.resize(540, 540); host.show(); app.processEvents()
d.set_sky((120, 30), (250, 40, .5), [
  {"label": "NOAA-19 (demo)", "az": 45, "el": 50, "demo": True},
  {"label": "ISS (ZARYA)", "az": 300, "el": 35, "demo": False},
  {"label": "NOAA-19 (demo)", "az": 90, "el": 5, "demo": True}], [])
app.processEvents()
f = d.font(); fi = QtGui.QFontInfo(f); fm = QtGui.QFontMetrics(f)
print(tag, "dome size", d.width(), d.height(), "family", fi.family(), "pixelSize", fi.pixelSize(), "height", fm.height(), "ascent", fm.ascent(), "descent", fm.descent())
for t in ("NOAA-19 (demo)", "ISS (ZARYA)", "N", "W", "☉"):
    print("  adv", repr(t), fm.horizontalAdvance(t), "tightH", fm.tightBoundingRect(t).height())
d.grab().save(os.path.join(out, f"skydome_{tag}.png"))
# quantitative: draw label in the code's rect vs unclipped, count lost ink
def ink(text, w, h, clip):
    img = QtGui.QImage(300, 60, QtGui.QImage.Format_ARGB32); img.fill(0)
    p = QtGui.QPainter(img); p.setFont(f); p.setPen(QtGui.QColor("white"))
    fl = QtCore.Qt.AlignLeft | (QtCore.Qt.TextDontClip if not clip else 0)
    p.drawText(QtCore.QRectF(10, 20, w, h), fl, text); p.end()
    n = 0
    for y in range(60):
        for x in range(300):
            if QtGui.qAlpha(img.pixel(x, y)) > 40: n += 1
    return n
for t, w, h in (("NOAA-19 (demo)", 120, 16), ("ISS (ZARYA)", 120, 16)):
    a, b = ink(t, w, h, True), ink(t, w, h, False)
    print(f"  ink {t!r} clipped={a} unclipped={b} lost={100*(b-a)/max(b,1):.0f}%")
