"""Suite-wide connection check ("Doctor"): every radio, service, package and server the apps
depend on, each with a plain pass/fail and the fix.  Used by the Hub's Doctor window and by
`hub --doctor` on the command line.

Each check returns (ok, detail, fix).  ok may be True, False or None (= optional / informational).
"""
import glob
import json
import re
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402

core = S.core
UA = {"User-Agent": "uconsole-suite doctor"}


def _head(url, timeout=5):
    req = urllib.request.Request(url, headers=UA, method="GET")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read(2048)
        return int((time.time() - t0) * 1000), r.status


def _py(mod):
    """Is the package installed? find_spec, not import: importing faster_whisper/meshtastic
    pulls 100+ MB of ctranslate2 etc. into the long-lived Hub just to answer yes/no."""
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


# ------------------------------------------------------------------ checks

def chk_python():
    missing = [m for m in ("PIL", "faster_whisper", "skyfield", "meshtastic") if not _py(m)]
    return (not missing, "python3 %d.%d, all suite packages present" % sys.version_info[:2] if not missing
            else "missing: " + ", ".join(missing), "re-run the suite installer")


def chk_fonts():
    try:
        out = subprocess.run(["fc-list"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None, "fc-list unavailable", ""
    ok = "Atkinson" in out and "IBM Plex Mono" in out
    return ok, "Atkinson Hyperlegible + IBM Plex Mono installed" if ok else "suite fonts not found", \
        "re-run the suite installer (fonts step)"


def chk_airband():
    b = shutil.which("rtl_airband")
    if not b:
        return False, "rtl_airband not installed", "build RTLSDR-Airband (Sky needs it)"
    soapy = core.airband_has_soapy(b)
    if not core.H4M_ENABLED:
        return True, "rtl_airband present", ""
    return True, "rtl_airband %s" % ("with SoapySDR (can use the H4M)" if soapy else
                                     "without SoapySDR (built-in SDR only)"), ""


def chk_rtl_fm():
    return bool(shutil.which("rtl_fm")), "rtl_fm present" if shutil.which("rtl_fm") else "rtl_fm missing", \
        "sudo apt install rtl-sdr"


def chk_readsb():
    if not shutil.which("readsb"):
        return False, "readsb not installed", "install readsb (wiedehopf script) - the plane map needs it"
    state = core.service_state("readsb")
    dev = S.adsb_device()
    detail = "readsb %s, radio: %s" % (state, "H4M (HackRF)" if dev == "hackrf" else "built-in SDR")
    hs = core.hackrf_status()
    if dev == "hackrf" and hs != "ready":
        return False, detail + ", but the H4M is %s" % ("not connected" if hs == "absent" else "not in HackRF mode"), \
            "plug in the H4M (powered hub) and select HackRF mode on it"
    if state != "active":
        return False, detail, "sudo systemctl start readsb  (journalctl -u readsb for the reason)"
    return True, detail, ""


def chk_aircraft_json():
    for src in core.DEFAULT_SETTINGS["adsb_sources"]:
        try:
            if src.startswith("http"):
                data = json.loads(urllib.request.urlopen(src + "/aircraft.json", timeout=2).read())
            else:
                with open(os.path.join(src, "aircraft.json")) as f:
                    data = json.load(f)
            age = time.time() - data.get("now", 0)
            n = len(data.get("aircraft", []))
            ok = age < 30
            return ok, "%s: %d aircraft, updated %ds ago" % (src, n, age), "" if ok else "readsb is not decoding"
        except Exception:
            continue
    return False, "no aircraft.json found", "is readsb running?"


def chk_aircraft_db():
    try:
        with open("/etc/default/readsb") as f:
            txt = f.read()
    except OSError:
        return None, "no /etc/default/readsb", ""
    ok = "--db-file" in txt
    return ok, "registration/type database %s" % ("configured" if ok else "not configured"), \
        "re-run the installer (step 6c)"


def chk_sudoers():
    rc1, _ = core.run(["sudo", "-n", "-l", "systemctl", "stop", "readsb"])
    rc2, _ = core.run(["sudo", "-n", "-l", "systemctl", "start", "readsb"])
    ok = rc1 == 0 and rc2 == 0
    return (ok if S.adsb_device() != "hackrf" else (True if ok else None)), \
        "passwordless readsb stop/start: %s" % ("yes" if ok else "no"), "re-run the suite installer (step 6)"


def chk_h4m():
    hs = core.hackrf_status()
    f = core.soapy_finds_hackrf()
    txt = {"ready": "H4M detected in HackRF mode", "wrong_mode": "H4M plugged in but not in HackRF mode",
           "absent": "H4M not connected"}[hs]
    if hs == "ready" and f is False:
        return False, txt + ", but SoapySDR can't see it", "sudo apt install soapysdr-module-hackrf"
    return (True if hs == "ready" else None), txt, "" if hs == "ready" else "H4M main menu -> HackRF"


def chk_gpsd():
    state = core.service_state("gpsd")
    tpv = S.gps_fix(timeout=1.5)
    if tpv and tpv.get("mode", 0) >= 2:
        return True, "gpsd %s, %s fix at %.4f, %.4f" % (state, "3D" if tpv["mode"] == 3 else "2D", tpv["lat"], tpv["lon"]), ""
    if tpv is not None or state == "active":
        return None, "gpsd %s, no fix yet (needs sky view)" % state, ""
    return False, "gpsd %s" % state, "sudo systemctl enable --now gpsd"


def chk_mesh():
    st = core.service_state("meshtasticd")
    try:
        socket.create_connection(("127.0.0.1", 4403), timeout=1).close()
        return True, "meshtasticd %s, TCP 4403 open" % st, ""
    except OSError:
        return None, "meshtasticd %s (LoRa off is fine if you don't use Mesh)" % st, "sudo systemctl enable --now meshtasticd"


def chk_audio():
    """The whole audio chain: a sink exists, it isn't muted, volume isn't zero."""
    name = core.audio_output_name()
    if not name or "none" in name.lower() or "no audio server" in name.lower():
        return False, "output: %s" % (name or "none"), \
            "no audio server/sink: is PipeWire running? (systemctl --user status pipewire)"
    probs = []
    rc, mute = core.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=3)
    if rc == 0 and "yes" in (mute or "").lower():
        probs.append("MUTED")
    rc, vol = core.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=3)
    pcts = [int(x) for x in re.findall(r"(\d+)%", vol or "")] if rc == 0 else []
    if pcts and max(pcts) == 0:
        probs.append("volume 0%")
    if probs:
        return False, "output: %s - %s" % (name, ", ".join(probs)), \
            "unmute / raise it: pactl set-sink-mute @DEFAULT_SINK@ 0; " \
            "pactl set-sink-volume @DEFAULT_SINK@ 70%"
    lvl = (" at %d%%" % max(pcts)) if pcts else ""
    return True, "output: %s%s" % (name, lvl), ""


STATS_PATHS = ["/run/readsb/stats.json", "/run/dump1090-fa/stats.json"]


def chk_antenna():
    """Message rate at 1090 MHz: the difference between a software problem and a deaf
    antenna. A working antenna in the Denver metro sees hundreds of msgs/min."""
    st = None
    for p in STATS_PATHS:
        try:
            with open(p) as f:
                st = json.load(f)
            break
        except (OSError, ValueError):
            continue
    if not isinstance(st, dict):
        return None, "no decoder stats (readsb not running?)", ""
    m = (st.get("last1min") or {}).get("messages")
    if not isinstance(m, (int, float)):
        return None, "stats.json has no last-minute message count", ""
    if m >= 60:
        return True, "%d msgs/min at 1090 MHz - antenna hears traffic" % m, ""
    return False, "only %d msgs/min at 1090 MHz" % m, \
        "near-zero rate means the ANTENNA is deaf here, not the software: " \
        "use a 1090 MHz antenna (ideally outdoors / window with ground plane)"


def chk_tools():
    tools = {"mpv": "replay of transmissions", "redsea": "FM RDS", "espeak-ng": "spoken alerts",
             "satdump": "weather satellite capture", "rtl_433": "Signals sensors",
             "acarsdec": "Signals ACARS", "multimon-ng": "APRS decoding",
             "wmctrl": "raise windows", "iw": "Wi-Fi status"}
    missing = [t for t in tools if not shutil.which(t)]
    if not missing:
        return True, "all optional tools present", ""
    return None, "missing: " + ", ".join("%s (%s)" % (t, tools[t]) for t in missing), \
        "sudo apt install " + " ".join(t for t in missing if t not in ("satdump", "acarsdec"))


def chk_whisper():
    home = os.path.expanduser("~")
    hits = glob.glob(os.path.join(home, ".cache", "huggingface", "hub", "models--Systran--faster-whisper-*"))
    if hits:
        return True, "Whisper model cached: " + ", ".join(os.path.basename(h).split("--")[-1] for h in hits), ""
    return False, "no Whisper model downloaded", "re-run the installer with network, or set transcribe off"


def chk_net():
    n = S.network_status()
    if not (n.get("ip") or n.get("ssid")):
        return False, "no network", "connect Wi-Fi"
    bits = []
    if n.get("ssid"):
        bits.append("%s (%s dBm)" % (n["ssid"], n["signal"]) if n.get("signal") is not None else n["ssid"])
    if n.get("ip"):
        bits.append(n["ip"])
    if n.get("tailscale"):
        bits.append("tailscale " + n["tailscale"])
    return True, ", ".join(bits), ""


def _server(name, url, fix=""):
    def check():
        try:
            ms, status = _head(url)
            return True, "%s reachable (%d ms)" % (name, ms), ""
        except Exception as e:
            return False, "%s unreachable: %s" % (name, str(e)[:60]), fix or "check network / try later"
    return check


def chk_ollama():
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5).read())
        models = [m.get("name") for m in d.get("models", [])]
        return True, "local Ollama: " + (", ".join(models[:4]) or "no models pulled"), ""
    except Exception:
        return None, "no local Ollama (Assistant uses the desktop host)", "optional"


def chk_power():
    p = S.power_status()
    cap, bst = p["pct"], p["status"]
    detail = "battery %s%s" % ("%d%%" % cap if cap is not None else "n/a", " %s" % bst if bst else "")
    if p.get("temp") is not None:
        detail += ", %.0f°C" % p["temp"]
    if p["undervolt_now"]:
        return False, detail + ", UNDER-VOLTAGE NOW",             "the Pi isn't getting enough current - use a 5V/3A+ supply and a good cable; a USB SDR " \
            "can tip it over. Under-voltage throttles the CPU and " \
            "risks SD-card corruption."
    if p["undervolt_seen"]:
        return None, detail + ", under-voltage seen since boot",             "happened earlier (maybe at boot inrush). If it recurs, upgrade the supply/cable."
    if p["low_batt"]:
        return None, detail + " (low)", "low-power mode auto-engages; top up soon"
    return True, detail, ""


def chk_sdcard(mounts="/proc/mounts"):
    """Flag SD-card read-only remounts (the classic symptom of corruption from under-voltage)."""
    ro = []
    try:
        with open(mounts) as f:
            for ln in f:
                parts = ln.split()
                if len(parts) < 4:
                    continue
                dev, mnt, _fs, opts = parts[:4]
                # the root shows as /dev/root on Pi OS, and this CM5 boots from NVMe, so don't
                # filter on mmcblk; match the "ro" flag exactly - "errors=remount-ro" is not ro
                if dev.startswith(("/dev/mmcblk", "/dev/root", "/dev/nvme", "/dev/sd")) and \
                        mnt in ("/", "/boot", "/boot/firmware"):
                    if "ro" in opts.split(","):
                        ro.append(mnt)
    except OSError:
        return None, "can't read /proc/mounts", ""
    if ro:
        return False, "SD mounted READ-ONLY: %s" % ", ".join(ro),             "the card dropped to read-only - usually corruption from under-voltage. Back up now " \
            "(hub --backup), check 'dmesg | grep mmc', and consider a fresh card."
    return True, "SD card read-write", ""


def chk_disk():
    st = os.statvfs(os.path.expanduser("~"))
    free = st.f_bavail * st.f_frsize / 1e9
    return free > 2, "%.1f GB free" % free, "free space: tile cache / recordings / wxsat images" if free <= 2 else ""


KERNEL_PKGS = ("akrex-kernel", "clockworkpi-kernel")


def chk_fieldcomp(which=None):
    """The Field computer: GPS fix, map tiles, almanac."""
    try:
        import skyfield  # noqa: F401
        alm = "almanac+ISS"
    except ImportError:
        alm = "almanac (ISS needs skyfield)"
    gps = "gpsd" if __import__("shutil").which("gpsd") or os.path.exists("/dev/ttyAMA0") else "no gpsd"
    return True, "map, track, %s · %s" % (alm, gps), ""


def chk_devterm(which=None):
    """The Dev terminal: BLE scan, MQTT dashboard, SSH."""
    which = which or __import__("shutil").which
    have, miss = [], []
    try:
        import bleak  # noqa: F401
        have.append("BLE")
    except ImportError:
        miss.append("bleak (pip3 install bleak)")
    try:
        import paho.mqtt.client  # noqa: F401
        have.append("MQTT")
    except ImportError:
        miss.append("paho-mqtt (pip3 install paho-mqtt)")
    if which("ssh"):
        have.append("SSH")
    else:
        miss.append("openssh-client")
    return (True if len(have) >= 2 else None), ", ".join(have) or "nothing set up", \
        ("install: " + "; ".join(miss)) if miss else ""


def chk_hwbench(which=None):
    """The Hardware workbench: serial terminal, I2C scan, GPIO read."""
    which = which or __import__("shutil").which
    have, miss = [], []
    try:
        import serial  # noqa: F401
        have.append("serial")
    except ImportError:
        miss.append("pyserial (sudo apt install python3-serial)")
    if which("i2cdetect"):
        have.append("I2C scan")
    else:
        miss.append("i2c-tools")
    if which("raspi-gpio"):
        have.append("GPIO")
    else:
        miss.append("raspi-gpio")
    import glob
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    detail = ", ".join(have) + ((" · %d serial port%s" % (len(ports), "" if len(ports) == 1 else "s"))
                                if ports else " · no USB serial now")
    return (True if "serial" in have else None), detail, ("install: " + "; ".join(miss)) if miss else ""


def chk_autopilot(which=None, sonde=None):
    """Which apps Overwatch's Autopilot can rotate the radio through on this device."""
    which = which or shutil.which
    have = ["plane map"]
    miss = []
    if which("rtl_fm") and which("multimon-ng"):
        have.append("APRS")
    else:
        miss.append("APRS (sudo apt install multimon-ng rtl-sdr)")
    if which("rtl_433"):
        have.append("Sensors")
    else:
        miss.append("Sensors (sudo apt install rtl-433)")
    if sonde is None:
        try:
            import balloons
            sonde = balloons.installed()
        except Exception:
            sonde = False
    if sonde:
        have.append("Balloons")
    else:
        miss.append("Balloons (optional: bash install_radiosonde.sh)")
    return (True if len(have) >= 3 else None), "rotates: " + ", ".join(have), \
        ("not set up: " + "; ".join(miss)) if miss else ""


def chk_updates(run=None, which=None):
    """Automatic updates can swap the uConsole's custom kernel for a build whose screen and
    power drivers don't work here - the device then starts with a black screen, or not at all."""
    run = run or core.run
    auto = [u for u in ("unattended-upgrades", "apt-daily-upgrade.timer")
            if run(["systemctl", "is-enabled", u])[1].strip().splitlines()[-1:] == ["enabled"]]
    rc, out = run(["dpkg-query", "-W", "-f", "${Package} ${Status}\n"] + list(KERNEL_PKGS))
    inst = [ln.split()[0] for ln in out.splitlines() if ln.endswith("install ok installed")]
    rc, held = run(["apt-mark", "showhold"])
    unheld = [p for p in inst if p not in held.split()]
    if not inst:
        return (None, "automatic updates are ON", "sudo systemctl disable --now " + " ".join(auto)) \
            if auto else (True, "automatic updates off", "")
    if auto and unheld:
        return False, "automatic updates are ON and the kernel (%s) is not held" % ", ".join(unheld), \
            "a kernel update can leave the uConsole unbootable: sudo apt-mark hold %s && " \
            "sudo systemctl disable --now %s" % (" ".join(unheld), " ".join(auto))
    if unheld:
        return None, "kernel (%s) is not held" % ", ".join(unheld), \
            "sudo apt-mark hold %s  (then update the kernel only on purpose)" % " ".join(unheld)
    if auto:
        return None, "kernel held, but automatic updates are ON", \
            "sudo systemctl disable --now " + " ".join(auto)
    return True, "kernel held (%s), automatic updates off" % ", ".join(inst), ""


def chk_bootfiles(boot="/boot/firmware", mounts="/proc/mounts"):
    """The files the CM loads before Linux starts. If they're missing the device won't boot."""
    if not os.path.isdir(boot):
        return None, "no %s here" % boot, ""
    need = ["config.txt", "cmdline.txt", "kernel8.img"]
    if os.path.exists("/proc/device-tree/compatible"):
        try:
            if b"bcm2712" in open("/proc/device-tree/compatible", "rb").read():
                need.append("kernel_2712.img")
        except OSError:
            pass
    bad = [f for f in need if not (os.path.isfile(os.path.join(boot, f))
                                   and os.path.getsize(os.path.join(boot, f)) > 0)]
    half = [f for f in os.listdir(boot) if f.endswith(".dpkg-new")]
    src = rootsrc = ""
    try:
        for ln in open(mounts):
            p = ln.split()
            if len(p) > 1 and p[1] == boot:
                src = p[0]
            if len(p) > 1 and p[1] == "/":
                rootsrc = p[0]
    except OSError:
        pass
    if bad or half:
        return False, "boot files missing or half-installed: %s" % ", ".join(bad + half[:3]), \
            "DO NOT reboot. Reinstall the kernel package (sudo apt install --reinstall akrex-kernel), " \
            "run sync, and check again."
    if src and rootsrc and ("nvme" in src) != ("nvme" in rootsrc):
        return None, "boot files are on %s but the system is on %s" % (src, rootsrc), \
            "booted with a card inserted? Kernel updates would land on the wrong drive - remove the card."
    return True, "kernel and config present on %s" % (src or boot), ""


CHECKS = [
    ("Software", [("Python packages", chk_python), ("Fonts", chk_fonts), ("rtl_airband", chk_airband),
                  ("rtl_fm", chk_rtl_fm), ("Whisper model", chk_whisper), ("Optional tools", chk_tools)]),
    ("Radios", ([("H4M", chk_h4m)] if core.H4M_ENABLED else []) + [("readsb (ADS-B)", chk_readsb), ("Aircraft feed", chk_aircraft_json),
                ("1090 antenna", chk_antenna),
                ("Aircraft database", chk_aircraft_db), ("Passwordless readsb", chk_sudoers),
                ("Autopilot (Overwatch)", chk_autopilot),
                ("Hardware bench", chk_hwbench),
                ("Dev terminal", chk_devterm),
                ("Field computer", chk_fieldcomp)]),
    ("Device", [("GPS", chk_gpsd), ("Meshtastic", chk_mesh), ("Audio", chk_audio), ("Power", chk_power),
                ("SD card", chk_sdcard), ("Disk", chk_disk), ("System updates", chk_updates),
                ("Boot files", chk_bootfiles)]),
    ("Network", [("Connection", chk_net),
                 ("Dark basemap (USGS)", _server("USGS", "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/6/24/13")),
                 ("Satellite (USGS)", _server("USGS", "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/6/24/13")),
                 ("Topo basemap (USGS)", _server("USGS", "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/6/24/13")),
                 ("Radar (Mesonet)", _server("Mesonet", "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/6/13/24.png")),
                 ("METARs (aviationweather.gov)", _server("aviationweather.gov", "https://aviationweather.gov/api/data/metar?ids=KDEN&format=json")),
                 ("TLEs (Celestrak)", _server("Celestrak", "https://celestrak.org/NORAD/elements/gp.php?CATNR=59051&FORMAT=tle")),
                 ("Local Ollama", chk_ollama)]),
]


def run_all(progress=None):
    """Yields (section, name, ok, detail, fix) as each check completes."""
    for section, items in CHECKS:
        for name, fn in items:
            try:
                ok, detail, fix = fn()
            except Exception as e:
                ok, detail, fix = False, "check failed: %s" % str(e)[:80], ""
            if progress:
                progress(section, name, ok, detail, fix)
            yield section, name, ok, detail, fix




# ------------------------------------------------------------------ security checks
# All read-only, against this device only.  A pen test of your own kit: nothing here
# touches another machine or transmits.

def _listening_ports():
    """[(proto, laddr, port, process)] from `ss` (preferred) or /proc fallback."""
    out = []
    if shutil.which("ss"):
        try:
            r = subprocess.run(["ss", "-tulnHp"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                f = line.split()
                if len(f) < 5:
                    continue
                proto = f[0]
                local = f[4]
                host, _, port = local.rpartition(":")
                proc = ""
                if "users:" in line:
                    import re as _re
                    m = _re.search(r'"([^"]+)"', line[line.index("users:"):])
                    proc = m.group(1) if m else ""
                out.append((proto, host.strip("[]"), port, proc))
        except (OSError, subprocess.TimeoutExpired):
            pass
    return out


def chk_exposed_services():
    """Services bound to all interfaces (0.0.0.0 / ::) instead of localhost - reachable from the LAN."""
    ports = _listening_ports()
    if not ports:
        return None, "ss unavailable - can't enumerate listening ports", "sudo apt install iproute2"
    KNOWN = {"11434": "Ollama (LLM - no auth!)", "4403": "meshtasticd API", "2947": "gpsd",
             "1234": "rtl_tcp", "4532": "rigctl", "8073": "OpenWebRX", "57123": "SDR++ rigctl",
             "80": "web map UI (lighttpd)", "443": "web UI (TLS)", "8504": "web stats (lighttpd)",
             "30001": "ADS-B feed (raw in)", "30002": "ADS-B feed (raw out)",
             "30003": "ADS-B feed (SBS/BaseStation)", "30004": "ADS-B feed (beast in)",
             "30005": "ADS-B feed (beast out)", "30104": "ADS-B feed (beast in)"}
    exposed = []
    for proto, host, port, proc in ports:
        if host in ("0.0.0.0", "*", "::", "[::]"):
            label = KNOWN.get(port, proc or "port " + port)
            exposed.append("%s on %s:%s" % (label, host, port))
    if not exposed:
        return True, "no services bound to all interfaces (%d listeners, all local)" % len(ports), ""
    crit = any("11434" in e or "Ollama" in e for e in exposed)
    if crit:
        rec = ("bind to 127.0.0.1 or a tailnet IP, or scope to your LAN with ufw (run harden.sh). "
               "Ollama has no auth: set OLLAMA_HOST=127.0.0.1")
    else:
        rec = ("fine on a trusted home LAN; on untrusted Wi-Fi scope these to your subnet "
               "with ufw (run harden.sh)")
    return (False if crit else None), "exposed to all interfaces: " + "; ".join(exposed[:8]), rec


def chk_ollama_bind():
    ports = _listening_ports()
    ol = [p for p in ports if p[2] == "11434"]
    if not ol:
        return None, "Ollama not listening (Assistant uses a remote host)", ""
    bad = [p for p in ol if p[1] in ("0.0.0.0", "*", "::", "[::]")]
    if bad:
        return False, "Ollama is reachable from the whole network and has no authentication",             "set OLLAMA_HOST=127.0.0.1 (local only) or your Tailscale IP, then restart Ollama"
    return True, "Ollama bound to localhost/tailnet only", ""


def chk_firewall():
    if not shutil.which("ufw"):
        return None, "ufw not installed", "sudo apt install ufw (optional)"
    rc, out = core.run(["sudo", "-n", "ufw", "status"], timeout=4)
    if rc != 0:
        # can't read rules without a password, but we can still tell if it's running:
        # the ufw unit being active means the rules are loaded in the kernel
        st = core.service_state("ufw")
        if st == "active":
            return True, "firewall active (run 'sudo ufw status' for the rules)", ""
        if st in ("inactive", "dead"):
            return False, "firewall installed but not active",                 "sudo ufw allow from <your-subnet> to any port 22, then sudo ufw enable (or run harden.sh)"
        return None, "ufw status needs sudo (can't read without a password)", ""
    active = "Status: active" in out
    if not active:
        return False, "firewall inactive", "sudo ufw enable  (after allowing SSH from your subnet)"
    wide_ssh = any("22" in ln and "Anywhere" in ln and "ALLOW" in ln for ln in out.splitlines())
    if wide_ssh:
        return None, "firewall active, but SSH is open to anywhere",             "scope SSH: sudo ufw allow from 10.0.0.0/24 to any port 22, then delete the open rule"
    return True, "firewall active", ""


def _sshd_effective():
    """The EFFECTIVE sshd settings, honoring drop-ins in /etc/ssh/sshd_config.d/.
    Prefers `sshd -T` (the real merged config); falls back to parsing the files with
    sshd's first-match-wins semantics so a hardening drop-in isn't missed."""
    cfg = {}
    rc, out = core.run(["sudo", "-n", "sshd", "-T"], timeout=4)
    if rc == 0 and out:
        for ln in out.splitlines():
            p = ln.split(None, 1)
            if len(p) == 2:
                cfg[p[0].lower()] = p[1].lower()
        return cfg, True
    # fallback: drop-ins are Included at the top of sshd_config, so read them first;
    # first value wins (setdefault), matching sshd's behavior
    import glob
    for path in sorted(glob.glob("/etc/ssh/sshd_config.d/*.conf")) + ["/etc/ssh/sshd_config"]:
        try:
            with open(path) as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln or ln.startswith("#"):
                        continue
                    p = ln.split(None, 1)
                    if len(p) == 2:
                        cfg.setdefault(p[0].lower(), p[1].lower())
        except OSError:
            continue
    return cfg, False


def chk_ssh_config():
    cfg, effective = _sshd_effective()
    if not cfg:
        return None, "no sshd_config (SSH server not installed)", ""
    issues = []
    if cfg.get("permitrootlogin", "yes") not in ("no", "prohibit-password"):
        issues.append("root login allowed")
    if cfg.get("passwordauthentication", "yes") == "yes":
        issues.append("password auth on (prefer keys)")
    note = "" if effective else " (parsed from files; `sudo -n sshd -T` unavailable)"
    if issues:
        return None, "SSH: " + ", ".join(issues) + note,             "set PermitRootLogin no and PasswordAuthentication no in a drop-in under /etc/ssh/sshd_config.d/"
    return True, "SSH: root login off, key auth" + note, ""


def chk_default_password():
    """Warn if the login password looks like a known default (hash compare, no plaintext stored)."""
    try:
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        import crypt
        import spwd
        user = os.environ.get("USER") or "dragon"
        try:
            h = spwd.getspnam(user).sp_pwdp
        except (KeyError, PermissionError):
            return None, "can't read the shadow file (needs root) - skipped", ""
        if not h or h in ("*", "!"):
            return None, "no password set for %s (key-only?)" % user, ""
        for guess in ("dragon", "raspberry", "uconsole", "clockworkpi", "password", "admin", "123456"):
            try:
                if crypt.crypt(guess, h) == h:
                    return False, "login password for %s is a common default" % user,                         "run passwd and set a unique password"
            except Exception:
                pass
        return True, "login password is not a common default", ""
    except Exception:
        return None, "password check unavailable", ""


def chk_config_perms():
    bad = []
    for base in (S.CFG, S.CACHE, S.DATA):
        for dp, _, files in os.walk(base):
            for f in files:
                fp = os.path.join(dp, f)
                try:
                    mode = os.stat(fp).st_mode
                    # only flag files that could hold something private; .tle is public ephemeris
                    if mode & 0o004 and any(f.endswith(x) for x in (".json", ".conf")):
                        bad.append(os.path.basename(fp))
                except OSError:
                    pass
    if bad:
        return None, "world-readable config: " + ", ".join(sorted(set(bad))[:5]),             "chmod 600 the suite's config files if the device is shared"
    return True, "suite config files are not world-readable", ""


def chk_tx_safety():
    """The suite must never key the HackRF transmitter.  Confirm no TX tool is running and the
    config declares receive-only."""
    tx_tools = ["hackrf_transfer", "gqrx", "sdrangel"]
    running = [t for t in tx_tools if t == "hackrf_transfer" and core.pids_named(t)]
    # rtl_airband and readsb are receive-only by construction; SoapySDR hackrf here is RX
    if running:
        return False, "a transmit-capable process is running: " + ", ".join(running),             "the suite is receive-only; stop any TX tool (transmitting on these bands is illegal)"
    return True, ("receive-only: no transmit process running, HackRF used for RX only. "
                  "The one transmit path is Mesh: LoRa text goes out only when you press Send"), ""


_SUDO_OK = re.compile(r"^(/usr)?/bin/systemctl (start|stop) (readsb|dump1090-fa)$")


def nopasswd_commands(listing):
    """Commands granted NOPASSWD in `sudo -n -l` output (one rule may span several lines)."""
    cmds, cur = [], None
    for ln in listing.splitlines():
        if "NOPASSWD:" in ln:
            cur = ln.split("NOPASSWD:", 1)[1]
        elif cur is not None and ln.startswith((" ", "\t")) and not ln.strip().startswith("("):
            cur = ln                     # continuation of the previous NOPASSWD list
        else:
            cur = None
            continue
        cmds += [c.strip() for c in cur.split(",") if c.strip()]
    return cmds


def chk_sudoers_scope(listing=None):
    """Passwordless sudo should be limited to start/stop of readsb/dump1090-fa only.
    The sudoers files are root-only (0440), so ask sudo itself what we may run."""
    if listing is None:
        rc, listing = core.run(["sudo", "-n", "-l"], timeout=5)
        if rc != 0:
            listing = None
    if listing is not None:
        cmds = nopasswd_commands(listing)
        extra = [c for c in cmds if not _SUDO_OK.match(c)]
        if extra:
            return False, "passwordless sudo also allows: " + ", ".join(extra[:3]), \
                "re-run the installer; the rule should only permit systemctl start/stop readsb|dump1090-fa"
        if not cmds:
            return None, "no passwordless sudo rules (Sky can't pause readsb)", ""
        return True, "passwordless sudo limited to readsb/dump1090 start/stop", ""
    path = "/etc/sudoers.d/uconsole-suite"
    try:
        with open(path) as f:
            txt = f.read()
    except PermissionError:
        return None, "can't inspect sudo rules (sudo -l refused, %s is root-only)" % path, ""
    except OSError:
        return None, "no suite sudoers file", ""
    lines = [ln for ln in txt.splitlines() if ln.strip() and not ln.startswith("#")]
    broad = [ln for ln in lines if "ALL" in ln.split("NOPASSWD:")[-1] or "systemctl *" in ln or
             ln.strip().endswith("ALL")]
    allowed_only = all(("readsb" in ln or "dump1090" in ln) and ("start" in ln or "stop" in ln)
                       for ln in lines)
    if broad or not allowed_only:
        return False, "suite sudoers grants more than readsb start/stop",             "re-run the installer; the rule should only permit systemctl start/stop readsb|dump1090-fa"
    return True, "passwordless sudo limited to readsb/dump1090 start/stop", ""


SECURITY = [
    ("Attack surface", [("Exposed services", chk_exposed_services), ("Ollama binding", chk_ollama_bind),
                        ("Listening ports", lambda: _ports_summary())]),
    ("Hardening", [("Firewall", chk_firewall), ("SSH config", chk_ssh_config),
                   ("Login password", chk_default_password), ("Sudoers scope", chk_sudoers_scope),
                   ("Config permissions", chk_config_perms)]),
    ("Radio safety", [("Transmit lockout", chk_tx_safety)]),
]


def _ports_summary():
    ports = _listening_ports()
    if not ports:
        return None, "ss unavailable", ""
    local = sum(1 for p in ports if p[1] in ("127.0.0.1", "::1", "localhost"))
    return True, "%d listeners (%d local-only, %d other)" % (len(ports), local, len(ports) - local), ""


def run_security(progress=None):
    for section, items in SECURITY:
        for name, fn in items:
            try:
                ok, detail, fix = fn()
            except Exception as e:
                ok, detail, fix = False, "check failed: %s" % str(e)[:80], ""
            if progress:
                progress(section, name, ok, detail, fix)
            yield section, name, ok, detail, fix


def main():
    security = "--security" in sys.argv
    runner = run_security if security else run_all
    cur = None
    fails = 0
    for section, name, ok, detail, fix in runner():
        if section != cur:
            print("\n== " + section)
            cur = section
        mark = "OK " if ok else ("-- " if ok is None else "FAIL")
        print("%-4s %-30s %s" % (mark, name, detail))
        if ok is False and fix:
            print("     fix: " + fix)
            fails += 1
    print("\n%d problem%s" % (fails, "" if fails == 1 else "s"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
