"""PANIC raced against every radio holder, through the real hub.panic(). Per iteration: the lease
acquire takes a random 0-0.6 s (readsb stop), the holder is (re)started, PANIC lands after a random
0-1.2 s (so it hits ACQUIRING, mid-spawn and steady state), then we watch 2.5 s. VIOLATION if at
any sample after PANIC the arbiter is not FREE, or any decoder process (or zombie) is a child."""
import random
import sys
import time
import _harness as H
from PySide6 import QtCore
from palisade_qt import radio_arbiter, shell

which = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 12
random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 5)
DELAY = [0.0]


def mk(name):
    time.sleep(DELAY[0])
    return H.FakeLease(name)


radio_arbiter._make_lease = mk
A = radio_arbiter.arbiter
hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720); hub.show(); H.pump(0.5)

from palisade_qt.prowl import ProwlApp  # noqa: E402
from palisade_qt.babel import BabelApp  # noqa: E402
from palisade_qt.atlas import AtlasApp  # noqa: E402
from palisade_qt.prism import PrismApp  # noqa: E402

if which in ("babel_ais", "babel_pocsag", "sstv"):
    hub.open_callsign("BABEL"); H.pump(0.5)
    app = hub.pages["PROWL"].child(BabelApp)
    app.mode_combo.setCurrentText({"babel_ais": "AIS", "babel_pocsag": "POCSAG", "sstv": "SSTV"}[which])
    H.pump(0.5)

    def start():
        if app.run_btn.isChecked():
            app.run_btn.setChecked(False); H.pump(0.2)
        app.run_btn.setChecked(True)
elif which in ("nwr", "fm", "scan"):
    hub.open_callsign("PROWL"); H.pump(0.5)
    page = hub.pages["PROWL"]
    app = page.child(ProwlApp)
    page.switch_subtab(which.upper()); H.pump(0.3)

    def start():
        app._resume_radio()
elif which == "prism":
    hub.open_callsign("PRISM"); H.pump(0.5)
    app = hub.pages["PRISM"] if isinstance(hub.pages["PRISM"], PrismApp) else hub.pages["PRISM"].child(PrismApp)

    def start():
        app.primary_action()
elif which in ("atlas_ais", "atlas_aprs", "atlas_ais_hidden"):
    hub.open_callsign("ATLAS"); H.pump(0.5)
    app = hub.pages["ATLAS"].child(AtlasApp)
    kind = "station" if which == "atlas_aprs" else "vessel"

    def start():
        b = app._layer_btns[kind]
        if not b.isChecked():
            hub.show_page("ATLAS"); H.pump(0.1)
            b.click()
        if which.endswith("_hidden"):
            H.pump(1.0); hub.show_page("OPS")   # ATLAS hidden: its worker is paused
H.pump(1.0)
bad = 0
for k in range(N):
    DELAY[0] = random.uniform(0.0, 0.6)
    start()
    at = random.uniform(0.0, 1.2)
    H.pump(at)
    before = (A.state(), H.children())
    did = hub.panic()
    viol = []
    for i in range(10):
        H.pump(0.25)
        st, kids = A.state(), [c for c in H.children() if not c.endswith(":pgrep(Z)")]
        if st[0] != "FREE" or kids:
            viol.append("t+%.2f %s %s" % ((i + 1) * 0.25, st, kids))
    bad += bool(viol)
    H.log("iter %2d acquire=%.2fs panic@%.2fs before=%s banner=[%s] -> %s" % (
        k, DELAY[0], at, before, " · ".join(d for d in did if "radio" in d or "child" in d),
        ("VIOLATION " + " | ".join(viol[:3])) if viol else "clean"))
    hub._show_banner("")
H.log("RESULT %s: %d of %d iterations violated (arbiter not FREE or decoder alive after PANIC)"
      % (which, bad, N))
hub.close(); H.pump(1.5)
