import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["HOME"] = os.path.join(HERE, "home")
sys.dont_write_bytecode = True
tree, tag, mode = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, tree); os.chdir(tree)
from PySide6 import QtWidgets, QtCore, QtGui
app = QtWidgets.QApplication([])
from palisade_qt import theme
try:
    from palisade_qt.kit import tiles
    def _no(*a, **k): raise OSError("blocked")
    tiles.urlopen = _no
except Exception as e: print("tiles", e)
from palisade_qt.shell import PalisadeHub
if hasattr(theme, "load_fonts"): theme.load_fonts()
if hasattr(theme, "set_app_font"): theme.set_app_font(app)
app.setStyleSheet(theme.qss(mode))
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
hub = PalisadeHub(demo=True, mode=mode); hub.resize(1280, 720); hub.show(); pump(300)
def report(name):
    for v in hub.findChildren(QtWidgets.QTableView):
        if not v.isVisible() or not v.isVisibleTo(hub): continue
        m = v.model()
        if not m.rowCount(): continue
        fm = v.fontMetrics(); opt = QtWidgets.QStyleOptionViewItem()
        out = []
        for c in range(m.columnCount()):
            head = m.headerData(c, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole)
            texts = [str(m.data(m.index(r, c)) or "") for r in range(min(m.rowCount(), 30))]
            need = max(fm.horizontalAdvance(t) for t in texts)
            hint = v.sizeHintForColumn(c)   # Qt's own content width incl. margins
            w = v.columnWidth(c)
            # what Qt would paint: elide to the cell's text rect (margin = style focus frame +1 each side)
            mg = v.style().pixelMetric(QtWidgets.QStyle.PM_FocusFrameHMargin, None, v) + 1
            longest = max(texts, key=fm.horizontalAdvance)
            shown = fm.elidedText(longest, QtCore.Qt.ElideRight, w - 2 * mg)
            flag = "ELIDED" if shown != longest else "ok"
            out.append("%-9s col=%3d text=%3d hint=%3d %s shown=%r" % (head, w, need, hint, flag, shown[:28]))
        print("[%s %s] %s rows=%d fontpx=%d viewW=%d" % (tag, mode, name, m.rowCount(), v.font().pixelSize(), v.viewport().width()))
        for o in out: print("     ", o)
    hub.grab().save(os.path.join(HERE, "out", "%s_%s_%s.png" % (tag, mode, name.replace("/", "-").replace(" ", "_"))))
for spec in sys.argv[4:]:
    cs, _, sub = spec.partition(":")
    hub.open_callsign(cs); pump(300)
    p = hub.pages.get(cs)
    if sub:
        if hasattr(p, "switch_subtab"): p.switch_subtab(sub)
        elif hasattr(p, "_switch_submode"): p._switch_submode(sub)
    pump(6000)
    report(spec)
hub.close(); pump(300)
