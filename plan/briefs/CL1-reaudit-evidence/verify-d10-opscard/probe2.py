import os,sys
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0,"/Users/daltonhayes/SentryHub/tests"); sys.path.insert(0,"/Users/daltonhayes/SentryHub")
sys.dont_write_bytecode=True
import test_cl1_screen as t
from palisade_qt import eventbus
from PySide6 import QtWidgets
hub=t._hub(demo=False)
hub.show(); t._pump(100)
for i in range(7): eventbus.bus.publish(eventbus.alert("TEST","alert %d"%i,severity="warn"))
t._pump(300)
c=hub.ops.card_alert
for l in c.findChildren(QtWidgets.QLabel):
    print(repr(l.text()), "visible" if l.isVisible() else "hidden", l.geometry().getRect(), "inlayout", c.body.indexOf(l) if hasattr(c.body,'indexOf') else '?')
print("card geom", c.geometry().getRect())
hub.close(); t._pump(150)
