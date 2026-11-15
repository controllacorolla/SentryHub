"""RA-CL1b PoCs: PANIC (real pipelines, SIGTERM-ignoring, orphan), BENCH TX slot, popup, freeze."""
import os, sys, time, signal, subprocess, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = "/Users/daltonhayes/SentryHub"
sys.path[:0] = [REPO, REPO + "/tests"]
os.chdir(REPO)
from test_cl1_screen import _app, _pump, _hub  # noqa
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from palisade_qt import procs, chrome
import txguard

R = {}

def tree(pid):
    out = subprocess.run(["pgrep", "-g", str(pid)], capture_output=True, text=True).stdout
    return sorted(set(int(x) for x in out.split()) | set(procs.descendants(pid)))

def wait(c, t=5):
    e = time.time() + t
    while not c() and time.time() < e:
        _pump(20)
    return c()

def kill_all(pids):
    for p in pids:
        try: os.kill(p, signal.SIGKILL)
        except OSError: pass

# --- P1: real pipeline whose members ignore SIGTERM, plus a TERM-ignoring sh wrapper
cmd = "trap '' TERM; sleep 301 | sh -c \"trap '' TERM; sleep 302\""
proc = subprocess.Popen(["sh", "-c", cmd], start_new_session=True)
wait(lambda: len(tree(proc.pid)) >= 3)
members = tree(proc.pid)
hub = _hub(demo=False)
hub._list_children = lambda: [proc.pid]
t0 = time.monotonic()
hub.panic()
dt = time.monotonic() - t0
alive_after = [p for p in members if procs.alive(p)]
R["P1_term_ignoring_pipeline"] = {"members": members, "alive_after": alive_after,
                                  "panic_blocking_s": round(dt, 2), "banner": hub.panic_banner.text()}
kill_all(members); proc.wait()

# --- P2: a pipeline member that daemonizes (double fork -> reparented, new session)
proc = subprocess.Popen(["sh", "-c", "(setsid sleep 303 &) ; sleep 304"], start_new_session=True)
time.sleep(0.5)
orphan = [int(x) for x in subprocess.run(["pgrep", "-f", "sleep 303"], capture_output=True, text=True).stdout.split()]
hub._list_children = lambda: [proc.pid]
hub.panic()
R["P2_daemonized_member"] = {"orphan": orphan, "orphan_alive": [p for p in orphan if procs.alive(p)],
                             "banner": hub.panic_banner.text()}
kill_all(orphan); proc.wait()

# --- P3: PANIC through the REAL child listing (no seam) with real children of this process
hub._list_children = procs.child_pids if False else __import__("palisade_qt.shell", fromlist=["x"]).child_pids
p3 = subprocess.Popen(["sh", "-c", "sleep 305 | sleep 306"], start_new_session=True)
wait(lambda: len(tree(p3.pid)) >= 2)
m3 = tree(p3.pid)
hub.panic()
R["P3_real_child_listing"] = {"members": m3, "alive_after": [p for p in m3 if procs.alive(p)],
                              "banner": hub.panic_banner.text()}
kill_all(m3); p3.wait()

# --- P4: TX slot after PANIC with BENCH ack held; then is the ack checkbox still checked?
hub._list_children = lambda: []
hub.open_callsign("BENCH"); _pump(80)
bench = hub.pages["BENCH"]
bench.ack.setChecked(True); _pump(40); hub.state.poll()
before = hub.topbar.slots["tx"].painted_text()
hub.panic(); _pump(40)
R["P4_bench_after_panic"] = {"before": before, "after": hub.topbar.slots["tx"].painted_text(),
                             "ack_checked": bench.ack.isChecked(), "tx_btn_enabled": bench.tx_btn.isEnabled(),
                             "banner": hub.panic_banner.text()}
# leave SYSTEM page: does slot still say PERMITTED while bench not visible?
hub.open_callsign("OPS"); _pump(40); hub.state.poll()
R["P4_bench_after_panic"]["slot_on_other_page"] = hub.topbar.slots["tx"].painted_text()
# txguard armed + bench: slot shows ARMED only; PANIC disarm
txguard.arm(True); hub.state.poll()
R["P4_bench_after_panic"]["armed_plus_permit"] = hub.topbar.slots["tx"].painted_text()
txguard.arm(False)
bench.ack.setChecked(False); _pump(20)

# --- P5: PANIC with combo popup open (real key event to the popup)
hub.open_callsign("BENCH"); _pump(60)
hub.show(); _pump(100)
bench.band.showPopup(); _pump(100)
popup = QtWidgets.QApplication.activePopupWidget()
n_before = len(hub.alerts.items)
target = popup or bench.band
QTest.keyClick(target, QtCore.Qt.Key_Escape, QtCore.Qt.ShiftModifier); _pump(60)
R["P5_combo_popup_panic"] = {"popup": type(popup).__name__ if popup else None,
                             "panic_ran": len(hub.alerts.items) > n_before,
                             "popup_after": type(QtWidgets.QApplication.activePopupWidget()).__name__}
# QMenu exec'd modally with no parent (context menu) -> deliver F12
n_before = len(hub.alerts.items)
menu = QtWidgets.QMenu(); menu.addAction("x")
QtCore.QTimer.singleShot(150, lambda: QTest.keyClick(QtWidgets.QApplication.activePopupWidget() or menu, QtCore.Qt.Key_F12))
QtCore.QTimer.singleShot(1500, menu.close)
menu.exec(QtCore.QPoint(100, 100))
R["P5_menu_exec_panic"] = {"panic_ran": len(hub.alerts.items) > n_before}
# a tooltip-less, separate top-level window of this app (e.g. a standalone page) has focus
n_before = len(hub.alerts.items)
w = QtWidgets.QWidget(); w.show(); w.activateWindow(); w.setFocus(); _pump(50)
QTest.keyClick(w, QtCore.Qt.Key_Escape, QtCore.Qt.ShiftModifier); _pump(30)
R["P5_other_toplevel_panic"] = {"panic_ran": len(hub.alerts.items) > n_before}
w.close()

print(json.dumps(R, indent=1, default=str))
hub.close(); _pump(100)
