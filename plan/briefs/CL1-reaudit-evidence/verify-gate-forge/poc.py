import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.dont_write_bytecode = True
ROOT = sys.argv[1]; sys.path.insert(0, ROOT)
from PySide6 import QtWidgets, QtTest
app = QtWidgets.QApplication([])
pump = lambda ms=200: QtTest.QTest.qWait(ms)
import txguard, engagement
txguard.reset_session(); engagement.reset()
from palisade_qt.shell import PalisadeHub
from palisade_qt.forge import EngagementCard, ReplayTxCard, ForgeApp
from palisade_qt.app import PalisadeApp
import palisade_qt.forge as F
print("forge module:", F.__file__)
hub = PalisadeHub(demo=False, mode="dark")
if hasattr(hub, "_list_children"):
    hub._list_children = lambda: []; hub._kill = lambda pid: True
hub.resize(1280, 720); hub.show(); pump()
hub.open_callsign("FORGE") if hasattr(hub, "open_callsign") else hub.show_page("FORGE"); pump(300)
forge = hub.pages["FORGE"]
print("override on_gate_changed:", getattr(ForgeApp, "on_gate_changed", None) is not getattr(PalisadeApp, "on_gate_changed", None), "| base has hook:", hasattr(PalisadeApp, "on_gate_changed"))
cards = forge.findChildren(EngagementCard); rc = forge.findChildren(ReplayTxCard)[0]
c = cards[0]
def slot():
    try: return hub.topbar.slots["engagement"].text()
    except Exception as e: return "n/a(%s)" % type(e).__name__
def show(tag):
    print("%-34s engine_active=%s slot=%r\n    card=%r btn=%s inputs=%s" % (tag, engagement.is_active(), slot(), c.state.text(), c._btn.isEnabled(), [e.isEnabled() for e in c._inputs.values()]))
show("initial")
if hasattr(hub, "engage_panel"):
    hub.open_panel("engagement"); p = hub.engage_panel
    p.eng_operator.setText("op"); p.eng_name.setText("N"); p.eng_auth.setText("A"); p.eng_scope.setText("can0")
    p._activate()
else:
    print(" (no E panel on this rev: start via engine)", engagement.start("N", "A", ["can0"], "op"))
    if hasattr(hub, "state"): hub.state.poll()
pump(1500); show("after ACTIVATE +1.5s")
# user closes the panel and looks at FORGE without switching sub-tab
if hasattr(hub, "close_panel"): hub.close_panel()
pump(1500); show("panel closed +1.5s")
forge.refresh_gates(); show("after manual refresh_gates")
# stale-enabled direction: end the engagement
if hasattr(hub, "panic"):
    print(" panic ->", hub.panic())
else:
    engagement.end()
    if hasattr(hub, "state"): hub.state.poll()
pump(1500); show("after PANIC/END +1.5s")
# does pressing the stale-enabled button emit anything? engine must deny
for e in c._inputs.values(): e.setText("can0")
c._btn.click(); pump(50)
print(" click on stale card -> result=%r" % c.result.text())
# TX card staleness
print(" replay card:", repr(rc.state.text()), "tx state:", F._tx_state())
hub.close()
