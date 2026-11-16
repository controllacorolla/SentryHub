"""RA-CL5c renders at 1280x720, LIVE (fake decoders on PATH, lease seam patched), dark + sun.
States the brief names: NWR with a wedged rtl_fm · PROWL during a slow sub-mode switch ·
RADIOS after a hidden-ATLAS revoke · BABEL after PANIC.
usage (repo root): python3 plan/briefs/RA-CL5c-evidence/render_racl5c.py <outdir>"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["QT_QPA_PLATFORM"] = "offscreen:freetype"   # live seams open (they test == "offscreen")
import _harness as H  # noqa: E402
from palisade_qt import radio_arbiter as ra, theme  # noqa: E402
from palisade_qt.shell import PalisadeHub  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
app = H.APP
REL = {"s": 0.0}
WEDGED = os.path.join(HERE, "fakebin_wedged")
os.makedirs(WEDGED, exist_ok=True)
with open(os.path.join(WEDGED, "rtl_fm"), "w") as f:
    f.write("#!/bin/sh\nexec sleep 600\n")
os.chmod(os.path.join(WEDGED, "rtl_fm"), 0o755)
BASE_PATH = os.environ["PATH"]


class L(H.FakeLease):
    def release(self):
        time.sleep(REL["s"])


ra._make_lease = lambda name: L(name)
import txguard  # noqa: E402
import engagement  # noqa: E402
txguard.arm = lambda on: None
engagement.end = lambda: None


def shot(hub, name, mode, note=""):
    H.pump(0.3)
    pm = hub.grab()
    p = os.path.join(out, "%s_%s_live.png" % (name, mode))
    pm.save(p)
    print("%s %dx%d arbiter=%s %s" % (os.path.basename(p), pm.width(), pm.height(),
                                     ra.arbiter.state(), note), flush=True)


def fresh(mode):
    theme.load_fonts()
    theme.set_app_font(app)
    theme.set_palette(app, mode)
    app.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=False, mode=mode)
    hub.resize(1280, 720)
    hub.show()
    H.pump(0.4)
    return hub


for mode in ("dark", "sun"):
    # 1. NWR with a wedged rtl_fm (alive, no samples)
    ra.arbiter.reset_for_tests()
    os.environ["PATH"] = WEDGED + os.pathsep + BASE_PATH
    hub = fresh(mode)
    hub.open_callsign("PROWL"); H.pump(0.5)
    p = hub.page_app("PROWL"); p.switch_subtab("NWR"); H.pump(5.0)
    shot(hub, "prowl_nwr_wedged", mode, "state=%r chip=%r procs=%s" % (
        p.nwr_state.text(), p._last_status.get("sdr", {}).get("text"), H.procs_named("rtl_fm")))
    hub.close(); H.pump(0.8)
    os.environ["PATH"] = BASE_PATH

    # 2. PROWL during a slow sub-mode switch (lease release = 30 s)
    ra.arbiter.reset_for_tests()
    hub = fresh(mode)
    hub.open_callsign("PROWL"); H.pump(0.5)
    p = hub.page_app("PROWL"); p.switch_subtab("NWR"); H.pump(3.0)
    REL["s"] = 30.0
    p.switch_subtab("FM"); H.pump(1.5)
    shot(hub, "prowl_slow_switch", mode, "busy=%r chip=%r swapping=%s" % (
        p.busy.text(), p._last_status.get("sdr", {}).get("text"), p.swapping()))
    REL["s"] = 0.0
    hub.close(); H.pump(0.5)

    # 3. RADIOS after a hidden-ATLAS revoke
    ra.arbiter.reset_for_tests()
    from palisade_qt.atlas import AtlasApp
    hub = fresh(mode)
    hub.open_callsign("ATLAS"); H.pump(0.8)
    a = hub.pages["ATLAS"].child(AtlasApp)
    a._layer_btns["vessel"].click(); H.pump(3.0)
    hub.show_page("OPS"); H.pump(1.0)
    hub.open_panel("radios"); H.pump(0.3)
    hub.radios_panel.takeover_btn.click(); H.pump(3.0)
    shot(hub, "radios_after_atlas_hidden_revoke", mode, "rtl_ais=%s hist=%s" % (
        H.procs_named("rtl_ais"), [(r["event"], r["owner"]) for r in hub.radios_panel._history[:4]]))
    hub.radios_panel.hide(); H.pump(0.3)
    hub.close(); H.pump(0.5)

    # 4. BABEL after PANIC
    ra.arbiter.reset_for_tests()
    hub = fresh(mode)
    hub.open_callsign("BABEL"); H.pump(0.5)
    b = hub.page_app("BABEL"); b.mode_combo.setCurrentText("AIS"); H.pump(0.3)
    b.run_btn.setChecked(True); H.pump(2.0)
    did = hub.panic(); H.pump(3.0)
    shot(hub, "babel_after_panic", mode, "banner=%r children=%s RUN=%s" % (
        " · ".join(did), H.children(), b.run_btn.isChecked()))
    hub.close(); H.pump(0.5)
