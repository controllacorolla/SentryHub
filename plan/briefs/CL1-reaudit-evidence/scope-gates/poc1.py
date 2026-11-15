import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.dont_write_bytecode = True
ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
from PySide6 import QtWidgets, QtCore, QtTest
app = QtWidgets.QApplication([])
def pump(ms=200):
    QtTest.QTest.qWait(ms)
import txguard, engagement, bench
bench.TX_LOG = os.path.join(tempfile.mkdtemp(), "bench_tx.log")
txguard.reset_session(); engagement.reset()
from palisade_qt.shell import PalisadeHub
from palisade_qt import chrome
hub = PalisadeHub(demo=False, mode="dark")
hub._list_children = lambda: []
hub._kill = lambda pid: True
hub.resize(1280, 720); hub.show(); pump()

print("== A. engagement slot vs main's GateBanner")
ok, why = engagement.start("NightWatch", "ROE-42", ["10.0.0.*", "Corp-*", "AA:BB:CC:*"], "op1")
hub.state.poll(); pump(50)
s = hub.topbar.slots["engagement"]
print(" slot visible text:", repr(s.value.text()), "| full (tooltip only):", repr(s.text()))
hub.open_callsign("RECON"); pump(300)
recon = hub.pages["RECON"]
print(" RECON has gate_banner:", hasattr(recon, "gate_banner"))
labels = [l.text() for l in recon.findChildren(QtWidgets.QLabel) if l.isVisible()]
print(" any visible RECON label naming engagement/operator/auth:",
      [t for t in labels if "NightWatch" in t or "op1" in t or "ROE-42" in t])
engagement.start("X", "A", ["*"], "o"); hub.state.poll()
print(" wildcard scope ['*'] slot visible text:", repr(s.value.text()))
engagement.end(); hub.state.poll()

print("== B. PANIC vs BENCH conducted permit")
hub.open_callsign("BENCH"); pump(300)
b = hub.pages["BENCH"]
b.ack.setChecked(True); hub.state.poll(); pump(50)
print(" before PANIC: slot=%r bench.gate=%r tx_btn=%s armed=%s" % (hub.topbar.slots["tx"].text(), b.gate.text(), b.tx_btn.isEnabled(), txguard.is_armed()))
did = hub.panic(); pump(50)
print(" panic said:", did)
print(" after PANIC: slot=%r bench.gate=%r tx_btn=%s ack=%s" % (hub.topbar.slots["tx"].text(), b.gate.text(), b.tx_btn.isEnabled(), b.ack.isChecked()))
print(" engine gate after PANIC: bench.preflight ->", bench.preflight(b._settings(), b._band_freq()))
iq = os.path.join(tempfile.mkdtemp(), "x.iq"); open(iq, "wb").write(b"\0" * 16)
ran = []
st = b._settings(); st["iq_file"] = iq
print(" bench.transmit after PANIC (fake runner):", bench.transmit(st, run=lambda argv: ran.append(argv))[0], "runner called:", bool(ran))
b._tx(); print(" UI _tx() result card hero:", b.card.hero.text() if hasattr(b.card, "hero") else "?")
pump(700)
print(" 700ms later slot still:", repr(hub.topbar.slots["tx"].text()))

print("== C. FORGE gate cards vs engagement panel / PANIC")
hub.panic_banner.hide()
hub.open_callsign("FORGE"); pump(200)
forge = hub.pages["FORGE"]
from palisade_qt.forge import EngagementCard
cards = [c for c in forge.findChildren(EngagementCard)]
print(" forge EngagementCards:", len(cards), "has on_gate_changed override:", type(forge).on_gate_changed is not __import__("palisade_qt.app").app.PalisadeApp.on_gate_changed)
hub.open_panel("engagement"); p = hub.engage_panel
p.eng_operator.setText("op"); p.eng_name.setText("N"); p.eng_auth.setText("A"); p.eng_scope.setText("can0")
p._activate(); pump(700)
print(" after ACTIVATE: slot=%r card0.state=%r" % (hub.topbar.slots["engagement"].text(), cards[0].state.text() if cards else None))
forge.refresh_gates()
print(" (after manual refresh_gates) card0.state=%r" % (cards[0].state.text() if cards else None))
hub.panic(); pump(700)
print(" after PANIC: slot=%r card0.state=%r inputs enabled=%s" % (hub.topbar.slots["engagement"].text(), cards[0].state.text() if cards else None, [e.isEnabled() for e in cards[0]._inputs.values()] if cards else None))
hub.close()
