import os, sys, time, gc, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HOME"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "home")
os.environ["XDG_CONFIG_HOME"] = os.environ["HOME"] + "/.config"
os.environ["XDG_DATA_HOME"] = os.environ["HOME"] + "/.local/share"
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
sys.dont_write_bytecode = True
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from palisade_qt import radio_arbiter, theme, panels, eventbus, chrome
LEASES = []
class FakeLease:
    def __init__(s, n): s.n = n; s.released = False; LEASES.append(s)
    def release(s): s.released = True
radio_arbiter._make_lease = lambda name: FakeLease(name)

def pump(ms=200, step=5):
    t = 0
    while t < ms:
        app.processEvents(); time.sleep(step/1000.0); t += step

def qthreads():
    out = []
    for o in gc.get_objects():
        try:
            if isinstance(o, QtCore.QThread) and o.isRunning():
                out.append(type(o).__name__)
        except RuntimeError:
            pass
    return sorted(out)

def pythreads():
    return sorted(t.name for t in threading.enumerate() if t is not threading.main_thread())

def hub(mode="dark", demo=True):
    from palisade_qt.shell import PalisadeHub
    theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss(mode))
    h = PalisadeHub(demo=demo, mode=mode); h.resize(1280, 720); h.show(); pump(100)
    return h

def views(h):
    from palisade_qt import shell
    from palisade_qt.ops import CALLSIGNS
    out = []
    for name, _ in CALLSIGNS:
        cls = shell.QT_PAGES.get(name)
        tabs = []
        if cls is not None:
            tabs = [t for _f, ts in cls.PARTS for t, _s in ts] if getattr(cls, "PARTS", None) else list(cls.SUBTABS)
        out.append((name, None))
        out += [(name, t) for t in tabs]
    return out

def key(h, k, text=""):
    w = QtWidgets.QApplication.focusWidget() or h
    ev = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, k, QtCore.Qt.NoModifier, text)
    QtWidgets.QApplication.sendEvent(w, ev)
