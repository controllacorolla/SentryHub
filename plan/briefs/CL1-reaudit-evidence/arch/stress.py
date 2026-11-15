import sys
from common import *
demo = sys.argv[1] == "demo"
print("baseline qthreads", qthreads(), "py", pythreads())
h = hub(demo=demo)
vs = views(h)
print("views", len(vs))
# pass 1: slow, each view
for name, tab in vs:
    h.open_callsign(name, tab); pump(120)
print("after pass1 qthreads", len(qthreads()), qthreads())
print("py", pythreads())
n1 = len(qthreads())
# pass 2: rapid, no pumping
for rep in range(5):
    for name, tab in vs:
        h.open_callsign(name, tab)
    for name, tab in reversed(vs):
        h.open_callsign(name, tab); app.processEvents()
pump(300)
print("after rapid qthreads", len(qthreads()), qthreads())
print("py", pythreads())
print("owner", radio_arbiter.arbiter.owner(), "leases", [(l.n, l.released) for l in LEASES])
# overlays open/close
for p in ("radios", "engagement", "alerts", "keys", "palette"):
    h.open_panel(p); pump(30); assert h.top_overlay() is not None, p
    h.open_panel(p); pump(30); assert h.top_overlay() is None, p
# hidden-children activity: go to OPS
h.show_page("OPS"); pump(500)
print("on OPS: owner", radio_arbiter.arbiter.owner())
for n, p in h.pages.items():
    print("  ", n, type(p).__name__, "active", getattr(p, "_active", None), "started", p._started, "worker", type(p._worker).__name__ if p._worker else None)
h.close(); pump(300)
print("after close qthreads", qthreads())
print("py", pythreads())
print("owner", radio_arbiter.arbiter.owner(), "unreleased", [l.n for l in LEASES if not l.released])
