from common import *
from palisade_qt.ops import CALLSIGNS
hub=mkhub(demo=True)
kinds=(QtWidgets.QLineEdit,QtWidgets.QAbstractSpinBox,QtWidgets.QComboBox,QtWidgets.QPlainTextEdit,QtWidgets.QAbstractButton,QtWidgets.QAbstractItemView,QtWidgets.QSlider)
def lab(w):
    t=""
    if isinstance(w,QtWidgets.QAbstractButton): t=w.text()
    elif isinstance(w,QtWidgets.QLineEdit): t=w.placeholderText()
    return "%s:%s"%(type(w).__name__,t[:28])
tot=0; miss_all=[]
for name,_ in CALLSIGNS:
    hub.open_callsign(name); pump(200)
    pg=hub.pages[name]
    for t in (pg.subtabs() or [None]):
        if t: pg.switch_subtab(t); pump(150)
        hub.setFocus(); pump(20)
        ws=[w for w in pg.findChildren(QtWidgets.QWidget) if isinstance(w,kinds) and w.isVisible() and w.isEnabled()
            and not isinstance(w.parent(),(QtWidgets.QAbstractSpinBox,QtWidgets.QComboBox)) and not (w.objectName()=="qt_spinbox_lineedit")]
        reached=set()
        first=None
        for i in range(120):
            key(hub,K.Key_Tab); f=QtWidgets.QApplication.focusWidget()
            if f is None: break
            if id(f) in reached: break
            reached.add(id(f))
        miss=[lab(w) for w in ws if id(w) not in reached]
        nofocus=[lab(w) for w in ws if not (w.focusPolicy() & K.TabFocus)]
        tot+=len(ws)
        print("%s/%s: %d controls, tab-reached %d, UNREACHABLE %d %s"%(name,t,len(ws),len(ws)-len(miss),len(miss),miss[:6]))
        miss_all+=miss
print("TOTAL controls",tot,"unreachable by Tab",len(miss_all))
hub.close(); pump(300)
