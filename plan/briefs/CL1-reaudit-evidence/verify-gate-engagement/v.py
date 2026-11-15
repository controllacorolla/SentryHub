import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
sys.path.insert(0, "/Users/daltonhayes/SentryHub/tests")
import test_cl1_screen as T
from PySide6 import QtWidgets, QtCore
import engagement
app = T._app()
hub = T._hub(demo=False)
pump = T._pump
hub.resize(1280,720); hub.show(); pump(100)
hub.open_callsign("RECON"); recon = hub.pages["RECON"]
gated = [w for w in recon.findChildren(QtWidgets.QFrame) if type(w).__name__=="GatedTool"]
print("gated cards:", len(gated), [ [b.text() for b in g._btns] for g in gated])
print("no-eng: btn enabled:", [any(b.isEnabled() for b in g._btns) for g in gated], "|", gated[0].state.text())
# force-click with no engagement
g = recon.net_gated; g.target.setEnabled(True); g.target.setText("8.8.8.8")
for b in g._btns: b.setEnabled(True)
g._btns[0].click(); print("force-click no-eng:", g.result.text())
# empty activate
hub.topbar.slots["engagement"].clicked.emit(); pump(40)
p = hub.engage_panel
for f in (p.eng_name,p.eng_auth,p.eng_scope,p.eng_operator): f.setText("")
p._activate(); print("empty activate:", p.eng_msg.text(), engagement.is_active())
for scope in ("10.0.0.*", "*", "10.0.0.5, 10.0.0.6, corp-wifi", "AA:BB:CC:*"):
    p.eng_name.setText("NightWatch"); p.eng_auth.setText("ROE-42"); p.eng_scope.setText(scope); p.eng_operator.setText("N0CALL")
    p._activate(); pump(40); hub.state.poll(); pump(20)
    s = hub.topbar.slots["engagement"]
    print("scope=%r -> painted=%r full=%r tip=%r width=%d" % (scope, s.value.text(), s.text(), s.toolTip(), s.width()))
    print("   card state:", recon.net_gated.state.text())
p.eng_scope.setText("10.0.0.*"); p._activate(); pump(40)
g.target.setText("8.8.8.8"); g._btns[0].click(); print("out of scope:", g.result.text())
# visible text on RECON page mentioning name/operator/auth?
p.hide() if hasattr(p,'hide') else None
try: hub.close_panel()
except Exception as e: print("close_panel:", e)
pump(40)
vis = [w.text() for w in hub.findChildren(QtWidgets.QLabel) if w.isVisible() and w.text()]
for needle in ("NightWatch","N0CALL","ROE-42","10.0.0.*"):
    print("visible outside panel:", needle, [t for t in vis if needle in t][:4])
print("panel visible:", p.isVisible())
hub.grab().save(os.path.dirname(__file__)+"/recon_active.png")
engagement.end(); hub.state.poll(); pump(40)
print("after end:", recon.net_gated.state.text(), [b.isEnabled() for b in g._btns], hub.topbar.slots["engagement"].value.text())
hub.close(); pump(150)
