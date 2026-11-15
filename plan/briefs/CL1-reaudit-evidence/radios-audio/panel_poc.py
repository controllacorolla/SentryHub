import os, sys, tempfile, pathlib, time
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore, QtGui
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from palisade_qt import panels, radio_arbiter as ra, theme
ra._make_lease = lambda n: None
T = pathlib.Path(tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(__file__))))
def dev(root, n, vid, pid):
    d = root/"bus/usb/devices"/n; d.mkdir(parents=True); (d/"idVendor").write_text(vid); (d/"idProduct").write_text(pid)
def rf(root, n, typ, name, soft, hard):
    d = root/"class/rfkill"/n; d.mkdir(parents=True)
    for k, v in (("type", typ), ("name", name), ("soft", soft), ("hard", hard)): (d/k).write_text(v)
def pump(ms=50):
    t = time.time() + ms/1000
    while time.time() < t: app.processEvents()
def dump(p, tag):
    m = p.table.model
    print("--", tag)
    for r in range(m.rowCount()):
        print("   ", [m.data(m.index(r, c)) for c in range(m.columnCount())])
    print("    picker:", [p.device_pick.itemText(i) for i in range(p.device_pick.count())], "enabled", p.device_pick.isEnabled())
    print("    hero:", p.holder.hero.text(), "| btn enabled", p.takeover_btn.isEnabled())
host = QtWidgets.QWidget(); host.resize(1280, 720); host.setStyleSheet(theme.qss("dark")); host.show()
# 1. no sysfs at all (dev Mac / unknown)
p = panels.RadiosPanel("dark", host, sys_root=str(T/"nope")); p.open(); pump()
dump(p, "no sysfs"); p.grab().save("radios_nosysfs.png")
# elision check
v = p.table.view
for c in range(p.table.model.columnCount()):
    print("    col", c, "width", v.columnWidth(c), "hint", v.sizeHintForColumn(c))
p.stop(); p.hide()
# 2. staleness: open with RTL + wifi ON, then unplug + hard block while open
root = T/"live"; dev(root, "1-1", "0bda", "2838"); rf(root, "rfkill0", "wlan", "phy0", "0", "0")
p = panels.RadiosPanel("dark", host, sys_root=str(root)); p.open(); pump()
dump(p, "open: RTL plugged, wifi ON")
import shutil; shutil.rmtree(root/"bus/usb/devices/1-1"); (root/"class/rfkill/rfkill0/soft").write_text("1"); (root/"class/rfkill/rfkill0/hard").write_text("1")
pump(3500)
dump(p, "3.5 s after unplug + rfkill block, panel still open (visible=%s)" % p.isVisible())
timers = [t for t in p.findChildren(QtCore.QTimer)]
print("    QTimers owned by panel:", len(timers))
p.refresh(); dump(p, "after manual refresh()")
p.grab().save("radios_blocked.png")
for c in range(p.table.model.columnCount()):
    print("    col", c, "width", v.columnWidth(c) if False else p.table.view.columnWidth(c), "hint", p.table.view.sizeHintForColumn(c))
# 3. arbiter holds but dongle absent
ra.arbiter.request("ATLAS-APRS"); pump()
dump(p, "arbiter HELD ATLAS-APRS with dongle ABSENT")
ra.arbiter.release("ATLAS-APRS"); pump(); p.stop(); p.hide()
# 4. empty rfkill dir + unreadable usb
root = T/"empty"; (root/"bus/usb/devices").mkdir(parents=True); (root/"class/rfkill").mkdir(parents=True)
p = panels.RadiosPanel("dark", host, sys_root=str(root)); p.open(); pump(); dump(p, "empty sysfs dirs"); p.grab().save("radios_empty.png"); p.stop(); p.hide()
# 5. multi
root = T/"multi"; dev(root, "1-1", "1d50", "6089"); dev(root, "1-2", "0bda", "2838"); (root/"class/rfkill").mkdir(parents=True)
p = panels.RadiosPanel("dark", host, sys_root=str(root)); ra.arbiter.request("PRISM"); p.open(); pump(); dump(p, "HackRF+RTL, arbiter owner PRISM"); p.grab().save("radios_multi.png"); ra.arbiter.release("PRISM"); p.stop()
