#!/usr/bin/env python3
"""Render every page, every sub-tab and every shell panel at exactly 1280x720.

    python3 plan/briefs/CL1-renders/render.py <outdir> <dark|light|sun> <live|demo>

Writes one PNG per view plus sizes_<theme>_<mode>.json (grab size and the hub's minimum size hint
for each view). Headless (Qt offscreen); opens no radio. PNGs are git-ignored in this repo, so the
image sets are regenerated with this script rather than committed.
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, REPO)


def main(out, mode, run):
    os.makedirs(out, exist_ok=True)
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication([])
    from palisade_qt import theme, ops
    from palisade_qt.shell import PalisadeHub
    theme.load_fonts()
    theme.set_app_font(app)
    theme.set_palette(app, mode)
    app.setStyleSheet(theme.qss(mode))

    def pump(ms):
        t = time.time()
        while time.time() - t < ms / 1000:
            app.processEvents()
            time.sleep(0.01)

    hub = PalisadeHub(demo=(run == "demo"), mode=mode)
    hub.resize(1280, 720)
    hub.show()
    pump(500)
    sizes = {}

    def shot(tag):
        hub.resize(1280, 720)
        pump(120)
        pm = hub.grab()
        pm.save(os.path.join(out, "%s_%s_%s.png" % (tag, mode, run)))
        hint = hub.minimumSizeHint()
        sizes[tag] = [pm.width(), pm.height(), hint.width(), hint.height()]

    for name, _label in ops.CALLSIGNS:
        hub.open_callsign(name)
        pump(900 if run == "demo" else 400)
        page = hub.pages[name]
        tabs = page.subtabs()
        if not tabs:
            shot(name.lower())
        for t in tabs:
            page.switch_subtab(t)
            pump(700 if run == "demo" else 300)
            shot("%s-%s" % (name.lower(), t.lower().replace(" ", "")))
    for panel in ("radios", "engagement", "alerts", "keys", "palette"):
        hub.open_callsign("OPS")
        hub.open_panel(panel)
        pump(200)
        shot("panel-" + panel)
        hub.open_panel(panel)
        pump(50)
    # stress (CL1-fix): an open engagement with a six-target scope, the radio held, a dozen alerts
    import engagement
    from palisade_qt import eventbus, radio_arbiter
    engagement.start("Operation LONG NAME 2026", "ROE-17/B",
                     ["192.168.100.0/24", "10.0.0.*", "AA:BB:CC:*", "Net-*", "172.16.0.0/12",
                      "Corp-Guest"], "N0CALL")
    radio_arbiter.arbiter.changed.emit("PROWL-SCAN")
    for i in range(12):
        eventbus.bus.publish(eventbus.alert("SWEEP", "stress alert %d — unknown emitter" % i,
                                            severity="alert" if i % 3 == 0 else "warn"))
    hub.state.poll()
    hub.open_callsign("OPS")
    pump(300)
    shot("stress-ops")
    for panel in ("engagement", "alerts", "radios"):
        hub.open_panel(panel)
        pump(250)
        shot("stress-panel-" + panel)
        hub.open_panel(panel)
        pump(50)
    engagement.end()
    radio_arbiter.arbiter.changed.emit("")
    with open(os.path.join(out, "sizes_%s_%s.json" % (mode, run)), "w") as f:
        json.dump(sizes, f, indent=1)
    bad = {k: v for k, v in sizes.items() if v[0] != 1280 or v[1] != 720}
    print(mode, run, len(sizes), "shots; not 1280x720:", bad or "none")
    hub.close()
    pump(300)
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
