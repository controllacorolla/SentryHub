import sys, os
sys.path.insert(0, os.getcwd())
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt.kit.topbar import TopBar
from palisade_qt import panels
tb = TopBar(mode="dark")
tb.set_state("LIVE", ("FREE", None), "ARMED", ("ACTIVE", "10.0.0.*"))
for k in ("tx", "engagement"):
    s = tb.slots[k]; print(k, s.text(), s.value.styleSheet(), s.glyph._color)
p = panels.EngagePanel(mode="dark")
p.eng_name.setText("Op"); p.eng_auth.setText("ROE-1"); p.eng_scope.setText("10.0.0.*"); p.eng_operator.setText("N0CALL")
p._activate(); print(repr(p.eng_msg.text()[:40]), p.eng_msg.styleSheet())
import engagement; engagement.end() if hasattr(engagement, "end") else None
