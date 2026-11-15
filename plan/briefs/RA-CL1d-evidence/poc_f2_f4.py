"""RA-CL1d F2: hub/strip minimum width at 999/1000/100000 targets x 3 themes x live/demo, longest owner,
PERMITTED, 99+, focus on SYSTEM. F4: lost -> contact returns; layer hidden; card text each step."""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = sys.argv[1]; sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "tests"))
from test_cl1_screen import _app, _pump, _hub
_app()
import engagement
from palisade_qt import chrome, radio_arbiter
owners = sorted(set(list(radio_arbiter.OWNER_LABELS.values()) + ["PROWL SC"]), key=len)[-2:]
for mode in ("dark", "light", "sun"):
    for demo in (False, True):
        h = _hub(mode=mode, demo=demo); h.state.stop(); out = []
        for n in (999, 1000, 100000):
            engagement.reset(); engagement.start("t", "ROE-1", ["10.%d.%d.%d" % (i >> 16, (i >> 8) & 255, i & 255) for i in range(n)], "op")
            st = chrome.read_engagement(); worst = 0
            for o in owners:
                h.topbar.set_state("DEMO" if demo else "LIVE", ("HELD", o), "PERMITTED", st)
                h.topbar.set_alerts(150); h.topbar.nav_keys["SYSTEM"].setFocus(); _pump(40)
                worst = max(worst, h.minimumSizeHint().width())
            out.append("%d->%r hub_min=%d" % (n, st[1], worst))
        print(mode, "demo" if demo else "live", " | ".join(out))
        engagement.reset(); h.close(); _pump(100)
h = _hub(mode="sun", demo=True); h.open_callsign("ATLAS"); _pump(300)
a = h.pages["ATLAS:inner"]; a._timer.stop(); now = time.time()
def c(i, lbl, kind="aircraft"):
    return {"id": i, "label": lbl, "kind": kind, "x": 3.0, "y": 4.0, "alt": 123456, "spd": 400,
            "severity": "info", "_ts": now, "rng": 5.0, "brg": 37.0}
def card(tag):
    from PySide6 import QtWidgets
    sel = a.feed.view.currentIndex().row()
    print("F4 %-28s selected=%r cursor_row=%d hero=%r sub=%r rows=%s" % (tag, a._selected, sel, a.detail.hero.text(), a.detail.sub.text(),
          [w.text() for w in a.detail.box.findChildren(QtWidgets.QLabel)]))
a._contacts = {"X1": c("X1", "N12345"), "X2": c("X2", "N777")}; a._render(); _pump(50)
row = next(i for i, r in enumerate(a.feed.model.rows) if r["_id"] == "X1"); a.feed.view.setCurrentIndex(a.feed.model.index(row, 0)); _pump(50)
card("selected")
del a._contacts["X1"]; a._render(); _pump(50); card("after vanish")
a._render(); _pump(50); card("next refresh")
a._contacts["X1"] = c("X1", "N12345"); a._render(); _pump(50); card("X1 reported again")
row = next(i for i, r in enumerate(a.feed.model.rows) if r["_id"] == "X1"); a.feed.view.setCurrentIndex(a.feed.model.index(row, 0)); _pump(50)
card("reselected")
a._toggle("aircraft", False); _pump(50); card("aircraft layer hidden")
a._toggle("aircraft", True); _pump(50); card("aircraft layer shown")
a._contacts["X1"]["_ts"] = now - 10 ** 6; a._render(); _pump(50); card("X1 stale (STALE_S)")
h.close(); _pump(100)
