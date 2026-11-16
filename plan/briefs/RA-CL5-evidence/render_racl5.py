"""RA-CL5 renders at 1280x720, LIVE (fake decoders on PATH, lease seam patched), dark + sun.
idle: PROWL, BABEL, ATLAS, RADIOS panel. stress: ACQUIRING held long, revoke pending, forced free,
FAULT backoff, PROWL-NWR after revoke.   usage: python render_racl5.py <outdir>"""
import os
import sys
import time

import _harness as H
from palisade_qt import radio_arbiter as ra, theme
from palisade_qt.shell import PalisadeHub

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
app = H.APP
SLOW = {"on": False}


def lease(name):
    if SLOW["on"]:
        time.sleep(120)                 # ACQUIRING held long (readsb slow to stop)
    return H.FakeLease(name)


ra._make_lease = lease


def shot(hub, name, mode, note=""):
    H.pump(0.3)
    pm = hub.grab()
    p = os.path.join(out, "%s_%s_live.png" % (name, mode))
    pm.save(p)
    st = ra.arbiter.state()
    b = hub.pages.get("BABEL")
    print("%s %dx%d arbiter=%s strip_min=%d %s %s" % (
        p, pm.width(), pm.height(), st, hub.minimumSizeHint().width(), note,
        ("| BABEL chip=%r banner=%r" % (b._last_status.get("sdr", {}).get("text"), b.busy.text()))
        if b is not None and name.startswith("babel") else ""), flush=True)


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
    ra.arbiter.reset_for_tests()
    hub = fresh(mode)
    hub.open_callsign("PROWL"); H.pump(1.5); shot(hub, "prowl", mode)
    hub.open_callsign("BABEL"); H.pump(1.2); shot(hub, "babel", mode)
    hub.open_callsign("ATLAS"); H.pump(1.2); shot(hub, "atlas", mode)
    hub.open_panel("radios"); H.pump(0.8); shot(hub, "radios", mode)
    hub.close(); H.pump(0.3)

    # stress 1: ACQUIRING held long -> BABEL reports LIVE while the arbiter is ACQUIRING
    ra.arbiter.reset_for_tests()
    SLOW["on"] = True
    hub = fresh(mode)
    hub.open_callsign("BABEL"); H.pump(0.5)
    b = hub.pages["BABEL"]; b.mode_combo.setCurrentText("AIS"); H.pump(0.3)
    b.run_btn.setChecked(True); H.pump(2.0)
    shot(hub, "babel_stress_acquiring", mode)
    hub.open_panel("radios"); H.pump(0.8)
    shot(hub, "radios_stress_acquiring", mode)
    SLOW["on"] = False
    hub.close(); H.pump(0.3)
    ra.arbiter.reset_for_tests()

    # stress 2: SSTV holds (never acknowledges) -> revoke pending -> forced free
    hub = fresh(mode)
    hub.open_callsign("BABEL"); H.pump(0.5)
    b = hub.pages["BABEL"]; b.mode_combo.setCurrentText("SSTV"); H.pump(2.0)
    hub.open_panel("radios"); H.pump(0.5)
    hub.radios_panel.takeover_btn.click(); H.pump(1.0)
    shot(hub, "radios_stress_revoke_pending", mode)
    H.pump(5.0)
    shot(hub, "radios_stress_forced_free", mode, note="(SSTV rtl_fm alive: %s)" % H.children())
    hub.radios_panel.hide() if hasattr(hub.radios_panel, "hide") else None
    hub.open_callsign("BABEL"); H.pump(1.2)
    shot(hub, "babel_stress_sstv_after_forced_free", mode)
    hub.close(); H.pump(0.3)
    ra.arbiter.reset_for_tests()

    # stress 3: FAULT backoff (decoder exits at once)
    d = os.path.join(H.HERE, "fakebin_fail")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rtl_ais"), "w") as f:
        f.write("#!/bin/sh\necho 'usb_claim_interface error -6' >&2\nexit 1\n")
    os.chmod(os.path.join(d, "rtl_ais"), 0o755)
    old = os.environ["PATH"]
    os.environ["PATH"] = d + os.pathsep + old
    hub = fresh(mode)
    hub.open_callsign("BABEL"); H.pump(0.5)
    b = hub.pages["BABEL"]; b.mode_combo.setCurrentText("AIS"); H.pump(0.3)
    b.run_btn.setChecked(True); H.pump(4.0)
    shot(hub, "babel_stress_fault", mode)
    hub.close(); H.pump(0.3)
    os.environ["PATH"] = old
    ra.arbiter.reset_for_tests()

    # stress 4: PROWL NWR revoked -> what does PROWL still say?
    hub = fresh(mode)
    hub.open_callsign("PROWL"); H.pump(0.5)
    hub.pages["PROWL"].switch_subtab("NWR"); H.pump(2.0)
    hub.open_panel("radios"); H.pump(0.3)
    hub.radios_panel.takeover_btn.click(); H.pump(2.0)
    hub.radios_panel.hide(); H.pump(0.5)      # PROWL (NWR) is still the page underneath
    shot(hub, "prowl_stress_nwr_after_revoke", mode,
         note="| PROWL chip=%r" % hub.pages["PROWL"].current_child()._last_status.get("sdr"))
    hub.close(); H.pump(0.3)
