"""GUI-thread blocking on a sub-mode / decoder-type switch (and on PANIC), with the two slow
things the device really has: a decoder stage that ignores SIGTERM (1 s grace before SIGKILL) and
a lease release that takes 2 s (RtlLease.release = `sudo systemctl start readsb`). We time each
GUI-thread call; anything that waits on a process or the release shows up here."""
import os
import time
import _harness as H
from palisade_qt import radio_arbiter, shell

d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebin_trap")
os.makedirs(d, exist_ok=True)
for name in ("rtl_ais", "rtl_fm"):
    with open(os.path.join(d, name), "w") as f:
        f.write("#!/bin/sh\n# decoder stage that ignores SIGTERM\ntrap '' TERM\n"
                "while :; do echo '!AIVDM,1,1,,A,15M67FC000G?ufbE`FepT@3n00Sa,0*5C'; sleep 0.2; done\n")
    os.chmod(os.path.join(d, name), 0o755)
os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


class SlowLease(H.FakeLease):
    def release(self):
        H.log("LEASE.release %s start (2 s: systemctl start readsb) children=%s" % (self.name, H.children()))
        time.sleep(2.0)


radio_arbiter._make_lease = lambda name: SlowLease(name)
A = radio_arbiter.arbiter
from palisade_qt.prowl import ProwlApp  # noqa: E402
from palisade_qt.babel import BabelApp  # noqa: E402

hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720); hub.show(); H.pump(0.5)


def timed(label, fn):
    t0 = time.monotonic()
    fn()
    H.log("GUI-THREAD %-46s blocked %.2f s" % (label, time.monotonic() - t0))


hub.open_callsign("PROWL"); H.pump(0.5)
page = hub.pages["PROWL"]
page.switch_subtab("NWR"); H.pump(3.0)
H.log("NWR live: arbiter=%s children=%s" % (A.state(), H.children()))
timed("PROWL sub-mode NWR -> FM (switch_subtab)", lambda: page.switch_subtab("FM"))
H.pump(4.0)
timed("PROWL sub-mode FM -> SCAN (switch_subtab)", lambda: page.switch_subtab("SCAN"))
H.pump(3.0)

hub.open_callsign("BABEL"); H.pump(3.0)
b = page.child(BabelApp)
b.mode_combo.setCurrentText("AIS"); H.pump(0.5)
b.run_btn.setChecked(True); H.pump(3.0)
H.log("BABEL AIS live: arbiter=%s children=%s" % (A.state(), H.children()))
timed("BABEL decoder AIS -> SSTV (mode combo)", lambda: b.mode_combo.setCurrentText("SSTV"))
H.pump(4.0)
b.mode_combo.setCurrentText("AIS"); H.pump(0.5)
b.run_btn.setChecked(True); H.pump(3.0)
H.log("BABEL AIS live again: arbiter=%s children=%s" % (A.state(), H.children()))
timed("hub.panic()", hub.panic)
H.pump(3.0)
hub.close(); H.pump(3.0)
