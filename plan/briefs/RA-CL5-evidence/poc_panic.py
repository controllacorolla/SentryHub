"""PANIC vs a radio holder, through the real PalisadeHub.panic(): after PANIC, is the dongle free
(arbiter FREE, no decoder process, no zombie) and does it stay free?"""
import sys

import _harness as H
from palisade_qt import radio_arbiter
from palisade_qt import shell

radio_arbiter._make_lease = lambda name: H.FakeLease(name)
A = radio_arbiter.arbiter
which = sys.argv[1] if len(sys.argv) > 1 else "babel"

hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720)
hub.show()
H.pump(0.5)
if which == "babel":
    hub.open_callsign("BABEL")
    H.pump(0.5)
    page = hub.pages["BABEL"]
    page.mode_combo.setCurrentText("AIS")
    H.pump(0.5)
    page.run_btn.setChecked(True)
elif which == "nwr":
    hub.open_callsign("PROWL")
    H.pump(0.5)
    page = hub.pages["PROWL"]
    page.switch_subtab("NWR")
H.pump(3.0)
H.log("BEFORE PANIC arbiter=%s children=%s" % (A.state(), H.children()))
did = hub.panic()
H.log("PANIC banner: %s" % " · ".join(did))
for _ in range(8):
    H.pump(0.5)
    H.log("AFTER PANIC arbiter=%s children=%s chip=%r" % (
        A.state(), H.children(), getattr(page, "_last_status", {}).get("sdr")))
hub.close()
H.pump(1.0)
H.log("AFTER CLOSE arbiter=%s children=%s" % (A.state(), H.children()))
