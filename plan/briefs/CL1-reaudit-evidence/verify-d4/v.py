import os, sys, time, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PALISADE_OFFLINE"] = "1"
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = os.environ["HOME"]
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtCore, QtWidgets
app = QtWidgets.QApplication([])
import engagement, txguard, bench
from palisade_qt import chrome, shell, radio_arbiter as ra, theme
ra._make_lease = lambda name: None
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, "dark"); app.setStyleSheet(theme.qss("dark"))
def pump(ms=50):
    t = time.time()
    while (time.time() - t) * 1000 < ms:
        app.processEvents(); time.sleep(0.005)
def slots(h): return {k: (s.text(), s.value.text()) for k, s in h.topbar.slots.items()}
engagement.reset(); txguard.reset_session(); chrome.reset()
h = shell.PalisadeHub(demo=False); h.resize(1280, 720); h.show(); pump(100)
h._list_children = lambda: []   # never kill anything real
print("== (a) PANIC vs BENCH")
b = h.page_app("BENCH"); pump(200)
print("bench type", type(b).__name__)
b.ack.setChecked(True); pump(700)
print("before panic: tx slot", slots(h)["tx"], "tx_btn enabled", b.tx_btn.isEnabled(), "preflight", bench.preflight(b._settings(), b._band_freq()))
h.panic(); pump(50)
print("after panic : tx slot", slots(h)["tx"], "tx_btn enabled", b.tx_btn.isEnabled(), "ack", b.ack.isChecked(), "preflight", bench.preflight(b._settings(), b._band_freq()), "sources", chrome.tx_permit_sources())
pump(1200)
print("after 1.2s  : tx slot", slots(h)["tx"], "tx_btn enabled", b.tx_btn.isEnabled())
# does clicking reach bench.transmit?
calls = []
orig = bench.transmit
bench.transmit = lambda *a, **k: (calls.append((a, k)) or (False, "FAKE - not transmitted"))
try:
    b.tx_btn.click(); pump(100)
except Exception as e: print("click exc", e)
print("bench.transmit reached after PANIC with slot OFF:", len(calls), "slot", slots(h)["tx"])
bench.transmit = orig
b.ack.setChecked(False); pump(50); chrome.reset()
print("== (f) stale PERMITTED under SUITE_TX_LOCK")
b.ack.setChecked(True); pump(600)
os.environ["SUITE_TX_LOCK"] = "1"; pump(1200)
print("slot", slots(h)["tx"], "preflight", bench.preflight(b._settings(), b._band_freq()))
del os.environ["SUITE_TX_LOCK"]; b.ack.setChecked(False); pump(50)
print("== (b) reader exceptions")
txguard.arm(True); print("arm ->", txguard.is_armed())
print("start", engagement.start("Op", "ROE-1", ["10.0.0.*"], "N0CALL"))
h.state.poll(); pump(30); print("truth armed+active:", slots(h))
oa, oi = txguard.is_armed, engagement.info
def boom(*a, **k): raise RuntimeError("state file unreadable")
txguard.is_armed = boom; engagement.info = boom
h.state.poll(); pump(30); print("readers raise:", slots(h), "| real armed:", oa(), "real active:", oi().get("active"))
txguard.is_armed, engagement.info = oa, oi
h.state.poll(); pump(30)
print("== (c) elision")
for owner in ["PRISM", "PROWL-FM", "PROWL-SCAN", "PROWL-NWR", "ATLAS-APRS", "ATLAS-AIS", "BABEL", "BABEL-SSTV"]:
    ra.arbiter.request(owner); pump(30)
    print("  RADIO %-11s" % owner, slots(h)["radio"]); ra.arbiter.release(owner); pump(30)
for scope in (["10.0.0.*"], ["AA:BB:CC:*", "Net-*"], ["x"]):
    engagement.end(); engagement.start("Op", "ROE", scope, "N0CALL"); h.state.poll()
    print("  ENGAGE", scope, slots(h)["engagement"], "tip", h.topbar.slots["engagement"].toolTip())
ra.arbiter.request("PROWL-FM"); pump(30)
h.topbar.grab().save("strip.png")
s = h.topbar.slots["radio"]; print("  radio slot w", s.width(), "value w", s.value.width(), "full px", s.value.fontMetrics().horizontalAdvance(s.text()))
ra.arbiter.release("PROWL-FM")
print("== (d) panel activate/end gap")
engagement.end(); txguard.arm(False); h.state.poll(); pump(30)
h.open_panel("engagement"); pump(50)
p = h.engage_panel
p.eng_name.setText("Op"); p.eng_auth.setText("ROE-9"); p.eng_scope.setText("10.0.0.*"); p.eng_operator.setText("N0CALL")
p._activate()
t0 = time.time()
print("immediately after _activate (no event loop): engine active", engagement.info().get("active"), "slot", slots(h)["engagement"], "msg", p.eng_msg.text())
while slots(h)["engagement"][0].startswith("NONE") and time.time() - t0 < 2: pump(5)
print("slot caught up after %.0f ms" % ((time.time() - t0) * 1000), slots(h)["engagement"])
p._deactivate(); t0 = time.time()
print("immediately after _deactivate: engine active", engagement.info().get("active"), "slot", slots(h)["engagement"])
while slots(h)["engagement"][0].startswith("ACTIVE") and time.time() - t0 < 2: pump(5)
print("slot caught up after %.0f ms" % ((time.time() - t0) * 1000))
print("== unknown word mapping")
h.topbar.set_state("???", ("???", ""), "???", ("???", "", "")); print(slots(h))
engagement.reset(); txguard.reset_session(); chrome.reset(); h.close(); pump(100)
