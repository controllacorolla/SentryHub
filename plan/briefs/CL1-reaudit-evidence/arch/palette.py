from common import *
h = hub(demo=True)
p = h.palette
h.open_panel("palette"); pump(20)
for q in ["5", "2", "8", "1", "sweep", "5 ", "5 sw", "recon", "88", "0.5", "panic", "p", "e", "a", "tx", "end", "kill", "mute", "ack"]:
    m = p.matches(q)
    print(repr(q), "->", [l for l, _ in m[:3]])
# actually run "5" + Enter via keys
for ch in "5":
    QTest.keyClicks(p.input, ch)
QTest.keyClick(p.input, QtCore.Qt.Key_Return); pump(100)
print("after '/5<Enter>': page", h._current, "subtab", h.current_page().current_subtab() if hasattr(h.current_page(), "current_subtab") else None)
pw = h.pages.get("PROWL:inner")
print("fm_freq", pw.fm_freq.value() if pw else None, "range", (pw.fm_freq.minimum(), pw.fm_freq.maximum()) if pw else None)
fw = QtWidgets.QApplication.focusWidget()
print("focus after palette run:", type(fw).__name__, fw.objectName() if fw else None)
# focus after non-navigating command
h.open_callsign("PROWL", "SCAN"); pump(50)
h.open_panel("palette"); pump(20)
QTest.keyClicks(p.input, "ack"); print("top:", p.list.currentItem().text())
QTest.keyClick(p.input, QtCore.Qt.Key_Return); pump(50)
fw = QtWidgets.QApplication.focusWidget()
print("focus after 'ack' cmd:", type(fw).__name__, "text-input?", isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)))
before = h._current
key(h, QtCore.Qt.Key_3, "3"); pump(50)
print("press 3 ->", h._current, "(was", before, ")", "focus text:", fw.text() if hasattr(fw, "text") else None)
# escape path
h.open_panel("palette"); pump(20); key(h, QtCore.Qt.Key_Escape); pump(20)
print("esc closes palette:", h.top_overlay() is None, "page", h._current)
# every command runs w/o exception (skip PANIC)
errs = []
for label, fn in h._commands():
    if label.startswith("PANIC"): continue
    try:
        fn(); pump(10)
        for o in h._overlays: o.close_overlay()
    except Exception as e:
        errs.append((label, repr(e)))
print("command errors:", errs)
# subtab commands land on right target
bad = []
for label, fn in h._commands():
    if " › " in label:
        n, t = label.split(" › ")
        fn(); app.processEvents()
        if h._current != n or h.current_page().current_subtab() != t:
            bad.append((label, h._current, h.current_page().current_subtab()))
print("wrong targets:", bad)
# freq commands
for mhz in (0.001, 5, 97.3, 162.55, 1090, 6000):
    for label, fn in h._freq_commands(mhz):
        try:
            fn(); app.processEvents()
            pg = h.current_page()
            if "PROWL" in label:
                print(label, "-> fm_freq", h.pages["PROWL:inner"].fm_freq.value(), "tab", pg.current_subtab())
            else:
                pr = h.pages["PRISM"]
                print(label, "-> prism", getattr(pr, "_lo", None), getattr(pr, "_hi", None))
        except Exception as e:
            print(label, "EXC", repr(e))
h.close(); pump(100)
