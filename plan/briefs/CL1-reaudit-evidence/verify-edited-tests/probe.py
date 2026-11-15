import sys, os
sys.path.insert(0, os.getcwd())
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
def pump(ms):
    loop = QtCore.QEventLoop(); QtCore.QTimer.singleShot(ms, loop.quit); loop.exec()
from palisade_qt.shell import PalisadeHub, QT_PAGES
hub = PalisadeHub(demo=True, mode="dark"); hub.show()
import gc
names = sys.argv[1].split(",")
watched = []
for n in names:
    try:
        p = hub.page_app(n)
    except AttributeError:
        hub.open_callsign(n); p = hub.pages[n]
    pump(250)
    w = p._worker
    print(n, type(p).__name__, "_worker=", type(w).__name__ if w else None, "_workers=", [type(x).__name__ for x in getattr(p, "_workers", [])])
    if w is not None: watched.append(n)
allthreads = [o for o in gc.get_objects() if isinstance(o, QtCore.QThread) and o.isRunning()]
print("watched by soak:", len(watched), watched, "| running QThreads:", len(allthreads), sorted(type(t).__name__ for t in allthreads))
hub.close(); pump(400)
print("running after close:", len([o for o in gc.get_objects() if isinstance(o, QtCore.QThread) and o.isRunning()]))
