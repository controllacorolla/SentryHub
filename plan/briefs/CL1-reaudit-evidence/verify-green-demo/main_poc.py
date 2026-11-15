import sys, time
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme
import palisade_qt; print(palisade_qt.__file__)
from palisade_qt.prowl import ProwlApp
from palisade_qt.kit.topbar import TopBar
theme.apply(app, "dark")
green = theme.tokens("dark")["live"].lower()
tb = TopBar(); tb.resize(1280, 40); tb.show()
p = ProwlApp(demo=True, mode="dark"); p.resize(1280, 480); p.show()
p.attach_topbar(tb); p.set_active(True); p.start()
try: p.mode_combo.setCurrentText("FM") if hasattr(p, "mode_combo") else None
except Exception as e: print(e)
c = tb.chips["sdr"]
for sub in ("SCAN", "FM", "NWR"):
    for attr in ("switch_subtab", "_set_mode", "_set_submode", "set_submode"):
        if hasattr(p, attr):
            try: getattr(p, attr)(sub); break
            except Exception as e: print(attr, e)
    t = time.time(); seen = {}
    while time.time() - t < 4:
        app.processEvents(); time.sleep(0.01)
        k = (c.text(), c.property("class")); seen[k] = seen.get(k, 0) + 1
    img = c.grab().toImage(); g = 0
    for x in range(img.width()):
        for y in range(img.height()):
            g += img.pixelColor(x, y).name() == green
    print(sub, seen, "final", c.text(), "green_px", g)
p.stop()
