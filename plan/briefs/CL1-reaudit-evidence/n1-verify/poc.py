import os, sys, shutil, tempfile, time
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtCore, QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import panels, shell
root = tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(__file__)))
u = os.path.join(root, "bus/usb/devices/1-1"); os.makedirs(u)
open(u+"/idVendor","w").write("0bda\n"); open(u+"/idProduct","w").write("2838\n")
r = os.path.join(root, "class/rfkill/rfkill0"); os.makedirs(r)
for k,v in (("type","wlan"),("name","phy0"),("soft","0"),("hard","0")): open(r+"/"+k,"w").write(v+"\n")
host = QtWidgets.QWidget(); host.resize(1280,720); host.show()
p = panels.RadiosPanel("dark", host, sys_root=root)
def rows(): return [[p.table.model.data(p.table.model.index(i,c)) for c in range(4)] for i in range(p.table.model.rowCount())]
p.open(); print("visible", p.isVisible()); print("t0", rows())
shutil.rmtree(u); open(r+"/soft","w").write("1\n"); open(r+"/hard","w").write("1\n")
end = time.time()+4
while time.time()<end: app.processEvents(); time.sleep(0.02)
print("t+4s", rows())
print("timers owned by panel:", len(p.findChildren(QtCore.QTimer)))
p.refresh(); print("after manual refresh", rows())
# Full hub: does any shell timer refresh the panel?
p.stop()
hub = shell.HubWindow() if hasattr(shell,"HubWindow") else None
print("hub class", [n for n in dir(shell) if "Hub" in n or "Shell" in n])
