import sys
sys.path.insert(0, "/private/tmp/claude-501/-Users-daltonhayes-SentryHub/f893c360-320b-4c7c-9dc4-e3ab8ef11055/scratchpad/reaudit/arch")
from common import *
h = hub(demo=False)
def sample(label, n=30):
    seen=set(); vis=set()
    for i in range(n):
        pump(200)
        p=h.current_page(); seen.add(p.page_status().get("sdr"))
        for l in h.findChildren(QtWidgets.QFrame, "page_status"):
            if l.isVisible():
                for q in l.findChildren(QtWidgets.QLabel):
                    if q.isVisible() and q.text(): vis.add(q.text())
    print(label, "page_status:", seen, "| visible row labels:", vis)
h.open_callsign("RECON","WIFI"); sample("RECON/WIFI",40)
p=h.current_page(); print(" current subtab:", p.current_subtab(), type(p).__name__)
h.open_callsign("SWEEP"); sample("SWEEP")
h.open_callsign("SYSTEM","SETTINGS"); pump(1500); sample("SYSTEM/SETTINGS",10)
h.open_callsign("FORGE","SERIAL"); sample("FORGE/SERIAL")
h.close(); pump(200)
