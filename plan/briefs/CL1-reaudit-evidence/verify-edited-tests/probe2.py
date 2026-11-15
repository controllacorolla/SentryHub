import sys, os
sys.path.insert(0, os.getcwd())
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from palisade_qt.shell import PalisadeHub, QT_PAGES
hub = PalisadeHub(demo=True, mode="dark"); hub.show()
print("fresh hub: stack.count", hub.stack.count(), "len(pages)", len(hub.pages), "QT_PAGES+1", len(QT_PAGES)+1)
for n in ["ATLAS","PRISM","PROWL","SWEEP","RECON","FORGE","SYSTEM","OVERWATCH","BABEL","BENCH","MORE"]:
    hub.page_app(n)
print("after all: stack.count", hub.stack.count(), "len(pages)", len(hub.pages), sorted(hub.pages))
hub.close()
