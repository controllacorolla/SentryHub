import os,sys
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0,"tests"); sys.path.insert(0,".")
import test_cl1_screen as t
from palisade_qt import eventbus
from PySide6 import QtWidgets
hub=t._hub(demo=False)
for i in range(7): eventbus.bus.publish(eventbus.alert("TEST","alert %d"%i,severity="warn"))
t._pump(60)
c=hub.ops.card_alert
labs=[l.text() for l in c.findChildren(QtWidgets.QLabel)]
print("store",len(hub.alerts.items),"card labels:",labs)
hub.close(); t._pump(150)
