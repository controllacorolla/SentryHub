import sys, os, tempfile, pathlib
sys.path.insert(0, os.getcwd())
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import radios, panels
t = pathlib.Path(tempfile.mkdtemp())
def mk(i, name, typ, soft, hard):
    d = t/"class"/"rfkill"/("rfkill%d"%i); d.mkdir(parents=True)
    for k,v in (("name",name),("type",typ),("soft",soft),("hard",hard)):
        if v is not None: (d/k).write_text(v+"\n")
mk(0,"phy0","wlan","0","1"); mk(1,"hci0","bluetooth",None,None)
(t/"bus"/"usb"/"devices").mkdir(parents=True)
for r in radios.inventory(sys_root=str(t)): print(r)
p = panels.RadiosPanel("dark", sys_root=str(t)); p.refresh()
m = p.table.model
print("panel rows", m.rowCount(), [[m.data(m.index(r,c)) for c in range(m.columnCount())] for r in range(m.rowCount())])
print("picker", [p.device_pick.itemText(i) for i in range(p.device_pick.count())])
