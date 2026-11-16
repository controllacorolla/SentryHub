"""Radio inventory for the RADIOS panel — read-only presence and power state.

Reads what the kernel already exposes (USB IDs under /sys/bus/usb/devices, rfkill switches under
/sys/class/rfkill). It powers nothing on or off and selects no device: this cluster only shows what
exists (radio power control and device selection are audit section 9 / cluster CL6). On a host with
no /sys (the dev Mac) presence is reported as unknown, never guessed.
"""
import glob
import os

# (vendor, product) -> name, for the SDRs the suite drives
SDR_USB_IDS = {
    ("0bda", "2832"): "RTL-SDR (RTL2832U)", ("0bda", "2838"): "RTL-SDR (RTL2832U)",
    ("1d50", "6089"): "HackRF One", ("1d50", "604b"): "HackRF Jawbreaker",
    ("1d50", "60a1"): "Airspy", ("1df7", "2500"): "SDRplay RSP1",
}
RFKILL_LABEL = {"wlan": "Wi-Fi", "bluetooth": "Bluetooth", "wwan": "Cellular modem",
                "gps": "GNSS", "fm": "FM"}


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def usb_sdrs(sys_root="/sys"):
    """SDR dongles on the USB bus -> list of {name, id}. None if there is no USB sysfs here."""
    base = os.path.join(sys_root, "bus", "usb", "devices")
    if not os.path.isdir(base):
        return None
    out = []
    for dev in sorted(glob.glob(os.path.join(base, "*"))):
        vid, pid = _read(os.path.join(dev, "idVendor")), _read(os.path.join(dev, "idProduct"))
        if vid and pid and (vid.lower(), pid.lower()) in SDR_USB_IDS:
            out.append({"name": SDR_USB_IDS[(vid.lower(), pid.lower())],
                        "id": "%s:%s" % (vid.lower(), pid.lower())})
    return out


# kernel drivers that bind an RTL2832U as a DVB-T TV tuner: while one is bound, librtlsdr tools
# (rtl_fm, rtl_power, readsb) usually cannot claim the dongle (audit H6)
DVB_DRIVERS = ("dvb_usb_rtl28xxu", "rtl2832", "rtl2832_sdr", "dvb_usb_v2")


def sdr_state(sys_root="/sys"):
    """The built-in SDR as the kernel sees it (audit H6), for OPS's SDR chip:
      {"present": True/False/None, "name": ..., "id": "0bda:2838", "driver": "dvb_usb_rtl28xxu"|
       None, "usable": True/False/None}
    present None = no USB sysfs on this host (cannot tell). usable False when a DVB kernel driver
    has bound the dongle (the state /dev/swradio0 appears in — the old check called that OK)."""
    base = os.path.join(sys_root, "bus", "usb", "devices")
    if not os.path.isdir(base):
        return {"present": None, "name": None, "id": None, "driver": None, "usable": None}
    for dev in sorted(glob.glob(os.path.join(base, "*"))):
        vid, pid = _read(os.path.join(dev, "idVendor")), _read(os.path.join(dev, "idProduct"))
        if not (vid and pid) or (vid.lower(), pid.lower()) not in SDR_USB_IDS:
            continue
        drivers = []
        for d in sorted(glob.glob(dev + ":*" + os.sep + "driver")):
            try:
                drivers.append(os.path.basename(os.path.realpath(d)))
            except OSError:
                continue
        dvb = [d for d in drivers if d in DVB_DRIVERS]
        return {"present": True, "name": SDR_USB_IDS[(vid.lower(), pid.lower())],
                "id": "%s:%s" % (vid.lower(), pid.lower()),
                "driver": dvb[0] if dvb else (drivers[0] if drivers else None),
                "usable": not dvb}
    return {"present": False, "name": None, "id": None, "driver": None, "usable": False}


def rfkill_switches(sys_root="/sys"):
    """rfkill switches -> list of {name, type, power}. None if there is no rfkill sysfs here."""
    base = os.path.join(sys_root, "class", "rfkill")
    if not os.path.isdir(base):
        return None
    out = []
    for sw in sorted(glob.glob(os.path.join(base, "rfkill*"))):
        typ = _read(os.path.join(sw, "type")) or "?"
        soft, hard = _read(os.path.join(sw, "soft")), _read(os.path.join(sw, "hard"))
        if hard == "1":
            power = "BLOCKED (hardware switch)"
        elif soft == "1":
            power = "BLOCKED (rfkill)"
        elif soft == "0":
            power = "ON"
        else:
            power = "UNKNOWN"
        out.append({"name": _read(os.path.join(sw, "name")) or typ, "type": typ, "power": power})
    return out


def inventory(owner_label=None, sys_root="/sys"):
    """Rows for the RADIOS table: radio, present, power, owner. `owner_label` is whoever the radio
    arbiter says holds the single SDR (the arbiter arbitrates only that one dongle)."""
    rows = []
    sdrs = usb_sdrs(sys_root)
    if sdrs is None:
        rows.append({"radio": "SDR dongle", "present": "UNKNOWN (no USB sysfs on this host)",
                     "power": "—", "owner": owner_label or "FREE"})
    elif not sdrs:
        rows.append({"radio": "SDR dongle", "present": "ABSENT", "power": "—",
                     "owner": owner_label or "—"})
    else:
        for i, d in enumerate(sdrs):
            rows.append({"radio": "%s [%s]" % (d["name"], d["id"]), "present": "PRESENT",
                         "power": "USB powered",
                         "owner": (owner_label or "FREE") if i == 0 else "not arbitrated"})
    switches = rfkill_switches(sys_root)
    if switches is None:
        rows.append({"radio": "Wi-Fi / Bluetooth", "present": "UNKNOWN (no rfkill on this host)",
                     "power": "—", "owner": "not arbitrated"})
    else:
        for sw in switches:
            rows.append({"radio": "%s (%s)" % (RFKILL_LABEL.get(sw["type"], sw["type"]), sw["name"]),
                         "present": "PRESENT", "power": sw["power"], "owner": "not arbitrated"})
    return rows
