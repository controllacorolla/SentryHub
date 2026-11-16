#!/usr/bin/env python3
"""CL8 device check — run on the uConsole (Debian 13, Python 3.13) from the repo root:

    python3 plan/briefs/device_check_cl8.py

Changes NOTHING on the system: no sudo, no firewall, no apt, no radio keyed. It reads, imports,
dry-runs and runs the CL8 regression tests. Last line: DEVICE CHECK CL8: PASS (n/n) or FAIL.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:                       # a check that crashes is a FAIL, with the reason
        ok, detail = False, "%s: %s" % (type(e).__name__, e)
    results.append(ok)
    print("%-4s %-44s %s" % ("OK" if ok else "FAIL", name, detail))


def py():
    v = sys.version_info
    return v >= (3, 12), "Python %d.%d.%d" % v[:3]


def qt():
    import PySide6
    import pyqtgraph
    import numpy
    return True, "PySide6 %s · pyqtgraph %s · numpy %s" % (
        PySide6.__version__, pyqtgraph.__version__, numpy.__version__)


def argsafe_poc():
    import argsafe
    import pager
    try:
        pager.pipeline_argv("929.6M -M fm; id > /tmp/x #", 0)
    except argsafe.SettingsRefused:
        return True, "pager.json PoC frequency refused"
    return False, "PoC frequency ACCEPTED"


def net_default():
    import netpolicy
    m = netpolicy.mode()
    return m in ("OFFLINE", "LAN", "ONLINE"), "NET mode %s (fresh install: OFFLINE)" % m


def libcrypt():
    import doctor
    fn = doctor._libcrypt()
    if fn is None:
        return False, "no libcrypt via ctypes"
    y = fn("dragon", "$y$j9T$abcdefghijklmnop$")      # yescrypt, Debian 13's default hash
    six = fn("dragon", "$6$saltsalt$")
    return bool(six and six.startswith("$6$")), "sha512 %s · yescrypt %s" % (
        "ok" if six else "NO", "ok" if (y and y.startswith("$y$")) else "not supported")


def doctor_pw():
    import doctor
    ok, msg, _fix = doctor.chk_default_password()
    return ok is not False or "common default" in msg, "doctor: %s" % msg


def harden_dry():
    r = subprocess.run(["bash", "harden.sh", "--field", "--dry-run"], capture_output=True,
                       text=True, timeout=30, stdin=subprocess.DEVNULL)
    return r.returncode == 0 and "dry run" in r.stdout, "harden.sh --field --dry-run (no change)"


def tools():
    want = ["rtl_fm", "multimon-ng", "rtl_433", "rtl_power", "iw", "readsb"]
    have = [t for t in want if shutil.which(t)]
    miss = [t for t in want if t not in have]
    return True, "present: %s%s" % (" ".join(have) or "none",
                                     (" · missing: " + " ".join(miss)) if miss else "")


def tests():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "tests/test_cl8_ship.py"], capture_output=True, text=True, env=env,
                       timeout=600)
    tail = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
    return r.returncode == 0, tail


def hub_builds():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    code = ("from PySide6 import QtWidgets; app=QtWidgets.QApplication([]);"
            "from palisade_qt.shell import PalisadeHub; h=PalisadeHub();"
            "print(len(h.topbar.nav_keys), h.topbar.net.text(), h.minimumSizeHint().width())")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                       timeout=120)
    out = (r.stdout.strip().splitlines() or [""])[-1].split()
    ok = r.returncode == 0 and len(out) == 3 and out[0] == "7" and int(out[2]) <= 1280
    return ok, "keys %s · NET %s · width %s px" % tuple(out) if len(out) == 3 else r.stderr[-200:]


for name, fn in (("python", py), ("Qt stack", qt), ("L4 settings PoC", argsafe_poc),
                 ("L3 network mode", net_default), ("S4 libcrypt (no crypt module)", libcrypt),
                 ("S4 doctor password check", doctor_pw), ("L2 harden.sh field profile", harden_dry),
                 ("radio tools", tools), ("PALISADE hub builds", hub_builds),
                 ("CL8 regression tests", tests)):
    check(name, fn)

n = sum(results)
print("\nDEVICE CHECK CL8: %s (%d/%d)" % ("PASS" if n == len(results) else "FAIL", n, len(results)))
print("Then look:  python3 -m palisade_qt   -> 7 keys (no SWEEP), NET OFF in the top strip.")
sys.exit(0 if n == len(results) else 1)
