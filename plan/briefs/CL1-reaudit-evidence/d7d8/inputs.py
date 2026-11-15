from common import *
from palisade_qt.ops import CALLSIGNS
hub=mkhub()
muted=lambda: hub.topbar.mute.isChecked()
hub.topbar.mute.setEnabled(True)  # so 'm' would be observable (audio.available False -> no mixer call)
probes=[("5",None),(" ",None),("/",None),("?",None),("r",None),("e",None),("a",None),("m",None),("[",None),("+",None),
        ("",K.Key_Left),("",K.Key_Right),("",K.Key_Up),("",K.Key_Down),("",K.Key_Return)]
kinds=(QtWidgets.QLineEdit,QtWidgets.QAbstractSpinBox,QtWidgets.QComboBox,QtWidgets.QPlainTextEdit,QtWidgets.QTextEdit,
       QtWidgets.QAbstractButton,QtWidgets.QAbstractItemView,QtWidgets.QSlider)
res={}
def probe_widget(w, where):
    for text,k in probes:
        while QtWidgets.QApplication.activePopupWidget(): QtWidgets.QApplication.activePopupWidget().close(); pump(20)
        hub.activateWindow(); w.setFocus(); pump(20)
        if QtWidgets.QApplication.focusWidget() is not w: 
            res.setdefault((type(w).__name__,"NOFOCUS"),[]).append(where+(text or str(k),)); continue
        s0=state(hub); m0=muted()
        try:
            if text: QTest.keyClicks(w,text)
            else: QTest.keyClick(w,k)
        except Exception as e: print("EXC",e)
        pump(30)
        s1=state(hub); m1=muted()
        if s1!=s0 or m1!=m0:
            nm=type(w).__name__+("(editable)" if isinstance(w,QtWidgets.QComboBox) and w.isEditable() else "")
            res.setdefault((nm, text or {K.Key_Left:"Left",K.Key_Right:"Right",K.Key_Up:"Up",K.Key_Down:"Down",K.Key_Return:"Enter"}[k], "%s->%s"%(s0,s1) if s1!=s0 else "mute toggled"),[]).append(where)
            # restore
            for o in hub._overlays: o.close_overlay()
            hub.open_callsign(where[0], where[1]) if where[1] else hub.open_callsign(where[0])
            if m1!=m0: hub.topbar.mute.setChecked(m0)
            pump(30)
for name,_ in CALLSIGNS:
    hub.open_callsign(name); pump(150)
    pg=hub.pages[name]
    for t in (pg.subtabs() or [None]):
        if t: pg.switch_subtab(t); pump(120)
        ws=[w for w in pg.findChildren(QtWidgets.QWidget) if isinstance(w,kinds) and w.isVisible() and w.isEnabled() and w.focusPolicy()!=K.NoFocus]
        for w in ws:
            if isinstance(w, QtWidgets.QAbstractButton): continue   # buttons separately (don't click actions)
            if w.parent() and isinstance(w.parent(), (QtWidgets.QAbstractSpinBox,QtWidgets.QComboBox)): continue
            probe_widget(w,(name,t))
import collections
agg=collections.defaultdict(set)
for k,v in res.items(): agg[k]|=set(v)
for k in sorted(agg, key=str): print(k, "x%d"%len(agg[k]), sorted(agg[k],key=str)[:3])
hub.close(); pump(300)
