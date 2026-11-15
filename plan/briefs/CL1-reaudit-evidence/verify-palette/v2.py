import sys
sys.path.insert(0, "/private/tmp/claude-501/-Users-daltonhayes-SentryHub/f893c360-320b-4c7c-9dc4-e3ab8ef11055/scratchpad/reaudit/arch")
from common import *
h = hub(demo=True); p = h.palette
h.open_panel("palette"); pump(20)
for q in ["1","2","5","8","9","10","5 s","sweep"]:
    print(repr(q), [l for l,_ in p.matches(q)[:3]])
h.close(); pump(100)
