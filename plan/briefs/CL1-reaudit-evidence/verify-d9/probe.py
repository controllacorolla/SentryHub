import sys, os
sys.path.insert(0, os.getcwd())
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
import engagement, txguard, palisade_qt
print("code from", palisade_qt.__file__)
from palisade_qt import theme
from palisade_qt.forge import ForgeApp
from palisade_qt.kit.topbar import TopBar
from palisade_qt import panels
t = theme.tokens("dark"); print("live", t["live"], "warn", t["warn"], "alert", t["alert"])
engagement.start("Op", "ROE-1", ["10.0.0.*", "aa:*"], "N0CALL")
f = ForgeApp(demo=False, mode="dark")
for c in f._cards:
    if hasattr(c, "_show_result"):
        c._show_result(True, "in scope", ["nmap", "x"]); print(type(c).__name__, repr(c.result.text()[:30]), c.result.styleSheet()); break
import inspect
print(inspect.signature(TopBar.__init__)); print([n for n in dir(TopBar) if n.startswith("set")])
