"""CL4 renders: the honest-state screens at 1280x720, dark + sun, LIVE (no hardware on the render
host, which is exactly the state CL4 is about). usage: python render_cl4.py <repo> <outdir> <tag>
Run once on main (tag=before) and once on the branch (tag=after)."""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PALISADE_OFFLINE"] = "1"
repo, out, tag = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo); os.chdir(repo)
os.makedirs(out, exist_ok=True)
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme, eventbus
from palisade_qt.shell import PalisadeHub


def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents(); time.sleep(0.01)


def more(hub, sub):
    hub.open_callsign("MORE"); pump(300)
    m = hub.pages["MORE"]
    m.switch_subtab(sub); pump(200)
    if sub == "SITREP":
        m._gen_sitrep()
    if sub == "ASSISTANT":
        m.asst_input.setText("any alerts?"); m._ask()
        m.asst_input.setText("what's the weather?"); m._ask()
    pump(200)


for mode in ("dark", "sun"):
    theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app, mode)
    app.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=False, mode=mode); hub.resize(1280, 720); hub.show(); pump(500)
    # one real alert, then map traffic: before CL4 it scrolled out of the assistant's window
    eventbus.bus.publish(eventbus.alert("PROWL", "NWR: Tornado Warning (test)", severity="alert"))
    shots = (("ops", lambda: hub.open_callsign("OPS")),
             ("sweep", lambda: hub.open_callsign("SWEEP")),
             ("prism", lambda: hub.open_callsign("PRISM")),
             ("prowl", lambda: hub.open_callsign("PROWL")),
             ("atlas", lambda: hub.open_callsign("ATLAS")),
             ("overwatch", lambda: hub.open_callsign("OVERWATCH")),
             ("recon_wifi", lambda: hub.open_callsign("RECON")),
             ("forge", lambda: hub.open_callsign("FORGE")),
             ("bench", lambda: hub.open_callsign("BENCH")),
             ("settings", lambda: more(hub, "SETTINGS")),
             ("assistant", lambda: more(hub, "ASSISTANT")),
             ("sitrep", lambda: more(hub, "SITREP")),
             ("mesh", lambda: more(hub, "MESH")),
             ("engagement", lambda: hub.open_panel("engagement")))
    for name, act in shots:
        try:
            act(); pump(1500)
            pm = hub.grab(); p = "%s/%s_%s_live_%s.png" % (out, name, mode, tag); pm.save(p)
            print(p, pm.width(), pm.height())
            if name == "engagement":
                hub.open_panel("engagement"); pump(200)          # toggle closed
        except Exception as e:
            print("FAIL", name, mode, repr(e)[:200])
    hub.close(); pump(200)
