"""R1 / R2 re-derived on the real hub.
r1   BABEL in each mode: RUN off, then page hidden (OPS fronted): does anything take the radio?
r2   a decoder that exits at once (stderr 'usb_claim_interface error -6'): lease churn in 10 s?"""
import os
import sys

import _harness as H
from palisade_qt import radio_arbiter, shell

acq = []
_orig = H.FakeLease


def mk(name):
    acq.append(name)
    H.log("LEASE.acquire", name)
    return H.FakeLease(name)


radio_arbiter._make_lease = mk
A = radio_arbiter.arbiter
which = sys.argv[1]
if which == "r2":
    d = os.path.join(H.HERE, "fakebin_fail")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "rtl_ais")
    with open(p, "w") as f:
        f.write("#!/bin/sh\necho 'usb_claim_interface error -6' >&2\nexit 1\n")
    os.chmod(p, 0o755)
    os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]

hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720)
hub.show()
H.pump(0.5)
hub.open_callsign("BABEL")
H.pump(0.5)
b = hub.pages["BABEL"]
if which == "r1":
    for mode in ("AIS", "SSTV"):
        b.mode_combo.setCurrentText(mode)
        H.pump(2.5)
        H.log("R1 %s RUN=%s front: arbiter=%s children=%s chip=%r busy=%r" % (
            mode, b.run_btn.isChecked(), A.state(), H.children(),
            b._last_status.get("sdr", {}).get("text"), b.busy.text()))
        hub.show_page("OPS")
        H.pump(2.5)
        H.log("R1 %s RUN=%s HIDDEN: arbiter=%s children=%s" % (
            mode, b.run_btn.isChecked(), A.state(), H.children()))
        hub.open_callsign("BABEL")
        H.pump(0.5)
else:
    b.mode_combo.setCurrentText("AIS")
    H.pump(0.3)
    b.run_btn.setChecked(True)
    H.pump(10.0)
    rel = [e for e in H.LOG if e[1] == "LEASE.release"]
    H.log("R2 in 10 s: acquires=%d releases=%d arbiter=%s chip=%r busy=%r" % (
        len(acq), len(rel), A.state(), b._last_status.get("sdr", {}).get("text"), b.busy.text()))
hub.close()
H.pump(0.5)
