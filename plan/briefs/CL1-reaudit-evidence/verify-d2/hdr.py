import sys, os
sys.path.insert(0, sys.argv[1]); os.chdir(sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
import test_cl1_screen as T
from PySide6 import QtWidgets, QtGui, QtCore
hub = T._hub("dark", demo=True); T._pump(600)
hub.open_callsign("PROWL"); T._pump(300)
tv = [t for t in hub.findChildren(QtWidgets.QTableView) if t.isVisible()][0]
h = tv.horizontalHeader()
img = h.grab().toImage()
# ink bbox height of header text: rows containing pixels differing from the background corner
bg = img.pixelColor(2, 2)
ys = [y for y in range(img.height()-3) if any(abs(img.pixelColor(x, y).lightness()-bg.lightness()) > 40 for x in range(0, min(img.width(), 300)))]
print("header fontInfo px", h.fontInfo().pixelSize(), "height", h.height(), "ink rows", (min(ys), max(ys), max(ys)-min(ys)+1) if ys else None, "text", tv.model().headerData(0, QtCore.Qt.Horizontal))
img.save(sys.argv[2])
hub.close(); T._pump(100)
