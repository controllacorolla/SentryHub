import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
out = sys.argv[1]
for mode in ("sun", "dark"):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=True, mode=mode); hub.resize(1280, 720); hub.show()
    for _ in range(40): app.processEvents(); time.sleep(0.01)
    for label, eng in (("active", ("ACTIVE", "10.0.0.*", "acme")), ("none", ("NONE", "", "")), ("scopeNONE", ("ACTIVE", "NONE", "x"))):
        hub.state.stop()
        hub.topbar.set_state("DEMO", ("HELD", "PROWL SC"), "PERMITTED", eng); hub.topbar.set_alerts(7)
        for _ in range(20): app.processEvents(); time.sleep(0.01)
        pm = hub.grab(); pm.copy(0, 0, 1280, 48).scaled(2560, 96).save("%s/strip_%s_%s.png" % (out, mode, label))
    hub.close()
