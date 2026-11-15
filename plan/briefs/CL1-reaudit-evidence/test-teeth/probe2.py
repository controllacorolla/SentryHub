"""Clipping probe: the fits test only checks minimumSizeHint/window size. Look for visible text that is
cut off (label narrower/shorter than its text needs) or children outside the 1280x720 window."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = "/Users/daltonhayes/SentryHub/.claude/worktrees/wf_aa62e8f8-bfc-8"
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_cl1_screen as T
from PySide6 import QtWidgets, QtCore, QtGui

mode = sys.argv[1] if len(sys.argv) > 1 else "dark"
demo = (sys.argv[2] if len(sys.argv) > 2 else "demo") == "demo"
hub = T._hub(mode, demo)
T._pump(600)
T._worst_case_strip(hub)
seen = set()
for name, tab in T._every_view(hub):
    T._pump(120)
    win = hub.rect()
    for w in hub.findChildren(QtWidgets.QWidget):
        if not w.isVisible():
            continue
        tl = w.mapTo(hub, QtCore.QPoint(0, 0))
        r = QtCore.QRect(tl, w.size())
        txt = ""
        if isinstance(w, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
            txt = w.text()
        if not win.contains(r) and w.visibleRegion().isEmpty() is False and txt:
            key = ("OUTSIDE", name, tab, type(w).__name__, txt[:30])
            if key not in seen:
                seen.add(key); print(key, r.getRect())
        if isinstance(w, QtWidgets.QLabel) and txt.strip() and not w.wordWrap() and (w.pixmap() is None or w.pixmap().isNull()):
            fm = w.fontMetrics()
            lines = txt.split("\n")
            need_w = max(fm.horizontalAdvance(l) for l in lines)
            need_h = fm.height() * len(lines)
            cr = w.contentsRect()
            if need_w > cr.width() + 1 or need_h > cr.height() + 1:
                key = ("CLIPPED", name, tab, (w.property("class") or ""), txt[:40])
                if key not in seen:
                    seen.add(key); print(key, "have %dx%d need %dx%d" % (cr.width(), cr.height(), need_w, need_h))
        if isinstance(w, QtWidgets.QAbstractButton) and txt.strip() and not w.layout():
            fm = w.fontMetrics()
            need_w = fm.horizontalAdvance(txt)
            if need_w > w.width() or fm.height() > w.height():
                key = ("BTN-CLIPPED", name, tab, txt[:40])
                if key not in seen:
                    seen.add(key); print(key, "have %dx%d need %dx%d" % (w.width(), w.height(), need_w, fm.height()))
print("total", len(seen))
hub.close(); T._pump(100)
