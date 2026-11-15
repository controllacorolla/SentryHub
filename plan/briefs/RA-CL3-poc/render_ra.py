import os, sys, subprocess, json, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.getcwd())
import suite, tempfile
suite.DATA = tempfile.mkdtemp()
from PySide6 import QtWidgets, QtCore
import engagement as E, txguard as G, executor, netpent, chain
E._profile_operator = lambda: "KD0ABC"
out = sys.argv[1]
def pump(s):
    t0=time.time()
    while time.time()-t0<s: qa.processEvents(); time.sleep(0.01)
qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
theme.load_fonts(); theme.set_app_font(qa)
for mode, tamper, stress in (("dark",0,0),("sun",0,0),("dark",1,0),("sun",1,1)):
    E.reset(); G.reset_session(); chain.reset_for_tests()
    theme.set_palette(qa, mode); qa.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=False, mode=mode); hub.resize(1280, 720); hub.show(); pump(0.4)
    assert E.start("acme-q4" + ("-very-long-engagement-name-xx" if stress else ""), "ROE-2026-117", ["10.0.0.0/24", "AA:BB:CC:*"], "KD0ABC")[0]
    G.arm(True); G.unlock_session(True)
    E.authorize_action("wifi:pmkid", "AA:BB:CC:11:22:33", kind="mac")
    E.authorize_action("net:portscan", "10.9.9.9")
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    executor.run(t, spawner=lambda a: subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True, stdout=subprocess.PIPE, text=True))
    ok, why, t2 = netpent.prepare("services", "10.0.0.6")
    executor.run(t2, spawner=lambda a: subprocess.Popen([sys.executable, "-c", "import sys;sys.exit(2)"], start_new_session=True, stdout=subprocess.PIPE, text=True))
    if stress:
        for i in range(30):
            E.authorize_action("net:portscan", "corp.example.internal.very-long-hostname.test" if i%2 else "10.0.0.%d"%(i+10))
    hub.open_panel("engagement"); pump(0.3)
    if tamper:
        info = E.chain_info()
        L = open(info["path"],"rb").read().splitlines()
        r = json.loads(L[2]); r["target"]="10.0.0.66"; L[2]=chain.canonical(r)
        open(info["path"],"wb").write(b"\n".join(L)+b"\n")
        p = hub._panels["engagement"] if hasattr(hub, "_panels") else None
        for w in qa.allWidgets():
            if type(w).__name__ == "EngagePanel": w.render_actions()
        pump(0.3)
    panel = [w for w in qa.allWidgets() if type(w).__name__ == "EngagePanel" and w.isVisible()]
    tbl = panel[0].eng_actions
    view = tbl if isinstance(tbl, QtWidgets.QAbstractItemView) else tbl.findChild(QtWidgets.QAbstractItemView)
    hs = view.horizontalScrollBar()
    g = panel[0].geometry()
    img = hub.grab().toImage(); assert img.width()==1280 and img.height()==720
    p = os.path.join(out, "engagement-%s%s%s-live.png" % (mode, "-tampered" if tamper else "", "-stress" if stress else "")); img.save(p)
    print(p, "panel", g.x(), g.y(), g.width(), g.height(), "hscroll max", hs.maximum(), "visible", hs.isVisible(), "caption:", panel[0].eng_chain.text(), "rows", view.model().rowCount())
    hub.close(); qa.processEvents()
