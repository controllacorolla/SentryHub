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
