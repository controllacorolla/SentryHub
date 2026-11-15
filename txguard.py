#!/usr/bin/env python3
"""
Transmit policy for the suite - the single place that decides whether keying the radio is
allowed, and the only gate any TX feature is permitted to go through.

The suite started life receive-only. Opening it up to transmit does NOT mean "key the HackRF
on any frequency": that same code would transmit on aviation, ADS-B, GPS and cellular bands,
where transmitting is a federal offence and a safety-of-life hazard. So the policy is:

  * license-free ISM bands for the configured REGION (default US)    -> allowed
  * amateur (ham) bands                                              -> allowed WITH a callsign
  * everything else, and anything unknown                            -> denied

Protected ranges (GPS, ADS-B, aviation voice, cellular, ...) are denied explicitly even if some
future band-plan edit would otherwise cover them - including for the conducted bench (owner
decision, strict default: CONDUCTED_PROTECTED_ALLOWED).

ONE public gate (audit G8): authorize(mode, ...). It knows the env hard lock, the master kill switch
(arm), the per-session unlock, the settings opt-in (tx_enabled must be exactly True), the per-mode
band whitelist, the callsign, power/gain/sample-rate sanity and the cross-process session state
(gatestate, audit L1). No service name is exempt (EXEMPT_SERVICES is empty: LoRa/Meshtastic goes
through the same chain). The band classifier (_decide) is private.

issue_ticket() turns a passed authorization into a single-use executor ticket bound to the exact
argv (audit G11); the executor re-runs authorize() at spawn and kills the process when it stops
passing (disarm, unlock dropped, hard lock).

subscribe(fn) registers a change listener for arm / unlock (audit G12).
"""
import math
import os

CALL_RE = __import__("re").compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z](?:-[0-9]{1,2})?$")

# ---- owner decisions, implemented at the strict answer (plan/briefs/CL2.md) -------------------
# 1. Conducted bench on protected bands (1090, 121.5, GNSS ...): denied even when conducted.
CONDUCTED_PROTECTED_ALLOWED = False
# 2. Modes exempt from the master kill switch + session unlock (NOT from the env lock, tx_enabled,
#    band or power checks). Empty - LoRa/Meshtastic included. Relaxing it is the owner's call.
EXEMPT_SERVICES = ()
# 3. (opprofile) a callsign alone never sets tx_enabled - see opprofile.tx_settings.

# Region for the band table. Unknown / missing -> the strict US table.
REGION_DEFAULT = "US"

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

# License-free ISM / short-range-device bands, per region (audit G10). In the US 433.05-434.79 MHz
# sits inside the 70 cm amateur band and is NOT licence-free: it is absent from the US table, so a
# 433.92 MHz burst classifies as amateur and needs a callsign. 902-928 overlaps the US 33cm ham
# band; LoRa/Meshtastic use it under Part 15.
ISM_BY_REGION = {
    "US": [(902_000_000, 928_000_000, "915 ISM"), (2_400_000_000, 2_483_500_000, "2.4 GHz ISM")],
    "EU": [(433_050_000, 434_790_000, "433 ISM/SRD"), (863_000_000, 870_000_000, "868 SRD"),
           (2_400_000_000, 2_483_500_000, "2.4 GHz ISM")],
}
ISM_BANDS = ISM_BY_REGION["US"]          # back-compat name: the default (strict) table

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

# ---- hardware sanity (audit G9) ---------------------------------------------------------------
HACKRF_GAIN_MAX = 47              # hackrf_transfer -x range is 0..47 dB
# Conservative: the HackRF One datasheet gives up to +15 dBm out (band dependent) at full gain, no
# amp. Assuming the high end means the derived gain never under-estimates the radiated power.
HACKRF_MAX_OUT_DBM = 15.0
POWER_FLOOR_DBM = -60.0           # below this a request is nonsense, not "very quiet"
SAMPLE_RATE_MIN = 2_000_000       # hackrf_transfer supports 2-20 Msps
SAMPLE_RATE_MAX = 20_000_000
TX_LOCK_FALSY = ("", "0", "false", "no", "off")


def _match(freq, table):
    for lo, hi, label in table:
        if lo <= freq <= hi:
            return label
    return None


def valid_callsign(call):
    """True for a plausibly-formatted amateur callsign (not a license check - just a gate so
    ham TX is deliberate and identifiable, as the FCC station-ID rules require)."""
    return bool(call) and bool(CALL_RE.match(str(call).strip().upper()))


def region_of(settings=None):
    """The band-table region from settings['tx_region']; unknown or missing -> strict US."""
    r = str((settings or {}).get("tx_region") or REGION_DEFAULT).strip().upper() \
        if isinstance(settings, dict) else REGION_DEFAULT
    return r if r in ISM_BY_REGION else REGION_DEFAULT


def _finite(x):
    """float(x) if x is a finite real number, else None. bool is not a number here."""
    if isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def as_hz(x):
    """A finite number (int, float, or text like "2e6" / "433.92e6") as a whole number of Hz / sps
    for an argv; None when it is not one. The gate checks the same _finite() value, so an argv
    builder never crashes on a value the gate accepted (CL2-fix N6)."""
    f = _finite(x)
    if f is None:
        return None
    return int(round(f))


def allocations(freq_hz, region=REGION_DEFAULT):
    """Every allocation the frequency falls in, for the region: subset of
    {'protected', 'ism', 'ham'}. Non-finite input -> {'protected'} (fail closed)."""
    f = _finite(freq_hz)
    if f is None:
        return {"protected"}
    out = set()
    if _match(f, PROTECTED):
        out.add("protected")
    if _match(f, ISM_BY_REGION.get(region, ISM_BY_REGION[REGION_DEFAULT])):
        out.add("ism")
    if _match(f, HAM_BANDS):
        out.add("ham")
    return out


def classify(freq_hz, region=REGION_DEFAULT):
    """'protected' | 'ham' | 'ism' | 'other'. Protected wins over everything. In the US the amateur
    table is checked first (audit G10); elsewhere the licence-free table is."""
    a = allocations(freq_hz, region)
    if "protected" in a:
        return "protected"
    order = ("ham", "ism") if region == "US" else ("ism", "ham")
    for kind in order:
        if kind in a:
            return kind
    return "other"


def env_locked():
    """The environment hard lock: any value except an explicit falsy one locks (audit G10)."""
    v = os.environ.get("SUITE_TX_LOCK")
    if v is None:
        return False
    return v.strip().lower() not in TX_LOCK_FALSY


def tx_locked(settings=None):
    """The settings kill switch. Locked unless settings say tx_enabled is exactly True (a string
    "yes", 1 or "true" from a hand-edited file does not count - audit G10), or if the environment
    forces a lock. Returns (locked: bool, reason: str)."""
    if env_locked():
        return True, "TX locked by SUITE_TX_LOCK in the environment"
    if not isinstance(settings, dict) or settings.get("tx_enabled") is not True:
        return True, "TX is disabled in settings (enable it deliberately to transmit)"
    return False, ""


def _decide(scope, f, callsign, settings):
    """PRIVATE band classifier for one mode scope. (ok, reason). Not a gate on its own: it knows
    nothing about arm / unlock / tx_enabled - only authorize() may call it."""
    region = region_of(settings)
    a = allocations(f, region)
    mhz = f / 1e6
    if "protected" in a:
        label = _match(f, PROTECTED)
        if scope == "conducted" and CONDUCTED_PROTECTED_ALLOWED:
            return True, "%.4f MHz conducted into a load (protected band %s)" % (mhz, label)
        return False, "%.4f MHz is in a protected band (%s) - transmitting there is illegal" % (
            mhz, label)
    if scope == "conducted":
        return True, "%.4f MHz conducted into a load, not radiating" % mhz
    if scope == "ham":
        if "ham" not in a:
            return False, "%.4f MHz is not an amateur band" % mhz
        call = str(callsign or (settings or {}).get("callsign", "")).strip().upper()
        if not valid_callsign(call):
            return False, ("%.4f MHz is the %s amateur band - a valid callsign is required "
                           "(and you must be licensed)" % (mhz, _match(f, HAM_BANDS)))
        return True, "%.4f MHz amateur %s, station %s" % (mhz, _match(f, HAM_BANDS), call)
    if scope == "ism":
        if "ism" not in a:
            hint = (" (in region %s it is amateur - needs a licence)" % region) if "ham" in a else ""
            return False, "%.4f MHz is not a license-free band in region %s%s" % (mhz, region, hint)
        return True, "%.4f MHz license-free (%s, region %s)" % (
            mhz, _match(f, ISM_BY_REGION[region]), region)
    return False, "%.4f MHz is not in any band the suite will transmit on" % mhz


# ===========================================================================================
# The gate: per-mode band/power caps, master kill switch, per-session unlock, TX event log.
# ===========================================================================================

# Per-mode TX profiles. scope: 'ham' (amateur bands, callsign required) | 'ism' (license-free) |
# 'conducted' (cabled into a load). power_dbm_max is a hard cap (enforced, not advisory); the
# authorized power is min(this, requested, hardware cap). 37 dBm = 5 W, 30 = 1 W, 20 = 100 mW.
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


# Session state: in-memory only (one process = one session). Never persisted - the plan requires
# a deliberate per-session unlock with no "remember my choice". A child process bound to a hub
# session (gatestate) reads the hub's state instead and cannot arm itself (audit L1).
_STATE = {"armed": False, "unlocked": False}
_LISTENERS = []


def subscribe(fn):
    """Call fn() whenever arm / unlock changes (audit G12). Listener errors are swallowed."""
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)


def unsubscribe(fn):
    try:
        _LISTENERS.remove(fn)
    except ValueError:
        pass


def _notify():
    for fn in list(_LISTENERS):
        try:
            fn()
        except Exception:
            pass


def _shared():
    """The hub's published gate state when this process is a bound child; None when this process
    owns its own state. gatestate.STALE (a dict with armed/unlocked False) when the hub is gone."""
    try:
        import gatestate
    except ImportError:
        return None
    return gatestate.shared_state()


def arm(on=True):
    """Master TX kill switch (default OFF/safe). While OFF, every authorize() denies. Disarming
    also drops any session unlock. Returns the new armed state. A child process bound to a hub
    session cannot arm (only the hub's switch counts)."""
    if _shared() is not None:
        return False if on else is_armed()
    before = dict(_STATE)
    _STATE["armed"] = bool(on) is True
    if not _STATE["armed"]:
        _STATE["unlocked"] = False
    if _STATE != before:
        _notify()
    return _STATE["armed"]


def is_armed():
    sh = _shared()
    if sh is not None:
        return sh.get("armed") is True
    return _STATE["armed"]


def unlock_session(on=True):
    """Explicit per-session unlock. Only takes effect while armed; never persisted."""
    if _shared() is not None:
        return False
    before = dict(_STATE)
    _STATE["unlocked"] = bool(on) is True and _STATE["armed"]
    if _STATE != before:
        _notify()
    return _STATE["unlocked"]


def session_unlocked():
    sh = _shared()
    if sh is not None:
        return sh.get("armed") is True and sh.get("unlocked") is True
    return _STATE["unlocked"]


def reset_session():
    """Drop arm + unlock (used at startup and by tests)."""
    changed = _STATE["armed"] or _STATE["unlocked"]
    _STATE["armed"] = False
    _STATE["unlocked"] = False
    if changed:
        _notify()


def emit_allowed():
    """The RF-silence gate for EVERY emitter, including the engagement-gated ones (Wi-Fi deauth,
    Zigbee inject, BLE, Flipper sub-GHz, Proxmark sim/clone …) — owner decision 2, CL2-fix N2.
    (ok, reason). Denied while the env hard lock is set, while a bound child's hub state is stale,
    or while the master kill switch is OFF. It does not need the session unlock or a band check:
    those belong to txguard's own SDR modes. The executor runs it at issue, at spawn and while the
    process runs, so a disarm kills a running emitter."""
    if env_locked():
        return False, "RF silenced: TX locked by SUITE_TX_LOCK in the environment"
    sh = _shared()
    if sh is not None and sh.get("stale"):
        return False, "RF silenced: hub session state is missing or stale (fail closed)"
    if not is_armed():
        return False, "RF silenced: the TX kill switch is OFF — arm it (TX slot) to emit"
    return True, ""


def gain_for_power(power_dbm):
    """hackrf_transfer -x gain that cannot exceed power_dbm, using the conservative full-gain
    output estimate. Clamped to 0..47. Non-finite -> 0 (the floor)."""
    p = _finite(power_dbm)
    if p is None:
        return 0
    g = int(math.floor(HACKRF_GAIN_MAX - (HACKRF_MAX_OUT_DBM - p)))
    return max(0, min(HACKRF_GAIN_MAX, g))


def check_gain(requested, power_allowed):
    """(ok, reason, gain). A requested -x gain is an integer 0..47; it is clamped DOWN to the gain
    the authorized power allows. Non-integer / non-finite / negative requests are denied."""
    cap = gain_for_power(power_allowed)
    if requested is None:
        return True, "gain %d dB (from %s dBm)" % (cap, power_allowed), cap
    if isinstance(requested, bool):
        return False, "TX gain is not a number", None
    f = _finite(requested)
    if f is None or f != int(f):
        return False, "TX gain must be a whole number of dB (got %r)" % (requested,), None
    g = int(f)
    if g < 0 or g > HACKRF_GAIN_MAX:
        if g > HACKRF_GAIN_MAX:
            return True, "gain %d clamped to %d dB (authorized %s dBm)" % (g, cap, power_allowed), cap
        return False, "TX gain %d is out of range 0..%d" % (g, HACKRF_GAIN_MAX), None
    if g > cap:
        return True, "gain %d clamped to %d dB (authorized %s dBm)" % (g, cap, power_allowed), cap
    return True, "gain %d dB" % g, g


def authorize(mode, freq_hz=None, power_dbm=None, callsign="", settings=None, sample_rate=None):
    """THE gate for a real key-up. Returns (ok, reason, power_dbm_allowed).

    Chain (all must pass, fail closed): known mode -> env not hard-locked -> hub session state
    valid (when bound) -> master kill switch armed -> session unlocked -> settings opt-in
    (tx_enabled is True) -> finite power within range -> sample rate within the radio's range ->
    frequency finite and positive -> per-mode band whitelist for the region (protected always
    denied) -> callsign on ham -> power clamped to the mode cap."""
    prof = profile(mode)
    if prof is None:
        return False, "unknown TX mode %r" % (mode,), 0
    if env_locked():
        return False, "TX locked by SUITE_TX_LOCK in the environment", 0
    sh = _shared()
    if sh is not None and sh.get("stale"):
        return False, "hub session state is missing or stale — TX refused (fail closed)", 0
    exempt = str(mode).lower() in EXEMPT_SERVICES
    if not exempt and not is_armed():
        return False, "TX kill switch is OFF — arm it (TX slot) to transmit", 0
    if not exempt and not session_unlocked():
        return False, "TX is not unlocked this session — unlock deliberately before keying", 0
    locked, why = tx_locked(settings)
    if locked:
        return False, why, 0
    cap = prof["power_dbm_max"]
    if power_dbm is None:
        want = cap
    else:
        p = _finite(power_dbm)
        if p is None:
            return False, "power %r is not a finite number" % (power_dbm,), 0
        if p < POWER_FLOOR_DBM:
            return False, "power %.1f dBm is below the %d dBm floor" % (p, POWER_FLOOR_DBM), 0
        want = min(cap, p)
        if want == int(want):
            want = int(want)
    if sample_rate is not None:
        sr = _finite(sample_rate)
        if sr is None or not (SAMPLE_RATE_MIN <= sr <= SAMPLE_RATE_MAX):
            return False, "sample rate %r outside %d..%d sps" % (
                sample_rate, SAMPLE_RATE_MIN, SAMPLE_RATE_MAX), 0
    if freq_hz is None:
        return False, "no frequency given — refusing to key the radio", 0
    f = _finite(freq_hz)
    if f is None:
        return False, "frequency is not a finite number", 0
    if f <= 0:
        return False, "frequency must be positive", 0
    if prof["scope"] == "conducted" and (settings or {}).get("bench_conducted_ack") is not True:
        return False, ("conducted-bench TX needs the conducted-only acknowledgment "
                       "(output into a dummy load/attenuator, not an antenna)"), 0
    ok, why = _decide(prof["scope"], f, callsign, settings)
    if not ok:
        return False, why, 0
    return True, "%s: %s — authorized (<= %s dBm)" % (prof["label"], why, want), want


# CL2-fix2 R6: TX programs txguard can issue for, with the exact option grammar their argv may
# use: {program: (frequency flag, {flag: takes_value})}. Anything outside it cannot be parsed, so
# its frequency cannot be verified, so it is refused (fail closed).
TX_ARGV_GRAMMAR = {
    "hackrf_transfer": ("-f", {"-t": True, "-f": True, "-s": True, "-x": True, "-R": False}),
}


def argv_freq_hz(argv):
    """The frequency (whole Hz) a TX argv keys, or (None, reason) when it cannot be read exactly:
    unknown program, a path or wrapper as argv[0], an option outside the grammar, a missing,
    repeated or non-numeric frequency. Returns (hz_or_None, reason)."""
    toks = [str(a) for a in (argv or ())]
    if not toks or toks[0] not in TX_ARGV_GRAMMAR:
        return None, ("cannot verify the frequency of %r — txguard issues only for %s"
                      % ((toks or ["?"])[0], ", ".join(sorted(TX_ARGV_GRAMMAR))))
    fflag, grammar = TX_ARGV_GRAMMAR[toks[0]]
    found, i = [], 1
    while i < len(toks):
        t = toks[i]
        if t not in grammar:
            return None, "cannot parse %r in the TX command — refusing" % t
        if grammar[t]:
            if i + 1 >= len(toks):
                return None, "%s has no value in the TX command — refusing" % t
            if t == fflag:
                found.append(toks[i + 1])
            i += 2
        else:
            i += 1
    if len(found) != 1:
        return None, "the TX command must give exactly one %s frequency (found %d)" % (fflag,
                                                                                    len(found))
    v = found[0]
    if not (v.isascii() and v.isdigit()):
        return None, "TX command frequency %r is not a whole number of Hz — refusing" % v
    return int(v), ""


def argv_matches_freq(argv, freq_hz):
    """(ok, reason): does the TX argv key exactly the authorized freq_hz?"""
    hz, why = argv_freq_hz(argv)
    if hz is None:
        return False, "TX blocked: " + why
    want = as_hz(freq_hz)
    if want is None or hz != want:
        return False, ("TX blocked: the command keys %d Hz but %s Hz was authorized — refusing"
                       % (hz, freq_hz))
    return True, ""


def issue_ticket(mode, argv, freq_hz=None, power_dbm=None, callsign="", settings=None,
                 sample_rate=None, label=None, files=None, live=None):
    """authorize() and, on success, a single-use executor ticket bound to exactly this argv. The
    executor re-runs the same authorize() at spawn and while the process runs, against the LIVE
    settings: the same `settings` object (not a copy), or `live()` when the caller's settings are
    rebuilt from a store on every read (bench). Returns (ok, reason, ticket_or_None, power)."""
    ok, why, power = authorize(mode, freq_hz, power_dbm, callsign, settings, sample_rate)
    if not ok:
        return False, why, None, 0
    # CL2-fix2 R6: the command must key exactly the frequency that was authorized — a 1090 MHz
    # argv on a 915 MHz authorization is refused, and so is any argv whose frequency cannot be read.
    f_ok, f_why = argv_matches_freq(argv, freq_hz)
    if not f_ok:
        return False, f_why, None, 0
    import executor

    def recheck():
        # LIVE settings (CL2-fix N8): the caller's own dict, or its loader when it passed
        # live=callable — clearing tx_enabled mid-transmission stops it, like disarm does.
        try:
            cur = live() if callable(live) else settings
        except Exception as e:
            return False, "settings could not be re-read (%s) — refusing" % e
        r = authorize(mode, freq_hz, power_dbm, callsign, cur, sample_rate)
        return r[0], r[1]
    t = executor.issue(argv, recheck, label=label or "tx:%s" % mode, binding="tx-gate",
                       reason=why, files=files)
    return True, why, t, power


def default_log_path():
    return os.path.join(os.path.expanduser("~"), ".local", "share", "uconsole-suite",
                        "tx_log.jsonl")


def log_tx(freq_hz, mode, power_dbm, duration_s, callsign, path=None, extra=None):
    """Append one TX event to tx_log.jsonl (timestamp, freq, mode, power, duration, callsign).
    Called by a TX module after a transmission; failure to log never raises."""
    import json
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
    if not args:
        print("usage: txguard.py <freq_hz> [callsign] [region]   (band classification only)")
        sys.exit(0)
    reg = args[2].upper() if len(args) > 2 else REGION_DEFAULT
    print("%s  %s" % (classify(float(args[0]), reg), sorted(allocations(float(args[0]), reg))))
