import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PALISADE_OFFLINE"] = "1"
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtCore, QtWidgets, QtGui
app = QtWidgets.QApplication([])
import engagement, txguard
from palisade_qt import chrome, shell, radio_arbiter as ra, theme
from palisade_qt.kit import TopBar
ra._make_lease = lambda name: None
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, "dark"); app.setStyleSheet(theme.qss("dark"))
def pump(ms=50):
    t = time.time()
    while (time.time() - t) * 1000 < ms:
        app.processEvents(); time.sleep(0.005)
here = os.path.dirname(os.path.abspath(__file__))
engagement.reset(); txguard.reset_session(); chrome.reset()
h = shell.PalisadeHub(demo=False); h.show(); pump(100)
print("window", h.size().toTuple(), "topbar h", h.topbar.height())
for owner in ["PRISM", "PROWL-FM", "PROWL-SCAN", "PROWL-NWR", "ATLAS-APRS", "ATLAS-AIS", "BABEL", "BABEL-SSTV"]:
    ra.arbiter.request(owner); pump(20)
    s = h.topbar.slots["radio"]
    fm = s.value.fontMetrics()
    print("RADIO owner %-11s full=%-22r shown=%-14r slot_w=%d label_w=%d full_text_px=%d" % (owner, s.text(), s.value.text(), s.width(), s.value.width(), fm.horizontalAdvance(s.text())))
    ra.arbiter.release(owner); pump(20)
for scope in (["10.0.0.*"], ["AA:BB:CC:*", "Net-*"], ["x"]):
    engagement.start("Op", "ROE", scope, "N0CALL"); h.state.poll()
    s = h.topbar.slots["engagement"]
    print("ENGAGE scope %-24r full=%-24r shown=%r slot_w=%d" % (scope, s.text(), s.value.text(), s.width()))
ra.arbiter.request("PROWL-FM"); pump(20)
h.topbar.grab().save(os.path.join(here, "strip_held_active.png"))
print("strip widths:", {k: (s.x(), s.width()) for k, s in h.topbar.slots.items()}, "nav end x:", max(k.x() + k.width() for k in h.topbar.nav_keys.values()), "opsec x", h.topbar.opsec_slot.x(), "clock", h.topbar.clock.geometry().getRect())
ra.arbiter.release("PROWL-FM"); engagement.reset(); h.state.poll()
# page row
h.open_callsign("RECON"); pump(400)
rec = h.pages["RECON"]
rec.set_chip("tx", "TX OFF", state="live"); rec.set_chip("gps", "ENGAGEMENT NONE", state="ok"); pump(30)
txguard.arm(True); h.state.poll(); pump(30)
h.grab().save(os.path.join(here, "page_row_vs_strip.png"))
print("page row labels:", [(l.text(), l.property("class")) for l in rec._status_labels.values()], "row y", rec._status_row.mapTo(h, QtCore.QPoint(0, 0)).y(), "children of row:", [type(c).__name__ for c in rec._status_row.children()])
print("strip tx:", h.topbar.slots["tx"].text())
h.close(); pump(100)
# standalone
from palisade_qt.bench_app import BenchApp
engagement.reset(); txguard.reset_session(); chrome.reset()
b = BenchApp(demo=False); w = b.standalone(); w.show(); pump(80)
tb2 = w.findChild(TopBar)
b.ack.setChecked(True); pump(700)
print("I1 standalone BENCH ack: slots", {k: s.text() for k, s in tb2.slots.items()})
w.close(); pump(100); print("I2 after close sources:", chrome.tx_permit_sources())
# info None
oi = engagement.info; engagement.info = lambda: None
try: print(chrome.read_engagement())
except Exception as e: print("H5 read_engagement raised:", type(e).__name__, e)
engagement.info = oi
