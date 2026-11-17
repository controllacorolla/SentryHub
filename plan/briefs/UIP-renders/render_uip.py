"""UI-polish (device notes) renders at 1280x720, dark + sun, LIVE.
usage: python render_uip.py <repo> <outdir> <tag>   (tag = before | after)
Screens: OPS, ATLAS (with HOME set + demo contacts), the strip with SDR held + engagement active,
and (after only) ATLAS and OPS with the side panel collapsed."""
import os, sys, time, tempfile
NET = os.environ.get("RENDER_NET") == "1"      # after-renders: real satellite tiles (xvfb, NET ON)
if not NET:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["PALISADE_OFFLINE"] = "1"
os.environ["HOME"] = tempfile.mkdtemp()
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


def contacts():
    for i, (cid, lab, x, y) in enumerate((("a1", "UAL123", 20, 30), ("a2", "N512SP", -35, 10),
                                          ("a3", "SWA88", 50, -40))):
        eventbus.bus.publish(eventbus.contact("ADS-B", cid, 39.7 + y / 60, -104.9 + x / 60 / 0.77,
                                              alt=12000, kind="aircraft", label=lab,
                                              track=(45, 300, 200)[i], spd=320))


def strip_states(hub):
    hub.state.stop()
    hub.topbar.set_state("LIVE", ("HELD", "PRISM"), "UNLOCKED", ("ACTIVE", "10.0.0.*", "t"))
    hub.topbar.set_alerts(3)


def settings_gps(hub):
    hub.open_callsign("SYSTEM"); pump(200)
    page = hub.pages["SYSTEM"]; page.switch_subtab("SETTINGS"); pump(200)
    more = page.current_child()
    more._gps_reader = lambda: None
    more.read_gps()


def collapse(hub, cs):
    hub.open_callsign(cs); pump(200)
    hub.page_app(cs).handle_key("f")


for mode in ("dark", "sun"):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode)
    app.setStyleSheet(theme.qss(mode))
    eventbus.set_home((39.7, -104.9), "render")
    if NET:
        import netpolicy
        netpolicy.set_mode("ONLINE")
    hub = PalisadeHub(demo=False, mode=mode); hub.resize(1280, 720); hub.show(); pump(500)
    contacts()
    shots = [("ops", lambda: hub.open_callsign("OPS")),
             ("atlas", lambda: hub.open_callsign("ATLAS")),
             ("strip_held_active", lambda: (strip_states(hub), hub.open_callsign("OPS")))]
    if after:
        shots += [("atlas_collapsed", lambda: collapse(hub, "ATLAS")),
                  ("ops_collapsed", lambda: collapse(hub, "OPS")),
                  ("atlas_zoomed", lambda: (hub.open_callsign("ATLAS"),
                                            hub.page_app("ATLAS").handle_key("+"),
                                            hub.page_app("ATLAS").handle_key("+"))),
                  ("atlas_light_sat", lambda: hub.page_app("ATLAS").map._combo.setCurrentIndex(1)),
                  ("settings_gps", lambda: settings_gps(hub))]
    for name, act in shots:
        try:
            act(); pump(6000 if NET else 1200)
            pm = hub.grab(); p = "%s/%s_%s_live_%s.png" % (out, name, mode, tag); pm.save(p)
            print(p, pm.width(), pm.height(), "strip", hub.topbar.minimumSizeHint().width())
        except Exception as e:
            print("FAIL", name, mode, repr(e)[:200])
    hub.close(); pump(200)
    eventbus.set_home(None)
