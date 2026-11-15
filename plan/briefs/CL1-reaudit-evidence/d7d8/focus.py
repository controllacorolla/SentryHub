from common import *
def diff(a,b):
    a=a.convertToFormat(QtGui.QImage.Format_RGB32); b=b.convertToFormat(QtGui.QImage.Format_RGB32)
    n=0
    for y in range(a.height()):
        for x in range(a.width()):
            if a.pixel(x,y)!=b.pixel(x,y): n+=1
    return n
for mode in ("dark","light","sun"):
    app.setStyleSheet(theme.qss(mode))
    hub=shell.PalisadeHub(demo=True, mode=mode); hub.resize(1280,720); hub.show(); hub.activateWindow(); pump(150)
    hub._list_children=lambda: []
    out=[]
    def chk(label,w):
        hub.setFocus(); pump(30); a=w.grab().toImage()
        w.setFocus(); pump(30); ok=QtWidgets.QApplication.focusWidget() is w; b=w.grab().toImage()
        out.append("%s:%d%s"%(label,diff(a,b),"" if ok else "(nofocus)"))
    chk("navkey",hub.topbar.nav_keys["PRISM"]); chk("slot",hub.topbar.slots["engagement"]); chk("alerts",hub.topbar.alerts)
    hub.open_callsign("SYSTEM","BENCH"); pump(200); sp=hub.pages["SYSTEM"]; b=hub.pages["SYSTEM"].child(shell.BenchApp)
    chk("subtab",sp._rail.buttons["DOCTOR"]); chk("combo",b.band); chk("spin",b.power); chk("checkbox",b.ack); chk("button",b.run_btn); chk("table",b.feed.view)
    hub.open_callsign("SYSTEM","SETTINGS"); pump(100); m=sp.child(shell.MoreApp); chk("lineedit",m.set_operator)
    # checked state of subtab
    r=sp._rail; x=r.buttons["DOCTOR"]; hub.setFocus(); pump(20); a=x.grab().toImage(); sp.switch_subtab("DOCTOR"); pump(50); hub.setFocus(); pump(20); c=x.grab().toImage()
    out.append("subtab-checked:%d"%diff(a,c))
    print(mode, " ".join(out))
    hub.close(); pump(200)
