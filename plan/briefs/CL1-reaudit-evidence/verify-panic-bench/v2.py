import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["PALISADE_OFFLINE"]="1"
sys.path.insert(0,"/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
app=QtWidgets.QApplication([])
import engagement, txguard, bench as benchmod
from palisade_qt import chrome, shell, radio_arbiter as ra
ra._make_lease=lambda name: None
ran=[]
import suite as S
S.run=lambda *a, **k: ran.append(a)   # belt and braces: never spawn
benchmod.append_log=lambda rec: ran.append(("log",rec))
engagement.reset(); txguard.reset_session(); chrome.reset()
h=shell.PalisadeHub(demo=False); h.show(); app.processEvents(); h._list_children=lambda: []
b=h.page_app("BENCH"); b.ack.setChecked(True); h.state.poll(); h.panic(); app.processEvents()
b.tx_btn.click(); app.processEvents()
print("slot:", h.topbar.slots["tx"].text(), "| iq_file in settings:", repr(b._settings()["iq_file"]))
print("card hero/rows:", b.card.findChildren(QtWidgets.QLabel) and [l.text() for l in b.card.findChildren(QtWidgets.QLabel)])
print("runner/log calls:", ran)
h.close()
