import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.dont_write_bytecode = True
ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
from PySide6 import QtWidgets, QtCore, QtTest
app = QtWidgets.QApplication([])
pump = QtTest.QTest.qWait
from palisade_qt.shell import PalisadeHub
from palisade_qt import recon
hub = PalisadeHub(demo=True, mode="dark")
if hasattr(hub, "_list_children"):
    hub._list_children = lambda: []
hub.show(); pump(100)
hub.open_callsign("RECON"); pump(400)
def dets():
    return [w for w in app.allWidgets() if False] or [o for o in __import__("gc").get_objects() if isinstance(o, recon.DetectorWorker) and o.isRunning()]
print("DetectorWorkers running after opening RECON only:", len(dets()))
if "SWEEP" in getattr(__import__("palisade_qt.shell").shell, "QT_PAGES"):
    hub.open_callsign("SWEEP"); pump(400)
    print("DetectorWorkers running after opening SWEEP:", len(dets()))
hub.close()
