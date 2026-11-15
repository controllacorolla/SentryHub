import os, sys, tempfile
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import panels
root = tempfile.mkdtemp()
d = os.path.join(root, "bus/usb/devices/1-0"); os.makedirs(d); os.makedirs(os.path.join(root, "class/rfkill"))
open(os.path.join(d, "idVendor"), "wb").write(b"\xff\xfe\n"); open(os.path.join(d, "idProduct"), "w").write("2838\n")
p = panels.RadiosPanel(sys_root=root)
try:
    p.open(); print("open ok")
except Exception as e:
    print("open RAISED", type(e).__name__)
os.remove(os.path.join(d, "idVendor")); open(os.path.join(d, "idVendor"), "w").write("0bda\n")
p.refresh()
t = p.table
m = t.model
print("rows with empty rfkill dir:", m.rowCount() if m else "?")
