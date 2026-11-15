import os, sys, tempfile
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from palisade_qt import radios
def mk(devs):
    r = tempfile.mkdtemp(dir=os.path.dirname(__file__))
    for n,(v,p) in devs.items():
        d=os.path.join(r,"bus/usb/devices",n); os.makedirs(d)
        open(d+"/idVendor","w").write(v+"\n"); open(d+"/idProduct","w").write(p+"\n")
    os.makedirs(os.path.join(r,"class/rfkill"))
    return r
for label, devs, owner in [
 ("hackrf@1-1 rtl@1-2 owner=PRISM", {"1-1":("1d50","6089"),"1-2":("0bda","2838")}, "PRISM"),
 ("rtl@1-1 hackrf@1-2 owner=PRISM", {"1-1":("0bda","2838"),"1-2":("1d50","6089")}, "PRISM"),
 ("two rtl, free", {"1-1":("0bda","2838"),"1-2":("0bda","2838")}, None)]:
    print(label)
    for r in radios.inventory(owner_label=owner, sys_root=mk(devs)): print("   ", r["radio"], "|", r["owner"])
