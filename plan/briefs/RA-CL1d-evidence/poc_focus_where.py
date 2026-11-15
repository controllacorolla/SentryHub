"""Where (x,y) the SUN focus cue overpaints glyph ink, and what the fix's own test text-rect is."""
import os, sys, time, collections
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
from PySide6 import QtCore, QtWidgets, QtGui
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
from test_cl1_fix3 import _text_rects
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.005)
mode = "sun"
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss(mode))
h = PalisadeHub(demo=True, mode=mode); h.resize(1280, 720); h.show(); pump(300)
for name in ("PRISM", "SYSTEM"):
    k = h.topbar.nav_keys[name]
    h.topbar.nav_keys["OPS"].setFocus(); pump(30)
    r = QtCore.QRect(k.mapTo(h, QtCore.QPoint(0, 0)), k.size())
    a = h.grab(r).toImage(); k.setFocus(); pump(30); b = h.grab(r).toImage()
    W, H = a.width(), a.height()
    bg = collections.Counter(a.pixel(x, y) for y in range(H) for x in range(W)).most_common(1)[0][0]
    hits = [(x, y, QtGui.QColor(a.pixel(x, y)).name()) for y in range(H) for x in range(W)
            if a.pixel(x, y) != bg and a.pixel(x, y) != b.pixel(x, y)]
    print(name, repr(k.call.text()), repr(k.label.text()), "key", W, "x", H, "label geom", k.label.geometry().getRect(),
          "test text rects", [q.getRect() for q in _text_rects(k)])
    fm = k.label.fontMetrics(); print("  label tight", fm.tightBoundingRect(k.label.text()).getRect(), "ascent", fm.ascent(), "descent", fm.descent())
    print("  overpainted ink (x,y,unfocused colour):", hits)
    s = 8
    for img, tag in ((a, "unf"), (b, "foc")):
        img.scaled(W * s, H * s).save("/tmp/ra-cl1d/zoom_sun_%s_%s.png" % (name, tag))
