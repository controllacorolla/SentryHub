"""CL5 renders: PROWL / BABEL (PROWL DECODE) / ATLAS / RADIOS panel at 1280x720, dark + sun, live.
usage: python render_cl5.py <repo> <outdir> <tag>"""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PALISADE_OFFLINE"] = "1"
repo, out, tag = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo); os.chdir(repo)
os.makedirs(out, exist_ok=True)
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
for mode in ("dark", "sun"):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=False, mode=mode); hub.resize(1280, 720); hub.show(); pump(400)
    for name, act in (("prowl", lambda: hub.open_callsign("PROWL")),
                      ("babel", lambda: hub.open_callsign("BABEL")),
                      ("atlas", lambda: hub.open_callsign("ATLAS")),
                      ("radios", lambda: hub.open_panel("radios"))):
        try:
            act(); pump(1200)
            pm = hub.grab(); p = "%s/%s_%s_live_%s.png" % (out, name, mode, tag); pm.save(p)
            print(p, pm.width(), pm.height())
        except Exception as e:
            print("FAIL", name, mode, e)
    hub.close(); pump(150)
