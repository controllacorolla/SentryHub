import os, sys, time, tempfile
WT = sys.argv[1]; OUT = sys.argv[2]; sys.path[:0] = [WT]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
def pump(ms):
    t = time.time()
    while time.time() - t < ms/1000: app.processEvents(); time.sleep(0.01)
def clipped(page):
    """visible widgets that extend past the page's right/bottom edge or are squeezed below their minimum size hint"""
    bad = []
    pr = page.rect()
    for w in page.findChildren(QtWidgets.QWidget):
        if not w.isVisibleTo(page) or not w.isVisible(): continue
        g = QtCore.QRect(w.mapTo(page, QtCore.QPoint(0, 0)), w.size())
        if g.right() > pr.right() + 1 or g.bottom() > pr.bottom() + 1:
            # ignore things inside scroll areas
            p = w.parentWidget(); inscroll = False
            while p is not None and p is not page:
                if isinstance(p, QtWidgets.QAbstractScrollArea): inscroll = True; break
                p = p.parentWidget()
            if not inscroll: bad.append((type(w).__name__, w.objectName(), (g.x(), g.y(), g.width(), g.height())))
        if isinstance(w, (QtWidgets.QPushButton, QtWidgets.QLabel)) and w.text() and w.width() < w.minimumSizeHint().width() - 2:
            bad.append(("SQUEEZED", type(w).__name__, w.text()[:30], w.width(), w.minimumSizeHint().width()))
    return bad
for demo in (True, False):
    for mode in ("dark", "sun", "light"):
        theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode)
        app.setStyleSheet(theme.qss(mode))
        hub = PalisadeHub(demo=demo, mode=mode); hub.resize(1280, 720); hub.show(); pump(200)
        for name in ("PRISM", "PROWL"):
            hub.open_callsign(name); pump(1500 if demo else 600)
            page = hub.pages[name]
            if name == "PROWL":
                try: page.switch_subtab("SCAN"); pump(1500 if demo else 400)
                except Exception as e: print("subtab", e)
            fn = os.path.join(OUT, "%s_%s_%s.png" % (name.lower(), mode, "demo" if demo else "live"))
            hub.grab().save(fn)
            st = hub.stack
            print(fn, "hub", hub.size().toTuple(), "stack geom", st.geometry().getRect(), "page", page.size().toTuple(), "page minSizeHint", page.minimumSizeHint().toTuple())
            for b in clipped(page)[:8]: print("   CLIP", b)
        hub.close(); pump(300)
