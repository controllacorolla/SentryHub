import os, sys, time, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PALISADE_OFFLINE"] = "1"
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtCore, QtWidgets, QtGui
app = QtWidgets.QApplication([])
import engagement, txguard
from palisade_qt import chrome, shell, radio_arbiter as ra, panels, theme
ra._make_lease = lambda name: None     # never open a radio

def pump(ms=50):
    t = time.time()
    while (time.time() - t) * 1000 < ms:
        app.processEvents(); time.sleep(0.005)

def slots(h): return {k: s.text() for k, s in h.topbar.slots.items()}
def fresh(demo=False):
    engagement.reset(); txguard.reset_session(); chrome.reset()
    h = shell.PalisadeHub(demo=demo); h.show(); pump(80); return h
def done(h): h.close(); pump(100)

print("=== A. readers raising -> slot word")
h = fresh()
txguard.arm(True); engagement.start("Op", "ROE", ["10.0.0.*"], "N0CALL"); h.state.poll()
print("A0 armed+active:", slots(h))
orig_armed, orig_info = txguard.is_armed, engagement.info
txguard.is_armed = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
engagement.info = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
h.state.poll()
print("A1 readers raise while engine state armed=%s active=%s ->" % (txguard._STATE["armed"], engagement._ENG["active"]), slots(h))
txguard.is_armed, engagement.info = orig_armed, orig_info
done(h)

print("=== A2. PANIC with failing disarm/end")
h = fresh()
h._list_children = lambda: []; 
txguard.arm(True); txguard.unlock_session(True); engagement.start("Op", "ROE", ["10.0.0.*"], "N0CALL"); h.state.poll()
oa, oe = txguard.arm, engagement.end
txguard.arm = lambda on=True: (_ for _ in ()).throw(RuntimeError("disarm broke"))
engagement.end = lambda: (_ for _ in ()).throw(RuntimeError("end broke"))
did = h.panic()
print("A2 panic did:", did); print("A2 engine armed=%s unlocked=%s active=%s; slots=%s" % (txguard.is_armed(), txguard.session_unlocked(), engagement.is_active(), slots(h)))
txguard.arm, engagement.end = oa, oe
done(h)

print("=== B. BENCH permit after PANIC")
h = fresh(); h._list_children = lambda: []
bench = h.page_app("BENCH"); pump(60)
bench.ack.setChecked(True); h.state.poll()
print("B0 ack checked: slot=%s btn_enabled=%s gate=%r sources=%s" % (slots(h)["tx"], bench.tx_btn.isEnabled(), bench.gate.text(), chrome.tx_permit_sources()))
h.panic(); pump(700)
import bench as benchmod
print("B1 after PANIC (+700ms): slot=%s btn_enabled=%s ack=%s gate=%r preflight=%s sources=%s" % (
    slots(h)["tx"], bench.tx_btn.isEnabled(), bench.ack.isChecked(), bench.gate.text(), benchmod.preflight(bench._settings(), bench._band_freq())[0], chrome.tx_permit_sources()))
ok_called = []
orig_tx = benchmod.transmit
benchmod.transmit = lambda s, run=None: (ok_called.append(benchmod.preflight(s, s["freq_hz"])) or (True, "would key"))
bench.tx_btn.click(); pump(20)
print("B2 clicking KEY CONDUCTED TX while slot says %s -> transmit called, preflight=%s" % (slots(h)["tx"], ok_called))
benchmod.transmit = orig_tx
done(h)

print("=== B3. env lock after permit (stale PERMITTED)")
h = fresh()
bench = h.page_app("BENCH"); pump(60); bench.ack.setChecked(True); h.state.poll()
os.environ["SUITE_TX_LOCK"] = "1"; pump(700)
print("B3 SUITE_TX_LOCK=1 set: slot=%s preflight=%s" % (slots(h)["tx"], benchmod.preflight(bench._settings(), bench._band_freq())))
del os.environ["SUITE_TX_LOCK"]
done(h)

print("=== B4. permit after hub close / page stop")
h = fresh(); bench = h.page_app("BENCH"); pump(60); bench.ack.setChecked(True)
done(h); print("B4 sources after hub close:", chrome.tx_permit_sources())
h = fresh(); print("B4 new hub tx:", slots(h)["tx"]); done(h)

print("=== C. polling gap, engagement activated via panel / arm")
h = fresh()
h.open_panel("engagement"); pump(30)
p = h.engage_panel
p.eng_operator.setText("N0CALL"); p.eng_name.setText("Op"); p.eng_auth.setText("ROE"); p.eng_scope.setText("10.0.0.*")
p._activate()
app.processEvents()
print("C1 right after panel ACTIVATE (no poll): engine active=%s slot=%s" % (engagement.is_active(), slots(h)["engagement"]))
t0 = time.time()
while slots(h)["engagement"] == "NONE" and time.time() - t0 < 2: pump(10)
print("C1 slot caught up after %.0f ms -> %s" % ((time.time() - t0) * 1000, slots(h)["engagement"]))
p._deactivate(); app.processEvents()
print("C2 right after panel END: engine active=%s slot=%s" % (engagement.is_active(), slots(h)["engagement"]))
pump(600)
txguard.arm(True); app.processEvents()
print("C3 right after txguard.arm(True): slot=%s" % slots(h)["tx"])
t0 = time.time()
while slots(h)["tx"] == "OFF" and time.time() - t0 < 2: pump(10)
print("C3 caught up after %.0f ms -> %s" % ((time.time() - t0) * 1000, slots(h)["tx"]))
# engagement authorize_action during the gap
done(h)

print("=== C4. GUI-thread stall: timer starves")
h = fresh()
txguard.arm(True); time.sleep(1.5)   # GUI thread blocked 1.5 s (no event loop)
print("C4 after 1.5 s blocked GUI thread, before events: slot=%s (engine armed=%s)" % (slots(h)["tx"], txguard.is_armed()))
done(h)

print("=== D. RADIO: real arbiter paths")
h = fresh()
print("D0", slots(h)["radio"])
ra.arbiter.request("PROWL-FM"); pump(30); print("D1 request PROWL-FM:", slots(h)["radio"], "| value label:", repr(h.topbar.slots["radio"].value.text()))
ra.arbiter.request("ATLAS-APRS"); pump(30); print("D2 second requester denied:", slots(h)["radio"])
ra.arbiter.release("ATLAS-APRS"); pump(30); print("D3 non-owner release:", slots(h)["radio"])
ra.arbiter.release("PROWL-FM"); pump(30); print("D4 release:", slots(h)["radio"])
# from a worker thread
th = threading.Thread(target=lambda: ra.arbiter.request("PRISM")); th.start(); th.join()
print("D5 right after worker-thread request, before events: owner=%r slot=%s" % (ra.arbiter.owner(), slots(h)["radio"]))
pump(30); print("D5 after events:", slots(h)["radio"])
# hub created while radio held
h2 = shell.PalisadeHub(demo=False); pump(30); print("D6 second hub built while held:", slots(h2)["radio"]); h2.close()
ra.arbiter.release("PRISM"); pump(30)
# direct RtlLease holder outside the arbiter (PalisadeApp.LEASE path)
import palisade_qt.app as papp
print("D7 pages with class LEASE (direct suite.RtlLease, not arbiter):", [(n, getattr(c, "LEASE", None)) for n, c in list(shell.QT_PAGES.items()) + [(k, v[2]) for k, v in shell.FOLDED.items()] if getattr(c, "LEASE", None)])
done(h)

print("=== D8. arbiter lock held during acquire blocks ChromeState()/RadiosPanel on GUI thread")
ev = threading.Event()
ra._make_lease = lambda name: (ev.wait(1.2), None)[1]
th = threading.Thread(target=lambda: ra.arbiter.request("SLOW")); th.start(); time.sleep(0.1)
t0 = time.time(); st = chrome.ChromeState(demo=False); dt = time.time() - t0
print("D8 ChromeState() construction blocked %.2f s while a layer was acquiring; radio=%s" % (dt, st.radio()))
st.stop(); th.join(); ra.arbiter.release("SLOW"); ra._make_lease = lambda name: None; pump(30)

print("=== E. MODE")
h = fresh(demo=True); print("E1 demo hub:", slots(h)["mode"], "border", h.demo_border is not None and h.demo_border.isVisible())
h.state.mode = "LIVE"; h._on_state(); print("E2 (attr writable) mode ->", slots(h)["mode"]); done(h)

print("=== F. direct write / overwrite attempts by a page")
h = fresh()
h.open_callsign("RECON"); pump(300)
rec = h.pages["RECON"]
print("F1 page has topbar ref attrs:", [a for a in dir(rec) if "topbar" in a.lower() or a == "tb"])
rec.attach_topbar(h.topbar); rec.set_chip("tx", "TX SAFE", state="live"); rec.on_status({"tx": {"text": "TX OFF", "state": "ok"}, "sdr": {"text": "RADIO FREE"}})
pump(30); print("F2 slots after page set_chip/on_status:", slots(h), "| page row:", rec.page_status())
row = rec._status_row
print("F3 page status row: geom=%s y_in_window=%s visible=%s labels=%s" % (row.geometry().getRect(), row.mapTo(h, QtCore.QPoint(0, 0)).y(), row.isVisible(), [(l.text(), l.property("class"), l.font().pixelSize(), l.fontInfo().pixelSize()) for l in rec._status_labels.values()]))
h.grab().save(os.path.join(os.path.dirname(__file__), "page_row_txsafe.png"))
# page reports a permit under someone else's name / clears it
chrome.report_tx_permit("BENCH", True); h.state.poll(); print("F4 any module can raise PERMITTED:", slots(h)["tx"])
chrome.report_tx_permit("BENCH", False); h.state.poll(); print("F5 any module can clear BENCH's permit:", slots(h)["tx"])
txguard.arm(True); chrome.reset(); h.state.poll(); print("F6 ARMED survives registry writes:", slots(h)["tx"])
done(h)

print("=== G. set_state with unknown words")
from palisade_qt.kit import TopBar
tb = TopBar()
print("G0 fresh TopBar with no ChromeState:", {k: s.text() for k, s in tb.slots.items()})
tb.set_state("UNKNOWN", ("ERROR", "x"), "FAULT", ("ERROR", "", ""))
print("G1 unknown words ->", {k: s.text() for k, s in tb.slots.items()})
tb.set_state("LIVE", ("HELD", "PROWL scan"), "PERMITTED", ("ACTIVE", "10.0.0.* +3", "x"))
print("G2 display text:", {k: s.value.text() for k, s in tb.slots.items()}, "tips:", {k: s.toolTip() for k, s in tb.slots.items()})
print("G3 opsec tip:", tb.opsec_slot.toolTip(), "| size", tb.opsec_slot.size().toTuple(), "focus", tb.opsec_slot.focusPolicy())

print("=== H. engagement.info odd shapes")
oi = engagement.info
for info in ({"active": True, "scope": "10.0.0.5"}, {"active": True, "scope": None}, {"active": 1, "scope": []}, {"active": True, "scope": [""]}, None):
    engagement.info = lambda i=info: i
    print("H", info, "->", chrome.read_engagement())
engagement.info = oi

print("=== I. standalone window")
from palisade_qt.bench_app import BenchApp
engagement.reset(); txguard.reset_session(); chrome.reset()
b = BenchApp(demo=False); w = b.standalone(); w.show(); pump(80)
tb2 = w.findChild(TopBar)
b.ack.setChecked(True); pump(700)
print("I1 standalone BENCH ack: slots", {k: s.text() for k, s in tb2.slots.items()})
w.close(); pump(100); print("I2 after close sources:", chrome.tx_permit_sources())
print("DONE")
