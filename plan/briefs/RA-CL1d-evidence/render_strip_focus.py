"""RA-CL1d: full 1280x720 SUN/demo worst-case strip with focus on each key (current page = OPS, then
focus on the current-page key), plus a 2x stack of the nav-key region for eyeballing. usage: <repo> <out>"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "tests")); os.makedirs(OUT, exist_ok=True)
from PySide6 import QtCore, QtGui
from test_cl1_screen import _app, _pump, _hub
_app()
from palisade_qt import chrome
for mode in ("sun", "dark"):
    h = _hub(mode=mode, demo=True); h.resize(1280, 720); h.state.stop()
    h.topbar.set_state("DEMO", ("HELD", "PROWL SC"), "PERMITTED", ("ACTIVE", chrome.scope_summary(["h"] * 100000), "x"))
    h.topbar.set_alerts(150); _pump(150)
    keys = h.topbar.nav_keys; xs = [k.mapTo(h, QtCore.QPoint(0, 0)).x() for k in keys.values()]
    x0, x1 = min(xs) - 4, max(k.mapTo(h, QtCore.QPoint(0, 0)).x() + k.width() for k in keys.values()) + 4
    crops = []
    for page in ("OPS", "SYSTEM"):
        h.topbar.set_active_page(page)
        for name, k in keys.items():
            k.setFocus(); _pump(40)
            img = h.grab(); assert (img.width(), img.height()) == (1280, 720)
            img.save("%s/%s_demo_page%s_focus%s.png" % (OUT, mode, page, name))
            crops.append(h.grab(QtCore.QRect(x0, 0, x1 - x0, 44)).toImage())
    W, H = crops[0].width() * 2, crops[0].height() * 2
    out = QtGui.QImage(W, (H + 6) * len(crops), QtGui.QImage.Format_RGB32); out.fill(0xFF808080)
    p = QtGui.QPainter(out)
    for i, c in enumerate(crops):
        p.drawImage(0, i * (H + 6), c.scaled(W, H))
    p.end(); out.save("%s/%s_navkeys_focus_stack_2x.png" % (OUT, mode))
    print(mode, "hub_min", h.minimumSizeHint().width(), "strip_min", h.topbar.minimumSizeHint().width())
    h.close(); _pump(150)
