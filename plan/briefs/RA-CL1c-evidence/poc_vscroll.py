import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.kit.feed import FeedTable
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("sun"))
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
ft = FeedTable([("label", "CONTACT"), ("rng", "NM"), ("alt", "ALT")], fit_viewport=True)
ft.resize(440, 300); ft.show(); pump(100)
ft.model.set_rows([{"_id": i, "label": "N%d" % i, "rng": "1", "alt": "45000"} for i in range(2)]); pump(200)
hdr = ft.view.horizontalHeader()
def st(): return sum(hdr.sectionSize(i) for i in range(3)), ft.view.viewport().width(), ft.view.verticalScrollBar().isVisible(), ft.view.horizontalScrollBar().maximum()
print("2 rows", st())
ft.model.set_rows([{"_id": i, "label": "N%d" % i, "rng": "1", "alt": "45000"} for i in range(40)]); pump(300)
print("40 rows", st())
ft.resize(400, 300); pump(300)        # splitter / window narrows, no model change
print("narrowed", st())
