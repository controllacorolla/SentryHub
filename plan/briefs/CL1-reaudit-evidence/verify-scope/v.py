import os, sys, gc, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = os.environ["HOME"]
sys.dont_write_bytecode = True
ROOT, DEMO = sys.argv[1], sys.argv[2] == "demo"
sys.path.insert(0, ROOT); os.chdir(ROOT)
from PySide6 import QtWidgets, QtTest
app = QtWidgets.QApplication([])
pump = QtTest.QTest.qWait
from palisade_qt import shell, recon, eventbus
hub = shell.PalisadeHub(demo=DEMO, mode="dark")
if hasattr(hub, "_list_children"): hub._list_children = lambda: []
def dets():
    return sorted(o.kind if hasattr(o, "kind") else "?" for o in gc.get_objects()
                  if isinstance(o, recon.DetectorWorker) and o.isRunning())
hub.show(); pump(300)
print("pages:", list(shell.QT_PAGES))
print("at launch:", dets())
for cs in ("RECON", "SWEEP", "OPS", "PRISM"):
    try:
        hub.open_callsign(cs); pump(400)
        print("after open", cs, ":", dets())
    except Exception as e:
        print("open", cs, "failed:", repr(e)[:100])
hub.close(); pump(300)
print("after close:", dets())
