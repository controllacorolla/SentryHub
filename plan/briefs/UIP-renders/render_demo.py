import os, sys, time, tempfile
os.environ["HOME"] = tempfile.mkdtemp()
repo, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, repo); os.chdir(repo)
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
import netpolicy; netpolicy.set_mode("ONLINE")
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.01)
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app,"dark"); app.setStyleSheet(theme.qss("dark"))
hub=PalisadeHub(demo=True, mode="dark"); hub.resize(1280,720); hub.show(); pump(8000)
hub.grab().save(out+"/demo_ops_dark_after.png")
hub.open_callsign("ATLAS"); pump(6000); hub.grab().save(out+"/demo_atlas_dark_after.png")
print("ok")
