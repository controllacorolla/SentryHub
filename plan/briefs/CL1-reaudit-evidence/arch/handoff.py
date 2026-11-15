from common import *
import shutil
from palisade_qt import prowl, prism
# fake presence of binaries; pipes stay None via the offscreen seams (no radio touched)
_w = shutil.which
prowl.shutil.which = lambda n, *a, **k: "/fake/" + n if n in ("rtl_fm", "multimon-ng", "rtl_power") else _w(n, *a, **k)
hist = []
radio_arbiter.arbiter.changed.connect(lambda o: hist.append(o))
h = hub(demo=False)
def owner(): return radio_arbiter.arbiter.owner()
h.open_callsign("PROWL", "FM"); pump(1200); print("FM ->", owner())
h.open_callsign("PROWL", "NWR"); pump(1200); print("NWR ->", owner())
h.open_callsign("PROWL", "DECODE"); pump(1200); print("DECODE (babel standby) ->", owner())
h.open_callsign("PROWL", "FM"); pump(1200); print("FM ->", owner())
h.open_callsign("PRISM"); pump(1500); print("PRISM ->", owner(), "prowl inner active", h.pages["PROWL:inner"]._active)
h.open_callsign("PROWL"); pump(1500); print("back PROWL(FM) ->", owner())
h.show_page("OPS"); pump(1500); print("OPS ->", owner())
# rapid
import random
random.seed(1)
tabs = ["SCAN", "FM", "NWR", "DECODE"]
t0 = time.time()
for i in range(40):
    h.open_callsign("PROWL", random.choice(tabs)); app.processEvents()
print("40 rapid switches took %.1fs" % (time.time() - t0))
h.open_callsign("PROWL", "NWR"); pump(1500); print("final NWR ->", owner(), "qthreads", qthreads())
# key-driven: Right arrow cycles
h.setFocus()
for i in range(9):
    key(h, QtCore.Qt.Key_Right); app.processEvents()
pump(1500)
print("after 9x Right: tab", h.current_page().current_subtab(), "owner", owner())
# composite hidden: Esc -> OPS
key(h, QtCore.Qt.Key_Escape); pump(1500); print("Esc->", h._current, owner())
h.close(); pump(300)
print("closed: owner", owner(), "unreleased", [l.n for l in LEASES if not l.released], "qthreads", qthreads(), pythreads())
print("lease count", len(LEASES))
