"""ATLAS single-layer views, LIVE (not demo), NET offline, default layers: the empty states must
say what each view's own source is doing (RA-UIPd N1). usage: render_views_live.py <repo> <out>"""
import os, sys, time, tempfile
os.environ["HOME"] = tempfile.mkdtemp()
repo, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, repo); os.chdir(repo)
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme, eventbus
from palisade_qt.shell import PalisadeHub
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, "dark"); app.setStyleSheet(theme.qss("dark"))
eventbus.set_home((39.7, -104.9), "settings")
hub = PalisadeHub(demo=False, mode="dark"); hub.resize(1280, 720); hub.show(); pump(2500)
hub.open_callsign("ATLAS"); pump(2500)
atlas = hub.page_app("ATLAS")
for v in ("DRONES", "DF", "SONDE", "SEA"):
    atlas.set_view(v); pump(1200)
    hub.grab().save("%s/views_%s_live_dark_uipd.png" % (out, v.lower()))
print("ok", sorted(atlas._layers))
