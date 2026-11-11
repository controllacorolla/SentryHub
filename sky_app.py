#!/usr/bin/env python3
"""
Sky - live ADS-B map + airband voice in one app, for the uConsole.

Radio layout
  * Built-in RTL-SDR  -> readsb (1090 MHz ADS-B). Left alone; the map never stops.
  * H4M Pro in HackRF mode (USB) -> rtl_airband via SoapySDR (118-137 MHz voice).
  * No H4M plugged in -> falls back to the built-in SDR for airband and pauses the
    map while you listen (the old single-dongle behaviour).

Usage
  sky              open the app
  sky --start      open and start listening immediately
  sky --stop       emergency stop: kill every rtl_airband, restore plane map
  sky --status     diagnostics (H4M, SoapySDR, readsb, audio)
"""

import skyintel as SI
import fcntl
import glob
import json
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

APP = "sky-app"
HOME = os.path.expanduser("~")
CFG_DIR = os.path.join(HOME, ".config", APP)
CACHE_DIR = os.path.join(HOME, ".cache", APP)
SETTINGS_PATH = os.path.join(CFG_DIR, "settings.json")
CONF_PATH = os.path.join(CFG_DIR, "rtl_airband.conf")
STATE_PATH = os.path.join(CACHE_DIR, "state.json")
LOG_PATH = os.path.join(CACHE_DIR, "sky.log")
LOCK_PATH = os.path.join(CACHE_DIR, "app.lock")
STATS_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or CACHE_DIR, "sky-airband-stats.txt")
USB_SYSFS = os.environ.get("SKY_USB_SYSFS", "/sys/bus/usb/devices")
REC_DIR = os.path.join(HOME, ".cache", "sky-app", "recordings")
TRANSCRIBER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcriber.py")
OLD_AIRBAND_SETTINGS = os.path.join(HOME, ".config", "airband-app", "settings.json")

# Airport reference data (OurAirports). Runways as (lat1, lon1, lat2, lon2).
AIRPORTS = {
    "KAPA": {"name": "Centennial", "lat": 39.57010, "lon": -104.84900, "elev": 5885,
             "rwys": [(39.57290, -104.84800, 39.56820, -104.83200),
                      (39.58410, -104.85100, 39.55670, -104.85000),
                      (39.57900, -104.85400, 39.55980, -104.85300)]},
    "KDEN": {"name": "Denver Intl", "lat": 39.86003, "lon": -104.67379, "elev": 5431,
             "rwys": [(39.84090, -104.72700, 39.84070, -104.68400),
                      (39.87760, -104.66200, 39.87720, -104.61900),
                      (39.89700, -104.68700, 39.86410, -104.68700),
                      (39.89580, -104.69600, 39.85190, -104.69700),
                      (39.86500, -104.64100, 39.83200, -104.64200),
                      (39.86120, -104.66000, 39.82830, -104.66100)]},
    "KBKF": {"name": "Buckley SFB", "lat": 39.70170, "lon": -104.75200, "elev": 5662,
             "rwys": [(39.71500, -104.76100, 39.68850, -104.74300)]},
    "KBJC": {"name": "Rocky Mtn Metro", "lat": 39.90880, "lon": -105.11700, "elev": 5673,
             "rwys": [(39.90590, -105.11800, 39.91400, -105.11100),
                      (39.91530, -105.12800, 39.90140, -105.10200),
                      (39.91420, -105.13200, 39.90340, -105.11100)]},
    "KFTG": {"name": "Colorado Air & Space Port", "lat": 39.78419, "lon": -104.53764, "elev": 5512,
             "rwys": [(39.79400, -104.56500, 39.79360, -104.53700),
                      (39.78560, -104.52400, 39.76360, -104.52400)]},
}

RWY_IDS = {
    "KAPA": [("10", "28"), ("17L", "35R"), ("17R", "35L")],
    "KDEN": [("07", "25"), ("08", "26"), ("16L", "34R"), ("16R", "34L"), ("17L", "35R"), ("17R", "35L")],
    "KBKF": [("14", "32")],
    "KBJC": [("03", "21"), ("12L", "30R"), ("12R", "30L")],
    "KFTG": [("08", "26"), ("17", "35")],
}

RWY_ENDS = {ident: SI.runway_ends(AIRPORTS[ident]["rwys"], RWY_IDS[ident])
            for ident in RWY_IDS if ident in AIRPORTS}

GAIN_STEPS_RTL = [0.0, 0.9, 1.4, 2.7, 3.7, 7.7, 8.7, 12.5, 14.4, 15.7, 16.6, 19.7, 20.7,
                  22.9, 25.4, 28.0, 29.7, 32.8, 33.8, 36.4, 37.2, 38.6, 40.2, 42.1, 43.4,
                  43.9, 44.5, 48.0, 49.6]
LNA_STEPS = [0, 8, 16, 24, 32, 40]  # HackRF LNA (IF) gain, dB

DEFAULT_CHANNELS = [
    {"freq": 118.900, "label": "APA Tower", "airport": "KAPA", "role": "tower", "on": True},
    {"freq": 120.300, "label": "APA ATIS", "airport": "KAPA", "role": "atis", "on": False},
    {"freq": 121.800, "label": "APA Ground", "airport": "KAPA", "role": "ground", "on": True},
    {"freq": 128.600, "label": "APA Clearance", "airport": "KAPA", "role": "clearance", "on": True},
    {"freq": 132.750, "label": "Denver App/Dep", "airport": "KDEN", "role": "approach", "on": True},
    {"freq": 125.600, "label": "DEN ATIS", "airport": "KDEN", "role": "atis", "on": False},
    {"freq": 124.300, "label": "DEN Tower", "airport": "KDEN", "role": "tower", "on": True},
    {"freq": 119.300, "label": "DEN Approach", "airport": "KDEN", "role": "approach", "on": True},
]

DEFAULT_SETTINGS = {
    # Airband radio.  "rtlsdr": the built-in SDR (default; readsb/ADS-B runs on the H4M)
    # "hackrf": H4M only   |   "auto": H4M if plugged in and not already running ADS-B
    "airband_device": "rtlsdr",
    "hackrf": {"lna": 32, "vga": 20, "amp": 0, "sample_rate": 2560000, "correction": 0},
    "rtlsdr": {"index": 0, "gain": 40.2, "correction": -5},
    "restore_plane_map": True,
    # one MP3 per transmission -> Whisper transcripts (needs the suite's transcriber)
    "transcribe": True,
    "whisper_model": "base.en",
    "keep_audio_hours": 24,
    "sdr_services": ["readsb", "dump1090-fa"],
    "kill_programs_rtl": ["sdrpp", "gqrx", "rtl_fm", "rtl_tcp", "rtl_433", "rtl_power",
                          "rtl_sdr", "dump1090", "dump1090-fa", "readsb"],
    "kill_programs_hackrf": ["hackrf_transfer", "hackrf_sweep", "sdrpp", "gqrx"],
    "kill_patterns": ["rx.py"],
    "adsb_sources": ["/run/readsb", "/run/dump1090-fa", "/run/adsb", "/run/dump1090",
                     "http://127.0.0.1/tar1090/data", "http://127.0.0.1:8080/data",
                     "http://127.0.0.1:8504/data"],
    "sky_mode": "both",     # "both" | "visual" (silent map) | "voice" (eyes-free audio)
    "tfr_states": ["CO"],   # states whose active FAA TFRs show in the situation report
    "map_center": "KAPA-KDEN",
    "map_layer": "dark",          # dark | sat | streets
    "map_zoom": 10,
    "map_radar": False,           # NEXRAD overlay on/off (R key)
    # alerts: callsigns / hex codes / registrations to announce when they appear
    "watch": [],
    # alert when any airborne contact comes within <nm> of the receiver below <below_ft>
    # (0 disables). Useful for "something is low over my head" while in the field.
    "fence": {"nm": 0, "below_ft": 3000},
    "show_coverage": True,        # antenna reception outline on the map (key C)
    "overhead_callout": True,     # say "overhead in 2 minutes" in Voice/Both views
    "route_lookup": True,         # look up the SELECTED flight's route (adsbdb, cached)
    # ATC bingo card phrases (5x5 card drawn from these each day)
    "bingo_phrases": ["say again", "go around", "expedite", "caution wake turbulence", "traffic in sight",
                      "any traffic please advise", "cleared for the option", "line up and wait",
                      "hold short", "cleared to land", "cleared for takeoff", "contact ground",
                      "contact departure", "squawk", "ident", "say intentions", "unable", "roger",
                      "wilco", "negative", "affirmative", "descend and maintain", "climb and maintain",
                      "reduce speed", "turn left heading", "turn right heading", "altimeter",
                      "wind calm", "runway change", "taxi via", "monitor tower", "good day",
                      "with you", "checking in", "looking for traffic", "touch and go",
                      "full stop", "request", "ready for departure", "position and hold",
                      "braking action", "low level wind shear", "birds", "pilot's discretion"],
    # spoken alert when one of these phrases shows up in an airband transcript
    "anomaly_alerts": True,       # flag military, circling, and new aircraft types
    "keywords": ["mayday", "pan pan", "declaring an emergency", "emergency", "go around",
                 "going around", "minimum fuel", "medical", "bird strike", "runway incursion",
                 "squawk 7700", "unable"],
    "channels": DEFAULT_CHANNELS,
}

BUSY_RE = re.compile(r"Failed to open rtlsdr|usb_claim_interface|resource busy|"
                     r"Failed to open SoapySDR|hackrf_open|No supported devices|"
                     r"device not found|Cannot open device|HACKRF_ERROR", re.I)


# --------------------------------------------------------------------------- utils

def ensure_dirs():
    for d in (CFG_DIR, CACHE_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass   # read-only filesystem: degrade, don't die


def file_log(msg):
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 300_000:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg.rstrip() + "\n")
    except OSError:
        pass


def run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    # unique temp name per writer: concurrent saves must never truncate each other's
    # temp file (os.replace itself is atomic; the shared ".tmp" name was the race)
    tmp = "%s.%d.%x.tmp" % (path, os.getpid(), threading.get_ident())
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def deepcopy(x):
    return json.loads(json.dumps(x))


def load_settings():
    s = load_json(SETTINGS_PATH, None)
    if not isinstance(s, dict):
        s = deepcopy(DEFAULT_SETTINGS)
        # carry over channel on/off + RTL gain from the Airband app, if present
        old = load_json(OLD_AIRBAND_SETTINGS, None)
        if isinstance(old, dict):
            known = {"%.3f" % c["freq"]: c for c in s["channels"]}
            chans = []
            for oc in old.get("channels", []):
                k = "%.3f" % float(oc.get("freq", 0))
                base = known.get(k, {"airport": "KAPA", "role": "other"})
                chans.append({"freq": float(oc["freq"]), "label": oc.get("label", k),
                              "airport": base["airport"], "role": base["role"],
                              "on": bool(oc.get("on", True))})
            if chans:
                s["channels"] = chans
            if "gain" in old:
                s["rtlsdr"]["gain"] = old["gain"]
            if "correction" in old:
                s["rtlsdr"]["correction"] = old["correction"]
        try:
            save_json(SETTINGS_PATH, s)
        except OSError:
            pass   # read-only filesystem: run on defaults
    def _typed(default, val):
        """A stored value only survives if it has the default's broad type; anything
        else (hand-edited or corrupt settings) falls back so no consumer crashes."""
        if isinstance(default, bool):
            return val if isinstance(val, bool) else default
        if isinstance(default, (int, float)):
            return val if isinstance(val, (int, float)) and not isinstance(val, bool) \
                else default
        if isinstance(default, str):
            return val if isinstance(val, str) else default
        if isinstance(default, list):
            return val if isinstance(val, list) else deepcopy(default)
        if isinstance(default, dict):
            if not isinstance(val, dict):
                return deepcopy(default)
            out = dict(val)
            for kk, vv in default.items():
                out[kk] = _typed(vv, val[kk]) if kk in val else deepcopy(vv)
            return out
        return val

    for k, v in DEFAULT_SETTINGS.items():
        s[k] = _typed(v, s[k]) if k in s else deepcopy(v)
    good = []
    for c in s["channels"]:
        try:
            c["freq"] = float(c["freq"])
        except (KeyError, TypeError, ValueError):
            continue
        c.setdefault("label", "%.3f" % c["freq"])
        c.setdefault("airport", "KAPA")
        c.setdefault("role", "other")
        c.setdefault("on", True)
        good.append(c)
    s["channels"] = good or deepcopy(DEFAULT_CHANNELS)
    if not H4M_ENABLED:
        s["airband_device"] = "rtlsdr"
    return s


def nearest_index(steps, v):
    return min(range(len(steps)), key=lambda i: abs(steps[i] - float(v)))


def pids_named(name):
    rc, out = run(["pgrep", "-x", name])
    return [int(p) for p in out.split()] if rc == 0 else []


def pids_matching(pattern):
    rc, out = run(["pgrep", "-f", pattern])
    me = os.getpid()
    return [int(p) for p in out.split() if p.isdigit() and int(p) != me] if rc == 0 else []


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_pids(pids, grace=3.0):
    pids = [p for p in pids if alive(p)]
    for sig, wait in ((signal.SIGINT, grace), (signal.SIGTERM, 2.0), (signal.SIGKILL, 1.0)):
        if not pids:
            break
        for p in pids:
            try:
                os.kill(p, sig)
            except (ProcessLookupError, PermissionError):
                pass
        end = time.time() + wait
        while time.time() < end and any(alive(p) for p in pids):
            time.sleep(0.1)
        pids = [p for p in pids if alive(p)]
    return pids


def service_state(name):
    rc, out = run(["systemctl", "is-active", name])
    return out.splitlines()[-1].strip() if out else "unknown"


def sudo_systemctl(action, name, timeout=20):
    return run(["sudo", "-n", "systemctl", action, name], timeout=timeout)


def usb_devices():
    """[(vid, pid, product)] from sysfs - no lsusb dependency."""
    out = []
    for d in glob.glob(os.path.join(USB_SYSFS, "*")):
        try:
            vid = open(os.path.join(d, "idVendor")).read().strip().lower()
            pid = open(os.path.join(d, "idProduct")).read().strip().lower()
        except OSError:
            continue
        try:
            prod = open(os.path.join(d, "product")).read().strip()
        except OSError:
            prod = ""
        out.append((vid, pid, prod))
    return out


H4M_ENABLED = False     # the H4M is not used: nothing probes it, opens it or offers it


def hackrf_status():
    """'ready' (HackRF mode), 'wrong_mode' (H4M plugged in, not HackRF mode), or 'absent'."""
    if not H4M_ENABLED:
        return "absent"
    devs = usb_devices()
    if any(v == "1d50" and p in ("6089", "cc15", "604b") for v, p, _ in devs):
        return "ready"
    # 1d50 is OpenMoko's shared vendor ID (ZMK keyboards use it too), so match the
    # PortaPack/Mayhem serial ID or the product string, not the vendor alone
    if any((v == "1d50" and p == "6018") or
           any(k in pr.lower() for k in ("portapack", "hackrf", "mayhem"))
           for v, p, pr in devs):
        return "wrong_mode"
    return "absent"


def airband_has_soapy(binary):
    if not binary:
        return False
    rc, out = run(["ldd", binary])
    return "libSoapySDR" in out


def adsb_device():
    """'hackrf' when readsb is configured for the H4M, else 'rtlsdr'."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:   # called on every redraw: don't grow sys.path each time
            sys.path.insert(0, here)
        import suite as _suite
        return _suite.adsb_device()
    except Exception:
        return "rtlsdr"


def soapy_finds_hackrf():
    """True / False / None (SoapySDRUtil not installed)."""
    if not shutil.which("SoapySDRUtil"):
        return None
    rc, out = run(["SoapySDRUtil", "--find=driver=hackrf"], timeout=15)
    if "no devices found" in out.lower():
        return False
    return bool(re.search(r"^\s*driver\s*=\s*hackrf\s*$", out, re.M | re.I))


RECORDS_PATH = os.path.join(HOME, ".local", "share", "uconsole-suite", "sky_records.json")
COVERAGE_PATH = os.path.join(HOME, ".local", "share", "uconsole-suite", "sky_coverage.json")
LOGBOOK_DIR = os.path.join(HOME, ".local", "share", "uconsole-suite", "logbook")
RECORD_LABELS = [
    ("fastest", "Fastest", "%d kt"), ("highest", "Highest", "%s ft"), ("closest", "Closest", "%.1f nm"),
    ("lowest_overhead", "Lowest within 3 nm", "%s ft"), ("farthest", "Farthest seen", "%.0f nm"),
    ("most_contacts", "Most contacts at once", "%d"),
]


def load_records():
    d = load_json(RECORDS_PATH, {})
    if not isinstance(d, dict):
        d = {}
    today = time.strftime("%Y-%m-%d")
    if d.get("date") != today:
        d = {"date": today, "today": {}, "best": d.get("best", {}), "days": d.get("days", 0) + (1 if d.get("date") else 0)}
    d.setdefault("today", {})
    d.setdefault("best", {})
    return d


def record_lines(d, scope="today"):
    """Human lines for the Hub tile / Sky info line."""
    out = []
    for key, label, fmt in RECORD_LABELS:
        r = d.get(scope, {}).get(key)
        if not r:
            continue
        v = r["v"]
        val = fmt % (format(int(v), ",") if "%s" in fmt else v)
        out.append("%s %s: %s %s" % (label, "today" if scope == "today" else "ever", r.get("cs", ""), val).replace("  ", " "))
    return out


def write_rtl_conf(s, device, record=False):
    chans = [c for c in s["channels"] if c.get("on")]
    if not chans:
        raise ValueError("No channels switched on.")
    freqs = ", ".join(str(int(round(float(c["freq"]) * 1_000_000))) for c in chans)
    labels = ", ".join('"%s"' % str(c["label"]).replace("\\", "/").replace('"', "'") for c in chans)
    L = ["# Generated by Sky - change radios and channels in Sky > Settings",
         'stats_filepath = "%s";' % STATS_PATH, "stats_update_interval = 1.0;",
         "devices:", "({"]
    if device == "hackrf":
        h = s["hackrf"]
        L += ['  type = "soapysdr";',
              '  device_string = "driver=hackrf";',
              '  gain = "LNA=%d,VGA=%d,AMP=%d";' % (int(h["lna"]), int(h["vga"]),
                                                     14 if int(h["amp"]) else 0),
              "  sample_rate = %d;" % int(h["sample_rate"]),
              "  correction = %d;" % int(h["correction"])]
    else:
        r = s["rtlsdr"]
        L += ['  type = "rtlsdr";',
              "  index = %d;" % int(r["index"]),
              "  gain = %.1f;" % float(r["gain"]),
              "  correction = %d;" % int(r["correction"])]
    L += ['  mode = "scan";', "  channels:", "  ({",
          "    freqs = ( %s );" % freqs, "    labels = ( %s );" % labels,
          "    outputs:", "    ({", '      type = "pulse";', '      stream_name = "Sky airband";',
          "    }"]
    if record:
        os.makedirs(REC_DIR, exist_ok=True)
        L += ["    ,{", '      type = "file";', '      directory = "%s";' % REC_DIR,
              '      filename_template = "tx";', "      split_on_transmission = true;",
              "      include_freq = true;", "    }"]
    L += ["    );", "  });", "});", ""]
    with open(CONF_PATH, "w") as f:
        f.write("\n".join(L))


def read_levels():
    """{freq_str: dBFS signal level} from the stats file (newer rtl_airband)."""
    out = {}
    try:
        with open(STATS_PATH) as f:
            for line in f:
                if line.startswith("channel_dbfs_signal_level{"):
                    m = re.search(r'freq="([\d.]+)".*}\s+(-?[\d.]+)', line)
                    if m:
                        out[m.group(1)] = float(m.group(2))
    except OSError:
        pass
    return out


def read_stats():
    out = {}
    try:
        with open(STATS_PATH) as f:
            for line in f:
                if line.startswith("channel_activity_counter{"):
                    m = re.search(r'freq="([\d.]+)".*}\s+(\d+)', line)
                    if m:
                        out[m.group(1)] = int(m.group(2))
    except OSError:
        return None
    return out


def audio_output_name():
    rc, sink = run(["pactl", "get-default-sink"], timeout=3)
    if rc != 0 or not sink:
        rc, info = run(["pactl", "info"], timeout=3)
        m = re.search(r"Default Sink:\s*(\S+)", info or "")
        sink = m.group(1) if m else ""
    if not sink:
        return "no audio server"
    rc, out = run(["pactl", "list", "sinks"], timeout=3)
    cur = None
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            cur = line.split(":", 1)[1].strip()
        elif line.startswith("Description:") and cur == sink:
            return line.split(":", 1)[1].strip()
    return sink


# ----------------------------------------------------------------------- geo/ADS-B

def dist_nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3440.065 * 2 * math.asin(math.sqrt(min(1, a)))


def on_ground(ac):
    return ac.get("alt_baro") == "ground"


def alt_ft(ac):
    a = ac.get("alt_baro")
    if a == "ground":
        return None
    if isinstance(a, (int, float)):
        return a
    a = ac.get("alt_geom")
    return a if isinstance(a, (int, float)) else None


def likely_on_channel(ch, aircraft):
    """Aircraft plausibly talking on a channel. A heuristic, not an ID: ATC audio has no
    aircraft identity in it. Returns hex codes, nearest first."""
    role = ch.get("role", "other")
    ap = AIRPORTS.get(ch.get("airport", ""))
    if role == "atis" or not ap:
        return []
    out = []
    for ac in aircraft:
        if "lat" not in ac:
            continue
        d = dist_nm(ap["lat"], ap["lon"], ac["lat"], ac["lon"])
        alt, gs, gnd = alt_ft(ac), ac.get("gs") or 0, on_ground(ac)
        ok = False
        if role == "tower":
            ok = (not gnd and alt is not None and d <= 8 and alt <= ap["elev"] + 4000) or \
                 (gnd and d <= 2 and gs >= 40)
        elif role in ("ground", "clearance"):
            ok = d <= 2.5 and (gnd or (alt is not None and alt <= ap["elev"] + 300 and gs < 60))
        elif role in ("approach", "departure"):
            near_field = any(dist_nm(a["lat"], a["lon"], ac["lat"], ac["lon"]) < 4 and
                             alt is not None and alt < a["elev"] + 1500 for a in AIRPORTS.values())
            ok = (not gnd and alt is not None and d <= 45 and alt <= 18000 and not near_field)
        if ok:
            out.append((d, ac["hex"]))
    out.sort()
    return [h for _, h in out[:8]]


ADSB_NUM_FIELDS = ("lat", "lon", "track", "gs", "baro_rate", "geom_rate", "alt_geom",
                   "seen", "seen_pos", "rssi", "messages", "nav_altitude_mcp", "nav_heading")


def clean_aircraft(a):
    """Coerce one aircraft dict from the wire into what the app assumes: numeric fields
    numeric or absent, sane coordinates, printable bounded strings. readsb is trusted in
    practice, but a hostile or corrupt feed must never crash the map."""
    a["hex"] = str(a.get("hex", "")).strip().lower()[:12]
    for k in ADSB_NUM_FIELDS:
        if k in a and not isinstance(a[k], (int, float)):
            try:
                a[k] = float(a[k])          # None and junk both fail -> key removed
            except (TypeError, ValueError):
                del a[k]
    if "alt_baro" in a and a["alt_baro"] != "ground" \
            and not isinstance(a["alt_baro"], (int, float)):
        try:
            a["alt_baro"] = float(a["alt_baro"])
        except (TypeError, ValueError):
            del a["alt_baro"]
    la, lo = a.get("lat"), a.get("lon")
    if la is not None and not (isinstance(lo, (int, float)) and -85.0 <= la <= 85.0
                               and -180.0 <= lo <= 180.0):
        a.pop("lat", None)
        a.pop("lon", None)
    if isinstance(a.get("track"), (int, float)):
        a["track"] = a["track"] % 360
    if isinstance(a.get("gs"), (int, float)) and a["gs"] < 0:
        a["gs"] = 0
    for k in ("flight", "r", "t", "desc", "ownOp", "squawk", "category", "emergency", "type"):
        v = a.get(k)
        if v is not None:
            if not isinstance(v, str):
                v = str(v)
            a[k] = "".join(ch for ch in v if ch.isprintable())[:48]
    return a


def bingo_card(phrases, rnd):
    """25 squares from the phrase list; repeats short lists so the 5x5 grid is always full."""
    phrases = [p for p in phrases if p] or ["free"]
    if len(phrases) >= 25:
        return rnd.sample(phrases, 25)
    return (phrases * 25)[:25]


# readsb "emergency" field values -> the alert kinds the UI ranks as emergencies
EMERG_SQUAWK = {"7500": "hijack", "7600": "radio failure", "7700": "emergency"}
EMERG_FIELD = {"general": "emergency", "downed": "emergency", "nordo": "radio failure",
               "unlawful": "hijack", "lifeguard": "lifeguard", "minfuel": "minimum fuel"}


def alert_kind(squawk, emergency):
    """Alert kind for an emergency squawk and/or readsb's emergency field."""
    if squawk in EMERG_SQUAWK:
        return EMERG_SQUAWK[squawk]
    em = str(emergency or "").lower()
    return EMERG_FIELD.get(em, "emergency")


MIL_PREFIXES_DEFAULT = ("RCH", "CNV", "EVAC", "PAT", "SPAR", "SAM", "GRIM", "DOOM", "HOBO",
                        "SHADE", "KING", "BOXER", "RODDY", "TITAN", "TABOR", "TREK", "TORCH",
                        "TOGA", "TROUT", "TUMBA", "TUNER", "TURBO", "GOLD", "TOPCAT", "BOLT",
                        "NOBLE", "QID", "REDEYE")


def is_military_ac(a, prefixes=MIL_PREFIXES_DEFAULT):
    """US military ICAO block, or a known military callsign prefix."""
    try:
        n = int(a.get("hex", ""), 16)
    except ValueError:
        n = 0
    if 0xADF7C8 <= n <= 0xAFFFFF:
        return True
    cs = (a.get("flight") or "").strip().upper()
    return any(cs.startswith(str(p)) for p in prefixes) and cs[:3].isalpha()


class AdsbFeed:
    """Polls readsb/dump1090 aircraft.json once a second on a background thread."""

    def __init__(self, sources):
        self.sources = sources
        self.aircraft = []
        self.receiver = None
        self.status = "none"     # live | stale | none
        self.source = None
        self.updated = 0.0
        self.trails = {}         # hex -> [(lat, lon)]
        self.history = []        # [(t, [compact aircraft])], one frame per ~2 s, last 60 min
        self._last_frame = 0.0
        self._rcv_retry = 0.0
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _get(self, base, name):
        if base.startswith("http"):
            with urllib.request.urlopen(base.rstrip("/") + "/" + name, timeout=2) as r:
                return json.loads(r.read().decode())
        with open(os.path.join(base, name)) as f:
            return json.load(f)

    stopped = False            # set when the workspace that owns this feed closes

    def _loop(self):
        order = list(self.sources)
        while not self.stopped:
            try:
                self._tick(order)
            except Exception:
                with self.lock:
                    self.status = "none"
            time.sleep(1.0)

    def _tick(self, order):
        if True:
            got = None
            for src in order:
                try:
                    data = self._get(src, "aircraft.json")
                    got = (src, data)
                    if order[0] != src:
                        order.remove(src)
                        order.insert(0, src)
                    break
                except Exception:
                    continue
            with self.lock:
                if got:
                    src, data = got
                    now = data.get("now", time.time())
                    acs = [clean_aircraft(a) for a in data.get("aircraft", [])
                           if isinstance(a, dict) and a.get("hex")]
                    acs = [a for a in acs if a["hex"] and a.get("seen", 99) < 60]
                    self.aircraft = acs
                    self.source = src
                    self.status = "live" if time.time() - now < 10 else "stale"
                    self.updated = time.time()
                    for a in acs:
                        if "lat" in a and a.get("seen_pos", 99) < 5:
                            t = self.trails.setdefault(a["hex"], [])
                            if not t or (t[-1][0], t[-1][1]) != (a["lat"], a["lon"]):
                                t.append((a["lat"], a["lon"]))
                                del t[:-30]
                    live = {a["hex"] for a in acs}
                    for h in list(self.trails):
                        if h not in live:
                            del self.trails[h]
                    if time.time() - self._last_frame >= 2.0 and \
                            not (self.history and now <= self.history[-1][0]):
                        # a stale aircraft.json repeats the same "now": skip it, or the
                        # 60-min cutoff never trims and history grows without bound
                        self._last_frame = time.time()
                        keep = ("hex", "flight", "lat", "lon", "track", "gs", "alt_baro", "alt_geom",
                                "baro_rate", "geom_rate", "squawk", "r", "t", "desc", "emergency",
                                "category")
                        frame = [{k: a[k] for k in keep if k in a} for a in acs
                                 if "lat" in a and a.get("seen_pos", 99) < 30]
                        self.history.append((now, frame))
                        cutoff = now - 3600
                        while self.history and self.history[0][0] < cutoff:
                            self.history.pop(0)
                else:
                    self.status = "none"
            # receiver position: fetched outside the lock (an http source can take 2 s and
            # snapshot() is called from the UI thread), and retried once a minute instead of
            # giving up for good after one failure or a receiver.json without lat/lon
            if got and not self.receiver and time.time() >= self._rcv_retry:
                self._rcv_retry = time.time() + 60
                try:
                    r = self._get(got[0], "receiver.json")
                    pos = (float(r["lat"]), float(r["lon"]))
                except Exception:
                    pos = False
                with self.lock:
                    if pos:
                        self.receiver = pos
                    elif self.receiver is None:
                        self.receiver = False

    def snapshot(self):
        with self.lock:
            return list(self.aircraft), dict(self.trails), self.status, self.receiver

    def history_span(self):
        with self.lock:
            if not self.history:
                return None, None
            return self.history[0][0], self.history[-1][0]

    def snapshot_at(self, t):
        """Aircraft and trails as they were at time t (nearest recorded frame at or before t)."""
        with self.lock:
            hist = self.history
            if not hist:
                return [], {}, "replay", self.receiver
            lo, hi = 0, len(hist) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if hist[mid][0] <= t:
                    lo = mid
                else:
                    hi = mid - 1
            idx = lo
            frame = [dict(a, seen=0, seen_pos=0) for a in hist[idx][1]]
            trails = {}
            for j in range(max(0, idx - 30), idx + 1):
                for a in hist[j][1]:
                    trails.setdefault(a["hex"], []).append((a["lat"], a["lon"]))
            return frame, trails, "replay", self.receiver


class DemoFeed:
    """Synthetic Front Range traffic so the display can be exercised without an antenna.

    Mirrors AdsbFeed.snapshot() so the real render path runs unchanged. The GUI labels
    it DEMO everywhere, never records it, and never raises alerts on it. Advances with
    wall-clock time on each snapshot() call - no thread, costs nothing while off.
    """
    CTR = (39.5701, -104.8490)   # receiver placed at KAPA

    def __init__(self):
        self.receiver = self.CTR
        self.updated = 0.0
        self._last = None
        self.trails = {}
        c_lat, c_lon = self.CTR

        def ac(hx, cs, dn, de, trk, gs, alt, rate=0, turn=0.0, typ="", desc="", gnd=False,
               cat="A3", mcp=None, loop_nm=None):
            # dn/de: nm north/east of the receiver; 0.774 ~ cos(39.6 deg)
            return {"hex": hx, "flight": cs, "lat": c_lat + dn / 60.0,
                    "lon": c_lon + de / (60.0 * 0.774), "track": float(trk), "gs": gs,
                    "alt_baro": "ground" if gnd else alt, "baro_rate": rate,
                    "squawk": "1200", "t": typ, "desc": desc, "category": cat,
                    "type": "adsb_icao", "messages": 0,
                    "rssi": -8.0 - (int(hx, 16) % 23),   # stable per aircraft
                    "nav_altitude_mcp": mcp if mcp is not None else (None if gnd else alt),
                    "_turn": turn, "_loop": loop_nm, "_flown": 0.0}
        self.aircraft = [
            ac("a9b2c4", "UAL1234", 18, -24, 92, 452, 36000, typ="B738", desc="BOEING 737-800"),
            ac("a41b22", "SWA2311", 24, 6, 228, 285, 13400, rate=2200, typ="B737", mcp=36000),
            ac("abf031", "FFT508", 30, 22, 213, 310, 21100, rate=-1400, typ="A20N", mcp=11000),
            ac("a1c5d8", "SKW4123", -12, -14, 178, 395, 23000, typ="E75L"),
            ac("a50e72", "N425CP", 6, -9, 124, 104, 7500, typ="C172", cat="A1"),
            ac("ae01ce", "RCH471", 14, 15, 131, 410, 24000, typ="C17",
               desc="C-17A Globemaster III", cat="A5"),
            ac("a7e9a3", "EJM452", -20, 10, 24, 338, 15500, rate=1000, typ="C68A", cat="A2",
               mcp=41000),
            ac("add441", "N990SP", 9, -2, 90, 95, 8300, turn=3.0, typ="EC30", cat="A7"),
            ac("a8daa8", "N67PD", 0.35, -0.3, 350, 14, 0, gnd=True, typ="C208", cat="A1"),
            # DEN 16R final, ~6 nm out on the glideslope; DEN 25 climb-out past the west end
            ac("a12b3c", "UAL2187", 25.54, 7.21, 181, 150, 7400, rate=-800, typ="A320",
               mcp=5500, loop_nm=6.0),          # flies the final, then starts it again
            ac("a4f5e6", "FFT1971", 16.27, 2.64, 270, 190, 7600, rate=2500, typ="A21N",
               mcp=17000, loop_nm=9.0),
        ]
        self._init = {a["hex"]: dict(a) for a in self.aircraft if a.get("_loop")}

    def _step(self, dt):
        c_lat, c_lon = self.CTR
        for a in self.aircraft:
            a["messages"] += int(dt * (2 if a["alt_baro"] == "ground" else 6))
            trk = (a["track"] + a["_turn"] * dt) % 360
            a["track"] = round(trk, 1)
            nm = a["gs"] * dt / 3600.0
            a["_flown"] += nm
            if a.get("_loop") and a["_flown"] >= a["_loop"]:
                msgs = a["messages"]
                a.update(dict(self._init[a["hex"]]))     # back to the start of its leg
                a["messages"], a["_flown"] = msgs, 0.0
                self.trails.pop(a["hex"], None)
                continue
            rad = math.radians(trk)
            a["lat"] += nm * math.cos(rad) / 60.0
            a["lon"] += nm * math.sin(rad) / (60.0 * math.cos(math.radians(a["lat"])))
            if a["baro_rate"] and a["alt_baro"] != "ground":
                a["alt_baro"] = int(a["alt_baro"] + a["baro_rate"] * dt / 60.0)
                # level off at the autopilot's selected altitude, like the real thing
                tgt = a.get("nav_altitude_mcp") or (7500 if a["baro_rate"] < 0 else 38000)
                if (a["baro_rate"] < 0 and a["alt_baro"] <= tgt) or \
                   (a["baro_rate"] > 0 and a["alt_baro"] >= tgt):
                    a["alt_baro"] = int(tgt)
                    a["baro_rate"] = 0
            if dist_nm(a["lat"], a["lon"], c_lat, c_lon) > 70:   # fly back inbound
                back = math.degrees(math.atan2(c_lon - a["lon"], c_lat - a["lat"])) % 360
                a["track"] = round((back + (int(a["hex"], 16) % 40) - 20) % 360, 1)
            if a["alt_baro"] != "ground":
                t = self.trails.setdefault(a["hex"], [])
                p = (round(a["lat"], 5), round(a["lon"], 5))
                if not t or t[-1] != p:
                    t.append(p)
                    del t[:-30]

    def snapshot(self):
        now = time.time()
        if self._last is None:
            self._last = now - 1.0
        dt = min(now - self._last, 5.0)
        self._last = now
        if dt > 0:
            self._step(dt)
        self.updated = now
        acs = []
        for a in self.aircraft:
            c = dict(a, seen=0, seen_pos=0)
            for k in [k for k in c if k.startswith("_")]:
                del c[k]
            acs.append(c)
        return acs, {h: list(t) for h, t in self.trails.items()}, "live", self.receiver


ROUTES_PATH = os.path.join(CACHE_DIR, "routes.json")


class RouteFeed:
    """Callsign -> origin/destination from adsbdb (free, no key). ADS-B never carries the
    route, so this is a lookup - polite by design: only the selected aircraft, one request
    at a time ~1.5 s apart, cached on disk (hits 3 days, misses 12 h)."""
    URL = "https://api.adsbdb.com/v0/callsign/%s"

    def __init__(self, path=ROUTES_PATH):
        self.path = path
        self.cache = SI.RouteCache(load_json(path, None))
        self.q = queue.Queue()
        self.pending, self.err_until = set(), {}
        self.lock = threading.Lock()
        self.saved = 0.0
        self.last_error = ""
        threading.Thread(target=self._run, daemon=True).start()
        try:
            import theme
            theme.on_workspace_close(lambda: self.q.put(None))
        except Exception:
            pass

    def get(self, cs):
        """(route or None, state) - state: hit | miss | pending | error | unknown."""
        cs = str(cs).strip().upper()
        with self.lock:
            rt, state = self.cache.get(cs)
            if state != "unknown":
                return rt, state
            if cs in self.pending:
                return None, "pending"
            if time.time() < self.err_until.get(cs, 0):
                return None, "error"
        return None, "unknown"

    def want(self, cs):
        cs = str(cs).strip().upper()
        if not SI.route_eligible(cs):
            return
        with self.lock:
            if self.cache.get(cs)[1] != "unknown" or cs in self.pending or \
                    time.time() < self.err_until.get(cs, 0):
                return
            self.pending.add(cs)
        self.q.put(cs)

    def _fetch(self, cs):
        test = os.environ.get("UCS_ROUTES_FILE")       # offline tests
        if test:
            with open(test) as f:
                data = json.load(f).get(cs, {"response": "unknown callsign"})
        else:
            req = urllib.request.Request(self.URL % urllib.parse.quote(cs),
                                         headers={"User-Agent": "uconsole-suite/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 404:                       # adsbdb: unknown callsign
                    return None
                raise
        return SI.parse_adsbdb(data)

    def _run(self):
        while True:
            cs = self.q.get()
            if cs is None:               # workspace closed
                return
            try:
                rt = self._fetch(cs)
                with self.lock:
                    self.cache.put(cs, rt)
                    self.pending.discard(cs)
                self.last_error = ""
            except Exception as e:   # offline, DNS, timeout: retry this one in 2 min
                with self.lock:
                    self.pending.discard(cs)
                    self.err_until[cs] = time.time() + 120
                self.last_error = str(e)[:60]
            if self.cache.dirty and time.time() - self.saved > 20:
                self.save()
            time.sleep(1.5)

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with self.lock:
                data = dict(self.cache.to_json())
            save_json(self.path, data)
            self.cache.dirty = False
            self.saved = time.time()
        except OSError:
            pass


def _ap(icao, iata, city, lat, lon):
    return {"icao": icao, "iata": iata, "name": city, "city": city, "lat": lat, "lon": lon}


# demo traffic never goes to the network: fixed routes that fit each demo plane's path
DEMO_ROUTES = {
    "UAL1234": {"orig": _ap("KSFO", "SFO", "San Francisco", 37.619, -122.375), "mid": None,
                "dest": _ap("KORD", "ORD", "Chicago", 41.978, -87.904), "airline": "United"},
    "SWA2311": {"orig": _ap("KDEN", "DEN", "Denver", 39.856, -104.674), "mid": None,
                "dest": _ap("KPHX", "PHX", "Phoenix", 33.434, -112.012), "airline": "Southwest"},
    "FFT508": {"orig": _ap("KMSP", "MSP", "Minneapolis", 44.882, -93.222), "mid": None,
               "dest": _ap("KDEN", "DEN", "Denver", 39.856, -104.674), "airline": "Frontier"},
    "SKW4123": {"orig": _ap("KDEN", "DEN", "Denver", 39.856, -104.674), "mid": None,
                "dest": _ap("KABQ", "ABQ", "Albuquerque", 35.040, -106.609), "airline": "SkyWest"},
    "UAL2187": {"orig": _ap("KORD", "ORD", "Chicago", 41.978, -87.904), "mid": None,
                "dest": _ap("KDEN", "DEN", "Denver", 39.856, -104.674), "airline": "United"},
    "FFT1971": {"orig": _ap("KDEN", "DEN", "Denver", 39.856, -104.674), "mid": None,
                "dest": _ap("KLAX", "LAX", "Los Angeles", 33.942, -118.408), "airline": "Frontier"},
}


class MetarFeed:
    """Fetches METARs for the map's airports every 10 minutes (aviationweather.gov, no key)."""

    URL = "https://aviationweather.gov/api/data/metar?ids=%s&format=json"
    CAT_COLOR = {"VFR": "#5fb77a", "MVFR": "#5a9be0", "IFR": "#e24b4a", "LIFR": "#c66bd4"}  # filtered via T.night in the GUI

    def __init__(self, idents):
        self.idents = list(idents)
        self.data = {}
        self.updated = 0.0
        self.error = ""
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    stopped = False

    def _loop(self):
        while not self.stopped:
            try:
                self._fetch()
                wait = 600
            except Exception as e:
                with self.lock:
                    self.error = str(e)[:80]
                wait = 120
            for _ in range(wait):         # sleep in 1 s steps so a closed workspace ends us
                if self.stopped:
                    return
                time.sleep(1)

    def _fetch(self):
        test = os.environ.get("UCS_METAR_FILE")
        if test:
            with open(test) as f:
                obs = json.load(f)
        else:
            req = urllib.request.Request(self.URL % ",".join(self.idents),
                                         headers={"User-Agent": "uconsole-suite/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                obs = json.loads(r.read().decode())
        out = {}
        for o in obs if isinstance(obs, list) else []:
            ident = o.get("icaoId")
            if not ident:
                continue
            wd, ws, wg = o.get("wdir"), o.get("wspd"), o.get("wgst")
            if isinstance(wd, str):            # "VRB"
                wind = "%s/%02d" % (wd, ws or 0)
            elif wd is None or ws is None:
                wind = ""
            else:
                wind = "%03d/%02d" % (wd, ws) + ("G%02d" % wg if wg else "")
            alt = o.get("altim")
            out[ident] = {
                "cat": o.get("fltCat") or "",
                "wind": wind,
                "altim": ("A%.2f" % (alt * 0.02953)) if isinstance(alt, (int, float)) else "",
                "temp": o.get("temp"), "dewp": o.get("dewp"), "visib": o.get("visib"),
                "raw": o.get("rawOb") or "",
                "time": o.get("obsTime") or 0,
            }
        with self.lock:
            self.data, self.updated, self.error = out, time.time(), ""

    def get(self, ident):
        with self.lock:
            return self.data.get(ident)


# ---------------------------------------------------------------------- controller

class Controller:
    def __init__(self, settings):
        self.s = settings
        self.events = queue.Queue()
        self.cmds = queue.Queue()
        self.proc = None
        self.state = "idle"
        self.device = None  # "hackrf" | "rtlsdr" while running
        self.binary = shutil.which("rtl_airband")
        self.record = False
        self.record_unsupported = False
        self.my_pids = set()
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import suite as _suite
            self.lease = _suite.RtlLease("Sky airband", log=self.log)
            self.lease.on_preempt = lambda: self.submit("stop")   # another workspace wants the radio
        except Exception:
            self.lease = None
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def paused_services(self):
        return self.lease.paused if self.lease else []

    def emit(self, kind, *args):
        self.events.put((kind,) + args)

    def log(self, msg):
        file_log(msg)
        self.emit("log", msg)

    def set_state(self, st, detail=""):
        self.state = st
        self.emit("state", st, detail)

    def submit(self, cmd):
        self.cmds.put(cmd)

    def _loop(self):
        while True:
            cmd = self.cmds.get()
            try:
                if cmd == "start":
                    self._start()
                elif cmd == "stop":
                    self._stop(restore=True)
                elif cmd == "restart":
                    if self.proc:
                        self._stop(restore=False)
                        self._start()
                elif cmd == "quit":
                    try:
                        self._stop(restore=True)
                    finally:
                        self.emit("quit_ok")
                    return
            except Exception as e:
                self.log("Internal error: %r" % e)
                self.set_state("error", str(e))

    # -- which radio does airband use?
    def choose_device(self):
        """Returns (device, reason)."""
        want = self.s.get("airband_device", "rtlsdr")
        hs = hackrf_status()
        soapy = airband_has_soapy(self.binary)
        adsb = adsb_device()
        if adsb == "hackrf":
            if want == "hackrf":
                raise RuntimeError("The H4M is assigned to ADS-B (readsb). Airband uses the "
                                   "built-in SDR; set airband_device to rtlsdr.")
            return "rtlsdr", "Built-in SDR for airband, H4M for ADS-B - map stays live"
        if want == "rtlsdr":
            return "rtlsdr", "Built-in SDR (set in settings) - map pauses while listening"
        if hs == "ready" and soapy:
            return "hackrf", "H4M (HackRF mode)"
        if want == "hackrf":
            if hs == "wrong_mode":
                raise RuntimeError("H4M is plugged in but not in HackRF mode. On the H4M: "
                                   "main menu -> HackRF, then try again.")
            if hs == "absent":
                raise RuntimeError("H4M not detected. Plug it into the uConsole USB port "
                                   "and select HackRF mode on it.")
            raise RuntimeError("Your rtl_airband was built without SoapySDR, so it can't "
                               "use the H4M. Run: sky --status")
        if hs == "wrong_mode":
            return "rtlsdr", "H4M found but not in HackRF mode - using built-in SDR, map pauses"
        if hs == "ready" and not soapy:
            return "rtlsdr", "rtl_airband lacks SoapySDR - using built-in SDR, map pauses"
        return "rtlsdr", "No H4M - using built-in SDR, map pauses while listening"

    def _free(self, device):
        stale = [p for p in pids_named("rtl_airband") if not (self.proc and p == self.proc.pid)]
        if stale:
            self.log("Killing %d leftover rtl_airband process(es): %s" % (len(stale), stale))
            left = kill_pids(stale)
            if left:
                raise RuntimeError("rtl_airband pid %s won't die (root-owned?). Run: "
                                   "sudo pkill -9 rtl_airband" % left)
        if device == "rtlsdr":
            if self.lease:
                self.lease.acquire(keep=("rtl_airband",))   # pauses readsb, closes rtl_* users
            names = self.s["kill_programs_rtl"]
        else:
            names = self.s["kill_programs_hackrf"]
        victims = []
        for n in names:
            if n in ("readsb", "dump1090-fa"):
                continue  # services: handled by the lease
            victims += pids_named(n)
        for pat in self.s["kill_patterns"]:
            victims += pids_matching(pat)
        victims = sorted(set(victims) - {os.getpid()})
        if victims:
            self.log("Closing programs holding the radio: %s" % victims)
            left = kill_pids(victims, grace=2.0)
            if left:
                self.log("Warning: couldn't close pid(s) %s" % left)
        time.sleep(0.8)

    def _start(self):
        if self.proc:
            return
        if not self.binary:
            self.set_state("error", "rtl_airband is not installed")
            return
        self.set_state("starting", "Picking a radio...")
        self.record_retry_pending = False   # a flag left by an earlier failed start must not leak
        try:
            device, reason = self.choose_device()
            self.log("Airband radio: " + reason)
            self.emit("device", device, reason)
            self.record = bool(self.s.get("transcribe")) and os.path.exists(TRANSCRIBER) \
                and not self.record_unsupported
            write_rtl_conf(self.s, device, record=self.record)
            self.set_state("starting", "Freeing the radio...")
            self._free(device)
        except Exception as e:
            self.log(str(e))
            self.set_state("error", str(e))
            # no scanner is going to run: drop the lease so readsb (plane map) comes back
            # and we don't sit as a stale owner blocking other apps
            if self.lease:
                try:
                    self.lease.release()
                except Exception:
                    pass
            return

        try:
            self._start_attempts(device, reason)
        except Exception as e:
            # Popen/_free/acquire failed mid-retry: don't leave readsb paused under our name
            self.proc = None
            self.log(str(e))
            self.set_state("error", str(e)[:140])
            if self.lease:
                try:
                    self.lease.release()
                except Exception:
                    pass

    def _start_attempts(self, device, reason):
        for attempt in range(1, 4):
            try:
                os.remove(STATS_PATH)
            except OSError:
                pass
            self.set_state("starting", "Starting scanner (try %d)..." % attempt)
            cmd = [self.binary, "-F", "-e", "-c", CONF_PATH]
            self.log("$ " + " ".join(cmd))
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, text=True, bufsize=1,
                                         start_new_session=True)
            lines = []
            threading.Thread(target=self._reader, args=(self.proc, lines), daemon=True).start()
            end = time.time() + (6 if device == "hackrf" else 4)
            while time.time() < end and self.proc.poll() is None:
                time.sleep(0.1)
            if self.proc.poll() is None:
                self.device = device
                self.my_pids.add(self.proc.pid)
                if getattr(self, "record_retry_pending", False):
                    # it only started once recording was removed: this build can't record
                    self.record_unsupported = True
                    self.record_retry_pending = False
                    self.log("Per-transmission recording unsupported by this rtl_airband - transcripts off.")
                self.set_state("running", reason)
                threading.Thread(target=self._watch, args=(self.proc,), daemon=True).start()
                return
            rc = self.proc.returncode
            self.proc = None
            text = "\n".join(lines)
            if self.record and not BUSY_RE.search(text) and re.search(
                    r"split_on_transmission|unknown output type|invalid.*(file|output)|"
                    r"filename_template|directory", text, re.I):
                self.log("This rtl_airband rejected the recording output - retrying without it.")
                self.record = False
                self.record_retry_pending = True
                write_rtl_conf(self.s, device, record=False)
                continue
            if BUSY_RE.search(text) and attempt < 3:
                self.log("Radio still busy, retrying...")
                self._free(device)
                time.sleep(1.5)
                continue
            first = next((l for l in lines if l.strip()), "exit code %s" % rc)
            self._restore_services()
            self.set_state("error", first[:140])
            return
        # every attempt used up (e.g. the record-fallback retry was the last one)
        self._restore_services()
        self.set_state("error", "rtl_airband would not start - see log")

    def _reader(self, proc, sink):
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                sink.append(line)
                self.log(line)

    def _watch(self, proc):
        proc.wait()
        if self.proc is proc and self.state == "running":
            self.proc = None
            taken_by = None
            if self.device == "rtlsdr" and self.lease:
                try:
                    import suite as _suite
                    st = _suite._lease_state()
                    owner = st.get("owner")
                    if owner and (owner != self.lease.who or st.get("pid") != os.getpid()):
                        taken_by = owner
                except Exception:
                    pass
            if taken_by:
                self.log("%s took the built-in SDR; airband stopped." % taken_by)
                self.device = None
                self.set_state("idle", "")
                self.emit("taken", taken_by)
                return
            self.log("Scanner exited unexpectedly (code %s)." % proc.returncode)
            # restore first: the "error" state re-enables Listen, and a new start must not
            # race this release (it would restart readsb under the new scanner)
            self._restore_services()
            if self.device == "hackrf" and hackrf_status() != "ready":
                self.set_state("error", "H4M disconnected or left HackRF mode")
            else:
                self.set_state("error", "Scanner stopped on its own - see log")

    def _stop(self, restore):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            self.set_state("stopping", "Stopping scanner...")
            for sig, wait in ((signal.SIGINT, 3.0), (signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    proc.wait(timeout=wait)
                    break
                except subprocess.TimeoutExpired:
                    self.log("Scanner ignored %s, escalating." % signal.Signals(sig).name)
        # only our own leftovers (earlier Sky runs), not another app's scanner
        stale = [p for p in pids_named("rtl_airband") if p in self.my_pids]
        if stale:
            kill_pids(stale, grace=1.5)
        if restore:
            self._restore_services()
        self.device = None
        self.set_state("idle", "")

    def _restore_services(self):
        if not self.s.get("restore_plane_map", True) or not self.lease:
            return
        try:
            self.lease.release()
        except Exception as e:
            self.log("Couldn't restore the plane map: %s" % e)


# ----------------------------------------------------------------------------- UI

def _fire(cmd):
    try:
        import suite as _suite
        return _suite.fire_and_forget(cmd)
    except Exception:
        return subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_gui():
    import tkinter as tk
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import theme as T
    import tiles
    BG, MAPBG = T.BG, T.MAPBG
    TXT, MUTED, DIM, LINE = T.TXT, T.MUTED, T.DIM, T.LINE
    GREEN, RED, AMBER = T.GREEN, T.RED, T.AMBER

    s = load_settings()
    ctl = Controller(s)
    feed = AdsbFeed(s["adsb_sources"])
    demo = DemoFeed()
    demo_on = ["--demo" in sys.argv]
    routes = RouteFeed()
    metar = MetarFeed(AIRPORTS.keys())

    root, F = T.make_root("Sky")
    T.on_workspace_close(lambda: routes.q.put(None))    # (built before the workspace existed)

    # ---- top bar
    top = T.top_bar(root, F, "Sky", "Front Range")
    adsb_pill = T.Tag(top, F, "ADS-B")
    air_pill = T.Tag(top, F, "Airband")
    out_lbl = tk.Label(top, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE)
    out_lbl.pack(side="right", padx=8)

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True)

    # ---- left dock (collapsible, so the map can take the whole screen)
    dock_outer = tk.Frame(body, bg=T.SURFACE, width=T.px(272))
    dock_outer.pack(side="left", fill="y")
    dock_outer.pack_propagate(False)
    dock_divider = tk.Frame(body, bg=LINE, width=1)
    dock_divider.pack(side="left", fill="y")
    inner = tk.Frame(dock_outer, bg=T.SURFACE)
    inner.pack(fill="both", expand=True, padx=14, pady=14)
    left = inner
    dock = {"shown": True}

    sec_air = T.section(left, F, "COMMS", right="")
    sec_air.pack(fill="x")
    ctl_row = tk.Frame(left, bg=T.SURFACE)
    ctl_row.pack(fill="x", pady=(T.px(6), 0))
    btn = T.btn(ctl_row, "Listen", lambda: on_button(), F, font="smb", padx=18, pady=6,
                kind="primary")
    btn.pack(side="left")
    detail = tk.Label(left, text="", font=F["sm"], fg=MUTED, bg=T.SURFACE, wraplength=T.px(300),
                      justify="left", anchor="w")
    detail.pack(fill="x", pady=(8, 0))

    nowbox = tk.Frame(left, bg=T.SURFACE)
    nowbox.pack(fill="x", pady=(T.px(8), 0))
    now_lbl = tk.Label(nowbox, text="Idle", font=F["now"], fg=T.TXT_3, bg=T.SURFACE, anchor="w")
    now_lbl.pack(fill="x")
    now_sub = tk.Label(nowbox, text="", font=F["mono"], fg=MUTED, bg=T.SURFACE, anchor="w")
    now_sub.pack(fill="x")
    meter = tk.Canvas(nowbox, bg=T.SURFACE, highlightthickness=0, height=T.px(22))
    meter.pack(fill="x", pady=(8, 0))
    level = {"db": None}

    def draw_meter():
        meter.delete("all")
        w = meter.winfo_width()
        if w < 20:
            return
        db = level["db"]
        frac = 0 if db is None else (db + 60) / 60
        lw = F["map"].measure("-60.0 dBFS") + T.px(8)
        T.level_bar(meter, 0, T.px(3), w - lw, T.px(8), frac, segments=24,
                    color=AMBER if live_channel[0] else T.TXT_3)
        meter.create_text(w, T.px(7), anchor="e", fill=T.TXT_3, font=F["map"],
                          text="%5.1f dBFS" % db if db is not None else "  -- dBFS")
    meter.config(height=T.px(16))

    tools = tk.Frame(left, bg=T.SURFACE)
    tools.pack(side="bottom", fill="x")
    gain_row = tk.Frame(left, bg=T.SURFACE)
    gain_row.pack(side="bottom", fill="x", pady=(0, 12))
    tk.Frame(left, bg=LINE, height=1).pack(fill="x", pady=(T.px(10), T.px(8)))

    # ---- tabbed lower dock: Channels and Alerts share the space so neither squeezes the other
    dock_tab = ["channels"]
    tabrow = tk.Frame(left, bg=T.SURFACE)
    tabrow.pack(fill="x", pady=(0, T.px(6)))
    panel = tk.Frame(left, bg=T.SURFACE)
    panel.pack(fill="both", expand=True)
    panel_chan = tk.Frame(panel, bg=T.SURFACE)
    panel_alerts = tk.Frame(panel, bg=T.SURFACE)
    panel_contact = tk.Frame(panel, bg=T.SURFACE)
    tab_btns = {}

    def show_panel(name):
        dock_tab[0] = name
        for pnl in (panel_chan, panel_alerts, panel_contact):
            pnl.pack_forget()
        {"channels": panel_chan, "alerts": panel_alerts,
         "contact": panel_contact}[name].pack(fill="both", expand=True)
        if name == "contact":
            root.after(10, redraw_map)        # fill it now, not on the next feed tick
        for k, b in tab_btns.items():
            if not (k == "alerts" and b._kind == "danger"):
                T.set_btn(b, kind="primary" if k == name else "ghost")

    for key, label in (("channels", "Channels"), ("alerts", "Alerts"), ("contact", "Contact")):
        b = T.btn(tabrow, label, lambda k=key: show_panel(k), F, padx=10, pady=3,
                  kind="primary" if key == "channels" else "ghost")
        b.pack(side="left", padx=(0, 6))
        tab_btns[key] = b

    # Contact tab: the selected plane, compact, without leaving DUAL
    c_cs = tk.Label(panel_contact, text="—", font=F["now"], fg=TXT, bg=T.SURFACE, anchor="w")
    c_cs.pack(fill="x")
    c_type = tk.Label(panel_contact, text="", font=F["sm"], fg=T.TXT_2, bg=T.SURFACE, anchor="w",
                      justify="left", wraplength=T.px(330))
    c_type.pack(fill="x")
    c_route = tk.Label(panel_contact, text="", font=F["smb"], fg=TXT, bg=T.SURFACE, anchor="w",
                       justify="left", wraplength=T.px(330))
    c_route.pack(fill="x", pady=(T.px(4), 0))
    c_status = tk.Label(panel_contact, text="", font=F["sm"], fg=T.TXT_2, bg=T.SURFACE,
                        anchor="w", justify="left", wraplength=T.px(330))
    c_status.pack(fill="x", pady=(T.px(2), T.px(4)))
    c_grid = tk.Frame(panel_contact, bg=T.SURFACE)
    c_grid.pack(fill="x")
    c_rows = {}
    for ri, (k1, k2) in enumerate((("ALT", "V/S"), ("GS", "TRK"), ("RANGE", "BRG"))):
        for ci, k in enumerate((k1, k2)):
            cell = tk.Frame(c_grid, bg=T.SURFACE)
            cell.grid(row=ri, column=ci, sticky="w", pady=1)
            c_grid.columnconfigure(ci, weight=1)
            tk.Label(cell, text=k, font=F["map"], fg=T.TXT_3, bg=T.SURFACE, width=7,
                     anchor="w").pack(side="left")
            c_rows[k] = tk.Label(cell, text="—", font=F["mono"], fg=TXT, bg=T.SURFACE,
                                 anchor="w")
            c_rows[k].pack(side="left")
    c_hint = tk.Label(panel_contact, text="Tap a plane on the map, or a transcript line\n"
                      "that names one.", font=F["map"], fg=T.TXT_3, bg=T.SURFACE,
                      justify="left", anchor="w")
    c_hint.pack(fill="x", pady=(T.px(6), 0))

    # emergency squawks: 7500 hijack, 7600 radio failure, 7700 general emergency
    EMERG = {"7500": "hijack", "7600": "radio failure", "7700": "emergency"}
    alerts = {}      # hex -> {"sq", "cs", "t0", "last", "kind"}
    acked = set()    # cleared by the user; not re-announced while the squawk persists
    slog = __import__("suite").SessionLog("sky")
    alert_box = tk.Frame(panel_alerts, bg=T.SURFACE)
    alert_box.pack(fill="both", expand=True)
    alert_rows = tk.Frame(alert_box, bg=T.SURFACE)
    alert_hdr = T.section(alert_box, F, "Alerts", fg=RED)
    alert_hdr.pack(fill="x", pady=(0, 2))
    alert_rows.pack(fill="x")

    def clear_alerts():
        acked.update(alerts)
        alerts.clear()
        del kw_log[:]
        rebuild_alerts()
        redraw_map()

    T.btn(alert_hdr, "Clear", clear_alerts, F, padx=6, pady=1, kind="quiet").pack(side="right")

    def rebuild_alerts():
        for w in alert_rows.winfo_children():
            w.destroy()
        fresh_kw = [r for r in kw_log if time.time() - r["t"] < 600]
        n = len(alerts) + len(fresh_kw)
        has_emerg = any(a["kind"] in ("hijack", "radio failure", "emergency") for a in alerts.values())
        akind = "danger" if has_emerg else ("primary" if dock_tab[0] == "alerts" else "ghost")
        T.set_btn(tab_btns["alerts"], "Alerts" + (" %d" % n if n else ""), akind)
        if not alerts and not fresh_kw:
            tk.Label(alert_rows, text="No alerts.\nWatch list, emergencies, nearby low traffic and\n"
                     "unusual contacts (military, circling) show here.", font=F["map"], fg=T.TXT_3,
                     bg=T.SURFACE, justify="left", anchor="w").pack(fill="x", pady=4)
            return
        for r in fresh_kw[:2]:
            row = tk.Frame(alert_rows, bg=T._mix(RED, T.SURFACE, 0.86), padx=8, pady=2)
            row.pack(fill="x", pady=(0, 2))
            tk.Frame(row, bg=RED, width=3).pack(side="left", fill="y", padx=(0, 8))
            tk.Label(row, text=r["kw"].upper(), font=F["monob"] if "monob" in F else F["mono"], fg=RED,
                     bg=row["bg"]).pack(side="left")
            tk.Label(row, text="  %s  %s" % (r.get("label", ""), time.strftime("%H:%M", time.localtime(r["t"]))),
                     font=F["sm"], fg=TXT, bg=row["bg"]).pack(side="left")
            tk.Label(row, text="heard", font=F["map"], fg=MUTED, bg=row["bg"]).pack(side="right")
            row.bind("<Button-1>", lambda e: (toggle_text() if not tx_visible[0] else None))
        EMERGENCY = ("hijack", "radio failure", "emergency")
        SOFT = {"watch": "watch list", "fence": "close & low", "military": "military",
                "orbit": "circling", "newtype": "new type"}
        ordered = sorted(alerts.items(), key=lambda kv: (kv[1]["kind"] not in EMERGENCY, kv[1]["t0"]))
        if len(ordered) > 4:
            tk.Label(alert_rows, text="+%d more" % (len(ordered) - 4), font=F["map"], fg=MUTED,
                     bg=T.SURFACE, anchor="e").pack(side="bottom", fill="x")
            ordered = ordered[:4]
        for h, a in ordered:
            ac = RED if a["kind"] in EMERGENCY else AMBER
            row = tk.Frame(alert_rows, bg=T._mix(ac, T.SURFACE, 0.86), padx=8, pady=2)
            row.pack(fill="x", pady=(0, 2))
            tk.Frame(row, bg=ac, width=3).pack(side="left", fill="y", padx=(0, 8))
            tk.Label(row, text=a["sq"], font=F["monob"] if "monob" in F else F["mono"], fg=ac,
                     bg=row["bg"]).pack(side="left")
            tk.Label(row, text="  %s  %s" % (a["cs"], a.get("alt", "")), font=F["sm"], fg=TXT,
                     bg=row["bg"]).pack(side="left")
            tk.Label(row, text=SOFT.get(a["kind"], a["kind"]),
                     font=F["map"], fg=MUTED, bg=row["bg"]).pack(side="right")
            row.bind("<Button-1>", lambda e, h=h: select_hex(h))
            for w in row.winfo_children():
                w.bind("<Button-1>", lambda e, h=h: select_hex(h))

    def select_hex(h):
        acs, _, _, _ = feed.snapshot()
        a = next((a for a in acs if a["hex"] == h), None)
        if a and "lat" in a:
            view["lat"], view["lon"] = a["lat"], a["lon"]
        view["sel"] = h
        redraw_map()

    # view mode: "both" (map + voice), "visual" (silent map), "voice" (eyes-free audio)
    sky_mode = [s.get("sky_mode") if s.get("sky_mode") in ("both", "visual", "voice") else "both"]

    def speak(text):
        if sky_mode[0] == "visual":
            return                      # Map mode is silent - no TTS, callouts, point, bingo
        if shutil.which("espeak-ng"):
            _fire(["espeak-ng", "-s", "150", text])

    # ---- anomaly detection: "what's unusual right now" from the feed alone
    MIL_PREFIXES = MIL_PREFIXES_DEFAULT
    anom_track = {}   # hex -> {"pts": [(t, track, lat, lon)], "turn": float}
    type_seen = {}    # type -> last date seen (persisted alongside records)

    def _load_type_seen():
        try:
            d = load_json(os.path.join(HOME, ".local", "share", "uconsole-suite", "sky_types.json"), {})
            if isinstance(d, dict):
                type_seen.update(d)
        except Exception:
            pass
    _load_type_seen()

    def is_military(a):
        try:
            n = int(a["hex"], 16)
        except (KeyError, ValueError):
            n = 0
        if 0xADF7C8 <= n <= 0xAFFFFF:        # US military ICAO allocation
            return True
        cs = (a.get("flight") or "").strip().upper()
        mp = s.get("mil_prefixes", MIL_PREFIXES)
        if not isinstance(mp, (list, tuple)):
            mp = MIL_PREFIXES
        return any(cs.startswith(str(p)) for p in mp) and cs[:3].isalpha()

    def update_orbit(a):
        """Track cumulative heading change to spot loitering/circling. Returns True if orbiting."""
        h, trk = a["hex"], a.get("track")
        if trk is None or "lat" not in a or on_ground(a):
            return False
        st = anom_track.setdefault(h, {"pts": [], "turn": 0.0})
        pts = st["pts"]
        now = time.time()
        if pts:
            dt = now - pts[-1][0]
            if dt < 2:
                return st.get("orbiting", False)
            d = (trk - pts[-1][1] + 540) % 360 - 180   # signed shortest turn
            st["turn"] += d
        pts.append((now, trk, a["lat"], a["lon"]))
        cutoff = now - 300
        while pts and pts[0][0] < cutoff:
            old = pts.pop(0)
            if len(pts) >= 1:
                d = (pts[0][1] - old[1] + 540) % 360 - 180
                st["turn"] -= d
        # orbiting: >400° of cumulative turn while staying inside a ~6 nm box over 2+ minutes
        if len(pts) >= 4 and (pts[-1][0] - pts[0][0]) > 120:
            lats = [p[2] for p in pts]
            lons = [p[3] for p in pts]
            span = dist_nm(min(lats), min(lons), max(lats), max(lons))
            st["orbiting"] = abs(st["turn"]) > 400 and span < 8
        return st.get("orbiting", False)

    def check_anomaly(a, cs, alt_s):
        if not s.get("anomaly_alerts", True):
            return None, None, None
        if is_military(a):
            return "military", "MIL", "Military contact. %s%s." % (cs, (", " + alt_s) if alt_s else "")
        if update_orbit(a):
            return "orbit", "ORBIT", "%s is circling%s." % (cs, (" at " + alt_s) if alt_s else "")
        typ = (a.get("t") or "").strip()
        today = time.strftime("%Y-%m-%d")
        if typ and type_seen.get(typ) != today:
            first = typ not in type_seen
            type_seen[typ] = today
            try:
                save_json(os.path.join(HOME, ".local", "share", "uconsole-suite", "sky_types.json"), type_seen)
            except OSError:
                pass
            if first and records["d"].get("days", 0) >= 1:
                return "newtype", "NEW", "New type on the scope: %s, %s." % (typ, cs)
        return None, None, None

    def check_alerts(acs):
        now = time.time()
        changed = False
        watch = {str(x).strip().upper() for x in s.get("watch", []) if str(x).strip()}
        fence = s.get("fence") or {}
        fence_nm = float(fence.get("nm") or 0)
        fence_ft = float(fence.get("below_ft") or 0)
        _, _, _, rcv = feed.snapshot()
        home = rcv or (AIRPORTS["KAPA"]["lat"], AIRPORTS["KAPA"]["lon"])
        seen_now = set()
        for a in acs:
            h = a["hex"]
            cs = (a.get("flight") or "").strip() or h.upper()
            reg = (a.get("r") or "").strip().upper()
            alt = alt_ft(a)
            alt_s = ("%s ft" % format(int(alt), ",")) if alt else ("GND" if on_ground(a) else "")
            sq = str(a.get("squawk") or "")
            em = a.get("emergency")
            kind, tag, say = None, None, None
            if sq in EMERG or (em and em != "none"):
                kind = alert_kind(sq, em)
                tag = sq if sq in EMERG else str(em).upper()
                say = ("Alert. %s squawking %s. %s." % (cs, " ".join(sq), kind)) if sq in EMERG \
                    else "Alert. %s reports %s." % (cs, kind)
            elif watch and ({cs.upper(), h.upper(), reg} & watch):
                kind, tag = "watch", "WATCH"
                say = "Watch list. %s is on the scope%s." % (cs, (", %s" % alt_s) if alt_s else "")
            elif fence_nm and "lat" in a and not on_ground(a) and alt and alt < fence_ft:
                d = dist_nm(home[0], home[1], a["lat"], a["lon"])
                if d <= fence_nm:
                    kind, tag = "fence", "NEAR"
                    say = "Traffic. %s, %d miles, %s." % (cs, round(d), alt_s)
            else:
                kind, tag, say = check_anomaly(a, cs, alt_s)
            if kind is None:
                if h in acked:
                    acked.discard(h)       # condition cleared: a new one announces again
                continue
            seen_now.add(h)
            if h in acked:
                continue
            if h not in alerts:
                alerts[h] = {"sq": tag, "cs": cs, "t0": now, "kind": kind}
                speak(say)
                slog.event(kind, "%s %s (%s)" % (cs or h, kind, tag), id=h,
                           cs=cs, hex=h, alt=alt_s, squawk=sq or None)
                changed = True
            al = alerts[h]
            al["last"] = now
            if al.get("alt") != alt_s or al["cs"] != cs:
                al["alt"], al["cs"] = alt_s, cs
                changed = True
        live_hexes = {a["hex"] for a in acs}
        for h in list(anom_track):
            if h not in live_hexes:
                del anom_track[h]
        for h in list(alerts):
            limit = 600 if alerts[h]["kind"] in ("hijack", "radio failure", "emergency") else 150
            if h not in seen_now and now - alerts[h].get("last", now) > limit:
                del alerts[h]
                changed = True
        if changed:
            rebuild_alerts()

    chan_hdr = T.section(panel_chan, F, "Channels")
    chan_hdr.pack(fill="x", pady=(0, 6))
    chan_frame = tk.Frame(panel_chan, bg=T.SURFACE)
    chan_frame.pack(fill="both", expand=True)
    show_panel("channels")

    def small_btn(parent, text, cmd, fg=None, bg=None, kind="ghost"):
        return T.btn(parent, text, cmd, F, fg=fg, padx=10, pady=4, kind=kind)

    restart_job = [None]

    def schedule_restart():
        if restart_job[0]:
            root.after_cancel(restart_job[0])
        if ctl.state == "running":
            detail.config(text="Applying change…")
            restart_job[0] = root.after(1200, lambda: ctl.submit("restart"))

    # gain: LNA for the H4M, tuner gain for the built-in SDR
    gain_lbl = tk.Label(gain_row, text="Gain", font=F["sm"], fg=MUTED, bg=T.SURFACE)
    gain_lbl.pack(side="left")
    gain_val = tk.Label(gain_row, text="", font=F["mono"], fg=TXT, bg=T.SURFACE, width=10)
    ui_device = [None]  # device the gain row is showing

    def gain_target():
        if ui_device[0]:
            return ui_device[0]
        if adsb_device() == "hackrf" or s.get("airband_device", "rtlsdr") == "rtlsdr":
            return "rtlsdr"
        return "hackrf" if hackrf_status() == "ready" else "rtlsdr"

    def draw_gain():
        d = gain_target()
        if d == "hackrf":
            gain_lbl.config(text="H4M gain")
            gain_val.config(text="LNA %d dB" % int(s["hackrf"]["lna"]))
        else:
            gain_lbl.config(text="SDR gain")
            gain_val.config(text="%.1f dB" % float(s["rtlsdr"]["gain"]))

    def set_gain(delta):
        if gain_target() == "hackrf":
            i = max(0, min(len(LNA_STEPS) - 1, nearest_index(LNA_STEPS, s["hackrf"]["lna"]) + delta))
            s["hackrf"]["lna"] = LNA_STEPS[i]
        else:
            i = max(0, min(len(GAIN_STEPS_RTL) - 1,
                           nearest_index(GAIN_STEPS_RTL, s["rtlsdr"]["gain"]) + delta))
            s["rtlsdr"]["gain"] = GAIN_STEPS_RTL[i]
        save_json(SETTINGS_PATH, s)
        draw_gain()
        schedule_restart()

    small_btn(gain_row, "+", lambda: set_gain(+1)).pack(side="right")
    gain_val.pack(side="right", padx=4)
    small_btn(gain_row, "−", lambda: set_gain(-1)).pack(side="right")
    draw_gain()

    # channels
    rows = []
    last_heard = {}
    live = set()
    chan_hist = {}  # freq -> list of activity timestamps (last 10 min)

    def activity_bins(k, n=18, span=600):
        now = time.time()
        b = [0] * n
        for t in chan_hist.get(k, []):
            age = now - t
            if 0 <= age < span:
                b[n - 1 - int(age / (span / n))] = 1
        return b

    def key_of(c):
        return "%.3f" % float(c["freq"])

    def ago(t):
        d = int(time.time() - t)
        return "%ds" % d if d < 60 else ("%dm" % (d // 60) if d < 3600 else "%dh" % (d // 3600))

    def draw_row(r):
        c, on = r["c"], r["c"].get("on")
        is_live = on and key_of(c) in live
        bg = T.ACCENT_BG if is_live else T.SURFACE
        for w in (r["f"], r["dot"], r["freq"], r["lab"], r["heard"], r["bar"], r["spark"]):
            w.config(bg=bg)
        sp = r["spark"]
        sp.delete("all")
        bins = activity_bins(key_of(c))
        sw, sh = T.px(54), T.px(16)
        sp.create_line(0, sh - 1, sw, sh - 1, fill=LINE)
        T.sparkline(sp, 0, 1, sw, sh - 2, bins, color=(AMBER if is_live else T.TXT_3) if on else LINE,
                    bars=True, vmax=1)
        r["bar"].config(bg=AMBER if is_live else bg)
        r["dot"].delete("all")
        d0, d1, y0 = T.px(3), T.px(10), T.px(6)
        if is_live:
            r["dot"].create_oval(d0, y0, d1, y0 + d1 - d0, fill=AMBER, outline=AMBER)
        elif on:
            r["dot"].create_oval(d0, y0, d1, y0 + d1 - d0, fill=T.TXT_2, outline=T.TXT_2)
        else:
            r["dot"].create_oval(d0, y0, d1, y0 + d1 - d0, fill="", outline=T.TXT_3)
        r["freq"].config(fg=(AMBER if is_live else T.TXT_2) if on else T.TXT_3)
        r["lab"].config(fg=(AMBER if is_live else TXT) if on else T.TXT_3)
        k = key_of(c)
        r["heard"].config(text="off" if not on else ("rx" if is_live else
                          (ago(last_heard[k]) if k in last_heard else "")),
                          fg=T.TXT_3 if not on else (AMBER if is_live else T.TXT_3))

    def toggle_chan(r):
        if r["c"].get("on") and sum(1 for c in s["channels"] if c.get("on")) == 1:
            detail.config(text="Keep at least one channel on.")
            return
        r["c"]["on"] = not r["c"].get("on")
        save_json(SETTINGS_PATH, s)
        draw_row(r)
        schedule_restart()
        redraw_map()

    def build_rows():
        for w in chan_frame.winfo_children():
            w.destroy()
        rows.clear()
        for c in s["channels"]:
            f = tk.Frame(chan_frame, bg=T.SURFACE, cursor="hand2")
            f.pack(fill="x")
            bar = tk.Frame(f, bg=T.SURFACE, width=2)
            bar.pack(side="left", fill="y")
            dot = tk.Canvas(f, width=T.px(14), height=T.px(20), highlightthickness=0, bg=T.SURFACE)
            dot.pack(side="left", padx=(4, 2), pady=1)
            fr = tk.Label(f, text="%.3f" % float(c["freq"]), font=F["mono"], width=8, anchor="w")
            fr.pack(side="left")
            lab = tk.Label(f, text=c["label"], font=F["sm"], anchor="w")
            lab.pack(side="left", fill="x", expand=True, padx=(4, 0))
            heard = tk.Label(f, text="", font=F["map"], width=5, anchor="e")
            heard.pack(side="right", padx=(0, 6))
            spark = tk.Canvas(f, width=T.px(54), height=T.px(16), bg=T.SURFACE, highlightthickness=0)
            spark.pack(side="right", padx=(0, 6))
            r = {"c": c, "f": f, "dot": dot, "freq": fr, "lab": lab, "heard": heard, "bar": bar,
                 "spark": spark}
            for w in (f, bar, dot, fr, lab, heard):
                w.bind("<Enter>", lambda e, r=r: r["f"].config(cursor="hand2"))
            for w in (f, bar, dot, fr, lab, heard):
                w.bind("<Button-1>", lambda e, r=r: toggle_chan(r))
            rows.append(r)
            draw_row(r)

    build_rows()

    # ---- map
    mapwrap = tk.Frame(body, bg=BG)
    mapwrap.pack(side="left", fill="both", expand=True)
    cv = tk.Canvas(mapwrap, bg=MAPBG, highlightthickness=0)
    cv.pack(fill="both", expand=True)

    def _corner_btn(open_):
        T.set_btn(dock_toggle, "⟨" if open_ else "☰ Panel")
        dock_toggle.place(x=T.px(8), y=T.px(8))
        dock_toggle.lift()

    def set_vdock(show):
        """Show/hide the voice (COMMS) dock. Only one left panel ever exists, so
        showing it also puts the contact card away."""
        if show:
            set_card(False)
        if show and not dock["shown"]:
            anchor = mapwrap if mapwrap.winfo_manager() else voicewrap
            dock_outer.pack(side="left", fill="y", before=anchor)
            dock_divider.pack(side="left", fill="y", before=anchor)
            dock["shown"] = True
        elif not show and dock["shown"]:
            dock_outer.pack_forget()
            dock_divider.pack_forget()
            dock["shown"] = False
        _corner_btn(dock["shown"] or info_shown[0])
        root.after(60, redraw_map)

    def set_card(show):
        """Show/hide the contact card (the Map tab's panel); showing it puts the
        voice dock away."""
        if show and dock["shown"]:
            dock_outer.pack_forget()
            dock_divider.pack_forget()
            dock["shown"] = False
        if show and not info_shown[0]:
            anchor = mapwrap if mapwrap.winfo_manager() else voicewrap
            infodock.pack(side="left", fill="y", before=anchor)
            infodock.pack_propagate(False)
            info_divider.pack(side="left", fill="y", before=anchor)
            info_shown[0] = True
        elif not show and info_shown[0]:
            infodock.pack_forget()
            info_divider.pack_forget()
            info_shown[0] = False
        _corner_btn(dock["shown"] or info_shown[0])

    def toggle_dock(_=None):
        # the corner button toggles whichever panel belongs to the current view
        if sky_mode[0] == "visual":
            set_card(not info_shown[0])
            root.after(60, redraw_map)
        else:
            set_vdock(not dock["shown"])

    # a single always-visible toggle on the map corner (reliable touch target)
    dock_toggle = T.btn(cv, "⟨", toggle_dock, F, font="smb", padx=9, pady=4, kind="quiet")
    dock_toggle.config(fg=TXT, bg=T.SURFACE)
    dock_toggle.place(x=T.px(8), y=T.px(8))
    root.bind("<F2>", toggle_dock)
    tk.Frame(mapwrap, bg=LINE, height=1).pack(fill="x")
    info = tk.Label(mapwrap, text="Select a contact for details", font=F["map"],
                    fg=T.TXT_3, bg=T.SURFACE, anchor="w", padx=14, pady=4)
    info.pack(fill="x")

    # ---- transcripts (Whisper worker writes them; we show the latest and match callsigns)
    # off by default so the map keeps its full height; toggle on from More -> Transcript
    txbox = tk.Text(mapwrap, height=2, bg=T.SURFACE, fg=TXT, font=F["map"], bd=0,
                    highlightthickness=0, wrap="word", padx=14, pady=5, spacing1=1)
    txbox.tag_config("time", foreground=T.TXT_3, font=F["map"])
    txbox.tag_config("chan", foreground=T.TXT_2, font=F["smb"])
    txbox.tag_config("heard", foreground=AMBER, font=F["map"], underline=1)
    txbox.tag_config("kw", foreground=RED)
    kw_log = []   # recent keyword hits, newest first
    tx_visible = [False]
    if tx_visible[0]:
        txbox.pack(fill="x", before=info)
    heard = {}  # hex -> time the callsign was heard
    tx_state = {"path": None, "pos": 0, "lines": []}

    # ---- voice console: the Voice tab's full pane - replaces the map, eyes-free type sizes
    import tkinter.font as _tkfont
    voicewrap = tk.Frame(body, bg=BG)
    voice_shown = [False]
    _vbig = _tkfont.Font(family=F["now"].cget("family"),
                         size=int(F["now"].cget("size") * 1.7), weight="bold")
    vpad = tk.Frame(voicewrap, bg=BG)
    vpad.pack(fill="both", expand=True, padx=T.px(26), pady=T.px(18))
    v_now = tk.Label(vpad, text="Idle", font=_vbig, fg=TXT, bg=BG, anchor="w")
    v_now.pack(fill="x")
    v_sub = tk.Label(vpad, text="press Listen to scan", font=F["now"], fg=T.TXT_3, bg=BG,
                     anchor="w")
    v_sub.pack(fill="x", pady=(0, T.px(8)))
    v_meter = tk.Canvas(vpad, bg=BG, highlightthickness=0, height=T.px(20))
    v_meter.pack(fill="x", pady=(0, T.px(12)))
    T.section(vpad, F, "Transcript").pack(fill="x")
    vtx = tk.Text(vpad, bg=BG, fg=TXT, font=F["now"], bd=0, highlightthickness=0,
                  wrap="word", spacing1=T.px(8), state="disabled")
    vtx.tag_config("time", foreground=T.TXT_3, font=F["sm"])
    vtx.tag_config("chan", foreground=AMBER, font=F["smb"])
    vtx.tag_config("heard", foreground=AMBER, underline=1)
    vtx.tag_config("kw", foreground=RED)
    vtx.pack(fill="both", expand=True, pady=(T.px(4), 0))

    # ---- contact card: the Map tab's side panel - selected plane, silhouette, data
    infodock = tk.Frame(body, bg=T.SURFACE, width=T.px(272))
    info_divider = tk.Frame(body, bg=LINE, width=1)
    info_shown = [False]
    ipad = tk.Frame(infodock, bg=T.SURFACE)
    ipad.pack(fill="both", expand=True, padx=T.px(12), pady=T.px(10))
    T.section(ipad, F, "Contact").pack(fill="x")
    i_csrow = tk.Frame(ipad, bg=T.SURFACE)
    i_csrow.pack(fill="x", pady=(T.px(4), 0))
    i_cs = tk.Label(i_csrow, text="—", font=F["now"], fg=TXT, bg=T.SURFACE, anchor="w")
    i_cs.pack(side="left")
    i_mil = tk.Label(i_csrow, text=" MIL ", font=F["smb"], fg=T.BG, bg=T.NOTE)
    i_type = tk.Label(ipad, text="", font=F["sm"], fg=T.TXT_2, bg=T.SURFACE, anchor="w",
                      wraplength=T.px(246), justify="left")
    i_type.pack(fill="x")
    i_route = tk.Label(ipad, text="", font=F["smb"], fg=TXT, bg=T.SURFACE, anchor="w")
    i_route.pack(fill="x")
    # tail number / country / how we're hearing it - all decoded offline from the hex
    i_origin = tk.Label(ipad, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w")
    i_origin.pack(fill="x")
    i_sil = tk.Canvas(ipad, bg=T.night("#10151a"), highlightthickness=0, height=T.px(96))
    i_sil.pack(fill="x", pady=(T.px(6), T.px(4)))
    # what it's doing and whether it'll pass over you
    i_status = tk.Label(ipad, text="", font=F["smb"], fg=T.TXT_2, bg=T.SURFACE, anchor="w",
                        wraplength=T.px(246), justify="left")
    i_status.pack(fill="x", pady=(0, T.px(4)))
    i_grid = tk.Frame(ipad, bg=T.SURFACE)
    i_grid.pack(fill="x")
    i_rows = {}
    alt_hist = {}   # hex -> [(t, alt_ft)], ~2 s samples, last 10 min, for the profile
    for r, (k1, k2) in enumerate((("ALT", "GS"), ("TRK", "V/S"), ("SQUAWK", "SEEN"),
                                  ("RANGE", "BRG"), ("SIGNAL", "HEX"))):
        for c, k in enumerate((k1, k2)):
            cell = tk.Frame(i_grid, bg=T.SURFACE)
            cell.grid(row=r, column=c, sticky="w", pady=1)
            i_grid.columnconfigure(c, weight=1)
            tk.Label(cell, text=k, font=F["map"], fg=T.TXT_3, bg=T.SURFACE,
                     width=7, anchor="w").pack(side="left")
            v = tk.Label(cell, text="—", font=F["mono"], fg=TXT, bg=T.SURFACE, anchor="w")
            v.pack(side="left")
            i_rows[k] = v
    T.section(ipad, F, "Closest").pack(fill="x", pady=(T.px(8), T.px(2)))
    i_list = tk.Frame(ipad, bg=T.SURFACE)
    i_list.pack(fill="both", expand=True)
    i_hint = tk.Label(ipad, text="tap a contact on the map", font=F["sm"], fg=MUTED,
                      bg=T.SURFACE, anchor="w")
    i_hint.pack(fill="x", pady=(T.px(4), 0))

    def draw_sil(a):
        """Top-down silhouette by class, in the contact's category color. Offline, no
        photo lookup: a drawn shape that always works in the field."""
        i_sil.delete("all")
        w, h = i_sil.winfo_width() or T.px(246), T.px(96)
        sil_w = h * 1.05            # silhouette gets a square on the left ...
        cx, cy, u = sil_w / 2, h / 2, h / 2.6
        col = T.NOTE if is_military(a) else contact_color(a, False)

        def P(*pts):
            i_sil.create_polygon(*[v * u + (cx if i % 2 == 0 else cy)
                                   for i, v in enumerate(pts)],
                                 fill="", outline=col, width=1.4)
        cat = (a.get("category") or "").upper()
        typ = (a.get("t") or "").strip().upper()
        heli = cat == "A7" or typ.startswith(HELI_T)
        light = cat in ("A1", "A2") or (not cat and (a.get("gs") or 0) < 170)
        if heli:
            P(0, -0.9, 0.16, -0.5, 0.16, 0.1, 0.05, 0.9, -0.05, 0.9, -0.16, 0.1, -0.16, -0.5)
            i_sil.create_oval(cx - u, cy - u * 0.75, cx + u, cy + u * 0.75,
                              outline=col, dash=(4, 3))
            i_sil.create_line(cx - u * 0.5, cy - u * 0.4, cx + u * 0.5, cy + u * 0.4, fill=col)
            i_sil.create_line(cx - u * 0.5, cy + u * 0.4, cx + u * 0.5, cy - u * 0.4, fill=col)
        elif is_military(a) and not light:
            P(0, -1.1, 0.12, -0.6, 0.12, 0.6, 0.06, 1.0, -0.06, 1.0, -0.12, 0.6, -0.12, -0.6)
            P(0.1, -0.15, 1.15, 0.5, 1.15, 0.64, 0.1, 0.25)
            P(-0.1, -0.15, -1.15, 0.5, -1.15, 0.64, -0.1, 0.25)
            P(0.05, 0.78, 0.5, 1.02, 0.5, 1.12, 0.05, 0.95)
            P(-0.05, 0.78, -0.5, 1.02, -0.5, 1.12, -0.05, 0.95)
            for sx in (0.45, 0.8):
                for sgn in (1, -1):
                    i_sil.create_oval(cx + sgn * sx * u - 3, cy + 0.18 * u - 3,
                                      cx + sgn * sx * u + 3, cy + 0.18 * u + 3,
                                      outline=col)
        elif light:
            P(0, -1.0, 0.09, -0.55, 0.09, 0.55, 0.04, 0.95, -0.04, 0.95, -0.09, 0.55,
              -0.09, -0.55)
            P(0.08, -0.35, 1.1, -0.3, 1.1, -0.14, 0.08, -0.1)
            P(-0.08, -0.35, -1.1, -0.3, -1.1, -0.14, -0.08, -0.1)
            P(0.03, 0.75, 0.42, 0.82, 0.42, 0.94, 0.03, 0.92)
            P(-0.03, 0.75, -0.42, 0.82, -0.42, 0.94, -0.03, 0.92)
            i_sil.create_line(cx - 0.3 * u, cy - u, cx + 0.3 * u, cy - u, fill=col)
        else:
            P(0, -1.15, 0.1, -0.65, 0.1, 0.65, 0.05, 1.05, -0.05, 1.05, -0.1, 0.65,
              -0.1, -0.65)
            P(0.09, -0.2, 1.2, 0.42, 1.2, 0.54, 0.09, 0.18)
            P(-0.09, -0.2, -1.2, 0.42, -1.2, 0.54, -0.09, 0.18)
            P(0.05, 0.8, 0.45, 1.04, 0.45, 1.14, 0.05, 0.97)
            P(-0.05, 0.8, -0.45, 1.04, -0.45, 1.14, -0.05, 0.97)
            for sgn in (1, -1):
                i_sil.create_oval(cx + sgn * 0.5 * u - 4, cy + 0.12 * u - 4,
                                  cx + sgn * 0.5 * u + 4, cy + 0.12 * u + 4, outline=col)
        draw_profile(a, sil_w + 6, w - 4, h)    # ... and the altitude profile the rest

    def note_alts(acs):
        """Sample every contact's altitude ~every 2 s for the card's profile graph."""
        now = time.time()
        for a in acs:
            af = alt_ft(a)
            if af is None or on_ground(a):
                continue
            hs = alt_hist.setdefault(a["hex"], [])
            if not hs or now - hs[-1][0] >= 2.0:
                hs.append((now, af))
                if len(hs) > 300:
                    del hs[:len(hs) - 300]
        if len(alt_hist) > 600 or int(now) % 60 == 0:
            for hx in [hx for hx, hs in alt_hist.items() if now - hs[-1][0] > 600]:
                del alt_hist[hx]

    def draw_profile(a, x0, x1, h):
        """Last 10 minutes of altitude, with the autopilot's selected altitude dashed."""
        if x1 - x0 < 40:
            return
        pts = [(t, v) for t, v in alt_hist.get(a["hex"], []) if time.time() - t <= 600]
        mcp = a.get("nav_altitude_mcp")
        cur = alt_ft(a)
        vals = [v for _, v in pts] + ([mcp] if mcp else []) + ([cur] if cur else [])
        if not vals:
            i_sil.create_text((x0 + x1) / 2, h / 2, text="no altitude", fill=T.TXT_3,
                              font=F["map"])
            return
        lo, hi = min(vals), max(vals)
        if hi - lo < 1000:
            mid = (hi + lo) / 2
            lo, hi = mid - 500, mid + 500
        top, bot = 14, h - 12

        def y(v):
            return bot - (v - lo) / (hi - lo) * (bot - top)
        i_sil.create_line(x0, bot, x1, bot, fill=T.night("#1d252c"))
        if mcp and (cur is None or abs(mcp - cur) > 250):
            i_sil.create_line(x0, y(mcp), x1, y(mcp), fill=AMBER, dash=(3, 3))
            i_sil.create_text(x1, y(mcp) - 2, anchor="se", text="SEL " + SI.fl(mcp),
                              fill=AMBER, font=F["map"])
        if len(pts) >= 2:
            t0 = time.time() - 600
            line = []
            for t, v in pts:
                line += [x0 + (t - t0) / 600.0 * (x1 - x0), y(v)]
            i_sil.create_line(*line, fill=contact_color(a, False), width=1.5)
            i_sil.create_oval(line[-2] - 2, line[-1] - 2, line[-2] + 2, line[-1] + 2,
                              fill=contact_color(a, False), outline="")
        if len(pts) >= 2:
            dv = pts[-1][1] - pts[0][1]
            mins = max(1, round((pts[-1][0] - pts[0][0]) / 60.0))
            chg = ("%s%s ft in %d min" % ("+" if dv > 0 else "", format(int(round(dv, -2)), ","),
                                          mins) if abs(dv) >= 200 else "steady %d min" % mins)
            i_sil.create_text(x0, 2, anchor="nw", text=chg, fill=T.TXT_2, font=F["map"])
        i_sil.create_text(x0, h - 1, anchor="sw", text="10 min", fill=T.TXT_3, font=F["map"])

    def home_pos(rcv=None):
        """Where 'you' are for range/overhead maths: GPS fix, else the receiver, else KAPA."""
        return my["pos"] or rcv or (AIRPORTS["KAPA"]["lat"], AIRPORTS["KAPA"]["lon"])

    def nearest_airport(lat, lon):
        best = None
        for ident, ap in AIRPORTS.items():
            d = dist_nm(lat, lon, ap["lat"], ap["lon"])
            if best is None or d < best[1]:
                best = (ident, d, ap.get("elev", 0))
        return best

    def route_for(a):
        """(route, state) for a contact; demo uses fixed routes and never the network."""
        cs = (a.get("flight") or "").strip().upper()
        if demo_on[0] and hist["t"] is None:
            rt = DEMO_ROUTES.get(cs)
            return rt, ("hit" if rt else ("miss" if SI.route_eligible(cs) else "none"))
        if not SI.route_eligible(cs):
            return None, "none"
        if s.get("route_lookup", True):
            routes.want(cs)
        return routes.get(cs)

    def route_line(a, phase, where):
        """(text, colour) for the card's route line."""
        rt, state = route_for(a)
        guess = SI.infer_route(phase, where)
        if rt:
            chk = SI.route_check(a["lat"], a["lon"], rt) if "lat" in a else None
            dest = rt["dest"].get("city") or rt["dest"].get("name") or ""
            txt = SI.route_short(rt) + (("  ·  to " + dest) if dest else "")
            if chk and not chk["plausible"]:
                return SI.route_short(rt) + " ?  listed route doesn't fit its position" + \
                    (("  ·  " + guess) if guess else ""), MUTED
            return txt, TXT
        if state == "pending":
            return "route: looking up…", MUTED
        if guess:
            return guess, TXT
        if state == "error":
            return "route: offline", MUTED
        if state == "miss":
            return "no published route", MUTED
        return "", MUTED

    def contact_status(a, home):
        """('APPROACH KDEN  ->  9,000  ·  overhead in 1:40', is_notable)"""
        bits, notable = [], False
        sq = str(a.get("squawk") or "")
        meaning = SI.SQUAWKS.get(sq)
        if meaning and sq != "1200":
            bits.append("SQ %s %s" % (sq, meaning))
            notable = True
        af = alt_ft(a)
        vr = a.get("baro_rate") or a.get("geom_rate") or 0
        near = nearest_airport(a["lat"], a["lon"]) if "lat" in a else None
        phase, where = SI.flight_phase(af, vr, a.get("gs"), on_ground(a), near)
        if phase:
            bits.append((phase.upper() + (" " + where if where else "")))
        mcp = a.get("nav_altitude_mcp")
        if mcp and af and not on_ground(a) and abs(mcp - af) > 250:
            tgt = "→ " + SI.fl(mcp)          # where the autopilot is taking it
            if bits:
                bits[-1] += "  " + tgt
            else:
                bits.append(tgt)
        if "lat" in a and not on_ground(a) and a.get("gs"):
            miss, t = SI.cpa(home[0], home[1], a["lat"], a["lon"], a.get("track"), a.get("gs"))
            if t > 0 and miss <= 1.5 and t <= 900:
                bits.append("OVERHEAD in %s" % SI.mmss(t))
                notable = True
            elif t > 0 and t <= 1800:
                bits.append("closest %.1f nm in %s" % (miss, SI.mmss(t)))
            elif t == 0:
                bits.append("receding")
        return "  ·  ".join(b for b in bits if b), notable

    def update_infodock(acs, rcv):
        home = rcv or (AIRPORTS["KAPA"]["lat"], AIRPORTS["KAPA"]["lon"])
        a = next((x for x in acs if x["hex"] == view["sel"]), None)
        for wdg in i_list.winfo_children():
            wdg.destroy()
        near = sorted((x for x in acs if "lat" in x),
                      key=lambda x: dist_nm(home[0], home[1], x["lat"], x["lon"]))[:5]
        for x in near:
            cs2, alt2 = label_for(x)
            d2 = dist_nm(home[0], home[1], x["lat"], x["lon"])
            fg = AMBER if x["hex"] == view["sel"] else (T.NOTE if is_military(x) else T.TXT_2)
            r = tk.Label(i_list, text="%-9s %6s %5.1fnm" % (cs2[:9], alt2 or "—", d2),
                         font=F["mono"], fg=fg, bg=T.SURFACE, anchor="w", cursor="hand2")
            r.pack(fill="x")
            r.bind("<Button-1>", lambda e, hh=x["hex"]: select_hex(hh))
        if not a:
            i_cs.config(text="—", fg=MUTED)
            i_mil.pack_forget()
            i_type.config(text="")
            i_route.config(text="")
            i_origin.config(text="")
            i_status.config(text="")
            i_sil.delete("all")
            for v in i_rows.values():
                v.config(text="—")
            i_hint.config(text="tap a contact on the map")
            return
        cs, _ = label_for(a)
        i_cs.config(text=cs, fg=T.NOTE if is_military(a) else TXT)
        (i_mil.pack(side="left", padx=(8, 0)) if is_military(a) else i_mil.pack_forget())
        cat = SI.CATEGORIES.get((a.get("category") or "").upper(), "")
        rt0, _ = route_for(a)
        op = a.get("ownOp") or (rt0 or {}).get("airline") or SI.airline_of(a.get("flight"))
        typ_txt = a.get("desc") or a.get("t") or (cat + " aircraft" if cat else "type unknown")
        i_type.config(text=((op + "  ·  ") if op else "") + typ_txt)
        af0 = alt_ft(a)
        vr0 = a.get("baro_rate") or a.get("geom_rate") or 0
        near0 = nearest_airport(a["lat"], a["lon"]) if "lat" in a else None
        ph0, wh0 = SI.flight_phase(af0, vr0, a.get("gs"), on_ground(a), near0)
        rtxt, rcol = route_line(a, ph0, wh0)
        i_route.config(text=rtxt, fg=rcol)
        reg = (a.get("r") or "").strip() or SI.n_number(a["hex"]) or ""
        if reg.upper() == cs.strip().upper():
            reg = ""                       # the title already shows it
        src_t = SI.SOURCES.get(a.get("type") or "", "")
        i_origin.config(text="  ·  ".join(x for x in (reg, SI.icao_country(a["hex"]), src_t) if x))
        draw_sil(a)
        stxt, notable = contact_status(a, home_pos(rcv))
        i_status.config(text=stxt, fg=AMBER if notable else T.TXT_2)
        af = alt_ft(a)
        vr = a.get("baro_rate") or a.get("geom_rate") or 0
        d = dist_nm(home[0], home[1], a["lat"], a["lon"]) if "lat" in a else None
        brg = bearing(home[0], home[1], a["lat"], a["lon"]) if "lat" in a else None
        i_rows["ALT"].config(text="GND" if on_ground(a) else
                             ("%s ft" % format(int(af), ",") if af else "—"))
        i_rows["GS"].config(text="%d kt" % a["gs"] if a.get("gs") is not None else "—")
        i_rows["TRK"].config(text="%03d°" % a["track"] if a.get("track") is not None else "—")
        i_rows["V/S"].config(text="%+d fpm" % vr if vr else "0 fpm")
        sq = str(a.get("squawk") or "")
        short = SI.SQUAWKS.get(sq, "")
        i_rows["SQUAWK"].config(text=(sq + (" " + short if short and len(short) <= 4 else ""))
                                or "—")
        i_rows["SEEN"].config(text="%ds ago" % int(a.get("seen", 0)))
        i_rows["RANGE"].config(text="%.1f nm" % d if d is not None else "—")
        i_rows["BRG"].config(text="%03d°" % brg if brg is not None else "—")
        i_rows["SIGNAL"].config(text="%.1f dB" % a["rssi"] if a.get("rssi") is not None
                                else "—")
        i_rows["HEX"].config(text=a["hex"].upper())
        i_hint.config(text="")

    def update_dock_contact(acs, rcv):
        """The DUAL dock's Contact tab: same facts as the SCOPE card, condensed."""
        a = next((x for x in acs if x["hex"] == view["sel"]), None)
        if not a:
            c_cs.config(text="—", fg=MUTED)
            for wdg in (c_type, c_route, c_status):
                wdg.config(text="")
            for v in c_rows.values():
                v.config(text="—")
            c_hint.pack(fill="x", pady=(T.px(6), 0))
            return
        c_hint.pack_forget()
        home = home_pos(rcv)
        cs, _ = label_for(a)
        mil = is_military(a)
        c_cs.config(text=cs + ("   MIL" if mil else ""), fg=AMBER if mil else TXT)
        cat = SI.CATEGORIES.get((a.get("category") or "").upper(), "")
        rt0, _ = route_for(a)
        op = a.get("ownOp") or (rt0 or {}).get("airline") or SI.airline_of(a.get("flight"))
        reg = (a.get("r") or "").strip() or SI.n_number(a["hex"]) or ""
        if reg.upper() == cs.strip().upper():
            reg = ""
        typ = a.get("desc") or a.get("t") or (cat + " aircraft" if cat else "type unknown")
        c_type.config(text="  ·  ".join(x for x in (op, typ, reg) if x))
        af = alt_ft(a)
        vr = a.get("baro_rate") or a.get("geom_rate") or 0
        near0 = nearest_airport(a["lat"], a["lon"]) if "lat" in a else None
        ph, wh = SI.flight_phase(af, vr, a.get("gs"), on_ground(a), near0)
        rtxt, rcol = route_line(a, ph, wh)
        c_route.config(text=rtxt, fg=rcol)
        stxt, notable = contact_status(a, home)
        sq = str(a.get("squawk") or "")
        if sq in ("7500", "7600", "7700"):
            stxt, notable = "SQUAWK %s %s  ·  %s" % (sq, SI.SQUAWKS.get(sq, ""), stxt), True
        c_status.config(text=stxt, fg=(RED if sq in ("7500", "7600", "7700") else AMBER)
                        if notable else T.TXT_2)
        c_route.pack_forget() if not rtxt else c_route.pack(fill="x", pady=(T.px(4), 0),
                                                               after=c_type)
        d = dist_nm(home[0], home[1], a["lat"], a["lon"]) if "lat" in a else None
        brg = bearing(home[0], home[1], a["lat"], a["lon"]) if "lat" in a else None
        vals = {"ALT": "GND" if on_ground(a) else ("%s ft" % format(int(af), ",") if af else "—"),
                "V/S": "%+d fpm" % vr if vr else "0 fpm",
                "GS": "%d kt" % a["gs"] if a.get("gs") is not None else "—",
                "TRK": "%03d°" % a["track"] if a.get("track") is not None else "—",
                "RANGE": "%.1f nm" % d if d is not None else "—",
                "BRG": "%03d°" % brg if brg is not None else "—"}
        for k, v in vals.items():
            c_rows[k].config(text=v)

    def draw_vmeter():
        v_meter.delete("all")
        w = v_meter.winfo_width()
        if w < 20:
            return
        db = level["db"]
        frac = 0 if db is None else (db + 60) / 60
        T.level_bar(v_meter, 0, T.px(5), w - T.px(90), T.px(10), frac, segments=30,
                    color=AMBER if live_channel[0] else T.TXT_3)
        v_meter.create_text(w, T.px(10), anchor="e", fill=T.TXT_3, font=F["map"],
                            text="%5.1f dBFS" % db if db is not None else "  -- dBFS")

    def open_contact(h):
        """Tapped a transcript that named a plane: show that plane."""
        if sky_mode[0] == "voice":
            set_mode("both")          # the map is hidden in Voice view
        select_hex(h)
        if dock["shown"]:
            show_panel("contact")
        info.config(text="Showing the aircraft named in that transmission", fg=MUTED)
        info_hold[0] = time.time() + 3

    def render_tx(box, n):
        box.config(state="normal")
        box.delete("1.0", "end")
        for i, r in enumerate(tx_state["lines"][-n:]):
            link = ("lnk%d" % i) if r.get("hexes") else None
            extra = (link,) if link else ()
            box.insert("end", time.strftime("%H:%M:%S ", time.localtime(r["t"])),
                       ("time",) + extra)
            box.insert("end", "%s: " % r.get("label", r.get("freq")), ("chan",) + extra)
            box.insert("end", (r.get("text") or "(no speech)"),
                       (("kw",) if r.get("kw") else ()) + extra)
            if r.get("calls"):
                box.insert("end", "  → " + ", ".join(r["calls"]) + "  ▸", ("heard",) + extra)
            box.insert("end", "\n")
            if link:   # the whole line is a tap target for the plane it named
                box.tag_bind(link, "<Button-1>", lambda e, h=r["hexes"][0]: open_contact(h))
                box.tag_bind(link, "<Enter>", lambda e, b=box: b.config(cursor="hand2"))
                box.tag_bind(link, "<Leave>", lambda e, b=box: b.config(cursor=""))
        box.config(state="disabled")
        box.see("end")
    worker = [None]
    try:
        from transcriber import mentioned_callsigns
    except Exception:
        mentioned_callsigns = None

    def start_worker():
        if s.get("transcribe") and os.path.exists(TRANSCRIBER) and not worker[0]:
            try:
                err = open(os.path.join(CACHE_DIR, "transcriber.err"), "w")
            except OSError:
                err = open(os.devnull, "w")
            with err:
                worker[0] = subprocess.Popen([sys.executable or "python3", TRANSCRIBER, "--worker"],
                                             start_new_session=True, stdout=subprocess.DEVNULL,
                                             stderr=err)

    def stop_worker():
        p = worker[0]
        if p and p.poll() is None:
            for sig, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 2)):
                try:
                    os.killpg(p.pid, sig)
                    p.wait(timeout=wait)
                    break
                except ProcessLookupError:
                    break
                except subprocess.TimeoutExpired:
                    continue
        worker[0] = None

    def poll_transcripts():
        out_dir = os.path.join(HOME, ".local", "share", "sky-app", "transcripts")
        path = os.path.join(out_dir, time.strftime("%Y-%m-%d") + ".jsonl")
        if tx_state["path"] != path:
            tx_state.update(path=path, pos=0)
        new = []
        try:
            # errors="replace": a corrupt or binary line must never kill the poller
            with open(path, errors="replace") as f:
                if tx_state["pos"] == 0:
                    # first look at a big day-file: tail it instead of parsing all of it
                    sz = os.fstat(f.fileno()).st_size
                    if sz > 262144:
                        f.seek(sz - 65536)
                        f.readline()   # discard the partial line we landed in
                        tx_state["pos"] = f.tell()
                f.seek(tx_state["pos"])
                for ln in f:
                    try:
                        r = json.loads(ln)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and isinstance(r.get("t"), (int, float)):
                        r["text"] = str(r.get("text") or "")
                        new.append(r)
                tx_state["pos"] = f.tell()
        except OSError:
            pass
        if new:
            acs, _, _, _ = feed.snapshot()
            flights = {(a.get("flight") or "").strip().upper(): a["hex"] for a in acs
                       if (a.get("flight") or "").strip()}
            kws = [str(k).lower() for k in s.get("keywords", []) if str(k).strip()]
            for r in new:
                r["calls"], r["hexes"] = [], []
                r["kw"] = None
                if mentioned_callsigns and r.get("text") and time.time() - r["t"] < 120:
                    for fl in sorted(mentioned_callsigns(r["text"], flights)):
                        heard[flights[fl]] = time.time()
                        r["calls"].append(fl)
                        r["hexes"].append(flights[fl])
                txt = (r.get("text") or "").lower()
                if txt and time.time() - r["t"] < 120:
                    try:
                        bingo_hear(txt)
                    except Exception:
                        pass
                    hit = next((k for k in kws if re.search(r"\b" + re.escape(k) + r"\b", txt)), None)
                    if hit:
                        r["kw"] = hit
                        speak("Heard %s on %s." % (hit, r.get("label", r.get("freq"))))
                        kw_log.insert(0, r)
                        del kw_log[8:]
                        rebuild_alerts()
                tx_state["lines"].append(r)
            del tx_state["lines"][:-12]
            render_tx(txbox, 4)
            if voice_shown[0]:
                render_tx(vtx, 10)
        for h in [h for h, t in heard.items() if time.time() - t > 90]:
            del heard[h]
        root.after(1000, poll_transcripts)

    def toggle_text():
        tx_visible[0] = not tx_visible[0]
        if tx_visible[0]:
            txbox.pack(fill="x", before=info)
        else:
            txbox.pack_forget()

    logbox = tk.Text(mapwrap, height=8, bg=T.BG, fg=T.TXT_2, font=F["map"], bd=0, padx=16,
                     highlightthickness=0, wrap="word")

    # ---- history scrub bar (last 60 min of ADS-B, recorded in memory while Sky is open)
    hist = {"t": None, "on": False, "play": None, "drag": False}
    hbar = tk.Frame(mapwrap, bg=T.SURFACE)
    hcv = tk.Canvas(hbar, bg=T.SURFACE, height=T.px(44), highlightthickness=0)
    hcv.pack(side="left", fill="x", expand=True, padx=(16, 8), pady=6)
    hbtns = tk.Frame(hbar, bg=T.SURFACE)
    hbtns.pack(side="right", padx=(0, 12))

    def hist_span():
        t0, t1 = feed.history_span()
        if t0 is None:
            return None, None
        return t0, max(t1, time.time())

    def draw_hbar():
        hcv.delete("all")
        w, h = hcv.winfo_width(), hcv.winfo_height()
        if w < 20:
            return
        t0, t1 = hist_span()
        y = h // 2
        hcv.create_line(0, y, w, y, fill=LINE, width=2)
        if t0 is None:
            hcv.create_text(w / 2, y, text="recording…", fill=T.TXT_3, font=F["map"])
            return
        span = max(60.0, t1 - t0)
        for m in range(0, 61, 5):          # tick every 5 min back from now
            tt = t1 - m * 60
            if tt < t0:
                break
            x = w * (tt - t0) / span
            hcv.create_line(x, y - (6 if m % 15 == 0 else 3), x, y + (6 if m % 15 == 0 else 3), fill=T.LINE_HI)
            if m % 15 == 0 and m:
                hcv.create_text(x, y + 9, text="−%d" % m, fill=T.TXT_3, font=F["map"], anchor="n")
        hcv.create_text(w, y + 9, text="now", fill=T.TXT_3, font=F["map"], anchor="ne")
        xt = w * (((hist["t"] if hist["t"] is not None else t1) - t0) / span)
        hcv.create_line(xt, 2, xt, h - 2, fill=AMBER, width=2)
        if hist["t"] is not None:
            an = "nw" if xt < 60 else ("ne" if xt > w - 60 else "n")
            hcv.create_text(xt + (6 if an == "nw" else (-6 if an == "ne" else 0)), 2, anchor=an,
                            fill=AMBER, font=F["map"],
                            text=time.strftime("%H:%M:%S", time.localtime(hist["t"])))

    def hist_seek(x):
        t0, t1 = hist_span()
        if t0 is None:
            return
        w = hcv.winfo_width()
        t = t0 + (t1 - t0) * max(0.0, min(1.0, x / max(1, w)))
        hist["t"] = None if t >= t1 - 1.5 else t
        draw_hbar()
        redraw_map()

    def hist_press(e):
        hist["drag"] = True
        hist_stop_play()
        hist_seek(e.x)

    def hist_motion(e):
        if hist["drag"]:
            hist_seek(e.x)

    def hist_release(e):
        hist["drag"] = False

    hcv.bind("<ButtonPress-1>", hist_press)
    hcv.bind("<B1-Motion>", hist_motion)
    hcv.bind("<ButtonRelease-1>", hist_release)
    hcv.bind("<Configure>", lambda e: draw_hbar())

    def hist_stop_play():
        if hist["play"]:
            root.after_cancel(hist["play"])
            hist["play"] = None
            T.set_btn(play_btn, "Play ×10", "quiet")

    def hist_step():
        hist["play"] = None
        if hist["t"] is None:
            return
        t0, t1 = hist_span()
        hist["t"] += 5.0               # 0.5 s real time -> 5 s replay = 10x
        if hist["t"] >= t1 - 1.5:
            hist["t"] = None
            T.set_btn(play_btn, "Play ×10", "quiet")
        else:
            hist["play"] = root.after(500, hist_step)
        draw_hbar()
        redraw_map()

    def hist_play():
        if hist["play"]:
            hist_stop_play()
            return
        if hist["t"] is None:
            t0, _ = hist_span()
            if t0 is None:
                return
            hist["t"] = max(t0, time.time() - 600)   # start 10 min back
        T.set_btn(play_btn, "Pause", "primary")
        hist["play"] = root.after(10, hist_step)

    def hist_live():
        hist_stop_play()
        hist["t"] = None
        draw_hbar()
        redraw_map()

    def hist_nudge(sec):
        t0, t1 = hist_span()
        if t0 is None:
            return
        hist_stop_play()
        cur = hist["t"] if hist["t"] is not None else t1
        t = max(t0, min(t1, cur + sec))
        hist["t"] = None if t >= t1 - 1.5 else t
        draw_hbar()
        redraw_map()

    for txt, cmd in (("−1m", lambda: hist_nudge(-60)), ("+1m", lambda: hist_nudge(60))):
        T.btn(hbtns, txt, cmd, F, padx=6, pady=2, kind="quiet").pack(side="left")
    play_btn = T.btn(hbtns, "Play ×10", hist_play, F, padx=8, pady=2, kind="quiet")
    play_btn.pack(side="left")
    T.btn(hbtns, "Live", hist_live, F, padx=8, pady=2, kind="quiet").pack(side="left")

    def export_history():
        """Write the recorded hour to CSV (one row per aircraft per frame) and KML (one path per aircraft)."""
        import csv as _csv
        with feed.lock:
            hist_copy = [(t, list(fr)) for t, fr in feed.history]
        if not hist_copy:
            info.config(text="Nothing recorded yet.", fg=MUTED)
            return
        outdir = os.path.join(HOME, ".local", "share", "uconsole-suite")
        os.makedirs(outdir, exist_ok=True)
        stem = os.path.join(outdir, time.strftime("adsb_%Y%m%d_%H%M", time.localtime(hist_copy[0][0])))
        with open(stem + ".csv", "w", newline="") as f:
            wr = _csv.writer(f)
            wr.writerow(["time_utc", "hex", "callsign", "registration", "type", "lat", "lon", "alt_ft",
                         "gs_kt", "track", "vrate_fpm", "squawk"])
            for t, fr in hist_copy:
                ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
                for a in fr:
                    wr.writerow([ts, a["hex"], (a.get("flight") or "").strip(), a.get("r", ""), a.get("t", ""),
                                 "%.5f" % a["lat"], "%.5f" % a["lon"], alt_ft(a) or "", a.get("gs", ""),
                                 a.get("track", ""), a.get("baro_rate", a.get("geom_rate", "")),
                                 a.get("squawk", "")])
        paths = {}
        names = {}
        for t, fr in hist_copy:
            for a in fr:
                paths.setdefault(a["hex"], []).append((a["lon"], a["lat"], (alt_ft(a) or 0) * 0.3048))
                if (a.get("flight") or "").strip():
                    names[a["hex"]] = a["flight"].strip()
        from xml.sax.saxutils import escape
        k = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             "<name>%s</name>" % escape(os.path.basename(stem)),
             '<Style id="trk"><LineStyle><color>ff3aa7f0</color><width>2</width></LineStyle></Style>']
        for h, pts in paths.items():
            if len(pts) < 2:
                continue
            k.append("<Placemark><name>%s</name><styleUrl>#trk</styleUrl><LineString>"
                     "<altitudeMode>absolute</altitudeMode><coordinates>%s</coordinates></LineString></Placemark>"
                     % (escape(names.get(h, h.upper())), " ".join("%.5f,%.5f,%.0f" % p for p in pts)))
        k.append("</Document></kml>")
        with open(stem + ".kml", "w") as f:
            f.write("\n".join(k))
        info.config(text="Exported %d aircraft, %d frames → %s.csv / .kml" % (len(paths), len(hist_copy), stem),
                    fg=MUTED)

    T.btn(hbtns, "Export", export_history, F, padx=8, pady=2, kind="quiet").pack(side="left", padx=(8, 0))

    def toggle_history(_=None):
        hist["on"] = not hist["on"]
        if hist["on"]:
            hbar.pack(fill="x", before=info)
            root.after(50, draw_hbar)
        else:
            hist_live()
            hbar.pack_forget()

    root.bind("h", toggle_history)

    # Web Mercator so basemap tiles line up pixel-exact.  view["z"] is the tile zoom.
    ZMIN, ZMAX = 6, 16
    view = {"z": 10, "lat": 39.715, "lon": -104.76, "sel": None, "drag": None, "moved": False}
    if s.get("map_center") in AIRPORTS:
        view["lat"], view["lon"] = AIRPORTS[s["map_center"]]["lat"], AIRPORTS[s["map_center"]]["lon"]
    view["z"] = int(s.get("map_zoom", 10)) if str(s.get("map_zoom", 10)).isdigit() else 10
    view["z"] = max(ZMIN, min(ZMAX, view["z"]))

    def scale_k():
        return tiles.px_per_nm(view["lat"], view["z"])

    def proj(lat, lon):
        w, h = cv.winfo_width(), cv.winfo_height()
        cx, cy = tiles.world_px(view["lat"], view["lon"], view["z"])
        x, y = tiles.world_px(lat, lon, view["z"])
        return w / 2 + (x - cx), h / 2 + (y - cy)

    def unproj(x, y):
        w, h = cv.winfo_width(), cv.winfo_height()
        cx, cy = tiles.world_px(view["lat"], view["lon"], view["z"])
        return tiles.from_world_px(cx + (x - w / 2), cy + (y - h / 2), view["z"])

    import suite as _suite
    _tw = 1 if _suite.low_power() else 3
    basemap = tiles.TileLayer(on_ready=lambda ok: root.after(0, tile_arrived), workers=_tw)
    basemap.layer = s.get("map_layer", "dark") if s.get("map_layer") in tiles.LAYER_ORDER else "dark"
    radar = tiles.TileLayer(on_ready=lambda ok: root.after(0, tile_arrived), workers=max(1, _tw - 1))
    radar.layer = "radar"
    radar_on = [bool(s.get("map_radar", False))]
    tile_redraw = [False]

    def tile_arrived():
        if not tile_redraw[0]:
            tile_redraw[0] = True
            root.after(120, flush_tiles)

    def flush_tiles():
        tile_redraw[0] = False
        redraw_map()

    def label_for(ac):
        cs = (ac.get("flight") or "").strip() or ac["hex"].upper()
        a = alt_ft(ac)
        alt = "GND" if on_ground(ac) else ("%s" % format(int(round(a, -2)), ",") if a else "")
        return cs, alt

    hit = []  # (x, y, hex)
    highlight = set()
    live_channel = [None]

    # category colors: jets cyan, GA green, helicopters purple, military amber
    C_JET, C_GA, C_HELI = (("#e8eaed", "#9aa1aa", "#a9bbd6") if T.STYLE == "maven"
                           else ("#62c6e8", "#8fd49a", "#c490e4"))
    HELI_T = ("EC", "R44", "R66", "B06", "B407", "B429", "AS3", "H60", "UH1",
              "A109", "A119", "A139", "AW", "S76", "S92", "MD5")

    def contact_color(a, stale):
        if stale:
            return T.night("#555d64")
        if is_military(a):
            return T.NOTE
        cat = (a.get("category") or "").upper()
        typ = (a.get("t") or "").strip().upper()
        if cat == "A7" or typ.startswith(HELI_T):
            return T.night(C_HELI)
        if cat in ("A1", "A2"):
            return T.night(C_GA)
        if cat in ("A3", "A4", "A5"):
            return T.night(C_JET)
        # no category broadcast: slow and low reads as GA, the rest as jets
        gs, af = a.get("gs") or 0, alt_ft(a) or 0
        return T.night(C_GA) if (gs and gs < 170 and af < 18000) else T.night(C_JET)

    def ctext(x, y, **kw):
        """Canvas text with a dark halo when drawn over imagery so labels stay legible."""
        if basemap.layer != "dark":
            sh = dict(kw)
            sh["fill"] = T.MAPBG
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1)):
                cv.create_text(x + dx, y + dy, **sh)
        return cv.create_text(x, y, **kw)

    rwy_watch = SI.RunwayWatch()
    rwy_t = [0.0]

    def note_runways(acs):
        """Which runways are in use: aircraft on final / climb-out, every ~2 s."""
        now = time.time()
        if now - rwy_t[0] < 2.0:
            return
        rwy_t[0] = now
        for a in acs:
            if "lat" not in a:
                continue
            for ident, ends in RWY_ENDS.items():
                ap = AIRPORTS[ident]
                if dist_nm(ap["lat"], ap["lon"], a["lat"], a["lon"]) > 15:
                    continue
                use = SI.runway_use(a, ends, ap["elev"])
                if use:
                    rwy_watch.note(ident, use[0], use[1], a["hex"], now)
                    break

    def _logbook_load():
        today = time.strftime("%Y-%m-%d")
        return SI.Logbook(load_json(os.path.join(LOGBOOK_DIR, today + ".json"), None),
                          load_json(os.path.join(LOGBOOK_DIR, "lifetime.json"), None), today)
    logbook = [_logbook_load()]
    lb_saved = [0.0]

    def logbook_save(force=False):
        lb = logbook[0]
        if not lb.dirty or (not force and time.time() - lb_saved[0] < 30):
            return
        try:
            os.makedirs(LOGBOOK_DIR, exist_ok=True)
            save_json(os.path.join(LOGBOOK_DIR, lb.date + ".json"), lb.day_json())
            save_json(os.path.join(LOGBOOK_DIR, "lifetime.json"), lb.life_json())
            lb.dirty = False
        except OSError:
            pass
        lb_saved[0] = time.time()

    coverage = SI.Coverage(load_json(COVERAGE_PATH, None))
    cov_on = [bool(s.get("show_coverage", True))]

    def draw_coverage(hp):
        """The antenna's real reception pattern: farthest contact heard per 10° sector.
        All-time dashed, today solid. Lopsided = terrain, walls or a poor ground plane."""
        for scope, dash, col in (("all", (2, 4), T.night("#3a4650")),
                                 ("today", None, T._mix(GREEN, MAPBG, 0.35))):
            pts = coverage.outline(scope)
            if len(pts) < 2:
                continue
            xy = []
            for brg_c, nm in pts:
                xy += list(proj(*SI.offset(hp[0], hp[1], brg_c, nm)))
            if len(pts) >= 3:
                cv.create_polygon(*xy, outline=col, fill="", dash=dash, width=1)
            else:
                cv.create_line(*xy, fill=col, dash=dash)

    sondes = {"t": 0.0, "d": []}
    SONDES_PATH = os.path.join(os.path.expanduser("~"), ".cache", "uconsole-suite", "sondes.json")

    def draw_sondes():
        """Weather balloons the Balloons app heard in the last 30 min (its cache file)."""
        now = time.time()
        if now - sondes["t"] > 5:
            sondes["t"] = now
            d = load_json(SONDES_PATH, None)
            sondes["d"] = [b for b in (d or {}).get("sondes", []) if isinstance(b, dict)
                           and now - float(b.get("t") or 0) < 1800] if isinstance(d, dict) else []
        col = T.night("#9ad0ff")
        for b in sondes["d"]:
            try:
                tr = [c for la, lo in b.get("track", [])[-120:] for c in proj(float(la), float(lo))]
                x, y = proj(float(b["lat"]), float(b["lon"]))
                alt_ft = float(b["alt"]) * 3.28084
            except (KeyError, TypeError, ValueError):
                continue
            if len(tr) >= 4:
                cv.create_line(*tr, fill=col, dash=(2, 3))
            cv.create_oval(x - 5, y - 7, x + 5, y + 3, outline=col, width=2)
            cv.create_line(x, y + 3, x, y + 9, fill=col)
            cv.create_text(x + 8, y, anchor="w", fill=col, font=F["map"],
                           text="%s  %s  %s" % (str(b.get("id", ""))[:12],
                                                (lambda v: v if v.startswith("FL") else v + " ft")(SI.fl(alt_ft)),
                                                str(b.get("phase", ""))[:10]))

    def toggle_coverage(_=None):
        cov_on[0] = not cov_on[0]
        s["show_coverage"] = cov_on[0]
        try:
            save_json(SETTINGS_PATH, s)
        except OSError:
            pass
        info.config(text=("Coverage outline ON: farthest contact per direction - today solid, "
                          "all-time dashed") if cov_on[0] else "Coverage outline off",
                    fg=MUTED)
        info_hold[0] = time.time() + 4
        redraw_map()

    def redraw_map():
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 10:
            return
        k = scale_k()
        missing = basemap.draw(cv, view["lat"], view["lon"], view["z"], w, h)
        if radar_on[0]:
            radar.draw(cv, view["lat"], view["lon"], view["z"], w, h, tag="radar")
        if hist["t"] is not None:
            acs, trails, status, rcv = feed.snapshot_at(hist["t"])
        elif demo_on[0]:
            acs, trails, status, rcv = demo.snapshot()
        else:
            acs, trails, status, rcv = feed.snapshot()
        if hist["t"] is None:
            note_alts(acs)
            note_runways(acs)
        c0 = rcv if rcv else (AIRPORTS["KAPA"]["lat"], AIRPORTS["KAPA"]["lon"])
        cx, cy = proj(*c0)
        for nm in (10, 25, 50, 100):
            r = nm * k
            if 30 < r < 2 * max(w, h):
                T.range_ring(cv, cx, cy, r, "%d" % nm, F)
        cv.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, outline=T.TXT_2)
        ring = 25 * k
        if 60 < ring < max(w, h) * 1.2:
            T.compass_ring(cv, cx, cy, ring, F)
        hp = home_pos(rcv)
        if cov_on[0]:
            draw_coverage(hp)
        draw_sondes()
        hit.clear()
        # airports: extended centerlines, runways, threshold numbers, ident
        for ident, ap in AIRPORTS.items():
            ids = RWY_IDS.get(ident, [])
            act = rwy_watch.active(ident)
            live_rwys = {r for kind in act for r, _ in act[kind]}
            for j, (la1, lo1, la2, lo2) in enumerate(ap["rwys"]):
                x1, y1 = proj(la1, lo1)
                x2, y2 = proj(la2, lo2)
                L = math.hypot(x2 - x1, y2 - y1) or 1
                ux, uy = (x2 - x1) / L, (y2 - y1) / L
                if ident in ("KAPA", "KDEN"):
                    ext = 6 * k  # 6 nm extended centreline, tick every nm
                    for sx, sy, d in ((x1, y1, -1), (x2, y2, 1)):
                        ex, ey = sx + d * ux * ext, sy + d * uy * ext
                        cv.create_line(sx, sy, ex, ey, fill=T.night("#20272d"), dash=(4, 4))
                        if k >= 24:
                            for nm in range(1, 7):
                                tx, ty = sx + d * ux * nm * k, sy + d * uy * nm * k
                                cv.create_line(tx - uy * 3, ty + ux * 3, tx + uy * 3, ty - ux * 3,
                                               fill=T.night("#2a3239"))
                in_use = j < len(ids) and (ids[j][0] in live_rwys or ids[j][1] in live_rwys)
                cv.create_line(x1, y1, x2, y2,
                               fill=T._mix(GREEN, MAPBG, 0.2) if in_use else T.night("#4a535c"),
                               width=max(2, int(k / 6)) + (1 if in_use else 0))
                if k >= 24 and j < len(ids):
                    for (px, py, d), lab in (((x1, y1, -1), ids[j][0]), ((x2, y2, 1), ids[j][1])):
                        ctext(px + d * ux * 9, py + d * uy * 9, text=lab, fill=T.TXT_3,
                                       font=F["map"])
            xs, ys = [], []
            for la1, lo1, la2, lo2 in ap["rwys"]:
                for la, lo in ((la1, lo1), (la2, lo2)):
                    px, py = proj(la, lo)
                    xs.append(px)
                    ys.append(py)
            lx, ly = min(xs) - 10, max(ys) + 8
            m = metar.get(ident)
            cat = (m or {}).get("cat", "")
            ccol = T.night(MetarFeed.CAT_COLOR.get(cat, T.TXT_2))
            ap_sel = view["sel"] == "ap:" + ident
            tid = ctext(lx, ly, text=ident, fill=ccol if cat else T.TXT_2, font=F["mapb"], anchor="ne")
            bx = cv.bbox(tid)
            if cat and bx:
                cv.create_rectangle(bx[0], bx[3], bx[2], bx[3] + 2, fill=ccol, outline="")
            if ap_sel and bx:
                cv.create_rectangle(bx[0] - 4, bx[1] - 3, bx[2] + 4, bx[3] + 20, outline=AMBER)
            if k >= 6:
                sub = "%d ft" % ap["elev"]
                if m and m["wind"] and k >= 12:
                    sub = m["wind"] + ("  " + m["altim"] if k >= 30 and m["altim"] else "")
                ctext(lx, ly + 15, text=sub, fill=T.TXT_3, font=F["map"], anchor="ne")
            rl = rwy_watch.label(ident)
            if rl:
                ctext(lx, ly + (30 if k >= 6 else 15), text=rl, anchor="ne", font=F["map"],
                      fill=T._mix(T.ACCENT, MAPBG, 0.15))
            hit.append((lx - 20, ly + 6, "ap:" + ident))
        # contacts: chevron + 1-min velocity vector + data block
        hl = highlight
        draw_acs = [a for a in acs if "lat" in a and a.get("seen_pos", 99) <= 60]
        overload = len(draw_acs) - 400
        if overload > 0:   # a feed this dense is corrupt or hostile; keep the UI alive
            draw_acs.sort(key=lambda a: dist_nm(c0[0], c0[1], a["lat"], a["lon"]))
            keep = {a["hex"] for a in draw_acs[:400]} | {view["sel"]} | set(hl)
            draw_acs = [a for a in draw_acs if a["hex"] in keep]
        for a in sorted(draw_acs, key=lambda a: (a["hex"] == view["sel"], a["hex"] in hl)):
            x, y = proj(a["lat"], a["lon"])
            if x < -60 or y < -60 or x > w + 60 or y > h + 60:
                continue
            is_heard = a["hex"] in heard
            is_hl, is_sel = a["hex"] in hl or is_heard, a["hex"] == view["sel"]
            stale = a.get("seen_pos", 0) > 15 or status not in ("live", "replay")
            mil = is_military(a)
            col = AMBER if (is_hl or is_sel) else contact_color(a, stale)
            is_alert = a["hex"] in alerts
            if is_alert:
                emergency = alerts[a["hex"]]["kind"] in ("hijack", "radio failure", "emergency")
                base_c = RED if emergency else AMBER
                col = base_c if (not emergency or int(time.time()) % 2 == 0) else T._mix(RED, MAPBG, 0.5)
                is_hl = True
                r = 18 + ((int(time.time() * 2) % 2) * 4 if emergency else 0)
                cv.create_oval(x - r, y - r, x + r, y + r, outline=col, width=1.5)
            t = trails.get(a["hex"], [])
            if len(t) > 1:
                seg = t[-16:]
                base = T.ACCENT if is_hl else col
                for j in range(1, len(seg)):
                    fade = 1 - j / len(seg)
                    x1, y1 = proj(*seg[j - 1])
                    x2, y2 = proj(*seg[j])
                    cv.create_line(x1, y1, x2, y2, fill=T._mix(base, T.MAPBG, 0.45 + 0.5 * fade))
                for la, lo in seg[:-1:3]:
                    px, py = proj(la, lo)
                    cv.create_rectangle(px - 0.5, py - 0.5, px + 0.5, py + 0.5,
                                        outline=T._mix(base, T.MAPBG, 0.5))
            trk = a.get("track")
            if on_ground(a):
                cv.create_rectangle(x - 2.5, y - 2.5, x + 2.5, y + 2.5, outline=col)
            else:
                ang = math.radians(trk or 0)
                sa, ca = math.sin(ang), math.cos(ang)
                size = 7
                pts = []
                for px, py in ((0, -1.2), (0.8, 0.9), (0, 0.4), (-0.8, 0.9)):
                    pts += [x + size * (px * ca - py * sa), y + size * (px * sa + py * ca)]
                cv.create_polygon(*pts, fill=col if (is_hl or is_sel) else "", outline=col, width=1.2)
                gs = a.get("gs") or 0
                if trk is not None and gs > 30:
                    L = gs / 60.0 * k  # 1-minute projection
                    cv.create_line(x + 9 * sa, y - 9 * ca, x + (9 + L) * sa, y - (9 + L) * ca,
                                   fill=col, width=1)
            if is_sel:
                cv.create_rectangle(x - 13, y - 13, x + 13, y + 13, outline=AMBER)
            if mil and not on_ground(a):
                cv.create_polygon(x, y - 11, x + 11, y, x, y + 11, x - 11, y,
                                  outline=col, fill="", width=1)
            if is_hl or is_sel or k >= 4:
                cs, alt = label_for(a)
                gs = a.get("gs")
                vr = a.get("baro_rate") or a.get("geom_rate") or 0
                trend = "↑" if vr > 300 else ("↓" if vr < -300 else " ")
                line2 = ("%s%s %s" % (("%03d" % round(alt_ft(a) / 100)) if alt_ft(a) else "GND",
                                      trend if alt_ft(a) else "", ("%d" % gs) if gs else "")).strip()
                if is_alert and alerts[a["hex"]]["kind"] in ("hijack", "radio failure", "emergency"):
                    line2 = "SQ %s  %s" % (alerts[a["hex"]]["sq"], line2)
                t_ovh = SI.overhead(hp[0], hp[1], a)
                if t_ovh is not None:
                    line2 += "  OVHD " + SI.mmss(t_ovh)
                # data block on the side away from the velocity vector
                right = trk is None or math.sin(math.radians(trk)) <= 0.25
                if not right and x < 110:
                    right = True
                elif right and x > w - 110:
                    right = False
                dx, an = (14, "w") if right else (-14, "e")
                typ = (a.get("t") or "").strip()
                reg = (a.get("r") or "").strip()
                line1 = cs + ("  MIL" if mil else "")
                if k >= 12 and typ:
                    line1 += "  " + typ
                if k >= 24 and reg and reg.upper() != cs.upper():
                    line1 += "  " + reg
                ctext(x + dx, y - 3, text=line1, fill=col if (is_hl or is_sel) else TXT,
                               anchor="s" + an, font=F["mapb"])
                ctext(x + dx, y - 2, text=line2,
                      fill=AMBER if (is_hl or is_sel or t_ovh is not None) else col,
                      anchor="n" + an, font=F["map"])
            hit.append((x, y, a["hex"]))
        # chrome: scale bar, counts, banners
        T.scale_bar(cv, 18, h - 18, k, F)
        # legend: what the colors mean, above the tile status line
        lx0, ly0 = 18, h - 72
        for lab, c in (("JET", T.night(C_JET)), ("GA", T.night(C_GA)),
                       ("HELI", T.night(C_HELI)), ("MIL", T.NOTE)):
            cv.create_rectangle(lx0, ly0 - 4, lx0 + 8, ly0 + 4, fill=c, outline="")
            ctext(lx0 + 13, ly0, text=lab, anchor="w", fill=T.TXT_3, font=F["map"])
            lx0 += 23 + F["map"].measure(lab) + 10
        vis = [a for a in acs if "lat" in a]
        mil_n = sum(1 for a in vis if is_military(a))
        ctext(w - 16, h - 28, anchor="se", fill=AMBER if mil_n else T.TXT_3, font=F["map"],
                       text="%d contacts%s" % (len(vis), ("  ·  %d MIL" % mil_n) if mil_n else ""))
        if cov_on[0]:
            summ = coverage.summary("today")
            ctext(w - 16, h - 46, anchor="se", fill=T.TXT_3, font=F["map"],
                  text=("coverage today: " + summ) if summ else "coverage: nothing heard yet today")
        bulk = basemap.bulk_status()
        if bulk["active"]:
            tstat = "downloading tiles %d / %d" % (bulk["done"], bulk["total"])
        elif missing and not basemap.online:
            tstat = "offline · %d tiles not cached" % missing
        elif missing:
            tstat = "loading %d tiles" % missing
        else:
            tstat = ""
        if tstat:
            ctext(18, h - 34, anchor="sw", fill=AMBER if bulk["active"] else T.TXT_3,
                           font=F["map"], text=tstat)
        ctext(w - 16, h - 12, anchor="se", fill=T._mix(T.TXT_3, T.MAPBG, 0.6), font=F["map"],
                       text=basemap.spec["credit"])
        if demo_on[0] and hist["t"] is None:
            banner("DEMO TRAFFIC · synthetic contacts, not real")
        elif status == "replay":
            banner("REPLAY  %s  ·  %s ago" % (time.strftime("%H:%M:%S", time.localtime(hist["t"])),
                                               ago(hist["t"])))
        elif status != "live" and ctl.device == "rtlsdr" and adsb_device() != "hackrf":
            banner("Map paused while the built-in SDR listens to airband. Connect the H4M to run both.")
        elif status == "none" and adsb_device() == "hackrf" and hackrf_status() != "ready":
            banner("No ADS-B: readsb is set to use the H4M, which is %s." %
                   ("not in HackRF mode" if hackrf_status() == "wrong_mode" else "not connected"))
        elif status == "none":
            banner("No ADS-B data. Is readsb running?  (sky --status)")
        if live_channel[0]:
            c = live_channel[0]
            n = len(highlight)
            txt = "%s  ·  %s" % (c["label"], "%d likely contact%s" % (n, "" if n == 1 else "s") if n else
                                 ("broadcast" if c.get("role") == "atis" else "no likely contact in view"))
            tid = ctext(16, 14, anchor="nw", fill=AMBER, font=F["smb"], text="RX  " + txt)
            bx = cv.bbox(tid)
            cv.create_rectangle(bx[0] - 8, bx[1] - 5, bx[2] + 8, bx[3] + 5, fill=T.SURFACE,
                                outline=T.AMBER_DIM)
            cv.tag_raise(tid)
        if info_shown[0]:
            update_infodock(acs, rcv)
        if dock["shown"] and dock_tab[0] == "contact":
            update_dock_contact(acs, rcv)
        draw_info(acs)

    def banner(text):
        w = cv.winfo_width()
        tid = cv.create_text(w / 2, 16, anchor="n", fill=TXT, font=F["sm"], text=text)
        bx = cv.bbox(tid)
        cv.create_rectangle(bx[0] - 10, bx[1] - 5, bx[2] + 10, bx[3] + 5, fill=T.SURFACE,
                            outline=LINE)
        cv.tag_raise(tid)

    info_hold = [0.0]   # timestamp until which a pinned message (Point, actions) stays put

    def route_progress(a):
        """Info-bar text while the contact card is open: only what the card doesn't show."""
        rt, _ = route_for(a)
        chk = SI.route_check(a["lat"], a["lon"], rt) if (rt and "lat" in a) else None
        if chk and chk["plausible"]:
            gs = a.get("gs") or 0
            pct = 100.0 * chk["flown"] / chk["total"] if chk["total"] else 0
            eta = ""
            if gs > 60 and not on_ground(a):
                m = int(chk["to_go"] / gs * 60)
                eta = "  ·  ~%dh%02d to go at %d kt" % (m // 60, m % 60, gs)
            return {"text": "%s  ·  %s nm route  ·  %d%% flown  ·  %s nm left%s" % (
                SI.route_short(rt), format(int(chk["total"]), ","), pct,
                format(int(chk["to_go"]), ","), eta), "fg": TXT}
        summ = coverage.summary("today")
        tips = "C coverage  ·  V views  ·  F2 panel"
        return {"text": ("coverage today: %s   ·   %s" % (summ, tips)) if summ else tips,
                "fg": MUTED}

    def draw_info(acs):
        if time.time() < info_hold[0]:
            return
        if not view["sel"]:
            return
        if str(view["sel"]).startswith("ap:"):
            ident = view["sel"][3:]
            m = metar.get(ident)
            ap = AIRPORTS.get(ident, {})
            if m and m["raw"]:
                info.config(text="%s  ·  %s" % (m["cat"] or "METAR", m["raw"]),
                            fg=T.night(MetarFeed.CAT_COLOR.get(m["cat"], TXT)))
            else:
                info.config(text="%s  ·  %s  ·  %d ft  ·  METAR unavailable%s" % (
                    ident, ap.get("name", ""), ap.get("elev", 0),
                    (" (" + metar.error + ")") if metar.error else " (no network yet)"), fg=MUTED)
            return
        a = next((a for a in acs if a["hex"] == view["sel"]), None)
        if not a:
            info.config(text="Selected aircraft out of range", fg=MUTED)
            return
        if info_shown[0]:
            info.config(**route_progress(a))
            return
        cs, _ = label_for(a)
        alt = alt_ft(a)
        reg = (a.get("r") or "").strip()
        bits = [cs, "MIL" if is_military(a) else "",
                reg if reg and reg.upper() != cs.upper() else "",
                a.get("desc") or a.get("t") or "", a.get("ownOp") or "",
                "GND" if on_ground(a) else ("%s ft" % format(int(alt), ",") if alt else ""),
                ("%d kt" % a["gs"]) if a.get("gs") is not None else "",
                ("trk %03d°" % a["track"]) if a.get("track") is not None else "",
                ("sq %s" % a["squawk"]) if a.get("squawk") else ""]
        if "lat" in a:
            near = min(AIRPORTS.items(), key=lambda kv: dist_nm(kv[1]["lat"], kv[1]["lon"],
                                                                 a["lat"], a["lon"]))
            bits.append("%.1f nm from %s" % (dist_nm(near[1]["lat"], near[1]["lon"],
                                                     a["lat"], a["lon"]), near[0]))
        info.config(text="  ·  ".join(b for b in bits if b), fg=TXT)

    def on_press(e):
        view["drag"] = (e.x, e.y, view["lat"], view["lon"])
        view["moved"] = False

    def on_motion(e):
        if not view["drag"]:
            return
        x0, y0, la0, lo0 = view["drag"]
        if abs(e.x - x0) + abs(e.y - y0) > 6:
            view["moved"] = True
        cx, cy = tiles.world_px(la0, lo0, view["z"])
        view["lat"], view["lon"] = tiles.from_world_px(cx - (e.x - x0), cy - (e.y - y0), view["z"])
        view["lat"] = max(-80, min(80, view["lat"]))
        redraw_map()

    def on_release(e):
        if view["drag"] and not view["moved"]:
            best = min(hit, key=lambda t: (t[0] - e.x) ** 2 + (t[1] - e.y) ** 2, default=None)
            if best and (best[0] - e.x) ** 2 + (best[1] - e.y) ** 2 < 30 ** 2:
                view["sel"] = best[2]
                if dock["shown"] and dock_tab[0] == "channels":
                    show_panel("contact")      # alerts stay up if that's what you're reading
            else:
                view["sel"] = None
                info.config(text="Select a contact for details", fg=T.TXT_3)
            redraw_map()
        view["drag"] = None

    def zoom(d, e=None):
        z = max(ZMIN, min(ZMAX, view["z"] + d))
        if z == view["z"]:
            return
        if e is not None:
            la, lo = unproj(e.x, e.y)
        view["z"] = z
        if e is not None:
            la2, lo2 = unproj(e.x, e.y)
            view["lat"] += la - la2
            view["lon"] += lo - lo2
        s["map_zoom"] = z
        redraw_map()

    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_motion)
    cv.bind("<ButtonRelease-1>", on_release)
    cv.bind("<Button-4>", lambda e: zoom(+1, e))
    cv.bind("<Button-5>", lambda e: zoom(-1, e))
    cv.bind("<MouseWheel>", lambda e: zoom(+1 if e.delta > 0 else -1, e))
    cv.bind("<Configure>", lambda e: redraw_map())

    centers = ["KAPA-KDEN", "KAPA", "KDEN", "ME"]
    ci = [0]

    def recenter():
        ci[0] = (ci[0] + 1) % len(centers)
        c = centers[ci[0]]
        _, _, _, rcv = feed.snapshot()
        if c == "KAPA-KDEN":
            view["lat"], view["lon"], view["z"] = 39.715, -104.76, 10
        elif c == "ME" and rcv:
            view["lat"], view["lon"] = rcv
        elif c in AIRPORTS:
            view["lat"], view["lon"], view["z"] = AIRPORTS[c]["lat"], AIRPORTS[c]["lon"], 12
        redraw_map()

    mapbtns = tk.Frame(cv, bg=T.SURFACE, highlightthickness=1, highlightbackground=LINE)
    mapbtns.place(relx=1.0, rely=0.0, x=-14, y=14, anchor="ne")
    for t, c in (("+", lambda: zoom(+1)), ("−", lambda: zoom(-1))):
        b = T.btn(mapbtns, t, c, F, font="h", padx=11, pady=2, kind="quiet")
        b.config(fg=TXT)
        b.pack(fill="x")
        tk.Frame(mapbtns, bg=LINE, height=1).pack(fill="x")
    ctr_btn = T.btn(mapbtns, "⌖", recenter, F, font="h", padx=11, pady=2, kind="quiet")
    ctr_btn.config(fg=TXT)
    ctr_btn.pack(fill="x")
    tk.Frame(mapbtns, bg=LINE, height=1).pack(fill="x")

    def save_view():
        s["map_layer"], s["map_zoom"], s["map_radar"] = basemap.layer, view["z"], radar_on[0]
        try:
            save_json(SETTINGS_PATH, s)
        except OSError:
            pass

    layers_sheet = {"win": None}

    def refresh_layers_sheet():
        w = layers_sheet["win"]
        if w and w.winfo_exists() and getattr(w, "rebuild", None):
            w.rebuild()

    def cycle_layer(_=None):
        basemap.cycle()
        view["z"] = basemap.clamp_zoom(view["z"])
        save_view()
        redraw_map()
        refresh_layers_sheet()

    # ---- offline maps dialog: pick a region, layers and zoom range; see the cost before downloading
    REGIONS = [
        ("Current view", None),
        ("Denver metro", (39.45, -105.35, 40.05, -104.45)),
        ("Front Range", (38.70, -105.80, 40.80, -104.20)),
        ("Colorado", (36.90, -109.10, 41.10, -102.00)),
    ]
    # average bytes per tile (measured on the public servers) and polite bulk caps
    LAYER_META = {"dark": (26000, 20000, 15), "sat": (32000, 25000, 15), "streets": (26000, 20000, 15)}
    offline = {"win": None}

    def open_offline(_=None):
        if offline["win"] and offline["win"].winfo_exists():
            offline["win"].lift()
            return
        win = tk.Toplevel(root, bg=T.SURFACE)
        win.title("Offline maps")
        win.transient(root)
        win.geometry("+%d+%d" % (root.winfo_rootx() + 80, root.winfo_rooty() + 60))
        offline["win"] = win
        pad = tk.Frame(win, bg=T.SURFACE, padx=T.px(16), pady=T.px(14))
        pad.pack(fill="both", expand=True)
        state = {"region": 0, "layers": {"dark": True, "sat": False, "streets": False},
                 "zmax": 13, "job": None}

        def bbox():
            r = REGIONS[state["region"]][1]
            if r:
                return r
            w, h = cv.winfo_width(), cv.winfo_height()
            la1, lo1 = unproj(0, h)
            la2, lo2 = unproj(w, 0)
            return (la1, lo1, la2, lo2)

        T.section(pad, F, "Region").pack(fill="x")
        rrow = tk.Frame(pad, bg=T.SURFACE)
        rrow.pack(fill="x", pady=(4, 10))
        rbtns = []

        def set_region(i):
            state["region"] = i
            for j, b in enumerate(rbtns):
                T.set_btn(b, kind="primary" if j == i else "ghost")
            estimate()

        for i, (name, _) in enumerate(REGIONS):
            b = T.btn(rrow, name, lambda i=i: set_region(i), F, padx=8, pady=3,
                      kind="primary" if i == 0 else "ghost")
            b.pack(side="left", padx=(0, 6))
            rbtns.append(b)

        T.section(pad, F, "Layers").pack(fill="x")
        lrow = tk.Frame(pad, bg=T.SURFACE)
        lrow.pack(fill="x", pady=(4, 10))
        lbtns = {}

        def toggle_layer(k):
            state["layers"][k] = not state["layers"][k]
            T.set_btn(lbtns[k], kind="primary" if state["layers"][k] else "ghost")
            estimate()

        for k in tiles.LAYER_ORDER:
            b = T.btn(lrow, tiles.LAYERS[k]["label"], lambda k=k: toggle_layer(k), F, padx=8, pady=3,
                      kind="primary" if state["layers"][k] else "ghost")
            b.pack(side="left", padx=(0, 6))
            lbtns[k] = b

        T.section(pad, F, "Detail").pack(fill="x")
        zrow = tk.Frame(pad, bg=T.SURFACE)
        zrow.pack(fill="x", pady=(4, 10))
        zlbl = tk.Label(zrow, text="", font=F["sm"], fg=TXT, bg=T.SURFACE, width=34, anchor="w")

        def set_zmax(d):
            state["zmax"] = max(9, min(15, state["zmax"] + d))
            estimate()

        T.btn(zrow, "−", lambda: set_zmax(-1), F, padx=10, pady=2, kind="quiet").pack(side="left")
        zlbl.pack(side="left", padx=6)
        T.btn(zrow, "+", lambda: set_zmax(+1), F, padx=10, pady=2, kind="quiet").pack(side="left")

        est = tk.Label(pad, text="", font=F["sm"], fg=T.TXT_2, bg=T.SURFACE, justify="left", anchor="w")
        est.pack(fill="x", pady=(0, 10))
        prog = tk.Label(pad, text="", font=F["sm"], fg=AMBER, bg=T.SURFACE, anchor="w")
        prog.pack(fill="x")
        brow = tk.Frame(pad, bg=T.SURFACE)
        brow.pack(fill="x", pady=(6, 12))

        T.section(pad, F, "Cached on this device").pack(fill="x")
        crow = tk.Frame(pad, bg=T.SURFACE)
        crow.pack(fill="x", pady=(4, 0))
        clbls = {}
        for k in tiles.LAYER_ORDER + ["radar"]:
            f = tk.Frame(crow, bg=T.SURFACE)
            f.pack(fill="x", pady=1)
            tk.Label(f, text=tiles.LAYERS[k]["label"], font=F["sm"], fg=TXT, bg=T.SURFACE, width=10,
                     anchor="w").pack(side="left")
            clbls[k] = tk.Label(f, text="", font=F["mono"], fg=T.TXT_2, bg=T.SURFACE, anchor="w")
            clbls[k].pack(side="left", padx=8)
            T.btn(f, "Clear", lambda k=k: (basemap.clear_cache(k), estimate(), redraw_map()), F, padx=6,
                  pady=1, kind="quiet").pack(side="right")

        ZDESC = {9: "region overview", 10: "cities", 11: "towns, major roads", 12: "neighbourhoods",
                 13: "streets", 14: "street names", 15: "buildings"}

        def plan():
            la1, lo1, la2, lo2 = bbox()
            out = []
            for k in tiles.LAYER_ORDER:
                if not state["layers"][k]:
                    continue
                bpt, cap, zcap = LAYER_META[k]
                zmax = min(state["zmax"], zcap)
                total, have = basemap.bbox_count(k, la1, lo1, la2, lo2, 6, zmax)
                out.append((k, total, have, bpt, cap, zmax))
            return out

        def estimate():
            zlbl.config(text="up to zoom %d  ·  %s" % (state["zmax"], ZDESC.get(state["zmax"], "")))
            rows = plan()
            need = sum(t - h for _, t, h, _, _, _ in rows)
            mb = sum((t - h) * b for _, t, h, b, _, _ in rows) / 1e6
            lines = []
            warn = []
            for k, t, h, b, cap, zmax in rows:
                lines.append("%-9s %6d tiles, %5d cached" % (tiles.LAYERS[k]["label"], t, h))
                if t - h > cap:
                    warn.append("%s: %d tiles is over this server's polite limit (%d) - shrink the region "
                                "or lower the detail." % (tiles.LAYERS[k]["label"], t - h, cap))
                if zmax < state["zmax"]:
                    warn.append("%s stops at zoom %d for bulk downloads." % (tiles.LAYERS[k]["label"], zmax))
            if not rows:
                lines.append("Pick at least one layer.")
            txt = "\n".join(lines) + ("\n\nTo download: %d tiles, about %.0f MB" % (need, mb) if rows else "")
            if warn:
                txt += "\n\n" + "\n".join(warn)
            est.config(text=txt, fg=AMBER if warn else T.TXT_2)
            state["ok"] = bool(rows) and not warn and need > 0
            T.set_btn(start_btn, kind="primary" if state["ok"] else "ghost")
            for k in clbls:
                clbls[k].config(text="%5d tiles  %6.1f MB" % (basemap.cached_count(k), basemap.cache_bytes(k) / 1e6))

        def start():
            if not state.get("ok"):
                return
            la1, lo1, la2, lo2 = bbox()
            n = 0
            for k, t, h, b, cap, zmax in plan():
                n += basemap.download_bbox(k, la1, lo1, la2, lo2, 6, zmax, limit=cap)
            prog.config(text="Queued %d tiles…" % n)
            tick()

        def cancel():
            n = basemap.cancel_bulk()
            prog.config(text="Cancelled (%d tiles skipped). What was fetched stays cached." % n)

        def tick():
            if state["job"]:
                root.after_cancel(state["job"])
                state["job"] = None
            if not win.winfo_exists():
                return
            b = basemap.bulk_status()
            if b["active"]:
                prog.config(text="Downloading  %d / %d%s" % (
                    b["done"], b["total"], "" if basemap.online else "   (offline - waiting for network)"))
                state["job"] = root.after(500, tick)
            elif b["total"]:
                prog.config(text="Done - %d tiles cached." % b["total"])
                estimate()

        start_btn = T.btn(brow, "Download", start, F, padx=12, pady=4, kind="primary")
        start_btn.pack(side="left")
        T.btn(brow, "Cancel download", cancel, F, padx=10, pady=4, kind="quiet").pack(side="left", padx=8)
        T.btn(brow, "Close", win.destroy, F, padx=10, pady=4, kind="quiet").pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())
        estimate()
        tick()


    def toggle_radar(_=None):
        radar_on[0] = not radar_on[0]
        save_view()
        redraw_map()
        refresh_layers_sheet()

    def set_layer(k):
        if basemap.layer != k:
            basemap.layer = k
            view["z"] = basemap.clamp_zoom(view["z"])
            save_view()
            redraw_map()
            refresh_layers_sheet()

    def build_layers(body):
        import tkinter as tk
        tk.Label(body, text="Basemap", font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w").pack(fill="x")
        brow = tk.Frame(body, bg=T.SURFACE)
        brow.pack(fill="x", pady=(2, 8))
        for k in tiles.LAYER_ORDER:
            T.btn(brow, tiles.LAYERS[k]["label"], lambda k=k: set_layer(k), F, padx=10, pady=3,
                  kind="primary" if basemap.layer == k else "ghost").pack(side="left", padx=(0, 6))
        tk.Frame(body, bg=LINE, height=1).pack(fill="x", pady=4)
        orow = tk.Frame(body, bg=T.SURFACE)
        orow.pack(fill="x")
        T.btn(orow, "Radar " + ("on" if radar_on[0] else "off"), toggle_radar, F, padx=10, pady=3,
              kind="primary" if radar_on[0] else "ghost").pack(side="left", padx=(0, 6))
        T.btn(orow, "Sonar " + ("on" if sonar["on"] else "off"), lambda: toggle_sonar(), F, padx=10,
              pady=3, kind="primary" if sonar["on"] else "ghost").pack(side="left", padx=(0, 6))
        T.btn(orow, "Offline maps…", lambda: (open_offline(), close_layers()), F, padx=10, pady=3,
              kind="ghost").pack(side="left")

    def close_layers():
        w = layers_sheet["win"]
        if w and w.winfo_exists():
            w.close()
        layers_sheet["win"] = None

    def open_layers(_=None):
        if layers_sheet["win"] and layers_sheet["win"].winfo_exists():
            close_layers()
            return
        win = T.sheet(layers_btn, F, "Map layers", build_layers, side="left")
        layers_sheet["win"] = win

    layers_btn = T.btn(mapbtns, "Layers", open_layers, F, font="sm", padx=8, pady=3, kind="quiet")
    layers_btn.pack(fill="x")
    root.bind("r", toggle_radar)
    root.bind("o", open_offline)
    root.bind("l", cycle_layer)

    # ---- tools
    log_visible = [False]

    def toggle_log():
        log_visible[0] = not log_visible[0]
        if log_visible[0]:
            logbox.pack(fill="x", before=info)
        else:
            logbox.pack_forget()

    SCHEMA = [
        ("Radios", [
            {"key": "airband_device", "label": "Airband radio", "type": "choice",
             "choices": ([("rtlsdr", "Built-in SDR"), ("auto", "H4M if free, else built-in"),
                          ("hackrf", "H4M only")] if H4M_ENABLED else [("rtlsdr", "Built-in SDR")]),
             "help": "One radio: the plane map pauses while Sky is listening"},
            {"key": "rtlsdr.gain", "label": "Built-in SDR gain", "type": "float", "min": 0, "max": 49.6,
             "step": 2, "unit": "dB"},
            {"key": "rtlsdr.correction", "label": "Built-in SDR PPM", "type": "int", "min": -100, "max": 100,
             "step": 1, "unit": "ppm"},
            {"key": "hackrf.lna", "label": "H4M LNA gain", "type": "int", "min": 0, "max": 40, "step": 8, "unit": "dB"},
            {"key": "hackrf.vga", "label": "H4M VGA gain", "type": "int", "min": 0, "max": 62, "step": 2, "unit": "dB"},
            {"key": "hackrf.amp", "label": "H4M RF amp", "type": "int", "min": 0, "max": 1, "step": 1,
             "help": "0 off, 1 on (can overload near strong transmitters)"},
            {"key": "restore_plane_map", "label": "Restart readsb after listening", "type": "bool",
             "help": "only matters when airband and ADS-B share the built-in SDR"},
        ]),
        ("Channels", [
            {"key": "channels", "label": "Airband channels", "type": "table",
             "help": "role: tower, ground, approach, clearance, atis, other",
             "columns": [("freq", "MHz", "float"), ("label", "Label", "str"), ("airport", "Airport", "str"),
                         ("role", "Role", "str"), ("on", "On", "bool")],
             "template": {"freq": 118.0, "label": "New", "airport": "KAPA", "role": "other", "on": True}},
        ]),
        ("Transcripts", [
            {"key": "transcribe", "label": "Transcribe with Whisper", "type": "bool"},
            {"key": "whisper_model", "label": "Whisper model", "type": "choice",
             "choices": [("tiny.en", "tiny.en (fastest)"), ("base.en", "base.en"), ("small.en", "small.en (slow)")]},
            {"key": "keep_audio_hours", "label": "Keep recordings", "type": "int", "min": 1, "max": 168, "step": 1,
             "unit": "hours"},
            {"key": "keywords", "label": "Alert keywords", "type": "list", "help": "spoken alert when heard"},
        ]),
        ("Alerts", [
            {"key": "watch", "label": "Watch list", "type": "list", "help": "callsigns, hex codes or N-numbers"},
            {"key": "fence.nm", "label": "Proximity alert radius", "type": "float", "min": 0, "max": 50, "step": 1,
             "unit": "nm", "help": "0 = off"},
            {"key": "fence.below_ft", "label": "...and below", "type": "int", "min": 0, "max": 60000, "step": 500,
             "unit": "ft"},
            {"key": "anomaly_alerts", "label": "Flag unusual contacts", "type": "bool",
             "help": "military, circling/loitering, and aircraft types new to your sky"},
        ]),
        ("Map", [
            {"key": "map_center", "label": "Start centred on", "type": "choice",
             "choices": [("KAPA-KDEN", "KAPA + KDEN"), ("KAPA", "KAPA"), ("KDEN", "KDEN")]},
            {"key": "map_layer", "label": "Basemap", "type": "choice",
             "choices": [("dark", "Dark"), ("sat", "Satellite"), ("streets", "Streets")]},
            {"key": "map_radar", "label": "Radar overlay", "type": "bool"},
        ]),
    ]

    def edit_settings():
        import settings_ui

        def on_save(new):
            save_json(SETTINGS_PATH, new)
            reload_settings()
            if basemap.layer != s.get("map_layer"):
                basemap.layer = s["map_layer"] if s.get("map_layer") in tiles.LAYER_ORDER else "dark"
            radar_on[0] = bool(s.get("map_radar"))
            refresh_layers_sheet()
            redraw_map()

        settings_ui.open_settings(root, F, "Sky settings", SCHEMA, s, on_save, path=SETTINGS_PATH)

    def reload_settings():
        new = load_settings()
        s.clear()
        s.update(new)
        draw_gain()
        build_rows()
        detail.config(text="Settings applied.")
        schedule_restart()

    tk.Frame(tools, bg=LINE, height=1).pack(fill="x", pady=(0, 6))
    trow = tk.Frame(tools, bg=T.SURFACE)
    trow.pack(fill="x")
    replay_proc = [None]

    def replay_last(_=None):
        """Play the most recent airband transmission (the per-transmission files Whisper uses)."""
        files = sorted(glob.glob(os.path.join(REC_DIR, "*.mp3")), key=os.path.getmtime)
        files = [f for f in files if os.path.getsize(f) > 2000]
        if not files:
            detail.config(text="No recorded transmission yet (transcribe must be on).", fg=MUTED)
            return
        f = files[-1]
        player = next((p for p in (["mpv", "--no-video", "--really-quiet"],
                                   ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
                                   ["cvlc", "--play-and-exit", "--quiet"]) if shutil.which(p[0])), None)
        if not player:
            detail.config(text="No audio player found: sudo apt install mpv", fg=RED)
            return
        if replay_proc[0] and replay_proc[0].poll() is None:
            try:
                replay_proc[0].terminate()
            except OSError:
                pass
        try:
            replay_proc[0] = subprocess.Popen(player + [f], stdin=subprocess.DEVNULL,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            detail.config(text="Replay failed: %s" % e, fg=RED)
            return
        try:
            from transcriber import parse_name, labels
            fr, ts = parse_name(f)
            lab = labels().get(fr, fr)
            when = "%s:%s:%s" % (ts[8:10], ts[10:12], ts[12:14]) if ts else ""
            detail.config(text="Replaying %s %s" % (lab, when), fg=MUTED)
        except Exception:
            detail.config(text="Replaying last transmission", fg=MUTED)

    def toggle_watch(_=None):
        sel = view["sel"]
        if not sel or str(sel).startswith("ap:"):
            info.config(text="Select a contact first, then Watch adds its callsign to the watch list.",
                        fg=MUTED)
            return
        acs, _, _, _ = feed.snapshot()
        a = next((a for a in acs if a["hex"] == sel), None)
        key = ((a.get("flight") or "").strip() if a else "") or sel.upper()
        watch = [str(x) for x in s.get("watch", [])]
        if key.upper() in {w.upper() for w in watch}:
            watch = [w for w in watch if w.upper() != key.upper()]
            info.config(text="%s removed from the watch list." % key, fg=MUTED)
        else:
            watch.append(key)
            info.config(text="%s added to the watch list - you'll hear an alert when it appears." % key,
                        fg=MUTED)
        s["watch"] = watch
        try:
            save_json(SETTINGS_PATH, s)
        except OSError:
            pass

    more_sheet = [None]
    # ---- ATC bingo: a 5x5 card of phrases; squares light up as Whisper hears them
    BINGO_PATH = os.path.join(CACHE_DIR, "bingo.json")
    bingo = {"win": None, "cells": [], "d": None}

    def bingo_load():
        d = load_json(BINGO_PATH, {})
        today = time.strftime("%Y-%m-%d")
        if not isinstance(d, dict) or d.get("date") != today or len(d.get("card", [])) != 25:
            import random
            phrases = [str(x) for x in s.get("bingo_phrases", []) if str(x).strip()]
            rnd = random.Random(today)
            card = bingo_card(phrases, rnd)
            d = {"date": today, "card": card, "hit": [False] * 25, "lines": 0, "heard": {}}
            d["hit"][12] = True   # free centre square
        bingo["d"] = d
        return d

    def bingo_save():
        try:
            save_json(BINGO_PATH, bingo["d"])
        except OSError:
            pass

    def bingo_lines(hit):
        rows = [all(hit[r * 5:(r + 1) * 5]) for r in range(5)]
        cols = [all(hit[c + 5 * r] for r in range(5)) for c in range(5)]
        diag = [all(hit[i * 6] for i in range(5)), all(hit[4 + i * 4] for i in range(5))]
        return sum(rows) + sum(cols) + sum(diag)

    def bingo_hear(text):
        """Called for every new transcript line; marks matching squares, announces a new line."""
        d = bingo["d"] or bingo_load()
        txt = (text or "").lower()
        if not txt:
            return
        changed = False
        for i, ph in enumerate(d["card"]):
            if not d["hit"][i] and re.search(r"\b" + re.escape(ph.lower()) + r"\b", txt):
                d["hit"][i] = True
                d["heard"][str(i)] = time.strftime("%H:%M")
                changed = True
        if changed:
            n = bingo_lines(d["hit"])
            if n > d.get("lines", 0):
                d["lines"] = n
                speak("Bingo!" if n == 1 else "Bingo, %d lines!" % n)
                info.config(text="BINGO - %d line%s on today's card" % (n, "" if n == 1 else "s"), fg=AMBER)
            bingo_save()
            if bingo["win"] and bingo["win"].winfo_exists():
                bingo_draw()

    def bingo_draw():
        d = bingo["d"]
        for i, (lbl, frame) in enumerate(bingo["cells"]):
            hit = d["hit"][i]
            frame.config(bg=T.ACCENT_BG if hit else T.SURFACE_2, highlightbackground=AMBER if hit else LINE)
            lbl.config(bg=frame["bg"], fg=AMBER if hit else TXT)
            when = d["heard"].get(str(i))
            lbl.config(text=d["card"][i] + ("\n" + when if when else ("\nfree" if i == 12 else "")))
        n = sum(d["hit"])
        bingo["status"].config(text="%d of 25 heard  ·  %d line%s" % (n, d["lines"], "" if d["lines"] == 1 else "s"))

    def open_bingo(_=None):
        if bingo["win"] and bingo["win"].winfo_exists():
            bingo["win"].lift()
            return
        d = bingo_load()
        win = tk.Toplevel(root, bg=T.SURFACE)
        win.title("ATC Bingo")
        win.transient(root)
        win.geometry("+%d+%d" % (root.winfo_rootx() + 460, root.winfo_rooty() + 50))
        bingo["win"] = win
        pad = tk.Frame(win, bg=T.SURFACE, padx=T.px(14), pady=T.px(12))
        pad.pack(fill="both", expand=True)
        hdr = tk.Frame(pad, bg=T.SURFACE)
        hdr.pack(fill="x", pady=(0, 8))
        tk.Label(hdr, text="ATC BINGO  ·  " + d["date"], font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left")
        bingo["status"] = tk.Label(hdr, text="", font=F["map"], fg=T.TXT_2, bg=T.SURFACE)
        bingo["status"].pack(side="right")
        grid = tk.Frame(pad, bg=T.SURFACE)
        grid.pack()
        bingo["cells"] = []
        for i in range(25):
            fr = tk.Frame(grid, bg=T.SURFACE_2, highlightthickness=1, highlightbackground=LINE,
                          width=T.px(118), height=T.px(64))
            fr.grid(row=i // 5, column=i % 5, padx=2, pady=2)
            fr.pack_propagate(False)
            lbl = tk.Label(fr, text="", font=F["map"], fg=TXT, bg=T.SURFACE_2, wraplength=T.px(108),
                           justify="center")
            lbl.pack(expand=True)

            def toggle(i=i):
                d["hit"][i] = not d["hit"][i]
                d["heard"].pop(str(i), None)
                d["lines"] = bingo_lines(d["hit"])
                bingo_save()
                bingo_draw()
            fr.bind("<Button-1>", lambda e, t=toggle: t())
            lbl.bind("<Button-1>", lambda e, t=toggle: t())
            bingo["cells"].append((lbl, fr))
        foot = tk.Frame(pad, bg=T.SURFACE)
        foot.pack(fill="x", pady=(10, 0))
        tk.Label(foot, text="Squares light up as Whisper hears the phrase. Tap to mark by ear. New card every day.",
                 font=F["map"], fg=T.TXT_3, bg=T.SURFACE, wraplength=T.px(460), justify="left").pack(side="left")

        def new_card():
            try:
                os.remove(BINGO_PATH)
            except OSError:
                pass
            d2 = bingo_load()
            d.clear()
            d.update(d2)
            bingo["d"] = d     # the cell toggles close over d; keep it the saved/drawn card
            bingo_draw()
        T.btn(foot, "Close", win.destroy, F, padx=10, pady=3, kind="quiet").pack(side="right")
        T.btn(foot, "New card", new_card, F, padx=10, pady=3, kind="quiet").pack(side="right", padx=6)
        win.bind("<Escape>", lambda e: win.destroy())
        bingo_draw()

    root.bind("b", open_bingo)
    root.bind("<F5>", lambda e: reload_settings())

    root.bind("p", replay_last)
    root.bind("w", toggle_watch)

    # ---- "where is it?": speak the selected contact's position relative to you, clock-face style
    my = {"pos": None, "trk": None, "alt_m": None, "t": 0}

    fix_stop = [False]

    def my_fix_thread():
        while not fix_stop[0]:
            try:
                import suite as _suite
                tpv = _suite.gps_fix(timeout=1.5)
                if tpv and tpv.get("mode", 0) >= 2:
                    my["pos"] = (tpv["lat"], tpv["lon"])
                    my["alt_m"] = tpv.get("altMSL", tpv.get("alt"))
                    if (tpv.get("speed") or 0) > 0.8 and tpv.get("track") is not None:
                        my["trk"] = tpv["track"]
                    my["t"] = time.time()
            except Exception:
                pass
            time.sleep(5)

    threading.Thread(target=my_fix_thread, daemon=True).start()

    def bearing(lat1, lon1, lat2, lon2):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dl = math.radians(lon2 - lon1)
        y = math.sin(dl) * math.cos(p2)
        x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    CARDINAL = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]

    def describe(a):
        """Spoken description of contact a from where you stand."""
        _, _, _, rcv = feed.snapshot()
        here = my["pos"] or rcv or (AIRPORTS["KAPA"]["lat"], AIRPORTS["KAPA"]["lon"])
        cs = (a.get("flight") or "").strip() or a["hex"].upper()
        typ = (a.get("t") or "").strip()
        d = dist_nm(here[0], here[1], a["lat"], a["lon"])
        brg = bearing(here[0], here[1], a["lat"], a["lon"])
        alt = alt_ft(a) or 0
        agl = alt - (my["alt_m"] or 1750) * 3.28084
        elev = math.degrees(math.atan2(agl, max(0.1, d) * 6076.0)) if agl > 0 else 0
        if my["trk"] is not None and time.time() - my["t"] < 60:
            rel = (brg - my["trk"] + 360) % 360
            clock = int(round(rel / 30)) % 12 or 12
            where = "%d o'clock" % clock
        else:
            where = "to the " + CARDINAL[int((brg + 22.5) // 45) % 8]
        height = "overhead" if elev > 60 else ("high" if elev > 25 else ("low" if elev > 5 else "on the horizon"))
        if on_ground(a):
            height = "on the ground"
        vr = a.get("baro_rate") or a.get("geom_rate") or 0
        trend = ", climbing" if vr > 300 else (", descending" if vr < -300 else "")
        spoken_cs = " ".join(cs) if cs.isalnum() and len(cs) <= 7 and not cs.isalpha() else cs
        txt = "%s%s, %s, %s miles, %s%s." % (spoken_cs, (", a %s" % typ) if typ else "", where,
                                               "%.0f" % d if d >= 2 else "%.1f" % d, height, trend)
        shown = "%s%s  ·  %s  ·  %.1f nm  ·  %s  ·  %03.0f°%s" % (
            cs, ("  " + typ) if typ else "", where, d, height, brg,
            "" if my["trk"] is not None else "  (no heading: directions are compass points)")
        return txt, shown

    def point_at(_=None):
        sel = view["sel"]
        acs, _, _, rcv = (demo.snapshot() if demo_on[0] else feed.snapshot())
        a = next((a for a in acs if a["hex"] == sel and "lat" in a), None)
        if not a:
            # nothing selected: describe the nearest airborne contact instead
            here = my["pos"] or rcv or (AIRPORTS["KAPA"]["lat"], AIRPORTS["KAPA"]["lon"])
            cands = [x for x in acs if "lat" in x and not on_ground(x)]
            if not cands:
                info.config(text="No airborne contact to point at.", fg=MUTED)
                return
            a = min(cands, key=lambda x: dist_nm(here[0], here[1], x["lat"], x["lon"]))
            view["sel"] = a["hex"]
            redraw_map()
        txt, shown = describe(a)
        info.config(text=shown, fg=TXT)
        info_hold[0] = time.time() + 8
        speak(txt)

    root.bind("t", point_at)

    # ---- sonar: a tick whose pitch follows the nearest contact's altitude and whose rate follows distance
    sonar = {"on": False, "thread": None, "gen": 0}

    def tone_bytes(freq, ms=70, rate=22050, vol=0.35):
        import struct
        n = int(rate * ms / 1000)
        out = bytearray()
        for i in range(n):
            env = min(1.0, i / (rate * 0.005), (n - i) / (rate * 0.02))
            out += struct.pack("<h", int(vol * env * 32767 * math.sin(2 * math.pi * freq * i / rate)))
        return bytes(out)

    def sonar_loop(gen):
        player = ["pacat", "--raw", "--format=s16le", "--rate=22050", "--channels=1", "--stream-name=Sky sonar"] \
            if shutil.which("pacat") else (["aplay", "-q", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-c", "1"]
                                            if shutil.which("aplay") else None)
        while sonar["on"] and sonar["gen"] == gen:
            acs, _, _, rcv = feed.snapshot()
            here = my["pos"] or rcv or (AIRPORTS["KAPA"]["lat"], AIRPORTS["KAPA"]["lon"])
            cands = [a for a in acs if "lat" in a and not on_ground(a) and a.get("seen_pos", 99) < 30]
            if not cands or not player:
                time.sleep(2.0)
                continue
            a = min(cands, key=lambda x: dist_nm(here[0], here[1], x["lat"], x["lon"]))
            d = dist_nm(here[0], here[1], a["lat"], a["lon"])
            alt = alt_ft(a) or 10000
            # pitch: 1,000 ft -> 1,200 Hz, 40,000 ft -> 300 Hz (log); rate: 1 nm -> 0.3 s, 40 nm -> 3 s
            pitch = 300 + 900 * max(0.0, min(1.0, 1 - math.log10(max(alt, 1000) / 1000) / math.log10(40)))
            gap = 0.3 + 2.7 * max(0.0, min(1.0, math.log10(max(d, 1.0)) / math.log10(40)))
            try:
                subprocess.run(player, input=tone_bytes(pitch), stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=3)
            except Exception:
                pass
            time.sleep(gap)

    def toggle_sonar(_=None):
        if not sonar["on"] and sky_mode[0] == "visual":
            info.config(text="Sonar is audio — switch to Voice or Both mode (press V).", fg=MUTED)
            return
        sonar["on"] = not sonar["on"]
        refresh_layers_sheet()
        if sonar["on"]:
            info.config(text="Sonar on: faster ticks = closer, higher pitch = lower altitude. N toggles.", fg=MUTED)
            sonar["gen"] += 1
            sonar["thread"] = threading.Thread(target=sonar_loop, args=(sonar["gen"],), daemon=True)
            sonar["thread"].start()
        else:
            info.config(text="Sonar off.", fg=MUTED)

    root.bind("n", toggle_sonar)
    pass  # action row is built once at the end, after every handler exists

    # ---- state
    def on_button(_=None):
        if ctl.state in ("idle", "error"):
            ctl.submit("start")
        elif ctl.state in ("running", "starting"):
            ctl.submit("stop")

    root.bind("<space>", on_button)

    SKY_KEYS = [("V", "View mode: Map / Voice / Both"), ("C", "Coverage outline (antenna range)"),
                ("G", "Logbook: every aircraft today"), ("Space", "Listen / stop airband"),
                ("+  −", "Zoom map"), ("L", "Cycle basemap"),
                ("R", "Radar overlay"), ("O", "Offline maps"), ("N", "Sonar (nearest contact)"),
                ("H", "History timeline"), ("T", "Spot: speak selected contact"),
                ("W", "Add/remove from watch list"), ("P", "Replay last transmission"),
                ("B", "ATC bingo"), ("F5", "Reload settings"), ("Q / Esc", "Quit")]

    def show_help(_=None):
        T.help_overlay(root, F, "Sky shortcuts", SKY_KEYS,
                       extra="Tap a contact, then T to hear where it is; tap an airport for its METAR. "
                             "The dock has Channels and Alerts tabs. Unusual contacts — military, "
                             "circling, new types — show in Alerts automatically.")

    root.bind("?", show_help)
    root.bind("<F1>", show_help)

    # ---- single action row: primary taps + a More sheet for the rest + Quit
    lbv = {"frame": None, "sort": "first", "job": None}

    def close_logbook(_=None):
        if lbv["job"]:
            root.after_cancel(lbv["job"])
            lbv["job"] = None
        if lbv["frame"] is not None:
            lbv["frame"].destroy()
            lbv["frame"] = None

    def open_logbook(_=None):
        """Every airframe heard today: a plane-spotter's log, kept automatically."""
        if lbv["frame"] is not None:
            close_logbook()
            return
        lb = logbook[0]
        # look up routes for today's airline flights we haven't asked about (polite queue)
        if s.get("route_lookup", True) and not demo_on[0]:
            asked = 0
            for e in sorted(lb.ent.values(), key=lambda e: -e["last"]):
                cs = e["calls"][-1] if e["calls"] else ""
                if SI.route_eligible(cs) and routes.get(cs)[1] == "unknown" and asked < 40:
                    routes.want(cs)
                    asked += 1
        fr = tk.Frame(mapwrap, bg=T.SURFACE, highlightthickness=1, highlightbackground=LINE)
        fr.place(relx=0.02, rely=0.03, relwidth=0.96, relheight=0.94)
        lbv["frame"] = fr
        hdr = tk.Frame(fr, bg=T.SURFACE)
        hdr.pack(fill="x", padx=T.px(12), pady=(T.px(10), T.px(4)))
        tk.Label(hdr, text="LOGBOOK  ·  " + lb.date, font=F["lbl"], fg=T.TXT_3,
                 bg=T.SURFACE).pack(side="left")
        T.btn(hdr, "Close", close_logbook, F, padx=8, pady=2, kind="quiet").pack(side="right")
        T.btn(hdr, "Export CSV", lambda: export_logbook(), F, padx=8, pady=2,
              kind="quiet").pack(side="right", padx=4)
        summ = tk.Label(fr, text="", font=F["smb"], fg=TXT, bg=T.SURFACE, anchor="w")
        summ.pack(fill="x", padx=T.px(12))
        newt = tk.Label(fr, text="", font=F["sm"], fg=GREEN, bg=T.SURFACE, anchor="w")
        newt.pack(fill="x", padx=T.px(12))
        srow = tk.Frame(fr, bg=T.SURFACE)
        srow.pack(fill="x", padx=T.px(12), pady=(T.px(4), T.px(4)))
        tk.Label(srow, text="sort", font=F["map"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left")
        sbtn = {}
        for key, lab in (("first", "first seen"), ("last", "latest"), ("closest", "closest"),
                         ("type", "type")):
            b = T.btn(srow, lab, lambda k=key: (lbv.update(sort=k), fill()), F, padx=6, pady=1,
                      kind="primary" if key == lbv["sort"] else "ghost")
            b.pack(side="left", padx=2)
            sbtn[key] = b
        box = tk.Text(fr, bg=T.SURFACE, fg=TXT, font=F["mono"], bd=0, highlightthickness=0,
                      wrap="none", cursor="arrow")
        box.pack(fill="both", expand=True, padx=T.px(12), pady=(0, T.px(8)))
        box.tag_config("hdr", foreground=T.TXT_3)
        box.tag_config("mil", foreground=AMBER)
        box.tag_config("new", foreground=GREEN)
        box.tag_config("dim", foreground=T.TXT_3)
        live = {a["hex"] for a in feed.snapshot()[0]}

        def fill():
            for k2, b in sbtn.items():
                T.set_btn(b, kind="primary" if k2 == lbv["sort"] else "ghost")
            sm = lb.summary()
            summ.config(text="%d aircraft  ·  %d types  ·  %d military  ·  %d new airframes" % (
                sm["aircraft"], sm["types"], sm["mil"], sm["new_frames"]))
            newt.config(text=("First time in your sky: " + "  ".join(sm["new_types"][:10]))
                        if sm["new_types"] else "")
            box.config(state="normal")
            box.delete("1.0", "end")
            box.insert("end", "%-5s %-8s %-7s %-5s %-11s %7s %6s  %s\n" % (
                "SEEN", "CALL", "TAIL", "TYPE", "ROUTE", "CLOSEST", "TOP", ""), "hdr")
            if not lb.ent:
                box.insert("end", "\nNothing logged yet today. Every aircraft the antenna "
                                  "hears is logged automatically\n(live traffic only - demo "
                                  "and replay are never logged).", "dim")
            for i, e in enumerate(lb.entries(lbv["sort"])):
                cs = e["calls"][-1] if e["calls"] else ""
                rt, _st = routes.get(cs) if SI.route_eligible(cs) else (None, "")
                flags = []
                if e["mil"]:
                    flags.append("MIL")
                if e.get("new_type"):
                    flags.append("NEW TYPE")
                elif e.get("new_frame"):
                    flags.append("new")
                tag = "lb%d" % i
                line = "%-5s %-8s %-7s %-5s %-11s %7s %6s  " % (
                    time.strftime("%H:%M", time.localtime(e["first"])), cs[:8] or "—",
                    (e["reg"] or "")[:7] or "—", (e["type"] or "")[:5] or "—",
                    (SI.route_short(rt).replace(" → ", ">") if rt else "")[:11] or "—",
                    ("%.1fnm" % e["closest"]) if e["closest"] is not None else "—",
                    SI.fl(e["max_alt"]).replace(",", "")[:6] if e["max_alt"] else "—")
                box.insert("end", line, (tag,) + (("dim",) if e["hex"] not in live else ()))
                box.insert("end", " ".join(flags) + "\n",
                           (tag, "mil" if e["mil"] else "new"))
                box.tag_bind(tag, "<Button-1>", lambda ev, h=e["hex"]: lb_pick(h))
            box.config(state="disabled")
            lbv["job"] = root.after(5000, refresh)

        def refresh():
            lbv["job"] = None
            if lbv["frame"] is not None:
                live.clear()
                live.update(a["hex"] for a in feed.snapshot()[0])
                y = box.yview()[0]
                fill()
                box.yview_moveto(y)

        def lb_pick(h):
            if h in live:
                close_logbook()
                select_hex(h)
            else:
                info.config(text="That aircraft is no longer in range", fg=MUTED)
                info_hold[0] = time.time() + 3
        fill()

    def export_logbook():
        lb = logbook[0]
        dest_dir = os.path.join(HOME, "Documents")
        if not os.path.isdir(dest_dir):
            dest_dir = LOGBOOK_DIR
        path = os.path.join(dest_dir, "sky-logbook-%s.csv" % lb.date)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            with open(path, "w") as f:
                f.write(lb.csv())
            msg, col = "Logbook saved: " + path, MUTED
        except OSError as e:
            msg, col = "Couldn't save logbook: %s" % e, RED
        info.config(text=msg, fg=col)
        info_hold[0] = time.time() + 5

    def toggle_demo(_=None):
        demo_on[0] = not demo_on[0]
        rwy_watch.ev.clear()
        if demo_on[0]:
            demo._last = None   # don't fast-forward the sim across time spent off
        detail.config(text="Demo traffic ON - synthetic contacts; nothing is recorded or alerted."
                      if demo_on[0] else "Demo traffic off.",
                      fg=AMBER if demo_on[0] else MUTED)
        redraw_map()

    def open_more():
        if more_sheet[0] and more_sheet[0].winfo_exists():
            more_sheet[0].close()
            more_sheet[0] = None
            return

        def build(body):
            for label, cmd in (("Replay last transmission", replay_last),
                               ("Demo traffic  (show synthetic planes)", toggle_demo),
                               ("Coverage outline  (antenna range, key C)", toggle_coverage),
                               ("Logbook  (every aircraft today, key G)", open_logbook),
                               ("Transcript panel", lambda: toggle_text()), ("ATC bingo", open_bingo),
                               ("Settings", edit_settings), ("Reload settings", reload_settings),
                               ("Event log", toggle_log), ("Shortcuts  (?)", show_help)):
                T.btn(body, label, lambda c=cmd: (more_sheet[0].close(), c()), F, padx=10, pady=5,
                      kind="ghost").pack(fill="x", pady=2)
        more_sheet[0] = T.sheet(more_btn, F, "More", build, side="below")

    # ---- view mode: Map (silent) / Voice (eyes-free) / Both -------------------
    mode_btns = {}

    def set_mode(m, announce=True):
        sky_mode[0] = m
        s["sky_mode"] = m
        try:
            save_json(SETTINGS_PATH, s)
        except Exception:
            pass
        for key, b in mode_btns.items():
            b.config(bg=(T.ACCENT if key == m else T.SURFACE),
                     fg=(T.BG if key == m else T.TXT_2))
        # swap the main pane: tactical map vs the eyes-free voice console
        want_voice = m == "voice"
        if want_voice and not voice_shown[0]:
            mapwrap.pack_forget()
            voicewrap.pack(side="left", fill="both", expand=True)
            voice_shown[0] = True
            render_tx(vtx, 10)
        elif not want_voice and voice_shown[0]:
            voicewrap.pack_forget()
            mapwrap.pack(side="left", fill="both", expand=True)
            voice_shown[0] = False
        if m == "visual":
            if sonar["on"]:
                toggle_sonar()
            if tx_visible[0]:
                toggle_text()
            set_card(True)
            msg = "SCOPE - map + contact card, audio announcements off"
        elif m == "voice":
            set_vdock(True)
            msg = "COMMS - eyes-free console: speech, transcripts and alerts"
        else:
            set_vdock(True)
            if not tx_visible[0]:
                toggle_text()
            msg = "DUAL - radio dock and map together"
        root.after(80, redraw_map)
        if announce:
            info.config(text=msg, fg=MUTED)
            info_hold[0] = time.time() + 4

    def cycle_mode(_=None):
        order = ["both", "visual", "voice"]
        set_mode(order[(order.index(sky_mode[0]) + 1) % 3])

    # the view tabs live in the top bar where they can be seen, not buried in the action row
    tabbar = tk.Frame(top, bg=T.SURFACE)
    tabbar.pack(side="left", padx=(T.px(10), 0))
    for key, label in (("visual", "SCOPE"), ("voice", "COMMS"), ("both", "DUAL")):
        b = tk.Label(tabbar, text=label, font=F["smb"], padx=T.px(6), pady=T.px(4),
                     cursor="hand2", bg=T.SURFACE, fg=T.TXT_2)
        b.pack(side="left", padx=1)
        b.bind("<Button-1>", lambda e, k=key: set_mode(k))
        mode_btns[key] = b
    root.bind("v", cycle_mode)
    root.bind("c", toggle_coverage)
    root.bind("g", open_logbook)
    set_mode(sky_mode[0], announce=False)   # apply saved/initial mode + highlight the control

    for t, cmd in (("Spot", point_at), ("Watch", toggle_watch), ("Hist", toggle_history)):
        T.btn(trow, t, cmd, F, padx=5, pady=3, kind="quiet").pack(side="left")
    T.btn(trow, "Quit", lambda: on_close(), F, padx=5, pady=3, kind="quiet").pack(side="right")
    more_btn = T.btn(trow, "More", open_more, F, padx=5, pady=3, kind="quiet")
    more_btn.pack(side="right", padx=(0, 4))

    def show_state(st, det):
        dev = "H4M" if ctl.device == "hackrf" else "built-in SDR"
        if st == "running":
            air_pill.config(text="Airband", bg=GREEN)
            sec_air.right.config(text=T.spaced(dev))
            T.set_btn(btn, "Stop", "danger")
            detail.config(text="%d channels" % sum(1 for c in s["channels"] if c.get("on")),
                          fg=MUTED)
        elif st == "starting":
            air_pill.config(text="Airband starting", bg=AMBER)
            T.set_btn(btn, "Stop", "danger")
            detail.config(text=det, fg=MUTED)
        elif st == "stopping":
            air_pill.config(text="Airband stopping", bg=AMBER)
            T.set_btn(btn, "Stopping…", "busy")
            detail.config(text=det, fg=MUTED)
        elif st == "error":
            air_pill.config(text="Airband fault", bg=RED)
            T.set_btn(btn, "Listen", "primary")
            detail.config(text=det + " — see Log.", fg=RED)
        else:
            air_pill.config(text="Airband off", bg=DIM)
            sec_air.right.config(text="")
            T.set_btn(btn, "Listen", "primary")
            hs = hackrf_status()
            if adsb_device() == "hackrf":
                txt = {"ready": "ADS-B on the H4M, airband on the built-in SDR. Map stays live.",
                       "wrong_mode": "H4M not in HackRF mode - ADS-B is down until it is.",
                       "absent": "H4M not connected - ADS-B is down. Airband still works."}[hs]
            else:
                txt = {"ready": "H4M ready. The map stays live while you listen.",
                       "wrong_mode": "H4M connected but not in HackRF mode.",
                       "absent": "No H4M. Listening pauses the map."}[hs]
            detail.config(text=txt, fg=MUTED)
            live.clear()
            highlight.clear()
            live_channel[0] = None
            now_lbl.config(text="Idle", fg=T.TXT_3)
            now_sub.config(text="")
            for r in rows:
                draw_row(r)
        if st in ("idle", "error"):
            ui_device[0] = None
        draw_gain()

    def pump():
        try:
            while True:
                ev = ctl.events.get_nowait()
                if ev[0] == "log":
                    logbox.insert("end", ev[1] + "\n")
                    logbox.see("end")
                    if int(logbox.index("end-1c").split(".")[0]) > 500:
                        logbox.delete("1.0", "100.0")
                elif ev[0] == "state":
                    show_state(ev[1], ev[2])
                elif ev[0] == "device":
                    ui_device[0] = ev[1]
                    draw_gain()
                elif ev[0] == "quit_ok":
                    sonar["on"] = False
                    if replay_proc[0] and replay_proc[0].poll() is None:
                        try:
                            replay_proc[0].terminate()   # mpv would keep playing after we exit
                        except OSError:
                            pass
                    # scanner is down, so its last MP3 is closed: give the worker a moment
                    root.after(1500, lambda: (stop_worker(), root.destroy()))
                    return
                elif ev[0] == "taken":
                    detail.config(text="%s took the built-in SDR, so airband stopped." % ev[1],
                                  fg=AMBER)
        except queue.Empty:
            pass
        root.after(100, pump)

    prev = {}
    seen = {"mt": 0.0, "t0": None}
    redraw_sig = [None]

    records = {"d": load_records(), "dirty": False, "saved": 0, "rot": 0, "rot_t": 0}

    def _rec(scope, key, v, cs, better):
        cur = records["d"][scope].get(key)
        if cur is None or better(v, cur["v"]):
            records["d"][scope][key] = {"v": v, "cs": cs, "t": time.time()}
            records["dirty"] = True
            return True
        return False

    def update_records():
        if records["d"].get("date") != time.strftime("%Y-%m-%d"):
            records["d"] = load_records()
        acs, _, status, rcv = feed.snapshot()
        if status != "live":
            return
        here = my["pos"] or rcv or (AIRPORTS["KAPA"]["lat"], AIRPORTS["KAPA"]["lon"])
        air = [a for a in acs if "lat" in a and not on_ground(a) and a.get("seen_pos", 99) < 15]
        new_best = []
        for scope in ("today", "best"):
            for a in air:
                cs = (a.get("flight") or "").strip() or a["hex"].upper()
                gs, alt = a.get("gs"), alt_ft(a)
                d = dist_nm(here[0], here[1], a["lat"], a["lon"])
                if gs and 30 < gs < 1200 and _rec(scope, "fastest", int(gs), cs, lambda n, o: n > o) and scope == "best":
                    new_best.append("fastest")
                if alt and 0 < alt < 70000 and _rec(scope, "highest", int(alt), cs, lambda n, o: n > o) and scope == "best":
                    new_best.append("highest")
                if d < 300 and _rec(scope, "closest", round(d, 2), cs, lambda n, o: n < o) and scope == "best":
                    new_best.append("closest")
                if d <= 3 and alt and _rec(scope, "lowest_overhead", int(alt), cs, lambda n, o: n < o) and scope == "best":
                    new_best.append("lowest_overhead")
                if d < 400 and _rec(scope, "farthest", round(d, 1), cs, lambda n, o: n > o) and scope == "best":
                    new_best.append("farthest")
            if air:
                _rec(scope, "most_contacts", len(air), "", lambda n, o: n > o)
        for a in air:            # live, directly received only - see SI.relayed()
            coverage.add(here[0], here[1], a)
        if logbook[0].date != time.strftime("%Y-%m-%d"):     # midnight: start a new page
            logbook_save(force=True)
            logbook[0] = SI.Logbook(None, logbook[0].life_json())
        for a in acs:
            if a.get("seen", 99) < 30 and (a.get("flight") or "lat" in a or a.get("t")):
                logbook[0].see(dict(a, _mil=is_military(a)), here)
        logbook_save()
        if new_best and records["d"].get("days", 0) >= 1:
            labels = dict((k, l) for k, l, _ in RECORD_LABELS)
            speak("New record: %s." % ", ".join(labels[k].lower() for k in sorted(set(new_best))))
        if (records["dirty"] or coverage.dirty) and time.time() - records["saved"] > 10:
            try:
                os.makedirs(os.path.dirname(RECORDS_PATH), exist_ok=True)
                if records["dirty"]:
                    save_json(RECORDS_PATH, records["d"])
                if coverage.dirty:
                    save_json(COVERAGE_PATH, coverage.to_json())
                    coverage.dirty = False
            except OSError:
                pass
            records["dirty"], records["saved"] = False, time.time()
        # rotate record facts through the info line while nothing is selected
        if view["sel"] is None and time.time() - records["rot_t"] > 6:
            records["rot_t"] = time.time()
            lines = record_lines(records["d"], "today")
            if records["d"].get("days", 0) >= 1:
                lines += record_lines(records["d"], "best")
            if lines:
                records["rot"] = (records["rot"] + 1) % len(lines)
                info.config(text=lines[records["rot"]] + "   ·   tap a contact for details", fg=T.TXT_3)

    ovh_said = {}   # hex -> time we last called it out

    def check_overhead(snap):
        acs, _, status, rcv = snap
        if status != "live" or not s.get("overhead_callout", True) or sky_mode[0] == "visual":
            return
        hp = home_pos(rcv)
        now = time.time()
        for hx in [hx for hx, t in ovh_said.items() if now - t > 1800]:
            del ovh_said[hx]
        for a in acs:
            t = SI.overhead(hp[0], hp[1], a, miss_nm=1.0, within_s=150)
            if t is None or t < 30 or a["hex"] in ovh_said:
                continue
            ovh_said[a["hex"]] = now
            cs, _ = label_for(a)
            af = alt_ft(a)
            speak("Overhead in %s: %s, %s." % (
                "%d minutes" % round(t / 60) if t >= 90 else "%d seconds" % (round(t / 10) * 10),
                cs, ("%s feet" % format(int(round(af, -2)), ",")) if af else "altitude unknown"))

    def poll():
        # ADS-B pill
        _, _, status, _ = feed.snapshot()
        if demo_on[0]:
            adsb_pill.config(text="ADS-B demo", bg=AMBER)
        else:
            adsb_pill.config(text="ADS-B " + {"live": "live", "stale": "paused",
                                              "none": "no data"}[status],
                             bg={"live": GREEN, "stale": AMBER, "none": DIM}[status])
        # airband activity
        if ctl.state == "running":
            if seen["t0"] is None:
                seen["t0"] = time.time()
            st = read_stats()
            try:
                mt = os.path.getmtime(STATS_PATH)
            except OSError:
                mt = 0
            if st is not None and mt != seen["mt"]:
                seen["mt"] = mt
                live.clear()
                for k, v in st.items():
                    if k in prev and v > prev[k]:
                        live.add(k)
                        last_heard[k] = time.time()
                        hh = chan_hist.setdefault(k, [])
                        hh.append(time.time())
                        del hh[:-400]
                prev.clear()
                prev.update(st)
                live_channel[0] = None
                highlight.clear()
                lv = read_levels()
                if live:
                    k = max(live, key=lambda x: last_heard[x])
                    level["db"] = lv.get(k)
                    c = next((c for c in s["channels"] if key_of(c) == k), None)
                    live_channel[0] = c
                    now_lbl.config(text=(c["label"] if c else k), fg=AMBER)
                    now_sub.config(text="%s MHz AM" % k)
                    if c:
                        acs, _, _, _ = feed.snapshot()
                        highlight.update(likely_on_channel(c, acs))
                else:
                    level["db"] = None
                    now_lbl.config(text="Scanning", fg=TXT)
                    if last_heard:
                        k, t = max(last_heard.items(), key=lambda kv: kv[1])
                        c = next((c for c in s["channels"] if key_of(c) == k), None)
                        now_sub.config(text="last %s, %s ago" % ((c["label"] if c else k), ago(t)))
                for r in rows:
                    draw_row(r)
        else:
            prev.clear()
            seen["mt"], seen["t0"] = 0.0, None
            level["db"] = None
        draw_meter()
        if voice_shown[0]:
            v_now.config(text=now_lbl.cget("text"), fg=now_lbl.cget("fg"))
            v_sub.config(text=now_sub.cget("text") or "press Listen to scan")
            draw_vmeter()
        try:
            update_records()
        except Exception:
            pass
        if not demo_on[0]:   # never alert or speak on synthetic traffic
            try:
                check_alerts(feed.snapshot()[0])
            except Exception:
                pass
            try:
                check_overhead(feed.snapshot())
            except Exception:
                pass
        # redraw the map only when something it shows has changed
        sig = (feed.updated, tuple(sorted(live)), tuple(sorted(highlight)), tuple(sorted(heard)),
               view["sel"], ctl.state, int(time.time()) if alerts else 0, basemap.layer,
               metar.updated, int(time.time() // 60) if radar_on[0] else 0, hist["t"],
               int(time.time()) if demo_on[0] else 0)
        if hist["on"] and not hist["drag"]:
            draw_hbar()
        if sig != redraw_sig[0] or view["drag"]:
            redraw_sig[0] = sig
            redraw_map()
        root.after(1000, poll)

    def poll_audio():
        try:
            import suite as _suite
            _suite.reap()
        except Exception:
            pass
        p = worker[0]
        if p and p.poll() is not None:
            worker[0] = None
            if s.get("transcribe") and p.returncode not in (0,):
                try:
                    st_ = json.load(open(os.path.join(CACHE_DIR, "transcriber.json")))
                    why = st_.get("error", "")
                except Exception:
                    why = ""
                ctl.log("Transcriber exited (%s)%s" % (p.returncode, (": " + why) if why else ""))
                detail.config(text="Transcripts unavailable: %s" % (why or "worker exited, see Log"),
                              fg=AMBER)

        def work():
            name = audio_output_name()
            root.after(0, lambda: out_lbl.config(text="♪ " + name[:18]))
        threading.Thread(target=work, daemon=True).start()
        root.after(5000, poll_audio)

    closing = [False]

    def on_close():
        if closing[0]:
            return
        closing[0] = True
        feed.stopped = metar.stopped = fix_stop[0] = True   # polling threads end with the workspace
        save_view()
        logbook_save(force=True)
        routes.save()
        detail.config(text="Shutting down cleanly...")
        ctl.submit("quit")

    root.protocol("WM_DELETE_WINDOW", on_close)
    # in the workstation Esc goes Home and Sky keeps running; standalone it quits
    root.bind("<Escape>", lambda e: root.go_home() if getattr(root, "embedded", False)
              else on_close())
    root.bind("q", lambda e: None if getattr(root, "embedded", False) else on_close())
    root.bind("+", lambda e: zoom(+1))
    root.bind("=", lambda e: zoom(+1))
    root.bind("-", lambda e: zoom(-1))
    if not getattr(root, "embedded", False):      # in the workstation the shell owns these
        signal.signal(signal.SIGTERM, lambda *a: root.after(0, on_close))
        signal.signal(signal.SIGINT, lambda *a: root.after(0, on_close))

    def tick():
        root.after(250, tick)
    tick()

    show_state("idle", "")
    if not ctl.binary:
        show_state("error", "rtl_airband is not installed")
    if ctl.paused_services:
        ctl.log("Plane map was left paused last time (%s)." % ", ".join(ctl.paused_services))
    if ("--start" in sys.argv or "--listen" in sys.argv) and ctl.binary:
        ctl.submit("start")
    if "--radar" in sys.argv and not radar_on[0]:
        toggle_radar()
    if "--history" in sys.argv and not hist["on"]:
        toggle_history()
    pump()
    poll()
    poll_audio()
    start_worker()
    poll_transcripts()
    root.mainloop()


# ---------------------------------------------------------------------------- CLI

def cli_stop():
    s = load_settings()
    pids = pids_named("rtl_airband")
    print("rtl_airband processes:", pids or "none")
    left = kill_pids(pids)
    if left:
        print("Still alive (root-owned?):", left, "-> sudo pkill -9 rtl_airband")
    if s.get("restore_plane_map", True):
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import suite as _suite
            lease = _suite.RtlLease("sky --stop", log=print)
            owner, _pid = _suite.lease_holder()
            if owner and not owner.startswith("Sky"):
                # another live app holds the built-in SDR: restarting readsb now would
                # fight it for the dongle; it restores the map itself when it lets go
                print("Built-in SDR is in use by %s - leaving the plane map to it." % owner)
            else:
                for svc in lease.paused:
                    print("restoring", svc)
                lease._write(owner=None, pid=None)
                lease.release()
        except Exception as e:
            print("Couldn't restore the plane map:", e)
    print("Stopped.")


def cli_status():
    s = load_settings()
    b = shutil.which("rtl_airband")
    ok = lambda x: "OK " if x else "-- "
    print("== Airband")
    print(ok(b), "rtl_airband:", b or "NOT INSTALLED")
    soapy = airband_has_soapy(b)
    print(ok(soapy), "rtl_airband built with SoapySDR:", "yes" if soapy else
          "NO - can't use the H4M (needs a rebuild with SoapySDR)")
    print(ok(pids_named("rtl_airband") == []), "rtl_airband running:",
          pids_named("rtl_airband") or "no")
    print("== H4M")
    hs = hackrf_status()
    print(ok(hs == "ready"), "H4M:", {"ready": "detected in HackRF mode",
                                      "wrong_mode": "plugged in but NOT in HackRF mode",
                                      "absent": "not detected on USB"}[hs])
    f = soapy_finds_hackrf()
    print(ok(f), "SoapySDR sees HackRF:", {True: "yes", False: "NO - install "
          "soapysdr-module-hackrf", None: "SoapySDRUtil not installed"}[f])
    print("== ADS-B")
    print("   readsb radio:", "H4M (HackRF)" if adsb_device() == "hackrf" else "built-in SDR")
    print("   airband radio:", s.get("airband_device", "rtlsdr"))
    for svc in s["sdr_services"]:
        print("   service %-12s %s" % (svc, service_state(svc)))
    found = None
    for src in s["adsb_sources"]:
        try:
            if src.startswith("http"):
                urllib.request.urlopen(src + "/aircraft.json", timeout=2).read()
            else:
                open(os.path.join(src, "aircraft.json")).read()
            found = src
            break
        except Exception:
            continue
    print(ok(found), "aircraft.json:", found or "NOT FOUND (is readsb running?)")
    rc1, _ = run(["sudo", "-n", "-l", "systemctl", "stop", "readsb"])
    rc2, _ = run(["sudo", "-n", "-l", "systemctl", "start", "readsb"])
    print(ok(rc1 == 0 and rc2 == 0), "passwordless readsb stop/start:",
          "yes" if (rc1 == 0 and rc2 == 0) else "no (re-run the suite installer)")
    print("== Audio")
    print("   output:", audio_output_name())


def main():
    ensure_dirs()
    if "--stop" in sys.argv:
        return cli_stop()
    if "--status" in sys.argv:
        return cli_status()
    try:
        lock = open(LOCK_PATH, "w")
    except OSError as e:
        print("Sky: no instance lock (%s) - continuing without it" % e)
        lock = None
    if lock is not None:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("Sky is already open.")
            if shutil.which("wmctrl"):
                subprocess.call(["wmctrl", "-a", "Sky"], stderr=subprocess.DEVNULL)
            return
    run_gui()


if __name__ == "__main__":
    main()
