#!/usr/bin/env python3
"""
Transmit policy for the suite - the single place that decides whether keying the radio is
allowed, and the only gate any TX feature is permitted to go through.

The suite started life receive-only. Opening it up to transmit does NOT mean "key the HackRF
on any frequency": that same code would transmit on aviation, ADS-B, GPS and cellular bands,
where transmitting is a federal offence and a safety-of-life hazard. So the policy is:

  * license-free ISM bands (LoRa/Meshtastic, 433/915 MHz, 2.4 GHz)  -> allowed
  * amateur (ham) bands                                             -> allowed WITH a callsign
  * everything else, and anything unknown                           -> denied

Protected ranges (GPS, ADS-B, aviation voice, cellular, ...) are denied explicitly even if some
future band-plan edit would otherwise cover them. A global kill switch (config tx_enabled=false,
or SUITE_TX_LOCK=1 in the environment) denies everything regardless.

Pure module: no radio, no I/O beyond reading suite settings. decide() is the one entry point.
"""

CALL_RE = __import__("re").compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z](?:-[0-9]{1,2})?$")

# (low_hz, high_hz, label). US amateur allocations, inclusive. Not exhaustive to the kHz, but
# conservative: a segment is listed only where the whole range is amateur.
HAM_BANDS = [
    (1_800_000, 2_000_000, "160m"), (3_500_000, 4_000_000, "80m"),
    (5_330_500, 5_406_500, "60m"), (7_000_000, 7_300_000, "40m"),
    (10_100_000, 10_150_000, "30m"), (14_000_000, 14_350_000, "20m"),
    (18_068_000, 18_168_000, "17m"), (21_000_000, 21_450_000, "15m"),
    (24_890_000, 24_990_000, "12m"), (28_000_000, 29_700_000, "10m"),
    (50_000_000, 54_000_000, "6m"), (144_000_000, 148_000_000, "2m"),
    (222_000_000, 225_000_000, "1.25m"), (420_000_000, 450_000_000, "70cm"),
    (902_000_000, 928_000_000, "33cm"), (1_240_000_000, 1_300_000_000, "23cm"),
]

# license-free ISM / unlicensed. 902-928 overlaps the 33cm ham band; LoRa/Meshtastic use it
# under Part 15, so it is allowed without a callsign.
ISM_BANDS = [
    (433_050_000, 434_790_000, "433 ISM"),
    (902_000_000, 928_000_000, "915 ISM"),
    (2_400_000_000, 2_483_500_000, "2.4 GHz ISM"),
]

# Hard no-TX ranges - safety-of-life and licensed services. Denied with a specific reason even
# if something above would otherwise match. Order matters only for the message.
PROTECTED = [
    (1_559_000_000, 1_610_000_000, "GNSS / GPS"),
    (1_087_000_000, 1_093_000_000, "ADS-B (1090 MHz)"),
    (978_000_000, 979_000_000, "ADS-B UAT (978 MHz)"),
    (108_000_000, 137_000_000, "aviation nav/voice"),
    (156_000_000, 162_050_000, "marine VHF"),
    (960_000_000, 1_215_000_000, "aeronautical radionav (DME/TACAN)"),
    (1_215_000_000, 1_240_000_000, "radiolocation / GNSS L2"),
    (698_000_000, 798_000_000, "700 MHz cellular / public safety"),
    (824_000_000, 849_000_000, "cellular uplink"),
    (1_710_000_000, 1_785_000_000, "cellular uplink (AWS/PCS)"),
    (121_400_000, 121_600_000, "121.5 MHz emergency"),
    (406_000_000, 406_100_000, "406 MHz emergency beacons"),
]


def _match(freq, table):
    for lo, hi, label in table:
        if lo <= freq <= hi:
            return label
    return None


def valid_callsign(call):
    """True for a plausibly-formatted amateur callsign (not a license check - just a gate so
    ham TX is deliberate and identifiable, as the FCC station-ID rules require)."""
    return bool(call) and bool(CALL_RE.match(str(call).strip().upper()))


def classify(freq_hz):
    """'protected' | 'ism' | 'ham' | 'other'. Protected wins over everything."""
    f = float(freq_hz)
    if _match(f, PROTECTED):
        return "protected"
    if _match(f, ISM_BANDS):
        return "ism"
    if _match(f, HAM_BANDS):
        return "ham"
    return "other"


def tx_locked(settings=None):
    """The global kill switch. Locked unless settings explicitly enable TX, or if the
    environment forces a lock. Returns (locked: bool, reason: str)."""
    import os
    if os.environ.get("SUITE_TX_LOCK") == "1":
        return True, "TX locked by SUITE_TX_LOCK=1 in the environment"
    # fail closed: no settings, or tx_enabled not explicitly true, means locked
    if not settings or not settings.get("tx_enabled", False):
        return True, "TX is disabled in settings (enable it deliberately to transmit)"
    return False, ""


def decide(freq_hz=None, service=None, callsign="", settings=None):
    """The one gate. Returns (ok: bool, reason: str).

    service="lora": license-free mesh/LoRa, allowed when unlocked without a frequency.
    Otherwise freq_hz is required and the band decides. A callsign is required on ham bands.
    """
    import os
    if os.environ.get("SUITE_TX_LOCK") == "1":
        return False, "TX locked by SUITE_TX_LOCK=1 in the environment"

    if service == "lora":
        # the pre-existing sanctioned path: license-free, gated only by the hard env lock
        # above, not by the tx_enabled setting that guards the new RF-TX surface.
        return True, "LoRa/Meshtastic on a license-free ISM band"

    if service == "bench":
        # Conducted bench testing: HackRF -> coax/attenuator -> dummy load or the receiver's
        # antenna port, nothing radiating. Band is irrelevant because nothing leaves the cable,
        # so any frequency is permitted - but ONLY with TX enabled AND an explicit per-session
        # acknowledgment that the output is terminated into a load, not an antenna.
        locked, why = tx_locked(settings)
        if locked:
            return False, why
        if not (settings or {}).get("bench_conducted_ack", False):
            return False, ("conducted-bench TX needs the conducted-only acknowledgment: confirm the "
                           "output goes to a dummy load/attenuator or a cabled receiver, not an antenna")
        f = "" if freq_hz is None else " @ %.4f MHz" % (float(freq_hz) / 1e6)
        return True, "conducted bench TX%s (into a load, not radiating)" % f

    locked, why = tx_locked(settings)
    if locked:
        return False, why

    if freq_hz is None:
        return False, "no frequency given - refusing to key the radio"
    try:
        f = float(freq_hz)
    except (TypeError, ValueError):
        return False, "frequency is not a number"
    if f <= 0:
        return False, "frequency must be positive"

    kind = classify(f)
    mhz = f / 1e6
    if kind == "protected":
        label = _match(f, PROTECTED)
        return False, "%.4f MHz is in a protected band (%s) - transmitting there is illegal" % (mhz, label)
    if kind == "ism":
        return True, "%.4f MHz is a license-free ISM band (%s)" % (mhz, _match(f, ISM_BANDS))
    if kind == "ham":
        band = _match(f, HAM_BANDS)
        call = str(callsign or (settings or {}).get("callsign", "")).strip().upper()
        if not valid_callsign(call):
            return False, ("%.4f MHz is the %s amateur band - set your callsign in settings "
                           "to transmit (and you must be licensed)" % (mhz, band))
        return True, "%.4f MHz amateur %s, station %s" % (mhz, band, call)
    return False, "%.4f MHz is not in any band the suite will transmit on" % mhz


# ===========================================================================================
# Phase 3a: license-gated TX controller — per-mode band/power caps, master kill switch,
# per-session unlock, and a TX event log. decide()/classify() above are unchanged (the RX-era
# callers still use them); the new authorize() is the fuller gate a TX module must pass.
# ===========================================================================================

# Per-mode TX profiles. scope: 'ham' (amateur bands, callsign required) | 'ism' (license-free) |
# 'conducted' (cabled into a load, any band). power_dbm_max is a hard cap (enforced, not advisory);
# the authorized power is min(this, requested, hardware cap). 37 dBm = 5 W, 30 = 1 W, 20 = 100 mW.
TX_PROFILES = {
    "aprs":   {"scope": "ham", "power_dbm_max": 37, "label": "APRS packet"},
    "ft8":    {"scope": "ham", "power_dbm_max": 37, "label": "FT8/FT4"},
    "ft4":    {"scope": "ham", "power_dbm_max": 37, "label": "FT8/FT4"},
    "wspr":   {"scope": "ham", "power_dbm_max": 30, "label": "WSPR (QRP)"},
    "js8":    {"scope": "ham", "power_dbm_max": 37, "label": "JS8Call"},
    "psk31":  {"scope": "ham", "power_dbm_max": 37, "label": "PSK31"},
    "rtty":   {"scope": "ham", "power_dbm_max": 37, "label": "RTTY"},
    "olivia": {"scope": "ham", "power_dbm_max": 37, "label": "Olivia"},
    "freedv": {"scope": "ham", "power_dbm_max": 37, "label": "FreeDV"},
    "packet": {"scope": "ham", "power_dbm_max": 37, "label": "AX.25 packet"},
    "sstv":   {"scope": "ham", "power_dbm_max": 37, "label": "SSTV"},
    "cw":     {"scope": "ham", "power_dbm_max": 37, "label": "CW/Morse"},
    "lora":   {"scope": "ism", "power_dbm_max": 20, "label": "LoRa/Meshtastic"},
    "replay": {"scope": "ism", "power_dbm_max": 10, "label": "IQ replay"},
    "bench":  {"scope": "conducted", "power_dbm_max": 15, "label": "conducted bench"},
}


def profile(mode):
    return TX_PROFILES.get(str(mode or "").lower())


# Session state: in-memory only (one process = one session). Never persisted — the plan requires
# a deliberate per-session unlock with no "remember my choice".
_STATE = {"armed": False, "unlocked": False}


def arm(on=True):
    """Master TX kill switch (default OFF/safe). The hub toolbar toggles this; while OFF, every
    authorize() denies. Disarming also drops any session unlock."""
    _STATE["armed"] = bool(on)
    if not _STATE["armed"]:
        _STATE["unlocked"] = False


def is_armed():
    return _STATE["armed"]


def unlock_session(on=True):
    """Explicit per-session unlock. Only takes effect while armed; never persisted."""
    _STATE["unlocked"] = bool(on) and _STATE["armed"]


def session_unlocked():
    return _STATE["unlocked"]


def reset_session():
    """Drop arm + unlock (used at startup and by tests)."""
    _STATE["armed"] = False
    _STATE["unlocked"] = False


def authorize(mode, freq_hz=None, power_dbm=None, callsign="", settings=None):
    """The full gate for a real key-up. Returns (ok, reason, power_dbm_allowed).

    Chain (all must pass): env not hard-locked -> master kill switch armed -> session unlocked ->
    settings opt-in (tx_enabled) -> per-mode band whitelist (via classify) -> callsign on ham ->
    power clamped to the mode cap. Protected bands are always denied."""
    import os
    prof = profile(mode)
    if prof is None:
        return False, "unknown TX mode %r" % (mode,), 0
    if os.environ.get("SUITE_TX_LOCK") == "1":
        return False, "TX locked by SUITE_TX_LOCK=1 in the environment", 0
    if not _STATE["armed"]:
        return False, "TX kill switch is OFF — arm it in the hub toolbar to transmit", 0
    if not _STATE["unlocked"]:
        return False, "TX is not unlocked this session — unlock deliberately before keying", 0
    locked, why = tx_locked(settings)
    if locked:
        return False, why, 0
    cap = prof["power_dbm_max"]
    want = cap if power_dbm is None else min(cap, power_dbm)      # hard-enforce the mode cap

    if prof["scope"] == "conducted":
        if not (settings or {}).get("bench_conducted_ack", False):
            return False, ("conducted-bench TX needs the conducted-only acknowledgment "
                           "(output into a dummy load/attenuator, not an antenna)"), 0
        return True, "%s authorized (into a load, not radiating)" % prof["label"], want

    if freq_hz is None:
        return False, "no frequency given — refusing to key the radio", 0
    try:
        f = float(freq_hz)
    except (TypeError, ValueError):
        return False, "frequency is not a number", 0
    kind = classify(f)
    mhz = f / 1e6
    if kind == "protected":
        return False, "%.4f MHz is protected (%s) — transmitting there is illegal" % (
            mhz, _match(f, PROTECTED)), 0
    if prof["scope"] == "ham":
        if kind != "ham":
            return False, "%.4f MHz is not an amateur band for %s" % (mhz, prof["label"]), 0
        call = str(callsign or (settings or {}).get("callsign", "")).strip().upper()
        if not valid_callsign(call):
            return False, "a valid callsign is required for %s" % prof["label"], 0
    elif prof["scope"] == "ism":
        if kind != "ism":
            return False, "%.4f MHz is not a license-free ISM band for %s" % (mhz, prof["label"]), 0
    return True, "%s @ %.4f MHz authorized (<= %d dBm)" % (prof["label"], mhz, want), want


def default_log_path():
    import os
    return os.path.join(os.path.expanduser("~"), ".local", "share", "uconsole-suite",
                        "tx_log.jsonl")


def log_tx(freq_hz, mode, power_dbm, duration_s, callsign, path=None, extra=None):
    """Append one TX event to tx_log.jsonl (timestamp, freq, mode, power, duration, callsign).
    Called by a TX module after a transmission; failure to log never raises."""
    import json
    import os
    import time
    rec = {"t": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "freq_hz": freq_hz, "mode": mode, "power_dbm": power_dbm,
           "duration_s": duration_s, "callsign": (callsign or "").strip().upper()}
    if extra:
        rec.update(extra)
    path = path or default_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass
    return rec


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    s = {"tx_enabled": True, "callsign": "KD0ABC"}
    if not args:
        print("usage: txguard.py <freq_hz> [callsign]   (demo with TX enabled)")
        sys.exit(0)
    ok, reason = decide(float(args[0]), callsign=args[1] if len(args) > 1 else "", settings=s)
    print(("ALLOW" if ok else "DENY ") + "  " + reason)
    sys.exit(0 if ok else 1)
