import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = sys.argv[1]
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_cl1_screen as T
from PySide6 import QtWidgets
hub = T._hub("dark", False); T._pump(200)
print("stack x=%d w=%d  hub min=%s" % (hub.stack.x(), hub.stack.width(), hub.minimumSizeHint().toTuple()))
bench = hub.page_app("BENCH"); T._pump(80); bench.ack.setChecked(False); bench._refresh_gate(); T._pump(80)
from palisade_qt.kit import DetailCard
for c in hub.findChildren(DetailCard):
    if not c.isVisible(): continue
    for l in c.findChildren(QtWidgets.QLabel):
        t = l.text()
        if l.isVisible() and len(t) > 40:
            print("  value wrap=%s have_w=%d text_w=%d h=%d :: %s" % (l.wordWrap(), l.width(), l.fontMetrics().horizontalAdvance(t), l.height(), t[:50]))
print("hub", hub.width(), hub.minimumSizeHint().width())
hub.close(); T._pump(100)
