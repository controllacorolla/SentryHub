"""What the RADIO / ENGAGEMENT slots actually paint (value label text) vs what tests read (slot.text())."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = "/Users/daltonhayes/SentryHub/.claude/worktrees/wf_aa62e8f8-bfc-8"
sys.path.insert(0, ROOT)
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt.kit import TopBar
from palisade_qt import radio_arbiter as ra
tb = TopBar()
vis = {}
for owner, label in sorted(ra.OWNER_LABELS.items()):
    tb.set_state("LIVE", ("HELD", label), "OFF", ("NONE", "", ""))
    s = tb.slots["radio"]
    vis.setdefault(s.value.text(), []).append(label)
    print("owner %-14s text()=%-22r painted=%r" % (owner, s.text(), s.value.text()))
print("ambiguous painted values:", {k: v for k, v in vis.items() if len(set(v)) > 1})
for scope in ("10.0.0.*", "192.168.1.0/24", "Corp-*"):
    tb.set_state("LIVE", ("FREE", ""), "OFF", ("ACTIVE", scope, "Op"))
    s = tb.slots["engagement"]
    print("scope %-16s text()=%-28r painted=%r" % (scope, s.text(), s.value.text()))
