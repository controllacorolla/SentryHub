import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.dont_write_bytecode=True
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore
from PySide6.QtTest import QTest
app=QtWidgets.QApplication([])
from palisade_qt import theme, shell, chrome
import txguard, engagement, bench
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.005)
hub=shell.PalisadeHub(demo=False, mode="dark"); hub.resize(1280,720); hub.show(); pump(200)
hub._list_children=lambda: []; hub._kill=lambda p: True
calls=[]
real_transmit=bench.transmit
bench.transmit=lambda s, run=None: (calls.append(dict(s)) or real_transmit(s, run=lambda argv: calls.append(argv)))
hub.open_callsign("BENCH"); pump(200)
b=hub.pages.get("BENCH:inner", hub.pages["BENCH"])
if not hasattr(b,"ack"): b=hub.page_app("BENCH")
def snap(tag):
    print(tag, "| btn", b.tx_btn.isEnabled(), "| gate", repr(b.gate.text()), "| slot", hub.topbar.slots["tx"].text(),
          "| permits", chrome.tx_permit_sources(), "| armed", txguard.is_armed(),
          "| preflight", bench.preflight(b._settings(), b._band_freq()))
snap("initial")
b.ack.setChecked(True); hub.state.poll(); pump(50)
snap("ack ticked")
QTest.keyClick(QtWidgets.QApplication.focusWidget() or hub, QtCore.Qt.Key_F12); pump(100)
snap("after F12 +100ms")
print("banner:", hub.panic_banner.text())
pump(1500)
snap("after +1.6s (3 polls)")
# does the key button still act?
b.tx_btn.click(); pump(50)
print("click KEY after panic -> transmit called with:", [c if isinstance(c,list) else {k:c[k] for k in ("tx_enabled","bench_conducted_ack","freq_hz","iq_file")} for c in calls])
print("card:", b.card.__dict__.get("_rows", None))
# with an IQ file present, would the runner be invoked?
iq=os.path.join(os.environ["HOME"],"x.iq"); open(iq,"wb").write(b"\0"*16)
s=b._settings(); s["iq_file"]=iq
os.environ["HOME_DATA_GUARD"]="1"
bench.append_log=lambda rec, path=None: None
argvs=[]; print("transmit w/ iq, fake runner:", real_transmit(s, run=lambda a: argvs.append(a)), argvs)
# recovery: toggling band re-reports
b.band.setCurrentIndex(1); hub.state.poll(); pump(50); snap("band changed")
hub.close(); pump(300)
