"""Render RECON WIFI (NetworkManager path) and BLE (live rows) at 1280x720, dark + sun."""
import os
import sys
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
import wifisurvey  # noqa: E402
from palisade_qt.recon import ReconApp  # noqa: E402
from palisade_qt import theme  # noqa: E402

NM = ("Cafe\\:Guest:AA\\:BB\\:CC\\:DD\\:EE\\:01:6:78:\nHOME-5G:AA\\:BB\\:CC\\:DD\\:EE\\:02:36:55:WPA2\n"
      ":AA\\:BB\\:CC\\:DD\\:EE\\:03:11:40:WPA2 802.1X\nMixed:AA\\:BB\\:CC\\:DD\\:EE\\:04:1:30:WPA2 WPA3\n")
BLE = [{"address": "AA:BB:CC:00:00:01", "name": "Fitbit Charge", "vendor": "unknown", "kind": "",
        "rssi": -58},
       {"address": "AC:BC:32:00:00:03", "name": "—", "vendor": "Apple", "kind": "apple", "rssi": -75},
       {"address": "60:60:1F:00:00:12", "name": "—", "vendor": "DJI", "kind": "drone", "rssi": -80},
       {"address": "AA:BB:CC:00:00:02", "name": "Tile", "vendor": "unknown", "kind": "",
        "rssi": None}]
out = os.path.dirname(os.path.abspath(__file__))
for mode in ("dark", "sun"):
    try:
        theme.apply(app, mode)
    except Exception:
        pass
    p = ReconApp(demo=False, mode=mode)
    p.setFixedSize(1280, 720)
    p._on_wifi({"aps": wifisurvey.parse_nmcli(NM), "path": "nmcli"})
    p._switch("WIFI")
    p.show()
    app.processEvents()
    p.grab().save(os.path.join(out, "recon-wifi-nmcli-%s.png" % mode))
    p._on_ble({"devs": BLE, "backend": "bluetoothctl"})
    p._switch("BLE")
    app.processEvents()
    p.grab().save(os.path.join(out, "recon-ble-live-%s.png" % mode))
    p.stop()
    p.close()
print("ok")
