import sys
sys.path.insert(0, "/private/tmp/claude-501/-Users-daltonhayes-SentryHub/f893c360-320b-4c7c-9dc4-e3ab8ef11055/scratchpad/reaudit/arch")
from common import *
h = hub(demo=True); p = h.palette
print("start page", h._current)
for q in ["1","2","5","8","9","10","5 ","sweep","162.55"]:
    print(repr(q), [l for l,_ in p.matches(q)[:3]])
h.open_panel("palette"); pump(20)
QTest.keyClicks(p.input, "5"); print("top:", p.list.currentItem().text())
QTest.keyClick(p.input, QtCore.Qt.Key_Return); pump(100)
pw = h.pages["PROWL:inner"] if "PROWL:inner" in h.pages else h.pages["PROWL"]
print("after /5 Enter:", h._current, h.current_page().current_subtab(), pw.fm_freq.value())
for mhz in (162.55, 162.4, 162.425, 5, 6000):
    h._freq_commands(mhz)[0][1](); pump(30)
    print(mhz, "-> fm_freq", pw.fm_freq.value(), "mode", pw.fm_mode.currentText())
h._freq_commands(5)[1][1](); pump(30)
pr = h.pages["PRISM"]; print("prism", {k:v for k,v in vars(pr).items() if k in ("_lo","_hi","_center","_span")})
h.close(); pump(100)
