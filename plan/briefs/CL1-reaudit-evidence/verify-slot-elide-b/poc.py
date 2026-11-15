import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["HOME"]=tempfile.mkdtemp()
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
sys.path.insert(0, "/Users/daltonhayes/SentryHub/tests")
import test_cl1_screen as T
import engagement, txguard
from palisade_qt import radio_arbiter as ra, chrome, panels
engagement.reset(); txguard.reset_session(); chrome.reset(); panels.reset_alert_store()
hub = T._hub(demo=False)
tb = hub.topbar
print("OWNER_LABELS", ra.OWNER_LABELS)
for o in list(ra.OWNER_LABELS) :
    ra.arbiter.changed.emit(o); T._pump(20)
    s = tb.slots["radio"]
    print("%-14s drawn=%-14r full=%r" % (o, s.value.text(), s.text()))
ra.arbiter.changed.emit(""); T._pump(20)
for sc in (["192.168.1.0/24"], ["AA:BB:CC:*"], ["Net-*","10.0.0.0/8"], ["a"]):
    engagement.reset(); engagement.start("Op","ROE-1",sc,"N0CALL"); hub.state.poll(); T._pump(20)
    s = tb.slots["engagement"]
    print("%-28s drawn=%-14r full=%r" % (sc, s.value.text(), s.text()))
tb.set_state("LIVE", ("ACQUIRING","PROWL scan"), "PERMITTED", ("ACTIVE","a","n")); T._pump(30)
print("ACQ drawn", tb.slots["radio"].value.text(), "| TX", tb.slots["tx"].value.text())
# spare width at worst case
T._worst_case_strip(hub)
lay = tb.layout()
print("topbar width", tb.width(), "minHint", tb.minimumSizeHint().width(), "sizeHint", tb.sizeHint().width())
for i in range(lay.count()):
    it = lay.itemAt(i)
    if it.spacerItem(): print("stretch spare px:", it.geometry().width())
for k,s in tb.slots.items(): print(k, s.width(), s.value.width(), s.value.fontMetrics().horizontalAdvance(s.value.text()), "full would need", s.value.fontMetrics().horizontalAdvance(s.text()))
hub.grab().save(os.path.dirname(__file__)+"/strip.png")
tb.grab().save(os.path.dirname(__file__)+"/topbar.png")
engagement.reset(); hub.close(); T._pump(150)
