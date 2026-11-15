import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"; sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtTest
app = QtWidgets.QApplication([]); pump = lambda ms=200: QtTest.QTest.qWait(ms)
import txguard, engagement
txguard.reset_session(); engagement.reset()
from palisade_qt.shell import PalisadeHub
from palisade_qt.forge import EngagementCard
hub = PalisadeHub(demo=False, mode="dark"); hub.resize(1280, 720); hub.show(); pump()
go = hub.open_callsign if hasattr(hub, "open_callsign") else hub.show_page
go("FORGE"); pump(200)
c = hub.pages["FORGE"].findChildren(EngagementCard)[0]
engagement.start("N", "A", ["can0"], "op")
go("RECON"); pump(700); go("FORGE"); pump(700)
print("leave to RECON and return (engine active): card=%r btn=%s" % (c.state.text(), c._btn.isEnabled()))
hub.close()
