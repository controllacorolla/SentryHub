import os, sys, time
HERE=os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["HOME"]=os.path.join(HERE,"home")
sys.dont_write_bytecode=True; sys.path.insert(0, sys.argv[1])
import subprocess
def _blk(*a,**k): raise OSError("blocked")
subprocess.Popen=_blk; subprocess.run=_blk
from PySide6 import QtWidgets
app=QtWidgets.QApplication([])
from palisade_qt import theme, eventbus
from palisade_qt.shell import PalisadeHub
app.setStyleSheet(theme.qss("dark"))
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.01)
try: hub=PalisadeHub(demo=False, mode="dark")
except TypeError: hub=PalisadeHub(demo=False)
hub.resize(1280,720); hub.show(); pump(200)
for i in range(7): eventbus.bus.publish(eventbus.alert("SWEEP","alert %d"%i,severity="alert"))
pump(100)
a=getattr(hub,"alerts",None)
if a is not None and hasattr(a,"items"):
    print("branch: kept", len(a.items), "unacked", sum(not x["acked"] for x in a.items))
    a.items[0] and None
else:
    from palisade_qt import ops
    import inspect
    src=inspect.getsource(ops)
    i=src.find("[:3]"); print("main: ops has 3-cap slice:", i>=0, repr(src[max(0,i-120):i+10]))
os._exit(0)
