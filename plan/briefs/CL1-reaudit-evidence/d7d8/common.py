import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.dont_write_bytecode=True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"branch"))
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtTest import QTest
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from palisade_qt import theme, shell, chrome, panels, eventbus
import txguard, engagement
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
K=QtCore.Qt
def pump(ms=120):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.005)
def mkhub(demo=True):
    hub=shell.PalisadeHub(demo=demo, mode="dark"); hub.resize(1280,720); hub.show(); hub.activateWindow(); pump(150)
    hub._list_children=lambda: []
    hub._kill=lambda p: True
    return hub
def key(hub, k=None, text="", mod=K.NoModifier):
    tgt=QtWidgets.QApplication.focusWidget() or hub
    if text: QTest.keyClicks(tgt, text, mod)
    else: QTest.keyClick(tgt, k, mod)
    pump(40)
def fw():
    f=QtWidgets.QApplication.focusWidget()
    return "%s(%s)"%(type(f).__name__, (f.objectName() or (f.text() if hasattr(f,'text') and callable(f.text) else ''))[:30]) if f else None
def state(hub):
    pg=hub.current_page()
    ov=hub.top_overlay()
    return (hub._current, pg.current_subtab() if pg else None, ov.TITLE if ov else None)
