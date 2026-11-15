import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = "/Users/daltonhayes/SentryHub/.claude/worktrees/wf_aa62e8f8-bfc-8"
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_cl1_screen as T
import engagement
from palisade_qt import radio_arbiter as ra
hub = T._hub("dark", demo=True)
# (a) visible vs text()
engagement.start("Op", "ROE-1", ["10.0.0.*"], "N0CALL")
hub.state.poll()
ra.arbiter.changed.emit("ATLAS-APRS"); T._pump(20)
for k, s in hub.topbar.slots.items():
    print("slot", k, "text()=%r" % s.text(), "VISIBLE=%r" % s.value.text(),
          "w=%d labelw=%d need=%d" % (s.width(), s.value.width(), s.value.sizeHint().width()))
hub.topbar.set_alerts(7); print("alerts", hub.topbar.alerts.text(), repr(hub.topbar.alerts.value.text()))
engagement.reset(); ra.arbiter.changed.emit(""); hub.state.poll()
# (b) worst-case strip persistence
T._worst_case_strip(hub)
w0 = {k: s.text() for k, s in hub.topbar.slots.items()}
print("worst set:", w0, "strip minhint", hub.topbar.minimumSizeHint().width())
lost = None
for name, tab in T._every_view(hub):
    cur = {k: s.text() for k, s in hub.topbar.slots.items()}
    if cur != w0 and lost is None:
        lost = (name, tab, cur)
print("worst-case state lost at:", lost)
print("alerts slot now:", hub.topbar.alerts.text())
# (c) nav key clipping
for n, k in hub.topbar.nav_keys.items():
    print("nav", n, "h=%d layout-min-h=%d call(h=%d need=%d) label(h=%d need=%d) w=%d needw=%d" % (
        k.height(), k.layout().minimumSize().height(), k.call.height(), k.call.sizeHint().height(),
        k.label.height(), k.label.sizeHint().height(), k.width(), k.layout().minimumSize().width()))
for k, s in hub.topbar.slots.items():
    print("slot", k, "h=%d need=%d" % (s.height(), s.layout().minimumSize().height()),
          "value h=%d need=%d" % (s.value.height(), s.value.sizeHint().height()))
print("topbar w", hub.topbar.width(), "minhint", hub.topbar.minimumSizeHint().width(), "sizehint", hub.topbar.sizeHint().width())
hub.close(); T._pump(100)
