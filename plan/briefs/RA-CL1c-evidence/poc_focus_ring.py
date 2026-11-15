"""Glyph pixels of each nav key that lie under the focus ring's left/right border (would be overpainted)."""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, sys.argv[1])
from PySide6 import QtGui, QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
for mode in ("dark", "light", "sun"):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
    h = PalisadeHub(demo=False, mode=mode); h.resize(1280, 720); h.show(); h.activateWindow(); pump(300)
    fw = int(theme.tokens(mode)["focus_w"].rstrip("px"))
    row = []
    for name, k in h.topbar.nav_keys.items():
        hit = 0
        for w in (k.call, k.label):
            fm = w.fontMetrics(); tb = fm.tightBoundingRect(w.text())
            x0 = w.x() + (w.width() - fm.horizontalAdvance(w.text())) // 2 + tb.left()   # AlignHCenter
            x1 = x0 + tb.width() - 1
            hit += max(0, fw - x0) + max(0, x1 - (k.width() - 1 - fw))
        # pixel truth: focused vs unfocused ink inside the key
        r = __import__('PySide6').QtCore.QRect(k.mapTo(h, k.rect().topLeft()), k.size())
        h.topbar.nav_keys["OPS" if name != "OPS" else "ATLAS"].setFocus(); pump(30)
        a = h.grab(r).toImage()
        k.setFocus(); pump(30)
        b = h.grab(r).toImage()
        bg = QtGui.QColor(a.pixel(k.width() // 2, 1))
        changed_text = 0
        for x in list(range(0, fw)) + list(range(k.width() - fw, k.width())):
            for y in range(fw, k.height() - fw):
                ca, cb = QtGui.QColor(a.pixel(x, y)), QtGui.QColor(b.pixel(x, y))
                ink = abs(ca.red() - bg.red()) + abs(ca.green() - bg.green()) + abs(ca.blue() - bg.blue()) > 120
                if ink and ca != cb: changed_text += 1
        row.append("%s:%d/%dpx" % (name, hit, changed_text))
    print(mode, "focus_w=%d" % fw, "glyph-cols-under-ring / glyph-pixels-overpainted:", " ".join(row))
    h.close(); pump(100)
