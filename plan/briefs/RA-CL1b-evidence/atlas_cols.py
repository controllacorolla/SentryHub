import os, sys, time, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
out = {}
for mode in ("light", "sun", "dark"):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=True, mode=mode); hub.resize(1280, 720); hub.show()
    hub.open_callsign("ATLAS")
    t = time.time()
    while time.time() - t < 2.5: app.processEvents(); time.sleep(0.01)
    a = hub.pages["ATLAS:inner"]; v = a.feed.view; h = v.horizontalHeader()
    cols = [(a.feed.model.columns[i][1], h.sectionPosition(i), h.sectionSize(i)) for i in range(h.count())]
    fm = v.fontMetrics()
    alts = [r.get("alt") for r in a.feed.model.rows]
    widest_alt = max((fm.horizontalAdvance(str(x)) for x in alts), default=0)
    last = cols[-1]
    out[mode] = {"viewport_w": v.viewport().width(), "cols": cols, "hscroll_max": v.horizontalScrollBar().maximum(),
                 "hscroll_visible": v.horizontalScrollBar().isVisible(),
                 "alt_visible_px": max(0, v.viewport().width() - last[1]), "widest_alt_px": widest_alt,
                 "sample_alts": alts[:6]}
    hub.close()
print(json.dumps(out, indent=1))
