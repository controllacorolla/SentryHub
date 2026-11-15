import sys
from common import *
from palisade_qt.kit.feed import FeedTable
demo = sys.argv[1] == "demo"
h = hub(demo=demo)
vs = views(h)
for name, tab in vs:
    h.open_callsign(name, tab); pump(900)
pump(2500)
rep = []
for name, tab in vs:
    h.open_callsign(name, tab); pump(150)
    pg = h.current_page()
    tabs = [t for t in pg.findChildren(FeedTable) if t.isVisible()]
    rows = [(len(t.model.rows)) for t in tabs]
    demo_lbls = sorted({l.text()[:40] for l in pg.findChildren(QtWidgets.QLabel) if l.isVisible() and "DEMO" in l.text().upper()})
    st = pg.page_status() if hasattr(pg, "page_status") else {}
    rep.append((name, tab, rows, st, demo_lbls))
    # multi-table Up/Down check
    if len(tabs) >= 2 and all(len(t.model.rows) >= 2 for t in tabs[:2]):
        tabs[1].view.setFocus(); tabs[1].view.selectRow(0); app.processEvents()
        r0, r1 = tabs[0].view.currentIndex().row(), tabs[1].view.currentIndex().row()
        key(h, QtCore.Qt.Key_Down); app.processEvents()
        print("  MULTI %s/%s: focus 2nd table, Down -> first %d->%d second %d->%d focus_on_first=%s" % (
            name, tab, r0, tabs[0].view.currentIndex().row(), r1, tabs[1].view.currentIndex().row(), tabs[0].view.hasFocus()))
for r in rep: print(r)
print("store alerts", len(h.alerts.items), sorted({(a["source"], a["text"][:50]) for a in h.alerts.items})[:12])
print("bus contacts", len(eventbus.bus.recent(1000, "contact")), "decodes", len(eventbus.bus.recent(1000, "decode")))
# border
img = h.grab().toImage()
def px(x, y): c = img.pixelColor(x, y); return (c.red(), c.green(), c.blue())
dpr = img.devicePixelRatio()
print("demo_border", h.demo_border is not None and h.demo_border.isVisible(), h.demo_border.geometry() if h.demo_border else None, "central", h.centralWidget().size())
if h.demo_border:
    cw = h.centralWidget()
    print("border on top:", cw.children()[-1] is h.demo_border, [type(c).__name__ for c in cw.children()[-4:]])
    for p in ("radios", "alerts", "palette"):
        h.open_panel(p); pump(30)
        o = h.top_overlay(); g = o.geometry()
        print(p, "overlay geom", g, "inside border:", g.left() >= 6 and g.top() >= 6 and g.right() <= cw.width()-6 and g.bottom() <= cw.height()-6)
        h.open_panel(p)
    h.panic_banner  # not triggered
print("mode slot:", h.topbar.slots["mode"].text() if hasattr(h.topbar.slots["mode"], "text") else None)
h.close(); pump(200)
