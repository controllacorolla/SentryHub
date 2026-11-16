"""NWR safety (owner priority): through the real hub, PROWL › NWR live, then one disturbance.
Every 0.1 s we sample what the page SAYS (receiver label, detail hero) and what is TRUE (arbiter
state, decoder processes alive). VIOLATION = the page says LIVE / 'no alerts' while the arbiter
does not say HELD by PROWL-NWR or no decoder process is alive.
Scenarios: revoke · forced (revoke timeout 0.05 s: the holder cannot ack in time) · panic · hide ·
submode (NWR -> FM) · hung (rtl_fm alive but silent from the start) · stall (worker thread blocked
10 s: fault injection, patches NwrWorker.step) · stall_revoke (same, then revoke: the holder never acks -> forced free) · decoder_dies."""
import os
import sys
import time
import _harness as H
from PySide6 import QtCore
from palisade_qt import radio_arbiter, shell

which = sys.argv[1]
if which == "hung":
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebin_hung")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rtl_fm"), "w") as f:
        f.write("#!/bin/sh\n# rtl_fm wedged on a USB stall: alive, no samples\nexec sleep 600\n")
    os.chmod(os.path.join(d, "rtl_fm"), 0o755)
    os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
if which == "decoder_dies":
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebin_dies")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "multimon-ng"), "w") as f:
        f.write("#!/bin/sh\n# multimon-ng that dies after 2 s\nsleep 2\nexit 3\n")
    os.chmod(os.path.join(d, "multimon-ng"), 0o755)
    os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]

radio_arbiter._make_lease = lambda name: H.FakeLease(name)
A = radio_arbiter.arbiter
from palisade_qt.prowl import ProwlApp, NwrWorker  # noqa: E402
if which in ("stall", "stall_revoke"):
    _orig = NwrWorker.step
    def _step(self):
        if getattr(self, "_stall_now", False):
            self._stall_now = False
            H.log("INJECT worker thread blocked 10 s")
            time.sleep(10)
        return _orig(self)
    NwrWorker.step = _step

hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720); hub.show(); H.pump(0.5)
hub.open_callsign("PROWL"); H.pump(0.5)
page = hub.pages["PROWL"]
prowl = page.child(ProwlApp)
page.switch_subtab("NWR")
H.pump(3.0)


def decoder_alive():
    return [k for k in H.children() if "(Z)" not in k and ("python3" in k or "cat" in k or "sleep" in k)]


def sample(tag):
    txt = prowl.nwr_state.text()
    hero = prowl.nwr_detail.sub.text()
    st = A.state()
    dec = decoder_alive()
    says_live = txt.startswith("LIVE") or hero == "NO ALERTS"
    true_live = st == ("HELD", "PROWL-NWR") and bool(dec)
    v = says_live and not true_live
    H.log("%s label=%r hero=%r arbiter=%s decoders=%s%s" % (tag, txt, hero, st, dec,
                                                           "  <<< VIOLATION" if v else ""))
    return v


sample("BEFORE")
viol = 0
w = prowl._worker
if which == "revoke":
    A.revoke()
elif which == "forced":
    A.revoke(timeout_s=0.05)
elif which == "panic":
    H.log("PANIC banner: " + " · ".join(hub.panic()))
elif which == "hide":
    hub.show_page("OPS")
elif which == "submode":
    page.switch_subtab("FM")
elif which == "stall":
    w._stall_now = True
elif which == "stall_revoke":
    w._stall_now = True
    H.pump(0.6)
    A.revoke()
for i in range(80):
    H.pump(0.1)
    viol += sample("t+%.1f" % ((i + 1) / 10.0))
H.log("RESULT %s: %d violating samples of 80" % (which, viol))
hub.close(); H.pump(1.5)
