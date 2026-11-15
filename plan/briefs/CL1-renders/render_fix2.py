import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
out = sys.argv[1]
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
for mode, demo, tag in (("dark", False, "live"), ("sun", False, "live"), ("sun", True, "stress"), ("dark", True, "stress")):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=demo, mode=mode); hub.resize(1280, 720); hub.show(); pump(300)
    hub.open_callsign("ATLAS"); pump(2500 if demo else 400)
    if tag == "stress":
        a = hub.pages["ATLAS:inner"]
        a._contacts["LONG"] = {"id": "LONG", "label": "OP RID-1581F5FAB2C3D4E5F60718", "kind": "aircraft", "x": 1.0, "y": 1.0,
                               "alt": 123456, "spd": 1, "severity": "info", "_ts": time.time() + 3600, "rng": 1.4, "brg": 45.0}
        a._render(); a.feed.move_cursor(0); pump(200)
        hub.state.stop()
        hub.topbar.set_state("DEMO", ("HELD", "PROWL SC"), "PERMITTED", ("ACTIVE", "999 targets", "x")); hub.topbar.set_alerts(150)
        pump(200)
    pm = hub.grab(); pm.save("%s/atlas_%s_%s.png" % (out, mode, tag))
    print(mode, tag, pm.width(), pm.height(), "strip min", hub.topbar.minimumSizeHint().width(), "hub min", hub.minimumSizeHint().width())
    hub.close(); pump(100)
