import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtCore, QtTest
app = QtWidgets.QApplication([])
pump = QtTest.QTest.qWait
import txguard, engagement, bench
bench.TX_LOG = os.path.join(tempfile.mkdtemp(), "tx.log")
txguard.reset_session(); engagement.reset()
from palisade_qt.shell import PalisadeHub
from palisade_qt import chrome
hub = PalisadeHub(demo=False, mode="dark")
hub._list_children = lambda: []; hub._kill = lambda p: True
hub.resize(1280, 720); hub.show(); pump(200)
b = hub.page_app("BENCH"); pump(200)
slot = lambda: hub.topbar.slots["tx"].text()
print("DEFAULTS iq_file:", repr(bench.DEFAULTS.get("iq_file")))
print("0 initial slot", slot(), "btn", b.tx_btn.isEnabled())
b.ack.setChecked(True); hub.state.poll()
print("1 ack on: slot", slot(), "gate", b.gate.text(), "btn", b.tx_btn.isEnabled())
ev = __import__("PySide6.QtGui").QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_F12, QtCore.Qt.NoModifier)
hub.handle_key(ev); pump(50)
print("2 after F12: banner", hub.panic_banner.text())
print("  slot", slot(), "| gate", b.gate.text(), "| btn", b.tx_btn.isEnabled(), "| ack", b.ack.isChecked(), "| permits", chrome.tx_permit_sources(), "| page visible", b.isVisible())
print("  rows:", [(l.text()) for l in b.card.findChildren(QtWidgets.QLabel)][:8])
print("  preflight", bench.preflight(b._settings(), b._band_freq()))
iq = os.path.join(tempfile.mkdtemp(), "x.iq"); open(iq, "wb").write(b"\0"*16)
ran = []; st = b._settings(); st["iq_file"] = iq
print("  engine transmit w/ fake runner:", bench.transmit(st, run=lambda a: ran.append(a))[0], "runner called", len(ran))
b.tx_btn.click(); pump(20)
print("  UI click KEY TX -> hero:", [l.text() for l in b.card.findChildren(QtWidgets.QLabel) if l.text() in ("KEYED","BLOCKED")], "rows", [l.text() for l in b.card.findChildren(QtWidgets.QLabel) if "IQ" in l.text() or "transmitting" in l.text()])
pump(1200); print("3 1.2s later slot", slot())
b.band.setCurrentIndex(1); hub.state.poll()
print("4 after band change: slot", slot())
hub.close(); pump(150)
