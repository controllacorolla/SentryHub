import os, sys, tempfile, shutil
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from palisade_qt import radios

def mk(root, usb=(), rf=()):
    os.makedirs(os.path.join(root, "bus/usb/devices")); os.makedirs(os.path.join(root, "class/rfkill"))
    for i, (v, p) in enumerate(usb):
        d = os.path.join(root, "bus/usb/devices", "1-%d" % i); os.makedirs(d)
        for n, val in (("idVendor", v), ("idProduct", p)):
            if val is not None:
                open(os.path.join(d, n), "wb").write(val if isinstance(val, bytes) else (val + "\n").encode())
    for i, kv in enumerate(rf):
        d = os.path.join(root, "class/rfkill", "rfkill%d" % i); os.makedirs(d)
        for n, val in kv.items(): open(os.path.join(d, n), "w").write(val + "\n")

def case(name, fn):
    root = tempfile.mkdtemp()
    try:
        try: print(name, "->", fn(root))
        except Exception as e: print(name, "-> RAISED", type(e).__name__, e)
    finally:
        os.system("chmod -R u+rwx %s" % root); shutil.rmtree(root)

WL = {"type": "wlan", "name": "phy0", "soft": "0", "hard": "0"}
def a(root):
    mk(root, [("0bda", "2838")], [WL])
    os.chmod(os.path.join(root, "bus/usb/devices"), 0); os.chmod(os.path.join(root, "class/rfkill"), 0)
    return radios.inventory(sys_root=root)
def b(root):
    mk(root, [("0bda", "2838")], [WL]); os.chmod(os.path.join(root, "bus/usb/devices/1-0/idVendor"), 0)
    return radios.inventory(sys_root=root)
def c(root):
    mk(root, [("0bda", "2838")], []); return radios.inventory(sys_root=root)
def d(root):
    mk(root, [], [WL]); p = os.path.join(root, "class/rfkill/rfkill0/hard")
    open(p, "w").write("1\n"); os.chmod(p, 0); return radios.inventory(sys_root=root)
def d2(root):
    mk(root, [], [{"type": "wlan", "name": "phy0", "soft": "0"}]); return radios.inventory(sys_root=root)
def e(root):
    mk(root, [("1df7", "3000"), ("2500", "0020")], [WL]); return radios.inventory(sys_root=root)
def f(root):
    mk(root, [(b"\xff\xfe\n", "2838")], [WL]); return radios.inventory(sys_root=root)
def g(root):
    mk(root, [("0bda", "2838")], [WL]); return radios.inventory(sys_root=root)
def ctrl(root):
    return radios.inventory(sys_root=os.path.join(root, "nope"))
for n, fn in (("a", a), ("b", b), ("c", c), ("d", d), ("d2-hard-missing", d2), ("e", e), ("f", f), ("g", g), ("control-no-sysfs", ctrl)):
    case(n, fn)
print("euid", os.geteuid())
