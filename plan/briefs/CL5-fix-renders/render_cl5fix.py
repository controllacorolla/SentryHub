"""CL5-fix renders at 1280x720, LIVE (RA-CL5's fake decoders on PATH, lease seam patched),
dark + sun: the screens the fix touched, in the states the audit flagged.
usage (repo root): QT_QPA_PLATFORM=offscreen:freetype python3 plan/briefs/CL5-fix-renders/render_cl5fix.py <outdir>"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "RA-CL5-evidence"))
os.environ["QT_QPA_PLATFORM"] = "offscreen:freetype"   # live seams open (they test == "offscreen")
import _harness as H  # noqa: E402
from palisade_qt import radio_arbiter as ra, theme  # noqa: E402
from palisade_qt.shell import PalisadeHub  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
app = H.APP
SLOW = {"on": False}


def lease(name):
    if SLOW["on"]:
        time.sleep(30)                 # ACQUIRING held long (readsb slow to stop)
    return H.FakeLease(name)


ra._make_lease = lease


def shot(hub, name, mode, note=""):
    H.pump(0.3)
    pm = hub.grab()
    p = os.path.join(out, "%s_%s_live.png" % (name, mode))
    pm.save(p)
    print("%s %dx%d arbiter=%s %s" % (p, pm.width(), pm.height(), ra.arbiter.state(), note),
          flush=True)


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
    # BABEL during a long ACQUIRING: no LIVE, no decodes, says ACQUIRING
    ra.arbiter.reset_for_tests()
    SLOW["on"] = True
    hub = fresh(mode)
    hub.open_callsign("BABEL"); H.pump(0.5)
    b = hub.page_app("BABEL"); b.mode_combo.setCurrentText("AIS"); H.pump(0.3)
    b.run_btn.setChecked(True); H.pump(2.0)
    shot(hub, "babel_acquiring", mode, "children=%s chip=%r" % (
        H.children(), b._last_status.get("sdr", {}).get("text")))
    SLOW["on"] = False
    hub.close(); H.pump(0.5)
    ra.arbiter.reset_for_tests()

    # PROWL NWR live, then after the operator frees the radio (N2)
    hub = fresh(mode)
    hub.open_callsign("PROWL"); H.pump(0.5)
    p = hub.page_app("PROWL"); p.switch_subtab("NWR"); H.pump(2.5)
    shot(hub, "prowl_nwr_live", mode, "state=%r" % p.nwr_state.text())
    hub.open_panel("radios"); H.pump(0.3)
    hub.radios_panel.takeover_btn.click(); H.pump(2.0)
    hub.radios_panel.hide(); H.pump(1.0)
    shot(hub, "prowl_nwr_after_revoke", mode, "state=%r children=%s" % (
        p.nwr_state.text(), H.children()))
    hub.close(); H.pump(0.5)
    ra.arbiter.reset_for_tests()

    # PANIC with BABEL running AIS: radio released, RUN unticked, nothing respawns (N3)
    hub = fresh(mode)
    hub.open_callsign("BABEL"); H.pump(0.5)
    b = hub.page_app("BABEL"); b.mode_combo.setCurrentText("AIS"); H.pump(0.3)
    b.run_btn.setChecked(True); H.pump(2.0)
    import txguard
    import engagement
    txguard.arm = lambda on: None
    engagement.end = lambda: None
    did = hub.panic(); H.pump(3.0)
    shot(hub, "babel_after_panic", mode, "banner=%r children=%s" % (" · ".join(did), H.children()))
    hub.close(); H.pump(0.5)
    ra.arbiter.reset_for_tests()

# ---- CL5-fix2 (RA-CL5b) ------------------------------------------------------------------
REL = {"s": 0.0}


class SlowRelease(H.FakeLease):
    def release(self):
        super().release()
        time.sleep(REL["s"])


ra._make_lease = lambda name: SlowRelease(name)

for mode in ("dark", "sun"):
    # N-a: AIS on, operator leaves ATLAS, then frees the radio from RADIOS: hidden ATLAS reaps
    # rtl_ais and releases (no forced free); RADIOS history shows RELEASE, not a FORCED FREE
    ra.arbiter.reset_for_tests()
    hub = fresh(mode)
    hub.open_callsign("ATLAS"); H.pump(0.5)
    a = hub.page_app("ATLAS")
    a._layer_btns["vessel"].click(); H.pump(2.5)
    hub.open_callsign("OPS"); H.pump(0.5)
    hub.open_panel("radios"); H.pump(0.3)
    hub.radios_panel.takeover_btn.click(); H.pump(2.0)
    shot(hub, "radios_after_atlas_hidden_revoke", mode, "children=%s hist=%s" % (
        H.children(), [r["event"] for r in hub.radios_panel.hist_feed.model.rows][:3]))
    hub.radios_panel.hide()
    hub.close(); H.pump(0.5)

    # N-c: NWR -> FM while the old lease takes 3.5 s to release: the GUI stays live, NWR says
    # NOT MONITORING, the page says it is waiting for the radio
    ra.arbiter.reset_for_tests()
    hub = fresh(mode)
    hub.open_callsign("PROWL"); H.pump(0.5)
    p = hub.page_app("PROWL"); p.switch_subtab("NWR"); H.pump(2.5)
    REL["s"] = 3.5
    t0 = time.time()
    p.switch_subtab("FM")
    took = time.time() - t0
    H.pump(0.8)
    shot(hub, "prowl_switch_waiting", mode, "gui_block=%.3fs busy=%r" % (took, p.busy.text()))
    H.pump(5.0)
    shot(hub, "prowl_switch_done", mode, "arbiter=%s busy=%r" % (ra.arbiter.state(), p.busy.text()))
    REL["s"] = 0.0
    hub.close(); H.pump(0.5)
    ra.arbiter.reset_for_tests()
