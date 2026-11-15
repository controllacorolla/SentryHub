import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
WT = sys.argv[1]; LOAD = sys.argv[2] == "plex"
sys.path.insert(0, WT); sys.path.insert(0, os.path.join(WT, "tests"))
from PySide6 import QtWidgets, QtGui
app = QtWidgets.QApplication([])
if LOAD:
    for f in ("IBMPlexMono-Regular.ttf", "IBMPlexMono-SemiBold.ttf", "IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf"):
        assert QtGui.QFontDatabase.addApplicationFont(os.path.join(WT, "fonts", f)) >= 0
import engagement
from palisade_qt import theme, chrome, radio_arbiter
from palisade_qt.shell import PalisadeHub
theme.load_fonts(); theme.set_app_font(app)
print("resolved font:", QtGui.QFontInfo(app.font()).family(), "plex loaded" if LOAD else "no app font")
longest = max(radio_arbiter.OWNER_LABELS.values(), key=len)
engagement._profile_operator = lambda: "OP"
for mode in ("dark", "light", "sun"):
    for demo in (False, True):
        app.setStyleSheet(theme.qss(mode))
        hub = PalisadeHub(demo=demo, mode=mode); hub.resize(1280, 720); hub.show(); hub.state.stop()
        engagement.reset(); engagement.start("t", "ROE-1", ["10.0.%d.%d" % (i // 250, i % 250) for i in range(999)])
        worst = 0
        for tx in ("PERMITTED", "UNLOCKED", "UNKNOWN"):
            for eng in (chrome.read_engagement(), ("EXPIRED", "", "t"), ("UNKNOWN", "", "")):
                hub.topbar.set_state("DEMO" if demo else "LIVE", ("HELD", longest), tx, eng)
                hub.topbar.set_alerts(150); hub.topbar.nav_keys["SYSTEM"].setFocus(); app.processEvents()
                w = hub.minimumSizeHint().width(); worst = max(worst, w)
        print(mode, "demo" if demo else "live", "worst minimumSizeHint =", worst)
        hub.close(); engagement.reset()
