"""CL1-fix3 renders (1280x720). usage: python render.py <repo> <outdir>
Strip worst case (DEMO/LIVE, PROWL SC, PERMITTED, 999+ tgts, 99+) with focus on each nav key, in
dark + sun; a 4x zoom of the strip for each; ATLAS with a selected contact, then after it is lost."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "tests"))
os.makedirs(OUT, exist_ok=True)
from PySide6 import QtCore
from test_cl1_screen import _app, _pump, _hub
_app()
from palisade_qt import chrome
log = []
for mode in ("dark", "sun"):
    for demo in (True, False):
        h = _hub(mode=mode, demo=demo); h.resize(1280, 720); h.state.stop()
        h.topbar.set_state("DEMO" if demo else "LIVE", ("HELD", "PROWL SC"), "PERMITTED",
                           ("ACTIVE", chrome.scope_summary(["h"] * 100000), "x"))
        h.topbar.set_alerts(150); _pump(150)
        tag = "%s_%s" % (mode, "demo" if demo else "live")
        for name, k in h.topbar.nav_keys.items():
            k.setFocus(); _pump(40)
            img = h.grab()
            assert img.width() == 1280 and img.height() == 720, (img.width(), img.height())
            img.save("%s/strip_%s_worst_focus%s.png" % (OUT, tag, name))
            h.grab(QtCore.QRect(0, 0, 1280, 44)).scaled(1280 * 4 // 2, 44 * 4 // 2).save(
                "%s/zoom_strip_%s_focus%s.png" % (OUT, tag, name))
        log.append("%s hub_min=%d strip_min=%d" % (tag, h.minimumSizeHint().width(),
                                                    h.topbar.minimumSizeHint().width()))
        h.close(); _pump(150)
for mode in ("dark", "sun"):
    h = _hub(mode=mode, demo=True); h.resize(1280, 720)
    h.open_callsign("ATLAS"); _pump(400)
    a = h.pages["ATLAS:inner"]; a._timer.stop(); a._render(); _pump(100)
    a.feed.view.setCurrentIndex(a.feed.model.index(0, 0)); _pump(100)
    sel = a._selected
    h.grab().save("%s/atlas_%s_selected.png" % (OUT, mode))
    a._contacts.pop(sel, None); a._render(); _pump(150)
    h.grab().save("%s/atlas_%s_lost.png" % (OUT, mode))
    log.append("atlas %s selected=%s -> hero=%r sub=%r" % (mode, sel, a.detail.hero.text(), a.detail.sub.text()))
    h.close(); _pump(150)
print("\n".join(log))
