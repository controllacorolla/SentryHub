import sys, os, time
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore, QtGui
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.prowl import ProwlApp
from palisade_qt.babel import BabelApp
for mode in ("dark", "light"):
    try: theme.apply(app, mode)
    except Exception as e: print("theme.apply", e)
    green = theme.tokens(mode)["live"]
    for cls in (ProwlApp, BabelApp):
        p = cls(demo=True, mode=mode)
        p.resize(1280, 660); p.show(); p.start()
        t = time.time()
        while time.time() - t < 3: app.processEvents(); time.sleep(0.02)
        for k, lbl in p._status_labels.items():
            if not lbl.text(): continue
            img = lbl.grab().toImage()
            cols = {}
            for x in range(img.width()):
                for y in range(img.height()):
                    c = img.pixelColor(x, y).name(); cols[c] = cols.get(c, 0) + 1
            top = sorted(cols.items(), key=lambda kv: -kv[1])[:3]
            print(mode, cls.__name__, k, repr(lbl.text()), lbl.property("class"), "token live=", green,
                  "palette fg=", lbl.palette().color(QtGui.QPalette.WindowText).name(), "green px:", cols.get(green.lower(), 0), top)
        p.stop()
