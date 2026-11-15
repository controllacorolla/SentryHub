"""Measure RENDERED font pixel sizes of every visible text widget, elision, h-scroll, strip worst case."""
import os, sys, time, json, collections
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = "/Users/daltonhayes/SentryHub"
sys.path[:0] = [REPO]
os.chdir(REPO)
mode, run = sys.argv[1], sys.argv[2]
from PySide6 import QtWidgets, QtGui, QtCore
app = QtWidgets.QApplication([])
from palisade_qt import theme, ops
from palisade_qt.shell import PalisadeHub
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
import pyqtgraph as pg

def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents(); time.sleep(0.01)

hub = PalisadeHub(demo=(run == "demo"), mode=mode); hub.resize(1280, 720); hub.show(); pump(400)
small = collections.defaultdict(set)   # (cls, text) -> views
elided = collections.defaultdict(set)
hscroll = {}
clipped = collections.defaultdict(set)

def visible_text_widgets(root):
    for w in root.findChildren(QtWidgets.QWidget):
        if not w.isVisibleTo(hub) or w.width() <= 1 or w.height() <= 1:
            continue
        yield w

def check(view):
    hub.resize(1280, 720); pump(150)
    for w in visible_text_widgets(hub):
        px = QtGui.QFontInfo(w.font()).pixelSize()
        txt = None
        if isinstance(w, QtWidgets.QLabel) and w.text() and not w.pixmap():
            txt = w.text()
            fm = w.fontMetrics()
            if not w.wordWrap() and "<" not in txt:
                avail = w.contentsRect().width()
                if fm.horizontalAdvance(txt) > avail + 1:
                    elided[(type(w).__name__, txt[:50], w.objectName() or w.property("class"))].add(view)
                if fm.height() > w.contentsRect().height() + 2:
                    clipped[("vclip", txt[:40])].add(view)
        elif isinstance(w, QtWidgets.QAbstractButton) and w.text():
            txt = w.text()
            if w.fontMetrics().horizontalAdvance(txt) > w.width():
                elided[("button", txt[:50], "")].add(view)
        elif isinstance(w, QtWidgets.QHeaderView):
            txt = "<header>"
        elif isinstance(w, QtWidgets.QComboBox):
            txt = "<combo:%s>" % w.currentText()[:30]
        elif isinstance(w, QtWidgets.QAbstractItemView):
            txt = "<items>"
            if isinstance(w, QtWidgets.QTableView) and w.horizontalScrollBar().isVisible():
                hscroll[view + ":" + (w.parent().objectName() or str(id(w)))] = [
                    w.horizontalScrollBar().maximum(), w.viewport().width()]
        if txt is not None and px < 16:
            small[(type(w).__name__, str(txt)[:40], px)].add(view)
    # pyqtgraph axis tick fonts
    for gv in hub.findChildren(pg.GraphicsView):
        if not gv.isVisibleTo(hub):
            continue
        for item in gv.scene().items():
            if isinstance(item, pg.AxisItem) and item.isVisible():
                f = item.style.get("tickFont") or item.font() if hasattr(item, "font") else None
                if f is not None:
                    px = QtGui.QFontInfo(f).pixelSize()
                    if px < 16:
                        small[("AxisItem", item.orientation, px)].add(view)
            if isinstance(item, pg.TextItem) and item.isVisible():
                f = item.textItem.font()
                px = QtGui.QFontInfo(f).pixelSize()
                if px < 16:
                    small[("TextItem", item.textItem.toPlainText()[:30], px)].add(view)

for name, _l in ops.CALLSIGNS:
    hub.open_callsign(name); pump(500 if run == "demo" else 250)
    page = hub.pages[name]
    tabs = page.subtabs() or [None]
    for t in tabs:
        if t: page.switch_subtab(t); pump(400 if run == "demo" else 200)
        check("%s/%s" % (name, t))
for p in ("radios", "engagement", "alerts", "keys", "palette"):
    hub.open_panel(p); pump(150); check("panel:" + p); hub.open_panel(p); pump(50)

# strip worst case: DEMO, owner longest label, PERMITTED, longest scope, 99+ alerts
from palisade_qt import radio_arbiter
longest = max(radio_arbiter.OWNER_LABELS.values(), key=len)
hub.topbar.set_state("DEMO", ("HELD", longest), "PERMITTED", ("ACTIVE", "999 targets", "x" * 40))
hub.topbar.set_alerts(150); pump(100)
strip = {k: [s.painted_text(), s.text(), s.value.width()] for k, s in hub.topbar.slots.items()}
strip["alerts"] = hub.topbar.alerts.painted_text()
strip["strip_min_w"] = hub.topbar.minimumSizeHint().width()
strip["hub_min"] = [hub.minimumSizeHint().width(), hub.minimumSizeHint().height()]
strip["hub_size"] = [hub.width(), hub.height()]
strip["nav_painted"] = {k: (v.call.text(), v.call.fontMetrics().horizontalAdvance(v.call.text()) <= v.call.width())
                        for k, v in hub.topbar.nav_keys.items()}
strip["longest_owner"] = longest

out = {"mode": mode, "run": run,
       "small_text": sorted([[*k, sorted(v)[:4], len(v)] for k, v in small.items()], key=str),
       "elided": sorted([[*k, sorted(v)[:4], len(v)] for k, v in elided.items()], key=str),
       "hscroll": hscroll, "strip_worst": strip}
print(json.dumps(out, indent=1, default=str))
hub.close(); pump(100)
