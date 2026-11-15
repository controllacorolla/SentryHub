#!/usr/bin/env python3
"""Render the CL2 gate states at exactly 1280x720.

    python3 plan/briefs/CL2-renders/render.py <outdir> <dark|light|sun> <live|demo>

For each gate state — disarmed, armed, armed + unlocked + engaged, expired engagement — renders
FORGE (BUS: engagement card, RADIO: replay banner), RECON (WIFI, NET), SYSTEM › BENCH, and the TX
and ENGAGEMENT panels. Headless (Qt offscreen); opens no radio and spawns nothing.

To show the PERMITTED states the renderer stands in for the operator's SAVED opt-ins (bench and
replay tx_enabled = True) and the operator profile (KD0ABC). Nothing here changes a gate: the
engines decide every state shown. PNGs are git-ignored; regenerate with this script.
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, REPO)

STATES = ("disarmed", "armed", "unlocked-engaged", "expired")


def main(out, mode, run):
    os.makedirs(out, exist_ok=True)
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication([])
    import engagement
    import txguard
    from palisade_qt import theme
    from palisade_qt.shell import PalisadeHub
    theme.load_fonts()
    theme.set_app_font(app)
    theme.set_palette(app, mode)
    app.setStyleSheet(theme.qss(mode))
    engagement._profile_operator = lambda: "KD0ABC"          # stand-in operator profile
    real_now = engagement._now

    def pump(ms):
        t = time.time()
        while time.time() - t < ms / 1000:
            app.processEvents()
            time.sleep(0.01)

    hub = PalisadeHub(demo=(run == "demo"), mode=mode)
    hub._list_children = lambda: []
    hub.resize(1280, 720)
    hub.show()
    pump(500)
    sizes = {}

    def shot(tag):
        hub.resize(1280, 720)
        pump(150)
        pm = hub.grab()
        pm.save(os.path.join(out, "%s_%s_%s.png" % (tag, mode, run)))
        sizes[tag] = [pm.width(), pm.height()]

    def set_state(st):
        engagement._now = real_now
        txguard.reset_session()
        engagement.reset()
        if st in ("armed", "unlocked-engaged", "expired"):
            txguard.arm(True)
        if st in ("unlocked-engaged", "expired"):
            txguard.unlock_session(True)
            engagement.start("NightWatch", "ROE-42", ["10.0.0.0/24", "AA:BB:CC:*",
                                                      "can0:0x700-0x7FF"], None)
        if st == "expired":
            t_exp = time.time() + 9 * 3600
            engagement._now = lambda: t_exp
            engagement.is_active()                  # the engine notices -> listeners fire
        pump(200)

    for st in STATES:
        set_state(st)
        hub.open_callsign("FORGE")
        forge = hub.pages["FORGE"]
        forge.replay_card._saved = lambda: {"tx_enabled": True, "tx_region": "US"}
        for tab in ("BUS", "RADIO"):
            forge.switch_subtab(tab)
            forge.refresh_gates()
            pump(300)
            shot("%s_forge-%s" % (st, tab.lower()))
        hub.open_callsign("RECON")
        recon = hub.pages["RECON"]
        for tab in ("WIFI", "NET"):
            recon.switch_subtab(tab)
            pump(300)
            shot("%s_recon-%s" % (st, tab.lower()))
        hub.open_callsign("BENCH")
        bench = hub.pages["BENCH"]
        bench._saved = lambda: {"tx_enabled": True}
        bench.ack.setChecked(True)
        bench._refresh_gate()
        pump(300)
        shot("%s_system-bench" % st)
        for panel in ("tx", "engagement"):
            hub.open_callsign("OPS")
            hub.open_panel(panel)
            pump(200)
            shot("%s_panel-%s" % (st, panel))
            hub.open_panel(panel)
            pump(50)
    engagement._now = real_now
    txguard.reset_session()
    engagement.reset()
    with open(os.path.join(out, "sizes_%s_%s.json" % (mode, run)), "w") as f:
        json.dump(sizes, f, indent=1)
    bad = {k: v for k, v in sizes.items() if v != [1280, 720]}
    print(mode, run, len(sizes), "shots; not 1280x720:", bad or "none")
    hub.close()
    pump(300)
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
