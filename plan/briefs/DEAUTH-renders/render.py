"""Render RECON WIFI at 1280x720 (dark + sun): engagement open, TX armed, a handshake capture
running, then a targeted deauth fired on its own pane. Nothing transmits: harmless children."""
import os
import subprocess
import sys
import tempfile
import time
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
import suite  # noqa: E402
suite.DATA = tempfile.mkdtemp()
import chain, engagement as E, executor, txguard as G, wifisurvey  # noqa: E402,E401
from palisade_qt import recon, theme  # noqa: E402
E._profile_operator = lambda: "KD0ABC"
tag = sys.argv[1] if len(sys.argv) > 1 else "after"
NM = ("LAB-AP:AA\\:BB\\:CC\\:11\\:22\\:33:6:71:WPA2\nHOME-5G:AA\\:BB\\:CC\\:DD\\:EE\\:02:36:55:WPA2\n")


def spawn(argv, **kw):
    code = ("import time\nfor i in range(99): print(' CH  6 ][ Elapsed: %d s ][ WPA handshake: -' % i, flush=True); time.sleep(1)"
            if argv[0] == "airodump-ng" else
            "print('Waiting for beacon frame (BSSID: AA:BB:CC:11:22:33) on channel 6');"
            "print('Sending 64 directed DeAuth (code 7). STMAC: [DE:AD:BE:EF:00:01] [ 0| 0 ACKs]')")
    return subprocess.Popen([sys.executable, "-u", "-c", code], start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)


recon.ReconApp._spawner = lambda self: spawn
out = os.path.dirname(os.path.abspath(__file__))
for mode in ("dark", "sun"):
    G.reset_session(); E.reset(); executor.reset(); chain.reset_for_tests()
    try:
        theme.apply(app, mode)
    except Exception:
        pass
    E.start("lab", "ROE-1", ["AA:BB:CC:11:22:33", "DE:AD:BE:EF:00:01"], "KD0ABC")
    G.arm(True)
    p = recon.ReconApp(demo=False, mode=mode)
    p.setFixedSize(1280, 720)
    p._on_wifi({"aps": wifisurvey.parse_nmcli(NM), "path": "nmcli"})
    p._switch("WIFI")
    p.show()
    p._wifi_pick({"bssid": "AA:BB:CC:11:22:33", "ch": "6"})
    p.wifi_iface.setText("wlan1mon")
    p.wifi_gated._authorize("handshake")
    p.wifi_client.setText("DE:AD:BE:EF:00:01")
    t = time.time()
    while time.time() - t < 2.5:
        app.processEvents(); time.sleep(0.02)
    p.wifi_gated._authorize("deauth")
    t = time.time()
    while time.time() - t < 1.5:
        app.processEvents(); time.sleep(0.02)
    p.grab().save(os.path.join(out, "%s-recon-wifi-%s.png" % (tag, mode)))
    p.stop(); p.close(); executor.kill_all("render"); app.processEvents()
print("ok")
