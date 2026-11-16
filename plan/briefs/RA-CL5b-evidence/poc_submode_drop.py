"""PROWL _switch_submode: stop() + wait(3000) on the GUI thread, then `self._worker = None` even
when the wait timed out. With a lease release that takes 3.5 s (sudo systemctl start readsb on a
busy CM5), is the still-running QThread dropped (GC'd while running -> Qt aborts the process)?
Run in a child process so an abort is observable as rc/stderr."""
import subprocess
import sys
import os
HERE = os.path.dirname(os.path.abspath(__file__))
REL = float(sys.argv[1]) if len(sys.argv) > 1 else 3.5
TRAP = len(sys.argv) > 2 and sys.argv[2] == "trap"
CODE = r'''
import sys, time, gc, os
REL = %(rel)r

sys.path.insert(0, %(here)r)
import _harness as H
if %(trap)r:   # multimon-ng stage that ignores SIGTERM (1 s grace, then SIGKILL)
    d = os.path.join(%(here)r, "fakebin_trap_mm"); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "multimon-ng"), "w").write("#!/bin/sh\ntrap '' TERM\nwhile :; do sleep 0.1; done\n")
    os.chmod(os.path.join(d, "multimon-ng"), 0o755)
    os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
from palisade_qt import radio_arbiter, shell
class SlowLease(H.FakeLease):
    def release(self):
        H.log("LEASE.release %%s start (%%.1f s)" %% (self.name, REL)); time.sleep(REL)
        H.log("LEASE.release %%s done" %% self.name)
radio_arbiter._make_lease = lambda n: SlowLease(n)
hub = shell.PalisadeHub(demo=False, mode="dark"); hub.resize(1280, 720); hub.show(); H.pump(0.5)
hub.open_callsign("PROWL"); H.pump(0.5)
page = hub.pages["PROWL"]
from palisade_qt.prowl import ProwlApp
prowl = page.child(ProwlApp)
page.switch_subtab("NWR"); H.pump(5.0)
H.log("NWR live, children=%%s" %% H.children())
old = prowl._worker
import weakref
ref = weakref.ref(old); del old
t0 = time.monotonic(); page.switch_subtab("FM")
H.log("switch_subtab blocked %%.2f s" %% (time.monotonic() - t0))
gc.collect(); H.pump(0.2)
o = ref()
H.log("old NwrWorker object after switch: %%s ; isRunning=%%s" %% ("collected" if o is None else "alive",
      None if o is None else o.isRunning()))
H.pump(4.0)
H.log("still alive at end")
'''
r = subprocess.run([sys.executable, "-c", CODE % {"here": HERE, "rel": REL, "trap": TRAP}], capture_output=True, text=True,
                   timeout=90, env=dict(os.environ, QT_QPA_PLATFORM="minimal"))
print(r.stdout.replace("This plugin does not support propagateSizeHints()\n", ""))
print("rc=%s" % r.returncode)
print("stderr:", " | ".join(l for l in r.stderr.splitlines() if "propagate" not in l and "QStandardPaths" not in l)[:600] or "-")
