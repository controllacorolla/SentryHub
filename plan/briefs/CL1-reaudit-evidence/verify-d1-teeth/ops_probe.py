import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = sys.argv[1]
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_cl1_screen as T
from PySide6 import QtWidgets, QtCore
for mode, demo in (("dark", True), ("dark", False)):
    T._isolate() if False else None
    hub = T._hub(mode, demo)
    hub.resize(1280, 720); hub.show(); T._pump(400)
    hub.open_callsign("OPS"); T._pump(300)
    print(mode, demo, "win", hub.width(), hub.height(), "stack x,w", hub.stack.x(), hub.stack.width())
    for w in hub.findChildren(QtWidgets.QLabel):
        t = w.text()
        if w.isVisible() and "HISTORY" in t.upper():
            fm = w.fontMetrics()
            print("  caption %r have %d need %d wrap=%s font=%dpx" % (t, w.contentsRect().width(), fm.horizontalAdvance(t), w.wordWrap(), w.font().pixelSize()))
            img = w.grab(); img.save(os.path.join(os.path.dirname(__file__), "caption_%s_%s.png" % (mode, demo)))
    hub.close(); T._pump(150)
