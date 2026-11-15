import sys, os, collections
sys.path.insert(0, sys.argv[1]); os.chdir(sys.argv[1])
sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
mode = sys.argv[2]; demo = sys.argv[3] == "demo"
import test_cl1_screen as T
from PySide6 import QtWidgets
hub = T._hub(mode, demo=demo)
T._pump(600)
sizes = collections.defaultdict(set)
rows = set(); hdr = set(); ctl = collections.defaultdict(set)
def scan(root, where):
    for w in root.findChildren(QtWidgets.QWidget):
        if not w.isVisible(): continue
        px = T._px(w)
        cls = (w.property("class") or "")
        txt = ""
        if isinstance(w, QtWidgets.QLabel):
            if not w.text().strip(): continue
            txt = w.text()[:24]
        elif isinstance(w, QtWidgets.QAbstractButton): txt = w.text()[:24]
        elif not isinstance(w, (QtWidgets.QLineEdit, QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QTableView, QtWidgets.QHeaderView, QtWidgets.QPlainTextEdit, QtWidgets.QListWidget, QtWidgets.QTabBar)):
            continue
        sizes[px].add((type(w).__name__, cls, txt if px < 16 else ""))
        if isinstance(w, QtWidgets.QTableView):
            vh = w.verticalHeader(); rows.add(vh.defaultSectionSize())
            m = w.model()
            if m:
                for r in range(min(m.rowCount(), 50)): rows.add(w.rowHeight(r))
            hdr.add(w.horizontalHeader().height())
        if isinstance(w, (QtWidgets.QCheckBox, QtWidgets.QPushButton, QtWidgets.QToolButton, QtWidgets.QComboBox, QtWidgets.QLineEdit, QtWidgets.QSlider)):
            ctl[type(w).__name__].add(w.height())
n = 0
for name, tab in T._every_view(hub):
    n += 1; scan(hub, (name, tab))
for panel in ("radios", "engagement", "alerts", "keys", "palette"):
    hub.open_panel(panel); T._pump(40); scan(hub.top_overlay(), panel); hub.open_panel(panel)
print("views", n, "mode", mode, "demo", demo)
for px in sorted(sizes):
    items = sizes[px]
    classes = collections.Counter((t, c) for t, c, _ in items)
    print(px, "px:", dict(classes) if px >= 16 else "")
    if px < 16:
        byc = collections.defaultdict(list)
        for t, c, x in sorted(items): byc[(t, c)].append(x)
        for k, v in byc.items(): print("    ", k, len(v), v[:8])
print("rows", rows, "hdr", hdr)
print("ctl", {k: sorted(v) for k, v in ctl.items()})
print("minhint", hub.minimumSizeHint())
hub.close(); T._pump(150)
