import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, sys.argv[1])
from PySide6 import QtGui, QtWidgets
import pyqtgraph as pg
app = QtWidgets.QApplication([])
from palisade_qt import theme, chrome, panels, eventbus
from palisade_qt.shell import PalisadeHub
import engagement, txguard
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, "sun"); app.setStyleSheet(theme.qss("sun"))
# P-A: BENCH ack held, operator on another page, PANIC
h = PalisadeHub(demo=False, mode="sun"); h.resize(1280, 720); h.show(); pump(200); h._list_children = lambda: []
h.open_callsign("BENCH"); pump(80); b = h.pages["BENCH"]; b.ack.setChecked(True); pump(30); h.state.poll()
h.open_callsign("ATLAS"); pump(100); h.state.poll()
print("A before:", h.topbar.slots["tx"].text(), "ack", b.ack.isChecked())
h.panic(); pump(50)
print("A after: ", h.topbar.slots["tx"].text(), "ack", b.ack.isChecked(), "btn", b.tx_btn.isEnabled(), "|", h.panic_banner.text())
# P-B: txguard ARMED + BENCH ack; PANIC
h.open_callsign("BENCH"); b.ack.setChecked(True); pump(30)
try:
    ok = txguard.arm(433.92e6) if hasattr(txguard, "arm") else None
except Exception as e:
    ok = "arm err %s" % e
h.state.poll(); print("B before:", h.topbar.slots["tx"].text(), ok)
h.panic(); pump(50); print("B after: ", h.topbar.slots["tx"].text(), "|", h.panic_banner.text())
# P-C: re-check the ack after PANIC: the gate passes again (expected: operator re-acks deliberately)
b.ack.setChecked(True); pump(30); h.state.poll(); print("C re-ack:", h.topbar.slots["tx"].text())
b.ack.setChecked(False); pump(30)
# P-D: alerts — late arrival, then close and reopen via the A key path
for i in range(3): eventbus.bus.publish(eventbus.alert("T", "old %d" % i, severity="warn"))
pump(30); h.open_panel("alerts"); pump(30)
eventbus.bus.publish(eventbus.alert("T", "late", severity="alert")); pump(30)
print("D count line:", h.alerts_drawer.count.text())
n = h.alerts_drawer.ack_all_seen(); print("D acked", n, "left", [a["text"] for a in h.alerts.items if not a["acked"]])
h.close(); pump(100)
# P-E: font walker on ATLAS (all sub-tabs) — every visible text widget >= 16 px
h = PalisadeHub(demo=True, mode="sun"); h.resize(1280, 720); h.show(); pump(300); h.open_callsign("ATLAS"); pump(1500)
small = []
for sub in ("MAP", "SKY DOME", "PASSES"):
    try: h.pages["ATLAS"].switch_subtab(sub)
    except Exception as e: print("subtab", sub, e)
    pump(300)
    for w in h.findChildren(QtWidgets.QWidget):
        if not w.isVisible(): continue
        if isinstance(w, (QtWidgets.QLabel, QtWidgets.QAbstractButton, QtWidgets.QAbstractItemView, QtWidgets.QComboBox, QtWidgets.QHeaderView)):
            px = QtGui.QFontInfo(w.font()).pixelSize()
            if px < 16: small.append((sub, type(w).__name__, getattr(w, "text", lambda: "")()[:20], px))
    for gv in h.findChildren(pg.GraphicsView):
        if not gv.isVisible(): continue
        for it in gv.scene().items():
            if isinstance(it, pg.TextItem):
                px = QtGui.QFontInfo(it.textItem.font()).pixelSize()
                if px < 16: small.append((sub, "TextItem", it.textItem.toPlainText()[:20], px))
            if isinstance(it, pg.AxisItem) and it.isVisible() and it.style.get("showValues", True):
                f = it.style.get("tickFont") or it.font() if hasattr(it, "font") else None
                if f is not None and QtGui.QFontInfo(f).pixelSize() < 16: small.append((sub, "Axis", it.orientation, QtGui.QFontInfo(f).pixelSize()))
print("E ATLAS widgets <16px:", small)
h.close(); pump(100)
