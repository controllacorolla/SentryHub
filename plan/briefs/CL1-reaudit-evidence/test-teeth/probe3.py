"""Which QThreads does the soak / per-callsign leak test actually watch, vs. which exist?"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = sys.argv[1]
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_palisade_qt as T
from PySide6 import QtCore
T._app()
from palisade_qt.shell import PalisadeHub
hub = PalisadeHub(demo=True, mode="dark")
hub.show()
watched = []
names = getattr(T, "ALL_CALLSIGNS")
for name in names:
    if hasattr(hub, "page_app"):
        w = hub.page_app(name)._worker
        T._pump(250)
    else:
        hub.open_callsign(name)
        T._pump(250)
        w = hub.pages[name]._worker
    watched.append((name, type(w).__name__ if w is not None else None))
print("watched:", watched)
allthreads = [o for o in hub.findChildren(QtCore.QThread)]
import gc
live = [o for o in gc.get_objects() if isinstance(o, QtCore.QThread) and o.isRunning()]
print("running QThreads (%d):" % len(live), sorted(type(o).__name__ for o in live))
watched_ids = set()
hub.close(); T._pump(400)
live2 = [o for o in gc.get_objects() if isinstance(o, QtCore.QThread) and o.isRunning()]
print("running after close:", sorted(type(o).__name__ for o in live2))
