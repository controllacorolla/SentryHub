#!/usr/bin/env python3
"""radio.py — TX hardware abstraction (Phase 3a).

RX SDR arbitration stays in suite.py (the RtlLease / single-dongle holder model); this module
owns the TRANSMIT side: detecting connected TX-capable hardware, modelling each device's limits,
and providing the one gated path a TX feature uses to key up. Every request passes through
txguard.authorize() before anything could transmit.

The built-in uConsole SDR is RECEIVE-ONLY and can never transmit — it is not in the TX hardware
table and is rejected in code. Detection only probes/queries devices; it never keys a radio.
If no TX hardware is present, everything degrades gracefully to RX-only (authorize() refuses).

Pure of Tk and of any actual RF: safe to import and unit-test. The real key-up lives in the
Phase 5 TX modules and only runs on an authorized TxRequest with real hardware present.
"""
import shutil
import subprocess

import txguard

# Known TX-capable hardware and conservative capability models. freq_hz (lo, hi); (0, 0) means the
# device sets its own frequency (a CAT rig / TNC), so radio.py does not range-check it.
TX_HARDWARE = {
    "hackrf":   {"name": "HackRF One", "freq_hz": (1_000_000, 6_000_000_000),
                 "power_dbm_max": 15, "duplex": "half"},
    "limesdr":  {"name": "LimeSDR", "freq_hz": (100_000, 3_800_000_000),
                 "power_dbm_max": 10, "duplex": "full", "soapy": "lime"},
    "pluto":    {"name": "PlutoSDR", "freq_hz": (70_000_000, 6_000_000_000),
                 "power_dbm_max": 7, "duplex": "full", "soapy": "plutosdr"},
    "rigctld":  {"name": "Hamlib rig (CAT)", "freq_hz": (0, 0),
                 "power_dbm_max": None, "duplex": "half", "tool": "rigctld"},
    "direwolf": {"name": "Direwolf TNC", "freq_hz": (0, 0),
                 "power_dbm_max": None, "duplex": "half", "tool": "direwolf"},
}

BUILTIN_RTL_IS_RX_ONLY = True       # the built-in SDR never transmits — enforced, not configurable


def _run(argv, timeout=4):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return None, ""


def _soapy_devices(runner, which):
    if not which("SoapySDRUtil"):
        return []
    _, out = runner(["SoapySDRUtil", "--find"])
    return out.lower().splitlines() if out else []


def detect_tx_hardware(runner=_run, which=shutil.which, soapy_devices=None):
    """Probe for connected TX hardware WITHOUT keying anything. Returns a list of device dicts
    (each a copy of a TX_HARDWARE entry plus 'id'). runner/which/soapy_devices are injectable so
    the detection logic is unit-testable with no hardware present."""
    found = []
    # HackRF: hackrf_info exits 0 and names the device when one is attached.
    if which("hackrf_info"):
        code, out = runner(["hackrf_info"])
        if code == 0 and "hackrf" in out.lower():
            found.append(dict(TX_HARDWARE["hackrf"], id="hackrf"))
    # SoapySDR-enumerated devices (LimeSDR, PlutoSDR).
    soapy = soapy_devices if soapy_devices is not None else _soapy_devices(runner, which)
    for key in ("limesdr", "pluto"):
        drv = TX_HARDWARE[key].get("soapy")
        if drv and any(drv in line for line in soapy):
            found.append(dict(TX_HARDWARE[key], id=key))
    # CAT rig / TNC: presence of the controlling tool indicates the path is available.
    for key in ("rigctld", "direwolf"):
        if which(TX_HARDWARE[key]["tool"]):
            found.append(dict(TX_HARDWARE[key], id=key))
    return found


def tx_hardware_available(**kw):
    return bool(detect_tx_hardware(**kw))


def pick_tx_device(devices=None, prefer=None, **kw):
    """Choose a TX device: the preferred id if present, else the first detected, else None."""
    devices = devices if devices is not None else detect_tx_hardware(**kw)
    if prefer:
        for d in devices:
            if d["id"] == prefer:
                return d
    return devices[0] if devices else None


class TxRequest:
    """A requested transmission. authorize() runs the full txguard gate AND the hardware check;
    it does NOT key the radio. A Phase-5 TX module calls authorize(), and only on success (with
    real hardware) does it build and run the device command, then calls log() afterwards."""

    def __init__(self, mode, freq_hz=None, power_dbm=None, callsign="", settings=None,
                 device=None):
        self.mode = mode
        self.freq_hz = freq_hz
        self.power_dbm = power_dbm
        self.callsign = callsign
        self.settings = settings or {}
        self.device = device            # a device dict, or None to auto-pick

    def authorize(self, devices=None):
        """Returns (ok, reason, power_dbm_allowed). Fails closed on any gate: txguard policy,
        no hardware, or a frequency the chosen device cannot reach. Power is the min of the mode
        cap and the device cap."""
        ok, reason, allowed = txguard.authorize(self.mode, self.freq_hz, self.power_dbm,
                                                 self.callsign, self.settings)
        if not ok:
            return False, reason, 0
        dev = self.device or pick_tx_device(devices=devices)
        if dev is None:
            return False, "no TX hardware detected — receive-only", 0
        lo, hi = dev.get("freq_hz", (0, 0))
        if self.freq_hz is not None and hi and not (lo <= float(self.freq_hz) <= hi):
            return False, "%s cannot reach %.4f MHz" % (dev["name"], float(self.freq_hz) / 1e6), 0
        dev_cap = dev.get("power_dbm_max")
        final_p = allowed if dev_cap is None else min(allowed, dev_cap)
        self.device = dev
        return True, "%s via %s (<= %d dBm)" % (reason, dev["name"], final_p), final_p

    def log(self, duration_s, power_dbm=None, path=None):
        """Record the transmission in tx_log.jsonl (call after a successful key-up)."""
        return txguard.log_tx(self.freq_hz, self.mode,
                              self.power_dbm if power_dbm is None else power_dbm,
                              duration_s, self.callsign,
                              path=path, extra={"device": (self.device or {}).get("id")})


# ===========================================================================================
# Phase 3b: generic SoapySDR device layer + remote sharing. Lets any supported dongle work
# (Airspy, SDRplay/RSP, RTL-SDR Blog V4, KrakenSDR, bladeRF, USRP, …), supports hot-plug
# detection by diffing device lists, and builds the commands to share Sentry's SDR to the
# network (server) or tune a remote one (client), via rtl_tcp or SoapyRemote.
# ===========================================================================================
SOAPY_DRIVERS = {
    "rtlsdr": {"name": "RTL-SDR", "tx": False}, "airspy": {"name": "Airspy", "tx": False},
    "airspyhf": {"name": "Airspy HF+", "tx": False}, "sdrplay": {"name": "SDRplay RSP", "tx": False},
    "hackrf": {"name": "HackRF One", "tx": True}, "lime": {"name": "LimeSDR", "tx": True},
    "plutosdr": {"name": "PlutoSDR", "tx": True}, "uhd": {"name": "Ettus USRP", "tx": True},
    "bladerf": {"name": "bladeRF", "tx": True}, "kraken": {"name": "KrakenSDR", "tx": False},
    "remote": {"name": "SoapyRemote", "tx": False},
}


def parse_soapy_find(text):
    """Parse `SoapySDRUtil --find` output into device dicts, annotated with a friendly name and
    whether the driver is TX-capable."""
    devices = []
    cur = None
    for line in (text or "").splitlines():
        s = line.strip()
        if s.lower().startswith("found device"):
            cur = {}
            devices.append(cur)
        elif "=" in s and cur is not None:
            k, v = (x.strip() for x in s.split("=", 1))
            cur[k.lower()] = v
    for d in devices:
        meta = SOAPY_DRIVERS.get(d.get("driver", ""), {"name": d.get("driver") or "unknown", "tx": False})
        d["name"] = d.get("label") or meta["name"]
        d["tx_capable"] = meta["tx"]
    return devices


def list_soapy_devices(runner=_run, which=shutil.which):
    if not which("SoapySDRUtil"):
        return []
    _, out = runner(["SoapySDRUtil", "--find"])
    return parse_soapy_find(out)


def devices_changed(old, new):
    """Hot-plug detection: did the set of attached devices change? (driver+serial/label key)."""
    def key(d):
        return (d.get("driver"), d.get("serial") or d.get("label") or d.get("name"))
    return {key(d) for d in old} != {key(d) for d in new}


def rtl_tcp_server_argv(bind="0.0.0.0", port=1234, freq_hz=None, sample_rate=2_048_000, gain=None):
    """Share the built-in RTL dongle to the network (RX only)."""
    argv = ["rtl_tcp", "-a", bind, "-p", str(int(port)), "-s", str(int(sample_rate))]
    if freq_hz:
        argv += ["-f", str(int(freq_hz))]
    if gain is not None:
        argv += ["-g", str(gain)]
    return argv


def soapy_remote_server_argv(bind="0.0.0.0", port=55132):
    """Share every local SoapySDR device to the network."""
    return ["SoapySDRServer", "--bind=%s:%d" % (bind, int(port))]


def rtl_tcp_client_device(host, port=1234):
    """Device string for tuning a remote rtl_tcp server."""
    return "rtl_tcp=%s:%d" % (host, int(port))


def soapy_remote_client_device(host, port=55132, driver=None):
    """SoapySDR device args for tuning a remote SoapyRemote server."""
    s = "driver=remote,remote=%s:%d" % (host, int(port))
    if driver:
        s += ",remote:driver=%s" % driver
    return s


if __name__ == "__main__":
    devs = detect_tx_hardware()
    if devs:
        print("TX hardware detected:")
        for d in devs:
            print("  %-10s %s" % (d["id"], d["name"]))
    else:
        print("No TX hardware detected — receive-only.")
