import sys, time
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtGui
app = QtWidgets.QApplication([])
from palisade_qt import theme, app as papp
from palisade_qt.prowl import ProwlApp
from palisade_qt.babel import BabelApp
from palisade_qt.system import MoreApp
theme.apply(app, "dark")
green = theme.tokens("dark")["live"].lower()
log = []
orig = papp.PalisadeApp.set_chip
t0 = [time.time()]
def spy(self, key, text=None, state=None, ok=None):
    orig(self, key, text, state, ok)
    log.append((round(time.time()-t0[0], 2), type(self).__name__, key, text, self._last_status[key]["state"]))
papp.PalisadeApp.set_chip = spy
def pump(s):
    t = time.time()
    while time.time() - t < s: app.processEvents(); time.sleep(0.01)
def dwell(p, total=6.0):
    # fraction of time the visible sdr label is class pstat_live
    live = n = 0; t = time.time(); seen = set()
    while time.time() - t < total:
        app.processEvents(); time.sleep(0.01)
        for k, l in p._status_labels.items():
            if l.text():
                n += 1; live += l.property("class") == "pstat_live"; seen.add((l.text(), l.property("class")))
    return live, n, sorted(seen)
def pix(p):
    out = []
    for k, l in p._status_labels.items():
        if not l.text(): continue
        img = l.grab().toImage(); g = 0
        for x in range(img.width()):
            for y in range(img.height()):
                g += img.pixelColor(x, y).name() == green
        out.append((l.text(), l.property("class"), "green_px", g))
    return out
for cls, subs in ((ProwlApp, None), (BabelApp, None), (MoreApp, None)):
    p = cls(demo=True, mode="dark"); p.resize(1280, 660); p.show(); p.start()
    names = list(getattr(p, "SUBTABS", []) or [None])
    print("==", cls.__name__, "subtabs", names)
    for name in names:
        if name is not None:
            try: p.switch_subtab(name if isinstance(name, str) else name[0])
            except Exception as e: print("switch fail", name, e)
        t0[0] = time.time(); del log[:]
        r = dwell(p)
        print(" sub", name, "live-samples %d/%d" % r[:2], r[2], "final", pix(p))
        print("   first emits:", log[:6])
    p.stop()
