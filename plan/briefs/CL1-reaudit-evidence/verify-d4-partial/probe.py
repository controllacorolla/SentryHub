import sys, os
sys.path.insert(0, sys.argv[1])
os.chdir(sys.argv[1])
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication([])
from palisade_qt import radio_arbiter as ra
from palisade_qt.kit import topbar as tb
import inspect
print("OWNER_LABELS", ra.OWNER_LABELS)
import engagement
from palisade_qt import chrome
t = tb.TopBar(mode="dark", nav=())
for scope in (["10.0.0.*"], ["192.168.1.0/24"], ["AA:BB:CC:DD:EE:FF"], ["corp-wifi","10.1.1.1"]):
    try: engagement.end()
    except Exception as e: pass
    engagement.start("Op", "ROE-1", scope, "N0CALL")
    eng = chrome.read_engagement()
    t.set_state("LIVE", ("FREE",""), "OFF", eng)
    s = t.slots["engagement"]
    print("ENG scope", scope, "| text()=", repr(s.text()), "| painted label=", repr(s.value.text()))
try: engagement.end()
except Exception: pass
for owner, label in ra.OWNER_LABELS.items():
    t.set_state("LIVE", ("HELD", label), "OFF", ("NONE","",""))
    s = t.slots["radio"]
    print("RADIO", owner, "| text()=", repr(s.text()), "| painted=", repr(s.value.text()))
for tx in ("OFF","PERMITTED","ARMED"):
    t.set_state("LIVE", ("FREE",""), tx, ("NONE","",""))
    print("TX", tx, "painted=", repr(t.slots["tx"].value.text()))
