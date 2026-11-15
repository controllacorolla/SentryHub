import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme, radio_arbiter
from palisade_qt.shell import PalisadeHub
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
longest = max(radio_arbiter.OWNER_LABELS.values(), key=len)
print("longest owner label", repr(longest))
for mode in ("sun", "dark"):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
    h = PalisadeHub(demo=True, mode=mode); h.resize(1280, 720); h.show(); pump(300); h.state.stop()
    for scope in ("999 targets", "1000 targets", "12345 targets"):
        for owner in ("PROWL SC", longest):
            h.topbar.set_state("DEMO", ("HELD", owner), "PERMITTED", ("ACTIVE", scope, "x")); h.topbar.set_alerts(150); pump(80)
            print(mode, scope, owner, "hub_min", h.minimumSizeHint().width(), "hub_w", h.width(), "strip_w", h.topbar.width(),
                  "panic_btn_right", max((w.mapTo(h, w.rect().topRight()).x() for w in h.topbar.findChildren(QtWidgets.QPushButton) if w.isVisible()), default=None))
    h.close(); pump(100)
