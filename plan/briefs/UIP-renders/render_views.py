"""ATLAS views + SETTINGS location renders (1280x720, dark, demo). usage: render_views.py <repo> <out>"""
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
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, "dark"); app.setStyleSheet(theme.qss("dark"))
hub = PalisadeHub(demo=True, mode="dark"); hub.resize(1280, 720); hub.show(); pump(3000)
hub.open_callsign("ATLAS"); pump(5000)
atlas = hub.page_app("ATLAS")
for v in ("ALL", "AIR", "SEA", "DRONES", "SONDE"):
    atlas.set_view(v)
    if v == "DRONES":
        atlas.on_status({"rid_note": {"text":
                         "Remote-ID: ACTIVE BLE scan — passive needs bluetoothd --experimental (see SYSTEM › DOCTOR)"}})
    pump(1500)
    hub.grab().save("%s/views_%s_dark_after.png" % (out, v.lower()))
hub.open_callsign("SYSTEM"); pump(1200)
hub.grab().save(out + "/settings_location_dark_after.png")
print("ok")
