import sys
from common import *
mode=sys.argv[1]
theme.set_palette(app, mode); app.setStyleSheet(theme.qss(mode))
hub=shell.PalisadeHub(demo=False, mode=mode); hub.resize(1280,720); hub.show(); hub.activateWindow(); pump(200)
def cnt(a,b):
    a=a.convertToFormat(QtGui.QImage.Format_RGB32); b=b.convertToFormat(QtGui.QImage.Format_RGB32)
    return sum(1 for y in range(a.height()) for x in range(a.width()) if a.pixel(x,y)!=b.pixel(x,y))
for label,w in (("navkey_PRISM(inactive)",hub.topbar.nav_keys["PRISM"]),("navkey_OPS(active)",hub.topbar.nav_keys["OPS"]),("slot_engage",hub.topbar.slots["engagement"]),("slot_radio",hub.topbar.slots["radio"])):
    hub.setFocus(); pump(40); a=hub.topbar.grab().toImage()
    w.setFocus(); pump(40); b=hub.topbar.grab().toImage()
    b.save("focus_%s_%s.png"%(mode,label.split("(")[0]))
    print(mode,label,"focused:",QtWidgets.QApplication.focusWidget() is w,"pixels changed in strip:",cnt(a,b), "of", w.width()*w.height())
hub.close(); pump(200)
