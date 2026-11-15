import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
WT = sys.argv[1]; OUT = sys.argv[2]
sys.path.insert(0, WT)
from PySide6 import QtWidgets, QtGui, QtCore
app = QtWidgets.QApplication([])
for f in ("IBMPlexMono-Regular.ttf", "IBMPlexMono-SemiBold.ttf", "IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf"):
    QtGui.QFontDatabase.addApplicationFont(os.path.join(WT, "fonts", f))
import engagement
from palisade_qt import theme, chrome
from palisade_qt.shell import PalisadeHub
theme.set_app_font(app)
engagement._profile_operator = lambda: "OPERATOR-ONE"
def pump(ms=120):
    end = time.time() + ms / 1000
    while time.time() < end: app.processEvents(); time.sleep(0.01)
def clipped(w):
    bad = []
    for lab in w.findChildren(QtWidgets.QLabel):
        if not lab.isVisible() or lab.wordWrap() or not lab.text(): continue
        need = lab.fontMetrics().horizontalAdvance(lab.text()) + lab.contentsMargins().left() + lab.contentsMargins().right()
        if need > lab.contentsRect().width() + 1 and "…" not in lab.text():
            bad.append((lab.text()[:40], need, lab.contentsRect().width()))
    return bad
for mode in ("dark", "sun"):
    app.setStyleSheet(theme.qss(mode)); theme.set_palette(app, mode)
    for state in ("single", "many", "expired", "unknown"):
        engagement.reset()
        orig = engagement.info
        if state == "single":
            engagement.start("ROE-ACME-Q4", "SOW-2026-114", ["10.0.0.5"])
        elif state == "many":
            engagement.start("ROE-ACME-Q4", "SOW-2026-114", ["10.0.%d.%d" % (i // 250, i % 250) for i in range(999)])
        elif state == "expired":
            engagement.start("ROE-ACME-Q4", "SOW-2026-114", ["10.0.0.5", "10.0.0.6"])
            engagement.info = lambda o=orig: dict(o(), expired=True, active=False, open=True)
        else:
            engagement.info = lambda: (_ for _ in ()).throw(RuntimeError("store unreadable"))
        hub = PalisadeHub(demo=False, mode=mode); hub.resize(1280, 720); hub.show()
        hub.state.poll(); pump()
        hub.open_panel("engagement"); pump(200)
        slot = hub.topbar.slots["engagement"].text()
        img = hub.grab()
        assert img.width() == 1280 and img.height() == 720, (img.width(), img.height())
        p = os.path.join(OUT, "eng_%s_%s_live.png" % (state, mode)); img.save(p)
        print(mode, state, "slot=%r" % slot, "minW=%d" % hub.minimumSizeHint().width(),
              "clipped=%s" % clipped(hub), p)
        engagement.info = orig
        hub.close(); pump(50)
engagement.reset()
