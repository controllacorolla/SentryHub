#!/usr/bin/env python3
"""blescan.py — BLE scanner / enumerator (Phase 6 #8). Passive scan + classification.

Passively lists Bluetooth LE advertisers (via bleak), decodes the manufacturer OUI, and flags
notable device classes — including OpenDroneID Remote ID (service 0xFFFA), so it pairs with
dronewatch. Active GATT service/characteristic enumeration is available with hardware; the passive
scan + classification here is pure and unit-testable. General-purpose, independent of dronewatch.
"""
import os
import sys
import time

# Small representative OUI table (first 3 MAC octets -> vendor). Not the full IEEE registry — a
# common-vendor subset; unknown prefixes return None.
OUI = {
    "00:1A:11": "Google", "3C:5A:B4": "Google", "F4:F5:D8": "Google",
    "AC:BC:32": "Apple", "A4:C1:38": "Telink (BLE)", "F8:1D:78": "Apple",
    "00:16:94": "Apple", "DC:A6:32": "Raspberry Pi", "B8:27:EB": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi", "00:0D:4B": "Roku", "5C:CB:99": "Samsung",
    "60:60:1F": "DJI", "34:D2:62": "DJI",
}
ODID_SERVICE = "0000fffa-0000-1000-8000-00805f9b34fb"


def oui_vendor(mac):
    """Vendor from the MAC OUI prefix, or None."""
    if not mac or len(mac) < 8:
        return None
    return OUI.get(mac.upper()[:8])


def classify_advert(adv):
    """Normalize+classify a BLE advertisement.
    adv: {address, rssi, name, service_uuids, manufacturer_data}."""
    uuids = [str(u).lower() for u in (adv.get("service_uuids") or [])]
    is_odid = any(u == ODID_SERVICE or u.startswith("0000fffa") for u in uuids)
    mfr = adv.get("manufacturer_data") or {}
    tags = []
    if is_odid:
        tags.append("drone-remoteid")
    if any(u.startswith("0000fe9f") for u in uuids):
        tags.append("google-fastpair")
    if 0x004C in mfr or "004c" in {("%04x" % k if isinstance(k, int) else str(k)).lower()
                                   for k in mfr}:
        tags.append("apple")
    return {"address": adv.get("address"), "rssi": adv.get("rssi"),
            "name": adv.get("name") or "", "vendor": oui_vendor(adv.get("address")),
            "service_uuids": uuids, "is_odid": is_odid, "tags": tags}


class Devices:
    def __init__(self, stale_s=60):
        self.by_addr = {}
        self.stale_s = stale_s

    def ingest(self, adv, now=None):
        now = time.time() if now is None else now
        d = classify_advert(adv)
        if not d.get("address"):
            return None
        d["first"] = self.by_addr.get(d["address"], {}).get("first", now)
        d["last"] = now
        self.by_addr[d["address"]] = d
        return d

    def active(self, now=None):
        now = time.time() if now is None else now
        return [d for d in self.by_addr.values() if now - d["last"] <= self.stale_s]

    def drones(self, now=None):
        return [d for d in self.active(now) if d["is_odid"]]


def kind_of(d):
    """A short device class for the table from classify_advert's tags."""
    tags = d.get("tags") or []
    if d.get("is_odid") or "drone-remoteid" in tags:
        return "drone"
    if "apple" in tags:
        return "apple"
    if "google-fastpair" in tags:
        return "fastpair"
    return ""


# ---- bluetoothctl fallback (SCAN-2) ----
# Used when bleak is not importable. `bluetoothctl --timeout N scan on` starts a BlueZ discovery
# for N seconds and prints the devices it hears. Discovery is BlueZ's normal scan (scan requests,
# no connection, no pairing).
import re as _re

_ANSI = _re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x01|\x02")
_MAC = r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})"
_DEV = _re.compile(r"\[(NEW|CHG|DEL)\]\s+Device\s+" + _MAC + r"\s*(.*)$")
_RSSI = _re.compile(r"RSSI:\s*(?:0x[0-9a-fA-F]+\s*\()?(-?\d+)\)?")


def bluetoothctl_scan_argv(seconds=8):
    return ["bluetoothctl", "--timeout", str(int(seconds)), "scan", "on"]


def clean_line(line):
    """Strip colour codes, readline markers and a leading '[bluetooth]# ' prompt."""
    s = _ANSI.sub("", line or "").replace("\r", "")
    s = _re.sub(r"^\s*\[[^\]]*\]#\s*", "", s)
    return s.strip()


def parse_bluetoothctl_line(line):
    """One bluetoothctl output line -> (address, fields) for a device event, ("!", reason) for a
    scan failure, ("+", None) when discovery has started, or None. fields may hold: name, rssi, uuid, mfr (company id int), new (bool)."""
    s = clean_line(line)
    if not s:
        return None
    m = _DEV.search(s)
    if not m:                      # device lines first: a device NAME never reads as a failure
        low = s.lower()
        if "discovery started" in low or ("controller" in low and "discovering: yes" in low):
            return ("+", None)
        for key, why in (("no default controller", "no Bluetooth adapter"),
                         ("not authorized", "not authorized by BlueZ (D-Bus policy)"),
                         ("notauthorized", "not authorized by BlueZ (D-Bus policy)"),
                         ("accessdenied", "not authorized by BlueZ (D-Bus policy)"),
                         ("access denied", "not authorized by BlueZ (D-Bus policy)"),
                         ("notready", "adapter is powered off"),
                         ("failed to start discovery", None),
                         ("waiting to connect to bluetoothd", "bluetoothd is not running")):
            if key in low:
                return ("!", why or s)
        return None
    ev, addr, rest = m.group(1), m.group(2).upper(), m.group(3).strip()
    if ev == "DEL":
        return None
    f = {}
    if ev == "NEW":
        f["new"] = True
        if rest and rest.replace("-", ":").upper() != addr:
            f["name"] = rest
        return addr, f
    r = _RSSI.match(rest)
    if r:
        f["rssi"] = int(r.group(1))
    elif rest.startswith(("Name:", "Alias:")):
        nm = rest.split(":", 1)[1].strip()
        if nm and nm.replace("-", ":").upper() != addr:
            f["name"] = nm
    elif rest.startswith("UUIDs:"):
        u = _re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                       r"[0-9a-fA-F]{12})", rest)
        if u:
            f["uuid"] = u.group(1).lower()
    elif rest.startswith("ManufacturerData Key:") or rest.startswith("ManufacturerData.Key:"):
        k = _re.search(r"0x([0-9a-fA-F]+)", rest)
        if k:
            f["mfr"] = int(k.group(1), 16)
    else:
        return None
    return addr, f


def parse_bluetoothctl_devices(text):
    """`bluetoothctl devices` ('Device AA:BB:.. Name') -> {address: name} for named devices."""
    names = {}
    for line in (text or "").splitlines():
        m = _re.match(r"Device\s+" + _MAC + r"\s+(.*)$", clean_line(line))
        if m:
            addr, nm = m.group(1).upper(), m.group(2).strip()
            if nm and nm.replace("-", ":").upper() != addr:
                names[addr] = nm
    return names


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("BLEScan")
    S.settings("blescan", {})
    root, F = S.make_root("BLE Scanner", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "BLE Scanner", "Passive BLE enumerate · OUI + Remote ID")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Passively lists BLE advertisers with vendor (OUI) and device-class tags, "
                  "including OpenDroneID Remote ID (pairs with DroneWatch). Active GATT "
                  "enumeration available with a Bluetooth adapter.").pack(fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
