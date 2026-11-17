"""CL8 renders at 1280x720, dark + sun, LIVE. usage: python render_cl8.py <repo> <outdir> <tag>
before (main): the strip, ATLAS. after (branch): + NET slot, fault indicator, session log, Remote-ID
UNCONFIRMED card, OPS selection."""
import os, sys, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PALISADE_OFFLINE"] = "1"
os.environ["HOME"] = tempfile.mkdtemp()            # no operator settings, OFFLINE default
repo, out, tag = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo); os.chdir(repo)
os.makedirs(out, exist_ok=True)
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme, eventbus
from palisade_qt.shell import PalisadeHub
after = tag == "after"


def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents(); time.sleep(0.01)


def atlas_rid(hub):
    from palisade_qt import atlas
    hub.open_callsign("ATLAS"); pump(300)
    a = hub.page_app("ATLAS")
    fl = [{"id": "UAS-SPOOF", "lat": 39.75, "lon": -104.95, "timestamp": 1.0, "first": 1.0,
           "adverts": 1, "operator_lat": 39.74, "operator_lon": -104.96}]
    for ev in atlas.rid_contacts(fl):
        ev["ts"] = time.time()
        a._on_event(ev)
    a._render(); pump(200)
    rows = a.feed.model.rows
    if rows:
        a.feed.view.selectRow(0); a._show(rows[0])


def fault(hub):
    hub.open_callsign("OPS"); pump(200)
    hub.page_app("PRISM").on_error("rtl_power exited: usb_claim_interface error -6")
    hub.open_callsign("OPS")


def ops_sel(hub):
    hub.open_callsign("OPS"); pump(200)
    ops = hub.ops
    for i, (cid, lab, x, y) in enumerate((("a1", "UAL123", 20, 30), ("a2", "N512SP", -35, 10))):
        eventbus.bus.publish(eventbus.contact("ADS-B", cid, 39.7 + y / 60, -104.9 + x / 60 / 0.77,
                                              alt=12000, kind="aircraft", label=lab))
    pump(300)
    if hasattr(ops, "select_contact"):
        ops.select_contact("a1")


for mode in ("dark", "sun"):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode)
    app.setStyleSheet(theme.qss(mode))
    eventbus.set_home((39.7, -104.9), "render")
    hub = PalisadeHub(demo=False, mode=mode); hub.resize(1280, 720); hub.show(); pump(500)
    shots = [("ops", lambda: hub.open_callsign("OPS")),
             ("ops_select", lambda: ops_sel(hub)),
             ("atlas_rid", lambda: atlas_rid(hub)),
             ("recon", lambda: hub.open_callsign("RECON"))]
    if after:
        shots += [("ops_fault", lambda: fault(hub)),
                  ("session_log", lambda: hub.open_panel("log")),
                  ("net_lan", lambda: (hub.log_panel.set_net("LAN"), hub.open_panel("log"),
                                       hub.open_panel("log")))]
    for name, act in shots:
        try:
            act(); pump(1200)
            pm = hub.grab(); p = "%s/%s_%s_live_%s.png" % (out, name, mode, tag); pm.save(p)
            print(p, pm.width(), pm.height(), "strip", hub.topbar.minimumSizeHint().width())
            if name == "session_log":
                hub.open_panel("log"); pump(100)
        except Exception as e:
            print("FAIL", name, mode, repr(e)[:200])
    if after:
        import netpolicy
        netpolicy.set_mode("OFFLINE")
    hub.close(); pump(200)
    eventbus.set_home(None)
