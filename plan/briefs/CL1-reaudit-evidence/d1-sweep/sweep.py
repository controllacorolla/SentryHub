#!/usr/bin/env python3
"""Cold re-audit harness: render every page / sub-tab / overlay at 1280x720 and measure.
usage: sweep.py <outdir> <dark|light|sun> <live|demo> [stress]
Read-only against the repo; HOME is redirected; network tile fetch is blocked.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HOME"] = os.path.join(HERE, "home")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
REPO = "/Users/daltonhayes/SentryHub"
sys.path.insert(0, REPO)

W, H = 1280, 720


def main(out, mode, run, stress=False):
    os.makedirs(out, exist_ok=True)
    from PySide6 import QtCore, QtGui, QtWidgets
    from palisade_qt import theme
    theme.configure_scale(os.environ)
    app = QtWidgets.QApplication([])
    from palisade_qt.kit import tiles

    def _no_net(*a, **k):
        raise OSError("network blocked by re-audit harness")
    tiles.urlopen = _no_net
    from palisade_qt import ops, panels, eventbus, radio_arbiter
    from palisade_qt.shell import PalisadeHub
    theme.load_fonts()
    theme.set_app_font(app)
    theme.set_palette(app, mode)
    app.setStyleSheet(theme.qss(mode))

    def pump(ms):
        t = time.time()
        while time.time() - t < ms / 1000:
            app.processEvents()
            app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
            time.sleep(0.01)

    hub = PalisadeHub(demo=(run == "demo"), mode=mode)
    hub.resize(W, H)
    hub.show()
    pump(500)

    if stress:
        import engagement
        ok, why = engagement.start(
            "OPERATION LONG ENGAGEMENT NAME — CLIENT ACME INDUSTRIAL HOLDINGS Q4 WIRELESS ASSESSMENT",
            "SOW-2026-11-0042 signed J. Doe-Featherstonehaugh, CISO, 2026-11-01 through 2026-12-15",
            ["192.168.100.0/24", "AA:BB:CC:*", "ACME-Corp-Guest-*", "10.20.0.0/16",
             "DE:AD:BE:EF:00:*", "acme-industrial-holdings.example"],
            "OPERATOR-CALLSIGN-KILO-SEVEN")
        print("engagement.start:", ok, why)
        radio_arbiter.arbiter._owner = "PROWL-SCAN"
        radio_arbiter.arbiter.changed.emit("PROWL-SCAN")
        for i in range(140):
            eventbus.bus.publish(eventbus.alert(
                "SWEEP" if i % 2 else "ATLAS-OVERWATCH",
                "alert %d: possible IMSI catcher — cell 310-410-%05d downgraded to 2G with "
                "null cipher A5/0, signal +18 dB over baseline, LAC changed twice in 40 s" % (i, i),
                severity=("alert", "warn", "info")[i % 3]))
        hub.state.poll()
        pump(200)

    report = {}

    def text_w(w, s):
        fm = w.fontMetrics()
        return max((fm.horizontalAdvance(line) for line in s.split("\n")), default=0)

    def in_scroll(w):
        p = w.parentWidget()
        while p is not None and p is not hub:
            if isinstance(p, QtWidgets.QAbstractScrollArea):
                return True
            p = p.parentWidget()
        return False

    def desc(w):
        cls = w.property("class") or ""
        t = ""
        if isinstance(w, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
            t = w.text()[:70]
        return "%s[%s]%s '%s'" % (type(w).__name__, cls, ("#" + w.objectName()) if w.objectName() else "", t)

    def inspect(tag):
        issues = []
        hub_rect = QtCore.QRect(0, 0, hub.width(), hub.height())
        skip_overlap = (panels.Overlay, panels.DemoBorder)
        for w in hub.findChildren(QtWidgets.QWidget):
            if not w.isVisible() or not w.isVisibleTo(hub):
                continue
            scr = in_scroll(w)
            tl = w.mapTo(hub, QtCore.QPoint(0, 0))
            r = QtCore.QRect(tl, w.size())
            if not scr and not hub_rect.contains(r) and w.width() > 0 and w.height() > 0:
                issues.append(("OFFSCREEN", desc(w), [r.x(), r.y(), r.width(), r.height()]))
            par = w.parentWidget()
            if (par is not None and not scr and not isinstance(par, QtWidgets.QAbstractScrollArea)
                    and not par.rect().contains(w.geometry()) and w.width() > 0 and w.height() > 0
                    and not isinstance(w, skip_overlap) and w is not hub.panic_banner):
                g = w.geometry()
                issues.append(("CLIPPED_BY_PARENT", desc(w), [g.x(), g.y(), g.width(), g.height(),
                                                             par.width(), par.height(), type(par).__name__]))
            # squeezed below its own minimum
            if not scr and w.layout() is None or True:
                mh = w.minimumSizeHint()
                if mh.isValid() and not scr:
                    if w.width() < mh.width() - 1 or w.height() < mh.height() - 1:
                        issues.append(("SQUEEZED", desc(w), [w.width(), w.height(), mh.width(), mh.height()]))
            if isinstance(w, QtWidgets.QLabel) and w.text() and w.pixmap().isNull():
                txt = w.text()
                if w.textFormat() != QtCore.Qt.RichText and "<" not in txt:
                    if not w.wordWrap():
                        tw = text_w(w, txt)
                        if tw > w.width():
                            issues.append(("LABEL_TEXT_CLIPPED", desc(w), [tw, w.width()]))
                    else:
                        hfw = w.heightForWidth(w.width())
                        if hfw > w.height() + 1:
                            issues.append(("WRAPPED_LABEL_CLIPPED_V", desc(w), [hfw, w.height(), w.width()]))
            if isinstance(w, QtWidgets.QAbstractButton) and w.text():
                tw = text_w(w, w.text())
                if tw > w.width() - 2:
                    issues.append(("BUTTON_TEXT_CLIPPED", desc(w), [tw, w.width()]))
            if isinstance(w, QtWidgets.QAbstractScrollArea):
                hb, vb = w.horizontalScrollBar(), w.verticalScrollBar()
                if hb.maximum() > 0:
                    issues.append(("H_SCROLL", desc(w), [hb.maximum(), w.width()]))
                if vb.maximum() > 0 and not isinstance(w, (QtWidgets.QAbstractItemView,
                                                           QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
                    issues.append(("V_SCROLL", desc(w), [vb.maximum(), w.height()]))
            if isinstance(w, QtWidgets.QTableView) and w.model() is not None:
                m = w.model()
                fm = w.fontMetrics()
                hh = w.horizontalHeader()
                for c in range(m.columnCount()):
                    cw = w.columnWidth(c)
                    head = str(m.headerData(c, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) or "")
                    hw = hh.fontMetrics().horizontalAdvance(head)
                    if hw > cw - 4 and not w.isColumnHidden(c):
                        issues.append(("TABLE_HEADER_ELIDED", desc(w), [head, hw, cw]))
                    worst = None
                    for rr in range(min(m.rowCount(), 40)):
                        s = str(m.data(m.index(rr, c), QtCore.Qt.DisplayRole) or "")
                        tw = fm.horizontalAdvance(s)
                        if tw > cw - 6 and (worst is None or tw > worst[1]):
                            worst = (s[:60], tw, cw)
                    if worst and not w.isColumnHidden(c):
                        issues.append(("TABLE_CELL_ELIDED", desc(w), [head, worst[0], worst[1], worst[2]]))
                vr = w.verticalHeader().defaultSectionSize()
                issues.append(("INFO_TABLE", desc(w), {"rows": m.rowCount(), "row_h": vr,
                                                        "view_h": w.viewport().height(),
                                                        "cols": [w.columnWidth(c) for c in range(m.columnCount())]}))
            if isinstance(w, QtWidgets.QComboBox):
                tw = text_w(w, w.currentText())
                if tw > w.width() - 24:
                    issues.append(("COMBO_TEXT_CLIPPED", desc(w), [w.currentText()[:50], tw, w.width()]))
            if isinstance(w, QtWidgets.QLineEdit) and (w.text() or w.placeholderText()):
                s = w.text() or w.placeholderText()
                tw = text_w(w, s)
                if tw > w.width() - 8:
                    issues.append(("LINEEDIT_%s_CLIPPED" % ("TEXT" if w.text() else "PLACEHOLDER"),
                                   desc(w), [s[:60], tw, w.width()]))
        # sibling overlap
        for par in [hub.centralWidget()] + hub.centralWidget().findChildren(QtWidgets.QWidget):
            if not par.isVisible() or isinstance(par, (QtWidgets.QAbstractScrollArea, QtWidgets.QStackedWidget,
                                                       QtWidgets.QSplitter)):
                continue
            kids = [k for k in par.children() if isinstance(k, QtWidgets.QWidget) and k.isVisible()
                    and not isinstance(k, skip_overlap) and k is not hub.panic_banner
                    and k.width() > 0 and k.height() > 0]
            for i in range(len(kids)):
                for j in range(i + 1, len(kids)):
                    inter = kids[i].geometry().intersected(kids[j].geometry())
                    if inter.width() > 1 and inter.height() > 1:
                        issues.append(("OVERLAP", desc(kids[i]) + "  X  " + desc(kids[j]),
                                       [inter.x(), inter.y(), inter.width(), inter.height()]))
        return issues

    def shot(tag, page=None):
        hub.resize(W, H)
        pump(150)
        pm = hub.grab()
        pm.save(os.path.join(out, "%s.png" % tag))
        mh, sh = hub.minimumSizeHint(), hub.sizeHint()
        ent = {"grab": [pm.width(), pm.height()], "hub_size": [hub.width(), hub.height()],
               "hub_min": [mh.width(), mh.height()], "hub_hint": [sh.width(), sh.height()],
               "topbar": [hub.topbar.width(), hub.topbar.height(),
                          hub.topbar.minimumSizeHint().width(), hub.topbar.sizeHint().width()],
               "stack": [hub.stack.width(), hub.stack.height()]}
        if page is not None:
            pmh, psh = page.minimumSizeHint(), page.sizeHint()
            ent["page_size"] = [page.width(), page.height()]
            ent["page_min"] = [pmh.width(), pmh.height()]
            ent["page_hint"] = [psh.width(), psh.height()]
        ent["issues"] = inspect(tag)
        report[tag] = ent

    for name, _label in ops.CALLSIGNS:
        hub.open_callsign(name)
        pump(1200 if run == "demo" else 400)
        page = hub.pages[name]
        tabs = page.subtabs()
        if not tabs:
            shot(name.lower(), page)
        for t in tabs:
            page.switch_subtab(t)
            pump(900 if run == "demo" else 300)
            shot("%s-%s" % (name.lower(), t.lower().replace(" ", "")), page)
    hub.open_callsign("OPS")
    pump(100)
    shot("ops-final", hub.pages["OPS"])
    for panel in ("radios", "engagement", "alerts", "keys", "palette"):
        hub.open_callsign("OPS")
        hub.open_panel(panel)
        pump(250)
        ov = hub.top_overlay()
        shot("panel-" + panel)
        if ov is not None:
            mh = ov.minimumSizeHint()
            report["panel-" + panel]["overlay"] = {
                "geom": [ov.x(), ov.y(), ov.width(), ov.height()],
                "min": [mh.width(), mh.height()], "hint": [ov.sizeHint().width(), ov.sizeHint().height()],
                "parent": [ov.parentWidget().width(), ov.parentWidget().height()]}
        hub.open_panel(panel)
        pump(50)
    if stress:
        # panic banner
        hub._list_children = lambda: []
        hub._kill = lambda p: False
        hub.panic()
        pump(100)
        b = hub.panic_banner
        shot("panic-banner")
        report["panic-banner"]["banner"] = {"geom": [b.x(), b.y(), b.width(), b.height()],
                                            "hfw": b.heightForWidth(b.width()), "text": b.text()}
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1, default=str)
    bad = {k: v["grab"] for k, v in report.items() if v["grab"] != [W, H]}
    worst_w = max(v["hub_min"][0] for v in report.values())
    worst_h = max(v["hub_min"][1] for v in report.values())
    print(mode, run, "stress" if stress else "", len(report), "shots; not 1280x720:", bad or "none",
          "| worst hub min:", worst_w, worst_h)
    hub.close()
    pump(300)
    import engagement
    engagement.reset()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], len(sys.argv) > 4)
