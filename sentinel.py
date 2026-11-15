#!/usr/bin/env python3
"""sentinel.py — autonomous RF watch: baseline + continuous diff + forensic log.

Drop PALISADE in a room / vehicle / on a rooftop. SENTINEL captures a baseline of the RF
environment and device inventory, then re-scans on an interval and diffs against the baseline:
a new transmitter, a device gone, or a signal that changed → an alert on the event bus, and a
timestamped line in a JSONL forensic log on disk (pull the NVMe later for the timeline).

This module is the PURE engine: baseline capture, the stateful diff (new / gone-after-grace /
changed), disk + log-rotation bookkeeping, and the demo generator. It is standard-library only
(it reuses the suite's existing pure parsers — noisefloor / wifisurvey / blescan) and it never
opens a radio, a Wi-Fi adapter, BLE, or gpsd itself: every live source is an injected *seam* that
returns None / "standby" off-device, so tests and offscreen runs produce no fake data and touch no
hardware. The Qt layer (OVERWATCH's SENTINEL sub-tab) supplies the real seams, wraps the spectrum
seam in the radio-arbiter lease, and runs the watch loop on a QThread.

SENTINEL is receive-only, so OPSEC (RF-dark) does NOT disable it — listening is not emitting.

Honesty: a baseline/scan contains only what a real scan returned. A domain with no hardware is
recorded as {"available": false, "status": "..."} — never a fabricated inventory. Demo baselines
and demo events are flagged demo=True throughout.
"""
import json
import os
import time

DOMAINS = ("spectrum", "wifi", "ble", "cellular")

DEFAULTS = {
    "storage_dir": "",                 # "" -> default_dir() under the suite data path
    "lo_mhz": 25.0, "hi_mhz": 1700.0,  # coarse wideband sweep
    "bin_khz": 1000, "gain": 0,
    "wifi_iface": "wlan0",
    "ble_secs": 6,
    "interval_s": 60,                  # watch re-scan cadence
    "grace_s": 300,                    # a baseline device must be gone this long before "gone"
    "rssi_delta_db": 12.0,             # RSSI change that counts as "changed"
    "spectrum_threshold_db": 10.0,     # dB above baseline floor that counts as a new emitter
    "rotate_mb": 100,                  # forensic-log rotation cap
}

DISK_WARN_PCT = 10.0                   # warn below this % free
DISK_REFUSE_PCT = 5.0                  # refuse to start watch below this % free


# ---------------------------------------------------------------- storage / disk
def default_dir():
    """SENTINEL's default storage, kept under the suite data path (CLAUDE.md: the data/config path
    stays uconsole-suite). Settings can override this to an NVMe / external mount."""
    try:
        import suite
        base = suite.DATA
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".local", "share", "uconsole-suite")
    return os.path.join(base, "sentinel")


def resolve_dir(config):
    return (config.get("storage_dir") or "").strip() or default_dir()


def ensure_dir(path):
    """Create the storage dir if missing. Returns (ok, reason)."""
    try:
        os.makedirs(path, exist_ok=True)
        return True, ""
    except OSError as e:
        return False, "cannot create %s: %s" % (path, e)


def disk_status(path):
    """Free-space status for the storage dir (or its nearest existing parent). Never raises."""
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        import shutil
        total, used, free = shutil.disk_usage(probe or os.path.expanduser("~"))
    except OSError:
        return {"total": 0, "free": 0, "pct_free": 100.0, "ok": True, "warn": False, "unknown": True}
    pct = 100.0 * free / total if total else 100.0
    return {"total": total, "free": free, "pct_free": pct,
            "ok": pct >= DISK_REFUSE_PCT, "warn": pct < DISK_WARN_PCT, "unknown": False}


def disk_gate(path):
    """(ok_to_start, message). Refuses a watch below 5% free; warns below 10%."""
    d = disk_status(path)
    if d["unknown"]:
        return True, "disk free space unknown"
    gb = d["free"] / 1e9
    if not d["ok"]:
        return False, "disk %.1f%% free (%.1f GB) — too low to start watch (need ≥%.0f%%)" % (
            d["pct_free"], gb, DISK_REFUSE_PCT)
    if d["warn"]:
        return True, "disk low: %.1f%% free (%.1f GB)" % (d["pct_free"], gb)
    return True, "%.1f%% free (%.1f GB)" % (d["pct_free"], gb)


# ---------------------------------------------------------------- forensic JSONL log
class SentinelLog:
    """Append-only JSONL forensic log with size-capped rotation. Best-effort: a logging failure is
    recorded but never raises into the watch loop."""

    def __init__(self, path, rotate_bytes=100 * 1024 * 1024):
        self.path = path
        self.rotate_bytes = int(rotate_bytes)
        self.rotations = 0

    def _maybe_rotate(self):
        try:
            if self.rotate_bytes and os.path.exists(self.path) \
                    and os.path.getsize(self.path) >= self.rotate_bytes:
                os.replace(self.path, self.path + ".1")   # keep one prior segment
                self.rotations += 1
        except OSError:
            pass

    def append(self, record):
        self._maybe_rotate()
        try:
            with open(self.path, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
            return True
        except OSError:
            return False


# ---------------------------------------------------------------- per-domain scan normalisers
def _index_aps(aps):
    """AP list -> {bssid: ap} (the diff key is the BSSID)."""
    return {a["bssid"]: a for a in (aps or []) if a.get("bssid")}


def _index_ble(advs):
    """Classified BLE advert list -> {address: device}."""
    import blescan
    out = {}
    for adv in (advs or []):
        d = blescan.classify_advert(adv) if "is_odid" not in adv else adv
        if d.get("address"):
            out[d["address"]] = d
    return out


def _domain(available, status, **payload):
    d = {"available": bool(available), "status": status}
    d.update(payload)
    return d


def scan_once(config, seams, now=None, on_progress=None, stop=None):
    """Run one pass across all configured domains via the injected seams. Returns a scan dict. Each
    seam returns its own availability/standby honestly; nothing here invents data. on_progress(domain,
    phase) is called 'scanning'/'done' around each domain so the UI can show per-domain progress. If
    stop() becomes true mid-pass, the remaining domains are left unavailable (status 'interrupted')
    so a close joins promptly without fabricating data."""
    now = time.time() if now is None else now
    scan = {"t": now, "demo": False, "domains": {}}
    for name in DOMAINS:
        if stop and stop():
            scan["domains"][name] = _domain(False, "interrupted")
            continue
        if on_progress:
            on_progress(name, "scanning")
        scan["domains"][name] = seams.get(name, _seam_unavailable)(config)
        if on_progress:
            on_progress(name, "done")
    scan["gps"] = None if (stop and stop()) else seams.get("gnss", lambda c: None)(config)
    return scan


def _seam_unavailable(config):
    return _domain(False, "no-seam")


def capture_baseline(config, seams, now=None, demo=False, on_progress=None, stop=None):
    """A scan, stamped as the baseline. The spectrum domain additionally keeps its bins as the
    noise-floor reference for later diffs."""
    now = time.time() if now is None else now
    scan = scan_once(config, seams, now, on_progress=on_progress, stop=stop)
    baseline = {
        "version": 1, "captured": now,
        "captured_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)),
        "demo": bool(demo),
        "config": {k: config.get(k, DEFAULTS.get(k)) for k in
                   ("lo_mhz", "hi_mhz", "bin_khz", "wifi_iface", "ble_secs")},
        "domains": scan["domains"], "gps": scan.get("gps"),
    }
    return baseline


def baseline_filename(now=None):
    now = time.time() if now is None else now
    return "sentinel_baseline_%s.json" % time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))


def save_baseline(storage_dir, baseline):
    """Write the baseline to sentinel_baseline_<ISO>.json. Returns (ok, path_or_reason)."""
    ok, why = ensure_dir(storage_dir)
    if not ok:
        return False, why
    path = os.path.join(storage_dir, baseline_filename(baseline.get("captured")))
    try:
        with open(path, "w") as f:
            json.dump(baseline, f, indent=2, default=str)
        return True, path
    except OSError as e:
        return False, str(e)


def load_baseline(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------- the diff engine (stateful watch)
def _spectrum_new_emitters(baseline_dom, current_dom, threshold_db):
    """New spectral emitters: current bins that rise threshold_db above the baseline floor. Reuses
    noisefloor's floor model (running minimum of the baseline sweep)."""
    import noisefloor
    base_bins = baseline_dom.get("bins")
    cur_bins = current_dom.get("bins")
    if not base_bins or not cur_bins:
        return []
    nf = noisefloor.NoiseFloor()
    nf.update([(f, db) for f, db in base_bins])
    return nf.new_signals([(f, db) for f, db in cur_bins], threshold_db=threshold_db)


class WatchState:
    """Holds the baseline + per-device last-seen bookkeeping and turns each fresh scan into diff
    events. Pure and deterministic: feed it a baseline and a sequence of scans (with explicit `now`)
    and it yields the same events every time.

    Event: {t, domain, kind: 'new'|'gone'|'changed', id, label, field, prev, cur, severity, detail,
            demo, gps}. Every event carries its evidence (which field, previous vs current)."""

    def __init__(self, baseline, config):
        self.baseline = baseline
        self.config = dict(DEFAULTS)
        self.config.update(config or {})
        self.demo = bool(baseline.get("demo"))
        dom = baseline.get("domains", {})
        # seed last-seen with the baseline capture time for every device present at baseline
        t0 = baseline.get("captured", time.time())
        self._last_seen = {}
        for bssid in _dict(dom.get("wifi", {}), "aps"):
            self._last_seen[("wifi", bssid)] = t0
        for addr in _dict(dom.get("ble", {}), "devices"):
            self._last_seen[("ble", addr)] = t0
        self._alerted_new = set()
        self._alerted_gone = set()
        self._alerted_changed = {}        # key -> last alerted value (so a change alerts once per step)

    # -- helpers
    def _base(self, domain, key):
        dom = self.baseline.get("domains", {}).get(domain, {})
        return _dict(dom, key)

    def _event(self, scan, domain, kind, ident, label, severity, detail,
               field=None, prev=None, cur=None):
        return {"t": scan["t"], "domain": domain, "kind": kind, "id": ident, "label": label,
                "field": field, "prev": prev, "cur": cur, "severity": severity, "detail": detail,
                "demo": bool(scan.get("demo") or self.demo), "gps": scan.get("gps")}

    def observe(self, scan, now=None):
        """Diff one fresh scan against the baseline + history. Returns a list of events."""
        now = scan.get("t", time.time()) if now is None else now
        events = []
        events += self._diff_devices(scan, now, "wifi", "aps", _wifi_label, _wifi_changed)
        events += self._diff_devices(scan, now, "ble", "devices", _ble_label, _ble_changed)
        events += self._diff_spectrum(scan)
        return events

    def _diff_devices(self, scan, now, domain, key, label_fn, change_fn):
        dom = scan.get("domains", {}).get(domain, {})
        if not dom.get("available"):            # no adapter this sweep -> observe nothing, claim nothing
            return []
        current = _dict(dom, key)
        base = self._base(domain, key)
        events = []
        # NEW: present now, not in the baseline (alert once)
        for ident, cur in current.items():
            self._last_seen[(domain, ident)] = now
            self._alerted_gone.discard((domain, ident))     # here again -> re-arm the gone detector
            if ident not in base and (domain, ident) not in self._alerted_new:
                self._alerted_new.add((domain, ident))
                events.append(self._event(scan, domain, "new", ident, label_fn(cur), "warn",
                                          "new %s not in baseline: %s" % (domain, label_fn(cur)),
                                          field="presence", prev="absent", cur="present"))
            elif ident in base:                 # CHANGED: a baseline device whose signature moved
                ch = change_fn(base[ident], cur, self.config)
                if ch:
                    if self._alerted_changed.get((domain, ident)) != ch["cur"]:
                        self._alerted_changed[(domain, ident)] = ch["cur"]
                        events.append(self._event(scan, domain, "changed", ident, label_fn(cur),
                                                  "warn", ch["detail"], field=ch["field"],
                                                  prev=ch["prev"], cur=ch["cur"]))
                else:
                    self._alerted_changed.pop((domain, ident), None)   # back to baseline -> re-arm
        # GONE: a baseline device absent longer than the grace period (alert once)
        grace = self.config["grace_s"]
        for ident, binfo in base.items():
            if ident in current:
                continue
            seen = self._last_seen.get((domain, ident), self.baseline.get("captured", now))
            if now - seen >= grace and (domain, ident) not in self._alerted_gone:
                self._alerted_gone.add((domain, ident))
                mins = (now - seen) / 60.0
                events.append(self._event(scan, domain, "gone", ident, label_fn(binfo), "info",
                                          "%s gone %.0f min (baseline device missing)" % (domain, mins),
                                          field="presence", prev="present", cur="absent"))
        return events

    def _diff_spectrum(self, scan):
        dom = scan.get("domains", {}).get("spectrum", {})
        base = self.baseline.get("domains", {}).get("spectrum", {})
        if not dom.get("available") or not base.get("available"):
            return []
        events = []
        news = _spectrum_new_emitters(base, dom, self.config["spectrum_threshold_db"])
        for s in news:
            mhz = s["freq_hz"] / 1e6
            ident = "%.3fMHz" % mhz
            if ("spectrum", ident) in self._alerted_new:
                continue
            self._alerted_new.add(("spectrum", ident))
            events.append(self._event(
                scan, "spectrum", "new", ident, "%.3f MHz" % mhz, "warn",
                "new emitter at %.3f MHz (%.0f dBm, %.0f dB over baseline floor %.0f)" % (
                    mhz, s["dbm"], s["over_db"], s["floor"]),
                field="dbm", prev=round(s["floor"], 1), cur=round(s["dbm"], 1)))
        return events


def _dict(domain, key):
    v = (domain or {}).get(key)
    return v if isinstance(v, dict) else {}


def _wifi_label(ap):
    return "%s (%s)" % (ap.get("ssid") or "<hidden>", ap.get("bssid"))


def _ble_label(d):
    return "%s (%s)" % (d.get("name") or d.get("vendor") or "BLE", d.get("address"))


def _wifi_changed(base, cur, config):
    if base.get("channel") != cur.get("channel") and cur.get("channel") is not None:
        return {"field": "channel", "prev": base.get("channel"), "cur": cur.get("channel"),
                "detail": "channel %s → %s" % (base.get("channel"), cur.get("channel"))}
    if base.get("security") != cur.get("security"):
        return {"field": "security", "prev": base.get("security"), "cur": cur.get("security"),
                "detail": "security %s → %s" % (base.get("security"), cur.get("security"))}
    return _rssi_change(base.get("signal"), cur.get("signal"), config)


def _ble_changed(base, cur, config):
    return _rssi_change(base.get("rssi"), cur.get("rssi"), config)


def _rssi_change(prev, cur, config):
    if prev is None or cur is None:
        return None
    if abs(cur - prev) >= config["rssi_delta_db"]:
        return {"field": "rssi", "prev": prev, "cur": cur,
                "detail": "RSSI %+d dB (%s → %s dBm)" % (cur - prev, prev, cur)}
    return None


# ---------------------------------------------------------------- demo generator
class Demo:
    """Synthetic baseline + evolving scans so the sub-tab is alive without hardware. Everything is
    flagged demo=True and must never be presented as a live observation."""

    def __init__(self):
        self.i = 0
        self._aps = {
            "a0:11:22:33:44:01": {"bssid": "a0:11:22:33:44:01", "ssid": "HOME-NET",
                                  "channel": 6, "signal": -47.0, "security": "WPA2/3"},
            "a0:11:22:33:44:02": {"bssid": "a0:11:22:33:44:02", "ssid": "Guest",
                                  "channel": 11, "signal": -63.0, "security": "open"},
        }
        self._ble = {
            "d1:02:03:04:05:06": {"address": "d1:02:03:04:05:06", "name": "Fitbit",
                                  "rssi": -58, "vendor": None, "is_odid": False, "tags": []},
        }

    def _spectrum(self, extra=None):
        bins = [(25_000_000 + k * 1_000_000, -108.0 + (3 if k % 40 else 20)) for k in range(120)]
        bins[30] = (bins[30][0], -42.0)                 # a steady baseline carrier
        if extra is not None:
            bins[extra] = (bins[extra][0], -40.0)       # a NEW emitter for the diff
        return _domain(True, "ok-demo", bins=bins)

    def baseline(self, config, now):
        return capture_baseline(config, {
            "spectrum": lambda c: self._spectrum(),
            "wifi": lambda c: _domain(True, "ok-demo", aps=dict(self._aps)),
            "ble": lambda c: _domain(True, "ok-demo", devices=dict(self._ble)),
            "cellular": lambda c: _domain(False, "no-modem-demo"),
            "gnss": lambda c: {"lat": 47.6062, "lon": -122.3321, "t": now, "demo": True},
        }, now=now, demo=True)

    def scan(self, config, now):
        """Each demo sweep mutates the world a little so diffs fire: a new AP appears, the Fitbit's
        RSSI jumps, and a new spectral emitter lights up."""
        self.i += 1
        aps = dict(self._aps)
        if self.i >= 1:
            aps["b0:aa:bb:cc:dd:ee"] = {"bssid": "b0:aa:bb:cc:dd:ee", "ssid": "NEW-AP·DEMO",
                                        "channel": 1, "signal": -55.0, "security": "WPA2/3"}
        ble = {k: dict(v) for k, v in self._ble.items()}
        if self.i >= 1:
            ble["d1:02:03:04:05:06"]["rssi"] = -30         # +28 dB jump -> "changed"
        scan = scan_once(config, {
            "spectrum": lambda c: self._spectrum(extra=72 if self.i >= 1 else None),
            "wifi": lambda c: _domain(True, "ok-demo", aps=aps),
            "ble": lambda c: _domain(True, "ok-demo", devices=ble),
            "cellular": lambda c: _domain(False, "no-modem-demo"),
            "gnss": lambda c: {"lat": 47.6062, "lon": -122.3321, "t": now, "demo": True},
        }, now=now)
        scan["demo"] = True
        return scan


# ---------------------------------------------------------------- real hermetic seams (off-device safe)
def _offscreen():
    return bool(os.environ.get("PALISADE_OFFLINE") or
                os.environ.get("QT_QPA_PLATFORM") == "offscreen")


def real_spectrum_bins(config, stop=None, on_proc=None):
    """Run ONE rtl_power sweep and assemble it into bins. Returns a spectrum-domain dict. None of
    the radio arbitration lives here (the Qt worker wraps this in the lease); this only decides
    availability + runs the sweep. Off-device / no rtl_power -> honest standby, never fake bins.
    on_proc(proc) hands the Popen to the caller so a close can terminate a wedged rtl_power."""
    import shutil
    if _offscreen():
        return _domain(False, "offscreen")
    if not shutil.which("rtl_power"):
        return _domain(False, "standby-no-rtl_power")
    import subprocess
    import waterfall
    import noisefloor
    lo = float(config.get("lo_mhz", DEFAULTS["lo_mhz"]))
    hi = float(config.get("hi_mhz", DEFAULTS["hi_mhz"]))
    bin_hz = int(float(config.get("bin_khz", DEFAULTS["bin_khz"])) * 1e3)
    argv = waterfall.rtl_power_sweep_argv(int(lo * 1e6), int(hi * 1e6), bin_hz, "-",
                                          config.get("gain", 0), "1")
    acc = {}
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, bufsize=1)
    except OSError:
        return _domain(False, "standby-no-rtl_power")
    if on_proc:
        on_proc(proc)                        # let the worker terminate it on stop (wedged dongle)
    try:
        for line in proc.stdout:
            if stop and stop():
                break
            r = noisefloor.parse_rtl_power_row(line)
            if not r:
                continue
            if r["f_low"] in acc:            # wrap: one full pass assembled
                break
            acc[r["f_low"]] = r["bins"]
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
    if on_proc:
        on_proc(None)
    bins = []
    for flow in sorted(acc):
        bins += acc[flow]
    bins.sort()
    if stop and stop():                      # interrupted -> no partial-sweep claim
        return _domain(False, "interrupted")
    if not bins:
        return _domain(False, "standby-no-sweep")
    return _domain(True, "ok", bins=bins)


def real_wifi(config, stop=None):
    """Passive `iw scan` -> AP inventory (wifisurvey parser, reused). Off-device / no iw -> standby.
    Interruptible: runs the scan as a subprocess polled against stop so a close joins promptly rather
    than blocking the worker for the full scan timeout."""
    import shutil
    import subprocess
    if _offscreen():
        return _domain(False, "offscreen")
    if not shutil.which("iw"):
        return _domain(False, "standby-no-wifi-adapter")
    import wifisurvey
    try:
        proc = subprocess.Popen(wifisurvey.scan_argv(config.get("wifi_iface", "wlan0")),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return _domain(False, "scan-failed")
    deadline = time.time() + 20.0
    while proc.poll() is None:
        if (stop and stop()) or time.time() > deadline:
            try:
                proc.terminate()
            except Exception:
                pass
            if stop and stop():
                return _domain(False, "interrupted")
            return _domain(False, "scan-failed")
        time.sleep(0.1)
    try:
        out = proc.stdout.read() if proc.stdout else ""
    except (OSError, ValueError):
        out = ""
    return _domain(True, "ok", aps=_index_aps(wifisurvey.parse_iw_scan(out)))


def real_ble(config, stop=None):
    """Passive BLE advert scan via bleak -> classified device inventory. Off-device / no bleak /
    no adapter -> standby. Never raises into the watch loop."""
    if _offscreen():
        return _domain(False, "offscreen")
    try:
        import asyncio
        from bleak import BleakScanner
    except Exception:
        return _domain(False, "standby-no-bleak")
    secs = int(config.get("ble_secs", DEFAULTS["ble_secs"]))

    async def _scan():
        found = {}

        def cb(dev, adv):
            found[dev.address] = {"address": dev.address, "name": dev.name or "",
                                  "rssi": getattr(adv, "rssi", None),
                                  "service_uuids": list(getattr(adv, "service_uuids", []) or []),
                                  "manufacturer_data": dict(getattr(adv, "manufacturer_data", {}) or {})}
        scanner = BleakScanner(detection_callback=cb)
        await scanner.start()
        waited = 0.0
        while waited < secs and not (stop and stop()):
            await asyncio.sleep(0.25)
            waited += 0.25
        await scanner.stop()
        return list(found.values())

    try:
        advs = asyncio.run(_scan())
    except Exception:
        return _domain(False, "scan-failed")
    return _domain(True, "ok", devices=_index_ble(advs))


def real_cellular(config):
    """Visible cell-tower inventory — only if a modem tool is present. No modem -> honest standby
    (no fabricated towers)."""
    import shutil
    if _offscreen() or not (shutil.which("mmcli") or shutil.which("ModemManager")):
        return _domain(False, "standby-no-cellular-modem")
    return _domain(False, "standby-no-cellular-modem")   # tower enumeration is device-specific; honest


def real_gnss(config):
    """Current GNSS fix from gpsd, or None (honest: no position). Off-device / no gpsd -> None."""
    if _offscreen():
        return None
    try:
        import socket
        s = socket.create_connection(("127.0.0.1", 2947), timeout=2.0)
        s.sendall(b'?WATCH={"enable":true,"json":true};\n')
        s.settimeout(3.0)
        buf = b""
        deadline = time.time() + 4.0
        while time.time() < deadline:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            for line in buf.split(b"\n"):
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if obj.get("class") == "TPV" and obj.get("lat") is not None:
                    s.close()
                    return {"lat": obj["lat"], "lon": obj.get("lon"), "t": time.time()}
            buf = buf.rsplit(b"\n", 1)[-1]
        s.close()
    except OSError:
        return None
    return None


def real_seams():
    """The default live seams. The spectrum seam here does NOT arbitrate the radio; the Qt worker
    wraps it with the radio_arbiter lease (keeping this module Qt-free)."""
    return {"spectrum": real_spectrum_bins, "wifi": real_wifi, "ble": real_ble,
            "cellular": real_cellular, "gnss": real_gnss}


def summarize(events, duration_s, sweeps):
    """Final watch summary: counts by kind, a baseline-deviation score, duration, sweep count."""
    by_kind = {}
    for e in events:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    score = len([e for e in events if e["severity"] == "warn"])
    return {"events": len(events), "by_kind": by_kind, "deviation_score": score,
            "duration_s": duration_s, "sweeps": sweeps}


if __name__ == "__main__":
    cfg = dict(DEFAULTS)
    d = Demo()
    now = time.time()
    base = d.baseline(cfg, now)
    print("baseline domains:", {k: v.get("available") for k, v in base["domains"].items()})
    ws = WatchState(base, cfg)
    for step in range(3):
        evs = ws.observe(d.scan(cfg, now + 60 * (step + 1)))
        for e in evs:
            print("  [%s] %s %s — %s" % (e["severity"], e["domain"], e["kind"], e["detail"]))
