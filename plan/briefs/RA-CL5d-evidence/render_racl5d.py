"""RA-CL5d renders at 1280x720, LIVE (fake decoders on PATH, lease seam patched), dark + sun.
States the brief names: NWR with an rtl_fm that only writes stderr · PROWL after a revoke during a
switch · BABEL after a revoke during a switch · BABEL after PANIC.
usage (repo root): python3 plan/briefs/RA-CL5d-evidence/render_racl5d.py <outdir>"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "RA-CL5c-evidence"))
os.environ["QT_QPA_PLATFORM"] = "offscreen:freetype"   # live seams open (they test == "offscreen")
import _harness as H  # noqa: E402
from palisade_qt import radio_arbiter as ra, theme  # noqa: E402
from palisade_qt.shell import PalisadeHub  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
app = H.APP
REL = {"s": 0.0}
CHATTER = os.path.join(HERE, "..", "RA-CL5c-evidence", "fakebin_chatter")
BASE_PATH = os.environ["PATH"]
EV = os.path.join(HERE, "..", "RA-CL5b-evidence")
TRAP_PATH = os.pathsep.join([os.path.join(EV, "fakebin_trap"), os.path.join(EV, "fakebin_trap_mm"),
                             BASE_PATH])     # SIGTERM-ignoring stages: the old mode still holds at 0.2 s


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


def openers():
    mine = {k.split(":")[0] for k in H.children() if "(Z)" not in k}
    return [p for p in H.procs_named("rtl_fm", "rtl_power", "rtl_ais", "multimon-ng")
            if p.split(":")[0] in mine]


for mode in ("dark", "sun"):
    # 1. NWR with an rtl_fm that only writes stderr (chatter)
    ra.arbiter.reset_for_tests()
    os.environ["PATH"] = CHATTER + os.pathsep + BASE_PATH
    hub = fresh(mode)
    hub.open_callsign("PROWL"); H.pump(0.5)
    p = hub.page_app("PROWL"); p.switch_subtab("NWR"); H.pump(6.0)
    shot(hub, "prowl_nwr_stderr_only", mode, "state=%r hero=%r chip=%r" % (
        p.nwr_state.text(), p.nwr_detail.sub.text(), p._last_status.get("sdr", {}).get("text")))
    hub.close(); H.pump(0.8)
    os.environ["PATH"] = BASE_PATH

    # 2. PROWL after a revoke during a switch (NWR -> FM, release 3 s, revoke 0.2 s in)
    ra.arbiter.reset_for_tests()
    os.environ["PATH"] = TRAP_PATH
    hub = fresh(mode)
    hub.open_callsign("PROWL"); H.pump(0.5)
    p = hub.page_app("PROWL"); p.switch_subtab("NWR"); H.pump(4.0)
    REL["s"] = 3.0
    p.switch_subtab("FM"); H.pump(0.2)
    print("revoke (PROWL, 0.2 s into NWR->FM) ->", ra.arbiter.revoke(), flush=True)
    H.pump(1.0)
    shot(hub, "prowl_revoke_mid_switch", mode, "busy=%r chip=%r swapping=%s openers=%s" % (
        p.busy.text(), p._last_status.get("sdr", {}).get("text"), p.swapping(), openers()))
    H.pump(5.0)
    shot(hub, "prowl_after_revoke_during_switch", mode, "busy=%r chip=%r worker=%s openers=%s" % (
        p.busy.text(), p._last_status.get("sdr", {}).get("text"), p._worker, openers()))
    REL["s"] = 0.0
    hub.close(); H.pump(0.5)

    os.environ["PATH"] = BASE_PATH
    # 3. BABEL after a revoke during a switch (AIS RUN -> SSTV, revoke 0.2 s in)
    ra.arbiter.reset_for_tests()
    os.environ["PATH"] = TRAP_PATH
    hub = fresh(mode)
    hub.open_callsign("BABEL"); H.pump(0.5)
    b = hub.page_app("BABEL"); b.mode_combo.setCurrentText("AIS"); H.pump(0.3)
    b.run_btn.setChecked(True); H.pump(2.5)
    REL["s"] = 3.0
    b.mode_combo.setCurrentText("SSTV"); H.pump(0.2)
    print("revoke (BABEL, 0.2 s into AIS->SSTV) ->", ra.arbiter.revoke(), flush=True)
    H.pump(6.0)
    shot(hub, "babel_after_revoke_during_switch", mode, "busy=%r chip=%r RUN=%s worker=%s openers=%s"
         % (b.busy.text(), b._last_status.get("sdr", {}).get("text"), b.run_btn.isChecked(),
            type(b._worker).__name__ if b._worker else None, openers()))
    REL["s"] = 0.0
    hub.close(); H.pump(0.5)
    os.environ["PATH"] = BASE_PATH

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
print("RENDER DONE", flush=True)
