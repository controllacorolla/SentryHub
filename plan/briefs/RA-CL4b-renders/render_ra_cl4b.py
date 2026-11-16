"""RA-CL4b renders at 1280x720, LIVE, dark + sun: OPS, ATLAS and ENGAGEMENT with HOME unset,
HOME set from SYSTEM > SETTINGS (no restart), and the ENGAGEMENT trail over a tampered chain and a
malformed head. Tile fetches are recorded, never sent (no network).
usage (repo root): python3 plan/briefs/RA-CL4b-renders/render_ra_cl4b.py <outdir>"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, REPO)
os.environ["QT_QPA_PLATFORM"] = "offscreen:freetype"     # live seams open (they test == "offscreen")
os.environ["HOME"] = tempfile.mkdtemp(prefix="racl4bhome")
os.environ.pop("PALISADE_OFFLINE", None)
from PySide6 import QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
import suite  # noqa: E402
suite.DATA = tempfile.mkdtemp(prefix="racl4bdata")
import chain  # noqa: E402
import engagement as E  # noqa: E402
from palisade_qt import eventbus, theme  # noqa: E402
from palisade_qt.kit import tiles  # noqa: E402
from palisade_qt.shell import PalisadeHub  # noqa: E402
from palisade_qt.system import MoreApp  # noqa: E402

FETCH = []
tiles.TileLayer.fetch = lambda self, style: FETCH.append((style, self.home_lat, self.home_lon))
E._profile_operator = lambda: "KD0ABC"
out = sys.argv[1]
os.makedirs(out, exist_ok=True)


def pump(s):
    t = time.time()
    while time.time() - t < s:
        APP.processEvents()
        time.sleep(0.01)


def shot(hub, name, mode, note=""):
    pump(0.3)
    pm = hub.grab()
    p = os.path.join(out, "%s_%s_live.png" % (name, mode))
    pm.save(p)
    print("%s %dx%d strip_min=%d %s" % (os.path.basename(p), pm.width(), pm.height(),
                                        hub.minimumSizeHint().width(), note), flush=True)


def fresh(mode):
    theme.load_fonts(); theme.set_app_font(APP); theme.set_palette(APP, mode)
    APP.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=False, mode=mode)
    hub.resize(1280, 720); hub.show(); pump(0.4)
    return hub


def traffic():
    for i, (la, lo) in enumerate([(47.60, -122.30), (47.90, -122.10), (47.30, -122.60),
                                  (47.45, -121.90)]):
        eventbus.bus.publish(eventbus.contact("ADS-B", "A%04X" % (0xA000 + i), la, lo,
                                              kind="aircraft", label="N%03dPA" % i, alt=12000))


for mode in ("dark", "sun"):
    eventbus.set_home(None); eventbus.bus.clear(); FETCH.clear()
    hub = fresh(mode)
    hub.open_callsign("ATLAS"); pump(0.5)
    a = hub.page_app("ATLAS")
    traffic(); pump(0.8); a._render()
    shot(hub, "atlas_home_unset", mode, "cover=%s pts=%d fetches=%s" % (
        a._home_cover.shown(), len(a.map.scatter.data), FETCH))
    hub.open_callsign("OPS"); pump(0.3)
    o = hub.page_app("OPS")
    traffic(); pump(0.8); o._refresh_ppi()
    shot(hub, "ops_home_unset", mode, "cover=%s sub=%r" % (o._home_cover.shown(), o.sub.text()))
    # SYSTEM > SETTINGS: type HOME and save (no restart)
    hub.open_callsign("SYSTEM"); pump(0.3)
    m = [w for w in hub.findChildren(MoreApp)][0]
    m.set_home.setText("47.6, -122.3"); m._save_settings(); pump(0.3)
    traffic(); pump(0.8)
    hub.open_callsign("OPS"); pump(0.3); o._refresh_ppi()
    shot(hub, "ops_home_set", mode, "cover=%s sub=%r" % (o._home_cover.shown(), o.sub.text()))
    hub.open_callsign("ATLAS"); pump(0.3); traffic(); pump(0.5); a._render()
    shot(hub, "atlas_home_set", mode, "cover=%s pts=%d fetches=%s" % (
        a._home_cover.shown(), len(a.map.scatter.data), FETCH))
    # ENGAGEMENT: none / tampered / malformed head
    E.reset(); chain.reset_for_tests()
    hub.open_panel("engagement"); pump(0.3); hub.engage_panel.refresh(); pump(0.2)
    shot(hub, "engagement_none", mode, repr(hub.engage_panel.eng_actions.empty.text()))
    ok, why = E.start("job", "ROE-1", ["10.0.0.0/24"], "KD0ABC")
    info = E.chain_info()
    E.authorize_action("net:portscan", "10.0.0.5", kind="ip")
    raw = open(info["path"], "rb").read().replace(b"10.0.0.5", b"10.0.0.6")
    open(info["path"], "wb").write(raw)
    hub.engage_panel.refresh(); pump(0.2)
    shot(hub, "engagement_tampered", mode, repr(hub.engage_panel.eng_chain.text()))
    with open(info["path"][:-len(".jsonl")] + ".head", "wb") as fh:
        fh.write(b"garbage")
    chain.reset_for_tests()
    hub.engage_panel.refresh(); pump(0.2)
    shot(hub, "engagement_malformed_head", mode, repr(hub.engage_panel.eng_chain.text()))
    hub.engage_panel.hide()
    E.reset(); chain.reset_for_tests()
    hub.close(); pump(0.4)
