"""RA-CL1c PoC: ATLAS fit under adversarial contacts; strip fit/font in worst states; selection drift."""
import json, os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = sys.argv[1]; OUT = sys.argv[2]
sys.path.insert(0, ROOT)
from PySide6 import QtCore, QtGui, QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme, chrome, panels
from palisade_qt.shell import PalisadeHub
import engagement, txguard
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.01)
def hub_for(mode, demo):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
    h = PalisadeHub(demo=demo, mode=mode); h.resize(1280, 720); h.show(); pump(300); return h
res = {}
def cellcheck(feed):
    v, m = feed.view, feed.model; hdr = v.horizontalHeader(); vw = v.viewport().width()
    bad, elided = [], []
    for r in range(m.rowCount()):
        for c in range(m.columnCount()):
            idx = m.index(r, c); rect = v.visualRect(idx); t = m.data(idx)
            if rect.right() >= vw: bad.append(("past-viewport", r, c, t, rect.right(), vw))
            opt = QtWidgets.QStyleOptionViewItem(); v.itemDelegate().initStyleOption(opt, idx)
            opt.rect = rect
            tr = v.style().subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, opt, v)
            margin = v.style().pixelMetric(QtWidgets.QStyle.PM_FocusFrameHMargin, None, v) + 1
            shown = v.fontMetrics().elidedText(t, QtCore.Qt.ElideRight, tr.width() - 2 * margin)
            if shown != t:
                elided.append((m.columns[c][1], t, shown))
                if not shown.endswith("…"): bad.append(("cut-no-ellipsis", t, shown))
                if m.data(idx, QtCore.Qt.ToolTipRole) != t: bad.append(("no-tooltip", t))
    return {"viewport": vw, "sections": [hdr.sectionSize(i) for i in range(hdr.count())],
            "hscroll_max": v.horizontalScrollBar().maximum(), "hscroll_visible": v.horizontalScrollBar().isVisible(),
            "vscroll_visible": v.verticalScrollBar().isVisible(), "bad": bad, "elided": elided[:12]}
# ---------- ATLAS stress
for mode in ("dark", "light", "sun"):
    h = hub_for(mode, True); h.open_callsign("ATLAS"); pump(2500)
    a = h.pages["ATLAS:inner"]
    base = dict(kind="aircraft", x=1.0, y=1.0, spd=400, severity="info", _ts=time.time() + 3600, brg=45.0)
    a._contacts["ALT6"] = dict(base, id="ALT6", label="N12345", alt=123456, rng=0.5)
    a._contacts["LONGCS"] = dict(base, id="LONGCS", label="OP RID-1581F5FAB2C3D4E5F60718", alt=45000, rng=0.6)
    a._contacts["LONGID"] = dict(base, id="1581F5FAB2C3D4E5F60718AABBCCDDEEFF", label="1581F5FAB2C3D4E5F60718AABBCCDDEEFF", alt=999999, rng=9999.0)
    a._contacts["NEG"] = dict(base, id="NEG", label="DRONE-7", alt=-120, rng=12345.0)
    for i in range(30):
        a._contacts["F%d" % i] = dict(base, id="F%d" % i, label="FILL%02d" % i, alt=10000 + i, rng=50 + i)
    a._render(); pump(400)
    res["atlas_" + mode] = cellcheck(a.feed)
    # select ALT6 then a re-sort pushes it away
    for r, row in enumerate(a.feed.model.rows):
        if row["_id"] == "ALT6": a.feed.view.selectRow(r)
    pump(50); a._contacts["ALT6"]["rng"] = 20000.0; a._render(); pump(100)
    cr = a.feed.view.currentIndex().row()
    res["atlas_" + mode]["resort_follow"] = (a.feed.model.rows[cr]["_id"] if cr >= 0 else None, a._selected, a.detail.hero.text() if hasattr(a.detail, "hero") else None)
    # removal
    del a._contacts["ALT6"]; a._render(); pump(100)
    res["atlas_" + mode]["after_removal"] = (a.feed.view.currentIndex().row(), a.feed.view.selectionModel().hasSelection(), a.detail.hero.text())
    h.grab().save("%s/atlas_stress_%s.png" % (OUT, mode))
    h.close(); pump(150)
# ---------- strip worst cases
def fontpx(w): return QtGui.QFontInfo(w.font()).pixelSize()
for mode in ("dark", "light", "sun"):
    for demo in (False, True):
        h = hub_for(mode, demo); h.state.stop()
        out = {}
        for tag, setup in (
            ("idle", lambda: None),
            ("worst", lambda: (h.topbar.set_state("DEMO" if demo else "LIVE", ("HELD", "PROWL SC"), "PERMITTED", ("ACTIVE", "999 targets", "x")), h.topbar.set_alerts(150))),
            ("unknown", lambda: (h.topbar.set_state("DEMO" if demo else "LIVE", ("HELD", "PROWL SC"), "UNKNOWN", ("UNKNOWN", "", "")), h.topbar.set_alerts(99))),
        ):
            setup(); pump(100)
            tb = h.topbar
            keys = {}
            for name, k in tb.nav_keys.items():
                k.setFocus(); pump(10)
                keys[name] = dict(w=k.width(), hint=k.sizeHint().width(),
                                  call=(k.call.text(), fontpx(k.call), k.call.fontMetrics().horizontalAdvance(k.call.text()), k.call.width()),
                                  label=(k.label.text(), fontpx(k.label), k.label.fontMetrics().horizontalAdvance(k.label.text()), k.label.width(), k.label.isVisible()))
            slots = {}
            for n, s in tb.slots.items():
                ws = [w for w in s.findChildren(QtWidgets.QLabel) if w.isVisible()]
                slots[n] = [(w.text(), fontpx(w), w.fontMetrics().horizontalAdvance(w.text()), w.width()) for w in ws]
            small = [(w.objectName() or w.text(), fontpx(w)) for w in tb.findChildren(QtWidgets.QWidget)
                     if w.isVisible() and isinstance(w, (QtWidgets.QLabel, QtWidgets.QAbstractButton)) and fontpx(w) < 16 and (getattr(w, "text", lambda: "")())]
            overflow = [(n, d) for n, d in keys.items() if d["w"] < d["hint"] or d["call"][2] > d["call"][3] or d["label"][2] > d["label"][3]]
            sl_over = [(n, x) for n, v in slots.items() for x in v if x[2] > x[3]]
            out[tag] = dict(strip_min=tb.minimumSizeHint().width(), strip_w=tb.width(), strip_h=tb.height(),
                            hub_min=h.minimumSizeHint().width(), small_fonts=small, key_overflow=overflow, slot_overflow=sl_over,
                            spare=tb.width() - tb.minimumSizeHint().width())
            if tag == "worst":
                h.topbar.nav_keys["SYSTEM"].setFocus(); pump(30)
                h.grab(QtCore.QRect(0, 0, 1280, 44)).save("%s/strip_%s_%s_worst_focusSYSTEM.png" % (OUT, mode, "demo" if demo else "live"))
                out["keys_sample"] = {k: keys[k] for k in ("FORGE", "SYSTEM", "PRISM")}
        res["strip_%s_%s" % (mode, "demo" if demo else "live")] = out
        h.close(); pump(150)
# ---------- ENG 1-target and state-word scopes through the real engine
for scope in (["NONE"], ["averyverylonghost.example.com"], ["10.0.0.5"], [], ["Unknown "], ["None"]):
    engagement.reset()
    try:
        engagement.start("t", "auth", scope, "op")
    except Exception as e:
        res["eng_%r" % scope] = "start refused: %s" % e; continue
    res["eng_%r" % scope] = chrome.read_engagement()
engagement.reset()
print(json.dumps(res, indent=1, default=str))
