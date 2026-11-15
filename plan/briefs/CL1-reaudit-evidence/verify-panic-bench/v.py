import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"]="offscreen"; sys.dont_write_bytecode=True
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtTest
app=QtWidgets.QApplication([])
import txguard, engagement, bench
bench.TX_LOG=os.path.join(tempfile.mkdtemp(),"tx.log")
txguard.reset_session(); engagement.reset()
from palisade_qt.shell import PalisadeHub
from palisade_qt import chrome
hub=PalisadeHub(demo=False, mode="dark")
hub._list_children=lambda: []; hub._kill=lambda p: True
hub.resize(1280,720); hub.show(); QtTest.QTest.qWait(200)
hub.open_callsign("BENCH"); QtTest.QTest.qWait(300)
b=hub.pages["BENCH"]; slot=hub.topbar.slots["tx"]
def st(tag):
    print("%-28s slot=%r value=%r gate=%r tx_btn=%s ack=%s permits=%s armed=%s"%(tag, slot.text(), slot.value.text(), b.gate.text(), b.tx_btn.isEnabled(), b.ack.isChecked(), chrome.tx_permit_sources(), txguard.is_armed()))
st("initial")
b.ack.setChecked(True); hub.state.poll(); st("ack ticked")
# real key press path
from PySide6 import QtCore
import palisade_qt.shell as sh
print("PANIC_KEY", sh.PANIC_KEY)
QtTest.QTest.keyClick(QtWidgets.QApplication.focusWidget() or hub, QtCore.Qt.Key_F12); QtTest.QTest.qWait(50)
print("banner:", hub.panic_banner.isVisible(), repr(hub.panic_banner.text()))
st("after F12 PANIC")
print("preflight:", bench.preflight(b._settings(), b._band_freq()))
QtTest.QTest.qWait(1500); st("1.5s later (3 polls)")
ran=[]; iq=os.path.join(tempfile.mkdtemp(),"x.iq"); open(iq,"wb").write(b"\0"*16)
s=b._settings(); s["iq_file"]=iq
print("engine transmit w/ fake runner:", bench.transmit(s, run=lambda a: ran.append(a)), "runner called", bool(ran))
import unittest.mock as um
with um.patch.object(bench, "transmit", wraps=bench.transmit) as tm:
    b.tx_btn.click(); print("UI KEY TX ->", tm.call_count, bench.transmit(b._settings(), run=lambda a: ran.append(a)))
st("after UI KEY TX click")
# navigate away and back
hub.open_callsign("PRISM"); QtTest.QTest.qWait(200); st("on PRISM")
hub.open_callsign("BENCH"); QtTest.QTest.qWait(200); st("back on BENCH")
b2=hub.pages["BENCH"]; print("same page obj:", b2 is b)
b.band.setCurrentIndex((b.band.currentIndex()+1)%b.band.count()); hub.state.poll(); st("band touched")
hub.close()
