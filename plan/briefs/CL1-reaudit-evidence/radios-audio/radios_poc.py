import os, sys, tempfile, pathlib, json
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from palisade_qt import radios
T = pathlib.Path(tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(__file__))))
def mk(name, usb=None, rfkill=None):
    r = T / name
    if usb is not None:
        (r/"bus/usb/devices").mkdir(parents=True)
        for n, files in usb.items():
            d = r/"bus/usb/devices"/n; d.mkdir()
            for k, v in files.items(): (d/k).write_text(v)
    if rfkill is not None:
        (r/"class/rfkill").mkdir(parents=True)
        for n, files in rfkill.items():
            d = r/"class/rfkill"/n; d.mkdir()
            for k, v in files.items(): (d/k).write_text(v)
    return r
def show(tag, root, owner=None):
    print("==", tag, "owner_label=%r" % owner)
    try:
        for row in radios.inventory(owner_label=owner, sys_root=str(root)): print("   ", row)
    except Exception as e:
        print("   EXC", type(e).__name__, e)
RTL = {"idVendor": "0bda\n", "idProduct": "2838\n"}
HRF = {"idVendor": "1d50\n", "idProduct": "6089\n"}
show("missing root", T/"nope")
show("missing root, arbiter held", T/"nope", "APRS")
show("empty dirs", mk("empty", {}, {}))
show("empty dirs, arbiter HELD", T/"empty", "PRISM")
# permission denied on the devices dir (cannot list)
r = mk("perm_dir", {"1-1": RTL}, {"rfkill0": {"type": "wlan\n", "name": "phy0\n", "soft": "0\n", "hard": "0\n"}})
os.chmod(r/"bus/usb/devices", 0); os.chmod(r/"class/rfkill", 0)
show("devices dir + rfkill dir chmod 000 (RTL plugged, wlan present)", r)
os.chmod(r/"bus/usb/devices", 0o755); os.chmod(r/"class/rfkill", 0o755)
# permission denied on id files
r = mk("perm_file", {"1-1": RTL}, {"rfkill0": {"type": "wlan\n", "name": "phy0\n", "soft": "1\n", "hard": "1\n"}})
for p in (r/"bus/usb/devices/1-1/idVendor", r/"class/rfkill/rfkill0/soft", r/"class/rfkill/rfkill0/hard", r/"class/rfkill/rfkill0/type"): os.chmod(p, 0)
show("idVendor unreadable; rfkill soft/hard/type unreadable (really hard+soft blocked)", r)
# hard unreadable, soft 0
r = mk("hard_unread", {}, {"rfkill0": {"type": "wlan\n", "name": "phy0\n", "soft": "0\n", "hard": "1\n"}})
os.chmod(r/"class/rfkill/rfkill0/hard", 0)
show("hard=1 but unreadable, soft=0", r)
# malformed
r = mk("malformed", {"1-1": {"idVendor": "0BDA\n", "idProduct": "2838\n"}, "1-2": {"idVendor": "", "idProduct": "2838"}, "1-3": {"idVendor": "0x0bda", "idProduct": "0x2838"}, "1-4": {"idVendor": "\xff\xfe", "idProduct": "zz"}},
       {"rfkill0": {"type": "", "name": "", "soft": "banana", "hard": "x"}, "rfkill1": {"type": "wlan", "soft": " 1 ", "hard": "0"}, "rfkill2": {"type": "nfc", "name": "nfc0", "soft": "0", "hard": "0"}, "rfkill3": {}})
show("malformed", r)
(r/"bus/usb/devices/1-5").mkdir(); (r/"bus/usb/devices/1-5/idVendor").write_bytes(b"\xff\xfe\n"); (r/"bus/usb/devices/1-5/idProduct").write_bytes(b"2838\n")
show("non-utf8 idVendor", r)
# multiple SDRs
r = mk("multi", {"1-1": HRF, "1-2": RTL, "1-2:1.0": {}, "usb1": {"idVendor": "1d6b", "idProduct": "0002"}}, {})
show("HackRF at 1-1 + RTL at 1-2, arbiter owner = PRISM (rtl_power user)", r, "PRISM")
r = mk("multi2", {"1-1": RTL, "1-2": RTL}, {})
show("two RTLs, FREE", r)
# unknown SDR
r = mk("unk", {"1-1": {"idVendor": "1df7", "idProduct": "3000"}, "1-2": {"idVendor": "2500", "idProduct": "0020"}, "1-3": {"idVendor": "0bda", "idProduct": "2813"}}, {})
show("RSP1A + USRP B200 + unlisted RTL plugged", r)
# usb dir is a file
r = T/"file"; (r/"bus/usb").mkdir(parents=True); (r/"bus/usb/devices").write_text("x"); (r/"class").mkdir(); (r/"class/rfkill").write_text("x")
show("devices is a regular file", r)
r = mk("blocked", {"1-1": RTL}, {"rfkill0": {"type": "wlan", "name": "phy0", "soft": "1", "hard": "1"}, "rfkill1": {"type": "bluetooth", "name": "hci0", "soft": "1", "hard": "0"}, "rfkill2": {"type": "wlan", "name": "phy1", "soft": "0", "hard": "0"}})
show("blocked", r, "ATLAS-APRS")
print("ROOT", T)
