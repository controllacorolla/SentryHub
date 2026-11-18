import os, sys, time, tempfile, json
WT = sys.argv[1]; OUT = sys.argv[2]; sys.path[:0] = [WT]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication([])
import suite
from palisade_qt import theme
from palisade_qt.prism import PrismApp
from palisade_qt.prowl import ProwlApp
def pump(ms):
    t = time.time()
    while time.time() - t < ms/1000: app.processEvents(); time.sleep(0.01)
W, H = 1152, 632    # 1280 - 128 px rail; 720 - top strip(40) - status/footer(~48)
for mode in ("dark", "sun"):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
    for engine in ("fast",):
        json.dump({"engine": engine}, open(os.path.join(suite.CFG, "prowl_scan.json"), "w"))
        for cls, nm in ((PrismApp, "prism"), (ProwlApp, "prowl")):
            for demo in (True, False):
                p = cls(demo=demo, mode=mode); p.resize(W, H); p.show(); p.set_active(True) if hasattr(p, "set_active") else None
                if hasattr(p, "start"):
                    try: p.start()
                    except Exception as e: print("start", e)
                pump(2500 if demo else 500)
                fn = os.path.join(OUT, "rail_%s_%s_%s.png" % (nm, mode, "demo" if demo else "live"))
                p.grab().save(fn)
                print(fn, "size", p.size().toTuple(), "minHint", p.minimumSizeHint().toTuple())
                p.close(); pump(300)
