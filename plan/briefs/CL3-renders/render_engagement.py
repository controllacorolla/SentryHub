import os, sys, subprocess
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.getcwd())
import suite, tempfile
suite.DATA = tempfile.mkdtemp()
from PySide6 import QtWidgets, QtCore
import engagement as E, txguard as G, executor, netpent
E._profile_operator = lambda: "KD0ABC"
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
for mode in ("dark", "sun"):
    E.reset(); G.reset_session()
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from palisade_qt import theme
    from palisade_qt.shell import PalisadeHub
    theme.load_fonts(); theme.set_app_font(qa); theme.set_palette(qa, mode); qa.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=True, mode=mode)
    hub.resize(1280, 720); hub.show()
    import time
    t0=time.time()
    while time.time()-t0<0.5: qa.processEvents(); time.sleep(0.01)
    assert E.start("acme-q4", "ROE-2026-117", ["10.0.0.0/24", "AA:BB:CC:*"], "KD0ABC")[0]
    G.arm(True); G.unlock_session(True)
    E.authorize_action("wifi:pmkid", "AA:BB:CC:11:22:33", kind="mac")
    E.authorize_action("net:portscan", "10.9.9.9")      # out of scope -> REFUSED
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    executor.run(t, spawner=lambda a: subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
    ok, why, t2 = netpent.prepare("services", "10.0.0.6")
    executor.run(t2, spawner=lambda a: subprocess.Popen([sys.executable, "-c", "import sys;sys.exit(2)"], start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
    hub.open_panel("engagement"); qa.processEvents()
    t0=time.time()
    while time.time()-t0<0.4: qa.processEvents(); time.sleep(0.01)
    img = hub.grab().toImage(); assert img.width() == 1280 and img.height() == 720, img.size()
    p = os.path.join(out, "engagement-%s.png" % mode); img.save(p); print(p)
    hub.open_panel("engagement"); hub.close(); qa.processEvents()
