"""Shell-level quit with live radio pages open (fake decoders on PATH): BABEL running (RUN), PROWL
NWR, PRISM, ATLAS. Quit, then report exit code, stderr, and any surviving child process."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = r'''
import os, sys, time
sys.path.insert(0, %(here)r)
import _harness as H
from PySide6 import QtCore
from palisade_qt import radio_arbiter, shell
radio_arbiter._make_lease = lambda name: H.FakeLease(name)
hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720); hub.show(); H.pump(0.5)
for cs in ("PRISM", "ATLAS", "PROWL"):
    hub.open_callsign(cs); H.pump(0.8)
hub.pages["PROWL"].switch_subtab("NWR"); H.pump(1.5)
hub.open_callsign("BABEL"); H.pump(0.5)
b = hub.pages["BABEL"]; b.mode_combo.setCurrentText("AIS"); H.pump(0.3); b.run_btn.setChecked(True)
H.pump(2.0)
H.log("before quit: arbiter=%%s children=%%s" %% (radio_arbiter.arbiter.state(), H.children()))
print("CHILDPIDS", " ".join(c.split(":")[0] for c in H.children()), flush=True)
t0 = time.monotonic(); hub.close()
H.log("hub.close() took %%.2fs" %% (time.monotonic() - t0))
QtCore.QTimer.singleShot(100, H.APP.quit); H.APP.exec()
H.log("after quit: arbiter=%%s children=%%s" %% (radio_arbiter.arbiter.state(), H.children()))
'''
r = subprocess.run([sys.executable, "-c", CODE % {"here": HERE}], capture_output=True, text=True,
                   timeout=90, cwd=HERE)
pids = []
for ln in r.stdout.splitlines():
    if ln.startswith("CHILDPIDS"):
        pids = ln.split()[1:]
    else:
        print(ln)
print("rc=%s" % r.returncode)
err = [ln for ln in r.stderr.splitlines() if "QStandardPaths" not in ln and "propagateSize" not in ln]
print("stderr:", " | ".join(err)[:800] or "-")
alive = [p for p in pids if os.path.exists("/proc/%s" % p)]
print("children of the dead hub still alive:", alive or "none")
