import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["HOME"]=os.path.join(os.path.dirname(os.path.abspath(__file__)),"home")
sys.dont_write_bytecode=True
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtCore
app=QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.kit import tiles
def _no(*a,**k): raise OSError("blocked")
tiles.urlopen=_no
from palisade_qt.shell import PalisadeHub
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete); time.sleep(0.01)
hub=PalisadeHub(demo=False, mode="dark"); hub.resize(1280,720); hub.show(); pump(300)
print("OPS  min", hub.minimumSizeHint().toTuple(), "size", hub.size().toTuple())
hub.open_callsign("BENCH"); pump(300)
hub.resize(1280,720); pump(100)
print("BENCH min", hub.minimumSizeHint().toTuple(), "size after resize(1280,720)", hub.size().toTuple())
hub.open_callsign("OPS"); pump(100); hub.resize(1280,720); pump(50)
print("back on OPS size", hub.size().toTuple())
hub.close(); pump(200)
