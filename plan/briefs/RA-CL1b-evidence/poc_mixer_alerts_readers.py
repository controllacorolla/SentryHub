import os, sys, time, signal, subprocess, json, threading
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = "/Users/daltonhayes/SentryHub"
sys.path[:0] = [REPO, REPO + "/tests"]
os.chdir(REPO)
from test_cl1_screen import _app, _pump, _hub  # noqa
from PySide6 import QtCore, QtWidgets
from palisade_qt import procs, chrome, eventbus, panels
from palisade_qt.kit import topbar as tb
from palisade_qt.kit.feed import FeedTable
R = {}

# --- P2b: pipeline member daemonizes (fork + setsid, parent exits) -> reparented to init
py = sys.executable
d = "import os,time\nif os.fork(): os._exit(0)\nos.setsid(); time.sleep(307)"
proc = subprocess.Popen(["sh", "-c", "%s -c '%s' ; sleep 308" % (py, d)], start_new_session=True)
time.sleep(1.0)
orph = [int(x) for x in subprocess.run(["pgrep", "-f", "sleep\\(307\\)"], capture_output=True, text=True).stdout.split()]
hub = _hub(demo=False)
hub._list_children = lambda: [proc.pid]
hub.panic()
R["P2b_daemonized"] = {"orphan": orph, "alive_after": [p for p in orph if procs.alive(p)],
                       "banner": hub.panic_banner.text()}
for p in orph:
    try: os.kill(p, 9)
    except OSError: pass
proc.wait()

# --- M: mixer that hangs 2 s on every call, then fails; UI responsiveness + state
class Sink:
    backend = "fake"; available = True
    def __init__(s, hang=0.0, ok=True, read=(50, False)):
        s.hang, s.ok, s.read, s.muted = hang, ok, read, read[1]
    def set_volume(s, p): time.sleep(s.hang); return s.ok
    def set_mute(s, m):
        time.sleep(s.hang)
        if s.ok: s.muted = m
        return s.ok
    def get(s):
        time.sleep(s.hang)
        return (s.read[0], s.muted) if s.read else (None, None)
bar = tb.TopBar(mode="dark", audio=Sink(hang=2.0))
t0 = time.monotonic(); _pump(50); bar.toggle_mute(); dt = time.monotonic() - t0
R["M_hang"] = {"toggle_ui_block_s": round(dt, 2), "checked_immediately": bar.mute.isChecked()}
end = time.time() + 8
while time.time() < end and bar.mixer.pending: _pump(50)
R["M_hang"]["after"] = bar.audio_state(); R["M_hang"]["checked"] = bar.mute.isChecked()
# failing mixer: set refused, read says not muted
bar2 = tb.TopBar(mode="dark", audio=Sink(ok=False))
end = time.time() + 3
while time.time() < end and bar2.mixer.pending: _pump(30)
bar2.toggle_mute()
end = time.time() + 3
while time.time() < end and bar2.mixer.pending: _pump(30)
R["M_fail"] = {"state": bar2.audio_state(), "checked": bar2.mute.isChecked(), "text": bar2.mute.text()}
# mixer that lies: set returns OK but read-back says unmuted
class Liar(Sink):
    def set_mute(s, m): return True
bar3 = tb.TopBar(mode="dark", audio=Liar())
end = time.time() + 3
while time.time() < end and bar3.mixer.pending: _pump(30)
bar3.toggle_mute()
end = time.time() + 3
while time.time() < end and bar3.mixer.pending: _pump(30)
R["M_liar"] = {"state": bar3.audio_state(), "checked": bar3.mute.isChecked(), "text": bar3.mute.text()}
# rapid M presses while the mixer hangs: each press computes want from last CONFIRMED state
bar4 = tb.TopBar(mode="dark", audio=Sink(hang=0.5))
end = time.time() + 3
while time.time() < end and bar4.mixer.pending: _pump(30)
bar4.toggle_mute(); bar4.toggle_mute()      # operator presses M twice: intends mute then unmute
end = time.time() + 5
while time.time() < end and bar4.mixer.pending: _pump(30)
R["M_double_press"] = {"final": bar4.audio_state(), "sink_muted": bar4.audio.muted}

# --- A: alert arrives mid-drawer; ack acts on selected id
panels.reset_alert_store()
store = panels.alert_store()
drawer = panels.AlertsDrawer("dark", None, store=store)
for i in range(3):
    eventbus.bus.publish(eventbus.alert("T", "alert %d" % i, severity="warn"))
_pump(30)
drawer.open() if hasattr(drawer, "open") else drawer.show(); _pump(30)
drawer.focus_first(); drawer.table.move_cursor(1); _pump(10)
sel = drawer.selected_id(); seltext = store.get(sel)["text"]
eventbus.bus.publish(eventbus.alert("T", "NEW arrival", severity="alert")); _pump(30)
drawer.ack_selected()
acked = [a["text"] for a in store.items if a["acked"]]
R["A_mid_drawer"] = {"selected": seltext, "acked": acked}
# 600 unacked alerts -> none dropped; drawer shows all?
for i in range(600):
    eventbus.bus.publish(eventbus.alert("T", "flood %d" % i, severity="info"))
_pump(30)
R["A_flood"] = {"items": len(store.items), "unacked": store.unacked(), "drawer_rows": drawer.table.model.rowCount(),
                "strip_text": None}

# --- U: readers raise -> UNKNOWN
import txguard, engagement
orig_a, orig_i = txguard.is_armed, engagement.info
txguard.is_armed = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
engagement.info = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
hub.state.poll(); _pump(20)
R["U_readers_raise"] = {"tx": hub.topbar.slots["tx"].painted_text(), "tx_shape": hub.topbar.slots["tx"].glyph.shape(),
                        "eng": hub.topbar.slots["engagement"].painted_text(),
                        "eng_shape": hub.topbar.slots["engagement"].glyph.shape()}
# engagement.info returns a non-dict / scope None -> ?
engagement.info = lambda: {"active": True, "scope": None, "name": None}
hub.state.poll(); _pump(20)
R["U_active_no_scope"] = hub.topbar.slots["engagement"].painted_text()
engagement.info = lambda: {"active": True, "scope": ["NONE"], "name": "x"}
hub.state.poll(); _pump(20)
R["U_scope_named_NONE"] = [hub.topbar.slots["engagement"].painted_text(), hub.topbar.slots["engagement"].glyph.shape()]
engagement.info = lambda: {"active": True, "scope": "10.0.0.0/24", "name": "x"}   # a str, not a list
hub.state.poll(); _pump(20)
R["U_scope_is_string"] = hub.topbar.slots["engagement"].painted_text()
txguard.is_armed, engagement.info = orig_a, orig_i
# radio arbiter raises on owner()? ChromeState caches via signal only
from palisade_qt import radio_arbiter
R["U_radio_reader"] = "signal-driven; owner() read once at init"

# --- L: FeedTable cursor restore by row index after reset (detail diverges)
ft = FeedTable([("id", "ID"), ("v", "V")]); ft.resize(400, 300); ft.show()
shown = []
ft.selected.connect(lambda r: shown.append(r["id"]))
ft.model.set_rows([{"id": "A"}, {"id": "B"}, {"id": "C"}]); _pump(20)
ft.move_cursor(1); ft.move_cursor(0); _pump(10)          # cursor on B
ft.model.set_rows([{"id": "X"}, {"id": "A"}, {"id": "B"}, {"id": "C"}]); _pump(20)
row = ft.view.currentIndex().row()
R["L_row_restore"] = {"detail_shows": shown[-1], "highlighted": ft.model.rows[row]["id"]}

print(json.dumps(R, indent=1, default=str))
hub.close(); _pump(50)
