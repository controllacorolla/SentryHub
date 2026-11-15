import sys, collections
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore, QtGui
from palisade_qt import theme, babel
app = QtWidgets.QApplication([])
try: theme.load_fonts()
except Exception as e: print("fonts", e)
for mode in ("dark", "light", "sun"):
    tok = theme.tokens(mode)
    try: theme.apply(app, mode)
    except Exception as e: print("apply?", e)
    w = babel.BabelApp(demo=True, mode=mode)   # not started: no worker, no radio
    w.resize(1280, 640); w.show()
    for p in ["AIS","ACARS","POCSAG","RDS","TPMS","CW","RTTY"][::-1]:
        w.on_row({"proto": p, "time": "12:00:00", "freq": "162.025", "text": "x", "summary": "x"})
    app.processEvents()
    m = w.feed.model; view = w.feed.findChild(QtWidgets.QTableView)
    hdr = [m.headerData(c, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) for c in range(m.columnCount())]
    pc = [c for c in range(m.columnCount()) if m.data(m.index(0,c), QtCore.Qt.DisplayRole) == "AIS"][0]
    img = w.grab().toImage()
    img.save("babel_%s.png" % mode)
    print(mode, "cols", hdr, "well", tok["well"], "row_alt", tok["row_alt"])
    for r in range(m.rowCount()):
        idx = m.index(r, pc)
        fg = m.data(idx, QtCore.Qt.ForegroundRole)
        col = (fg.color() if isinstance(fg, QtGui.QBrush) else QtGui.QColor(fg)).name().upper()
        rect = view.visualRect(idx)
        tl = view.viewport().mapTo(w, rect.topLeft())
        cnt = collections.Counter()
        for x in range(tl.x(), tl.x()+rect.width()):
            for y in range(tl.y(), tl.y()+rect.height()):
                cnt[img.pixelColor(x,y).name().upper()] += 1
        bgpix = cnt.most_common(1)[0][0]
        # darkest/most-distant rendered pixel = glyph core
        best = min(cnt, key=lambda c: theme.contrast(c, bgpix) * -1)
        print("  %-7s fgRole=%s renderedBg=%s role-vs-bg=%.2f  best-rendered-pixel=%s %.2f" % (
            m.data(idx, QtCore.Qt.DisplayRole), col, bgpix, theme.contrast(col, bgpix), best, theme.contrast(best, bgpix)))
    w.close()
