import os, sys
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0,"/Users/daltonhayes/SentryHub"); sys.path.insert(0,"/Users/daltonhayes/SentryHub/tests")
import test_cl1_screen as T
from PySide6 import QtWidgets
import engagement, txguard
from palisade_qt import chrome
engagement.reset(); txguard.reset_session(); chrome.reset()
hub=T._hub(demo=False)
engagement.start("NightWatch","ROE-42",["10.0.0.*","Corp-*","AA:BB:CC:*"],"op1"); hub.state.poll()
print("pages:",list(hub.pages) if hasattr(hub.pages,"keys") else hub.pages)
hub.show_page("RECON"); T._pump(300)
pg=hub.page_app("RECON") if callable(hub.page_app) else None
print("RECON app:",type(pg).__name__,"gate_banner:",hasattr(pg,"gate_banner"))
W=("NightWatch","op1","ROE-42","ENGAGEMENT","authorized scope")
for l in hub.findChildren(QtWidgets.QLabel):
    if l.isVisible() and any(w in l.text() for w in W): print(" visible label:",repr(l.text()))
hub.grab().save(sys.argv[1]+"/recon.png")
hub.close(); T._pump(100); engagement.reset()
