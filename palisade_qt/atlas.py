"""ATLAS — one layered live map (the first wired backend).

Every source publishes typed `contact` events to the event bus with a geo-native payload
(lat/lon/alt/kind); ATLAS's map AND the OPS PPI both consume that one stream, so a contact shows
in both places. Layers (aircraft / ships / APRS / drones / DF / balloons) toggle on the map.

Honesty (CLAUDE.md): demo mode flies synthetic tracks, flagged by the SDR-DEMO chip; LIVE mode
runs the real engine adapters, which publish nothing until they're wired — so a live ATLAS with
no backend shows zero contacts rather than inventing them. UI + wiring only; no decoding/radio
behaviour changes here.
"""
import json
import math
import os
import queue
import random
import sys
import threading
import time

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp
from . import theme, eventbus, radio_arbiter
from .kit import MapPanel, FeedTable, DetailCard
from .kit.components import Cover
from .worker import Worker
from .kit.seams import offscreen as _seam_offscreen

# kind -> (legend label, theme colour token). Severity "alert" overrides the colour to red.
# Remote-ID adds two kinds: the drone (alert red) and its OPERATOR (accent violet).
KINDS = [("aircraft", "AIRCRAFT", "accent"), ("vessel", "VESSELS", "cyan"),
         ("station", "APRS", "warn"), ("drone", "DRONES", "alert"),
         ("operator", "OPERATOR", "accent"),
         ("df", "DF", "text"), ("balloon", "BALLOONS", "muted")]
KIND_LABEL = {k: lbl for k, lbl, _ in KINDS}
KIND_TOKEN = {k: tok for k, _, tok in KINDS}
STALE_S = 12.0


# ------------------------------------------------------------------ demo tracks
def _offset(lat, lon, d_nm, brg_deg):
    b = math.radians(brg_deg)
    return (lat + d_nm / 60.0 * math.cos(b),
            lon + d_nm / 60.0 * math.sin(b) / max(0.2, math.cos(math.radians(lat))))


class _Track:
    _SPD = {"aircraft": (160, 480), "vessel": (4, 22), "station": (0, 55), "drone": (8, 40),
            "df": (0, 0), "balloon": (6, 30)}
    _ALT = {"aircraft": (6000, 39000), "drone": (60, 400), "balloon": (30000, 90000)}

    def __init__(self, kind):
        self.kind = kind
        home = eventbus.home() or eventbus.DEMO_HOME          # demo tracks only (H5)
        self.lat, self.lon = _offset(home[0], home[1], random.uniform(5, 68),
                                     random.uniform(0, 360))
        self.hdg = random.uniform(0, 360)
        self.spd = random.uniform(*self._SPD[kind])
        self.alt = random.randint(*self._ALT[kind]) if kind in self._ALT else None
        self.id = self._mkid(kind)
        self.mil = kind == "aircraft" and random.random() < 0.18
        if kind == "drone":          # a Remote-ID drone broadcasts its operator too
            self.op_lat, self.op_lon = _offset(self.lat, self.lon, random.uniform(0.2, 1.4),
                                               random.uniform(0, 360))

    @staticmethod
    def _mkid(kind):
        if kind == "aircraft":
            return random.choice(["UAL", "ASA", "DAL", "FDX", "N"]) + str(random.randint(100, 980))
        if kind == "vessel":
            return str(random.randint(200000000, 775000000))        # MMSI
        if kind == "station":
            return random.choice(["KD7", "W7", "N0", "KE7"]) + random.choice("ABCXYZ") + \
                str(random.randint(1, 9))
        if kind == "drone":
            return "RID-%06X" % random.randint(0, 0xFFFFFF)
        if kind == "df":
            return "BRG-%03d" % random.randint(0, 359)
        return "BAL-%04d" % random.randint(1, 9999)

    def step(self, dt):
        if self.spd:
            d = self.spd / 3600.0 * dt
            self.lat, self.lon = _offset(self.lat, self.lon, d, self.hdg)

    def event(self):
        sev = "alert" if (self.mil or self.kind == "drone") else "live"
        return eventbus.contact("ATLAS", self.id, self.lat, self.lon, alt=self.alt,
                                kind=self.kind, severity=sev, spd=round(self.spd), mil=self.mil,
                                demo=True)

    def operator_event(self):
        return eventbus.contact("RID", self.id + "-OP", self.op_lat, self.op_lon,
                                kind="operator", severity="warn", label="OP " + self.id,
                                drone=self.id, demo=True)


class AtlasDemoWorker(Worker):
    """Synthetic multi-layer traffic, published to the bus (demo only)."""
    _COUNT = {"aircraft": 6, "vessel": 4, "station": 3, "drone": 2, "df": 1, "balloon": 1}

    def __init__(self, parent=None):
        super().__init__(demo=True, interval_ms=600, parent=parent)
        self.tracks = [_Track(k) for k, n in self._COUNT.items() for _ in range(n)]
        self._t = time.time()

    def step(self):
        now = time.time()
        dt, self._t = now - self._t, now
        for tk in self.tracks:
            tk.step(dt)
            eventbus.bus.publish(tk.event())
            if tk.kind == "drone":              # plot the operator too (the RID differentiator)
                eventbus.bus.publish(tk.operator_event())
        self.status.emit({"sdr": {"text": "SDR DEMO", "state": "neutral"}})


_EMERG_SQ = {"7500", "7600", "7700"}


def adsb_to_contact(a):
    """Adapt ONE sky_app aircraft dict -> a typed contact event. The decoding is sky_app's and is
    left unchanged; this only reshapes its output. Returns None for an aircraft with no position."""
    lat, lon = a.get("lat"), a.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    cid = (a.get("flight") or "").strip() or str(a.get("hex", "")).upper()
    alt = a.get("alt_baro")
    if not isinstance(alt, (int, float)):
        alt = a.get("alt_geom")
    spd = a.get("gs")
    sq = str(a.get("squawk") or "")
    emerg = a.get("emergency")
    sev = "alert" if (emerg and emerg not in ("", "none")) or sq in _EMERG_SQ else "live"
    return eventbus.contact("ADS-B", cid, lat, lon,
                            alt=int(alt) if isinstance(alt, (int, float)) else None,
                            kind="aircraft", severity=sev,
                            spd=int(spd) if isinstance(spd, (int, float)) else None,
                            track=a.get("track"), hexid=a.get("hex"))


def adsb_contacts(aircraft):
    """Typed contact events for a sky_app aircraft snapshot (aircraft with a position only)."""
    return [ev for ev in (adsb_to_contact(a) for a in aircraft) if ev is not None]


# ------------------------------------------------------------------ Remote-ID (dronewatch)
RID_CONFIRM_ADVERTS = 3          # P3: Remote ID is an unauthenticated broadcast — one advert
RID_CONFIRM_SPAN_S = 2.0         # (anyone with a phone can send it) never raises a red drone


# what each positional source can be trusted for (shown on the detail card — P3)
SOURCE_TRUST = {            # short: one line on the detail card (the full reason is the tooltip)
    "RID": "UNAUTHENTICATED RID",
    "ADS-B": "UNAUTHENTICATED ADS-B",
    "AIS": "UNAUTHENTICATED AIS",
    "APRS": "UNAUTHENTICATED APRS",
}


def rid_contacts(fusion_list):
    """Adapt dronewatch fusion_contacts() -> typed contact events: the DRONE and, when the
    OpenDroneID System message carried it, the OPERATOR (operator kind). Decoding is
    dronewatch's, unchanged — this only reshapes its output.

    P3: a drone is ALERT (red) only once it has been heard RID_CONFIRM_ADVERTS times over at
    least RID_CONFIRM_SPAN_S; before that it is plotted amber and marked UNCONFIRMED."""
    out = []
    for fc in fusion_list:
        n = int(fc.get("adverts") or 0)
        first, last = fc.get("first"), fc.get("timestamp")
        span = (last - first) if isinstance(first, (int, float)) and \
            isinstance(last, (int, float)) else 0.0
        confirmed = n >= RID_CONFIRM_ADVERTS and span >= RID_CONFIRM_SPAN_S
        trust = "confirmed" if confirmed else "unconfirmed"
        lat, lon = fc.get("lat"), fc.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            alt_m = fc.get("alt_m")
            out.append(eventbus.contact(
                "RID", fc.get("id"), lat, lon,
                alt=int(alt_m * 3.28084) if isinstance(alt_m, (int, float)) else None,
                kind="drone", severity="alert" if confirmed else "warn",
                label=(fc.get("id") if confirmed else "%s ?" % fc.get("id")),
                spd=int(fc["speed_mps"]) if isinstance(fc.get("speed_mps"), (int, float)) else None,
                uas_id=fc.get("uas_id"), operator_id=fc.get("operator_id"),
                trust=trust, adverts=n))
        olat, olon = fc.get("operator_lat"), fc.get("operator_lon")
        if isinstance(olat, (int, float)) and isinstance(olon, (int, float)):
            out.append(eventbus.contact(
                "RID", (fc.get("operator_id") or fc.get("id") or "OP") + "-OP", olat, olon,
                kind="operator", severity="warn",
                label="OP " + str(fc.get("uas_id") or fc.get("id")), drone=fc.get("uas_id"),
                trust=trust, adverts=n))
    return out


class RidSource:
    """Drive dronewatch's OpenDroneID decoder from a BLE (bleak) scan and expose fusion contacts.
    BLE + Wi-Fi only (OpenDroneID) — NOT the SDR, so no lease is taken. The Wi-Fi-monitor path is
    device-only and left stubbed; BLE works on the dev Mac but sees zero without real beacons."""

    def __init__(self, on_fault=None):
        import dronewatch
        self._dw = dronewatch
        self._drones = dronewatch.Drones()
        self._q = queue.Queue()
        self._on = False
        self._thread = None
        self._fault = None             # E3: a scanner failure is surfaced, never swallowed
        self._on_fault = on_fault
        self.state = "off"             # off | scanning | fault | unavailable

    def start(self):
        if self._on:
            return
        self._on = True
        self._thread = threading.Thread(target=self._scan_ble, daemon=True)
        self._thread.start()
        # TODO(device-only): Wi-Fi monitor-mode OpenDroneID (NAN/beacon) — needs a monitor NIC;
        # validate on the uConsole. BLE covers the common case and runs here.

    def _set_fault(self, msg, state="fault"):
        self._fault = msg
        self.state = state
        if self._on_fault is not None:
            try:
                self._on_fault(msg)
            except Exception:
                pass

    @staticmethod
    def scanner_kwargs(platform=None):
        """E3: PASSIVE scanning only — Remote-ID beacons are broadcast; we never send scan
        requests. bleak: scanning_mode='passive'. On Linux (BlueZ, the uConsole) passive mode is
        an advertisement monitor and REFUSES to start without or_patterns (CL5-fix 10 / N8:
        "passive scanning mode requires bluez or_patterns"), so match the OpenDroneID service
        data: AD type 0x16 (Service Data, 16-bit UUID) starting with 0xFFFA little-endian."""
        kw = {"scanning_mode": "passive"}
        if (platform or sys.platform).startswith("linux"):
            try:
                from bleak.assigned_numbers import AdvertisementDataType
                ad_type = AdvertisementDataType.SERVICE_DATA_UUID16
            except Exception:
                ad_type = 0x16
            uuid_le = (0xFFFA).to_bytes(2, "little")
            kw["bluez"] = {"or_patterns": [(0, ad_type, uuid_le)]}
        return kw

    def _scan_ble(self):
        if _seam_offscreen():
            self.state = "unavailable"
            return                      # never open a real BLE scan under tests/offline
        try:
            import asyncio
            from bleak import BleakScanner
        except Exception as e:
            self._set_fault("Remote-ID: bleak not installed (%s)" % str(e)[:60], "unavailable")
            return

        async def run():
            def cb(dev, adv):
                sd = getattr(adv, "service_data", None) or {}
                p = sd.get(self._dw.ODID_SERVICE_UUID)
                if p:
                    self._q.put((dev.address, bytes(p), getattr(adv, "rssi", None)))
            kw = self.scanner_kwargs()
            try:
                scanner = BleakScanner(detection_callback=cb, **kw)
            except TypeError:           # backend without passive support: say so, stay off
                self._set_fault("Remote-ID: BLE backend has no passive scan mode — not scanning")
                return
            await scanner.start()
            self.state = "scanning"
            try:
                while self._on:
                    await asyncio.sleep(0.5)
            finally:
                await scanner.stop()
                if self.state == "scanning":
                    self.state = "off"
        try:
            asyncio.run(run())
        except Exception as e:
            self._set_fault("Remote-ID BLE scan failed: %s" % str(e)[:100])

    def ingest_payload(self, addr, payload, rssi=None):
        """Decode one BLE ODID service-data payload and fold it into the aggregator (dronewatch's
        decoder, unchanged). Exposed for the Wi-Fi stub and tests."""
        msgs = self._dw.decode_service_data(payload)
        if msgs:
            self._drones.ingest(addr, msgs, rssi=rssi)

    def contacts(self):
        while True:
            try:
                addr, payload, rssi = self._q.get_nowait()
            except queue.Empty:
                break
            self.ingest_payload(addr, payload, rssi)
        self._drones.prune()
        return rid_contacts(self._drones.fusion_contacts())

    def stop(self):
        self._on = False


# ------------------------------------------------------------------ lease-using layers (one SDR)
# APRS + AIS both need the single built-in dongle; they go through radio_arbiter so only ONE holds
# it at a time (a denied layer renders RADIO BUSY). _open_*_pipe are test seams -> None under
# offscreen/offline/no-tools, so CI never opens a real radio. Legacy decode paths reused AS-IS.
def _open_aprs_pipe(gain):
    import shutil
    if _seam_offscreen():
        return None
    if not shutil.which("rtl_fm") or not shutil.which("multimon-ng"):
        return None
    import aprs
    from .kit.procs import Pipeline
    return Pipeline(aprs.pipeline_argv(gain))          # one session: PANIC/arbiter kill the lot (A4)


def _open_ais_pipe(gain):
    import shutil
    if _seam_offscreen():
        return None
    if not shutil.which("rtl_ais"):
        return None
    import ais
    from .kit.procs import Pipeline
    return Pipeline(ais.pipeline_argv(gain))           # one session: PANIC/arbiter kill the lot (A4)


def aprs_station_contacts(stations, now):
    """aprs.Stations -> typed contact events (kind=station). Positions only; decoding is aprs's."""
    out = []
    for st in stations.s.values():
        lat, lon = st.get("lat"), st.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        out.append(eventbus.contact(
            "APRS", st["call"], lat, lon, kind="station",
            severity="live" if (st.get("speed_kt") or 0) >= 3 else "info",
            spd=int(st["speed_kt"]) if st.get("speed_kt") else None,
            course=st.get("course"), symbol=st.get("symbol"), comment=st.get("comment")))
    return out


def ais_vessel_contacts(vessels, now):
    """ais.Vessels -> typed contact events (kind=vessel). Decoding is ais's, unchanged."""
    out = []
    for v in vessels.active(now):
        fc = vessels.fusion_contact(v)
        lat, lon = fc.get("lat"), fc.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        spd = fc.get("speed_mps")
        out.append(eventbus.contact(
            "AIS", str(fc["mmsi"]), lat, lon, kind="vessel",
            severity="live" if (spd or 0) > 0.5 else "info",
            label=v.get("name") or str(fc["mmsi"]),
            spd=int(spd / 0.514) if isinstance(spd, (int, float)) else None,   # m/s -> kt
            course=fc.get("heading_deg"), mmsi=fc["mmsi"], ship_type=v.get("ship_type_name")))
    return out


# ------------------------------------------------------------------ non-lease geo sources
_SONDES_PATH = os.path.join(os.path.expanduser("~"), ".cache", "uconsole-suite", "sondes.json")


def balloon_contacts(path=None):
    """Read the radiosonde cache (sondes.json, written by the Balloons app's auto_rx UDP listener;
    the same file sky_app reads) -> balloon contacts. No SDR lease: auto_rx owns its pipeline.
    No file -> zero (honest)."""
    path = path or _SONDES_PATH
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for s in (data.get("sondes") or []):
        lat, lon = s.get("lat"), s.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        out.append(eventbus.contact(
            "SONDE", str(s.get("id") or "sonde"), lat, lon,
            alt=int(s["alt"] * 3.28084) if isinstance(s.get("alt"), (int, float)) else None,
            kind="balloon", severity="info",
            spd=int(s["vel_h"] * 1.94384) if isinstance(s.get("vel_h"), (int, float)) else None,
            model=s.get("model"), freq=s.get("freq")))
    return out


def df_contacts():
    """KrakenSDR direction finding. Device-only: needs the 5-channel array; kraken.triangulate is
    reused for the geolocation geometry. No array -> zero (honest)."""
    try:
        import kraken
    except Exception:
        return []
    if not kraken.kraken_available():
        return []
    # TODO(device-only): collect bearings from the KrakenSDR DAQ, kraken.triangulate(fixes) ->
    # emitter (lat, lon) + kraken.confidence(); publish kind="df". Validate with the array.
    return []


class LeaseSource:
    """A layer that needs the single SDR. Goes through radio_arbiter: poll() acquires the radio if
    free and runs its capture pipe; if the radio is held by another layer it stays idle and
    busy_owner() reports the holder (so the UI shows RADIO BUSY). stop() releases. Subclasses supply
    the pipe and the decode (reused from the legacy module AS-IS). Only ONE LeaseSource is ever live."""
    NAME = None

    def __init__(self, gain=0):
        self._gain = gain
        self._on = False
        self._has_radio = False
        self._proc = None
        self._thread = None
        self._revoke_req = False       # set on the GUI thread; acted on in poll() (worker thread)
        self.given_back = None         # why this layer gave the radio back (the page unticks it)
        self.wake = None               # the owning worker's poke(): act on a revoke NOW (CL5-fix2)

    def start(self):
        self._on = True          # acquire is deferred to poll() so a busy layer keeps retrying
        radio_arbiter.arbiter.revoked.connect(self._on_revoked)

    def _on_revoked(self, name):
        """A1: the operator asked for the radio back. This runs on the GUI thread, so it only
        flags it (CL5-fix 6: Pipeline.terminate + the lease release took 2 s here). The worker's
        next poll() stops the pipeline, waits for it to exit, then releases — the arbiter frees
        on that acknowledgement."""
        if name == self.NAME:
            self._revoke_req = True
            if self.wake is not None:
                self.wake()

    def hold_off(self, reason):
        """PANIC: same as a revoke, from the worker thread's next poll()."""
        self._revoke_req = True
        self.given_back = reason

    def _give_back(self, why):
        self._on = False
        self._revoke_req = False
        self._stop_pipe()                            # every stage reaped …
        if self._has_radio:
            radio_arbiter.arbiter.release(self.NAME)   # … THEN released
            self._has_radio = False
        self.given_back = self.given_back or why

    def poll(self):
        """Worker thread. Acquire if free, start the capture only once HELD (CL5-fix 1), give the
        radio back on a revoke/PANIC or if it was freed under us."""
        if self._revoke_req:
            self._give_back("radio given back")
            return []
        if not self._on:
            return []
        arb = radio_arbiter.arbiter
        if not self._has_radio:
            if not arb.request(self.NAME):
                return []        # radio busy: publish nothing (UI shows BUSY via busy_owner)
            self._has_radio = True
        st, owner = arb.state()
        if owner != self.NAME:                       # freed under us (forced free)
            self._has_radio = False
            self._give_back(radio_arbiter.lost_reason(self.NAME))
            return []
        if st != "HELD":
            return []                                # ACQUIRING: readsb is still being paused
        if self._proc is None and self._thread is None:
            self._proc = self._open_pipe()
            if self._proc is not None and not arb.held_by(self.NAME):
                self._has_radio = False              # N-j: lost it while spawning — reap first
                self._give_back(radio_arbiter.lost_reason(self.NAME))
                return []
            if self._proc is not None:
                self._thread = threading.Thread(target=self._read, daemon=True)
                self._thread.start()
            else:
                self._thread = False                 # seam opened nothing: don't retry each poll
        return self._contacts()

    def acquiring(self):
        st, owner = radio_arbiter.arbiter.state()
        return self._on and owner == self.NAME and st == "ACQUIRING"

    def busy_owner(self):
        """Holder's lease name if this source wants the radio but can't have it, else None."""
        if self._on and not self._has_radio:
            return radio_arbiter.arbiter.owner()
        return None

    def _read(self):
        proc = self._proc
        if proc is None:
            return
        try:
            for line in proc.stdout:
                if not self._on:
                    break
                self.feed_line(line)
        except Exception:
            pass

    def _stop_pipe(self):
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()                 # Pipeline: group SIGTERM → wait → SIGKILL → wait
            except Exception:
                pass

    def stop(self):
        self._on = False
        try:
            radio_arbiter.arbiter.revoked.disconnect(self._on_revoked)
        except (TypeError, RuntimeError):
            pass
        self._stop_pipe()
        if self._has_radio:
            radio_arbiter.arbiter.release(self.NAME)   # readsb / the autopilot resume
            self._has_radio = False

    def _open_pipe(self):
        raise NotImplementedError

    def feed_line(self, line):
        raise NotImplementedError

    def _contacts(self):
        raise NotImplementedError


class AprsSource(LeaseSource):
    """144.39 APRS (rtl_fm -> multimon-ng); aprs.parse_frame/decode/Stations unchanged."""
    NAME = "ATLAS-APRS"

    def __init__(self, gain=0):
        super().__init__(gain)
        import aprs
        self._aprs = aprs
        self._stations = aprs.Stations()

    def _open_pipe(self):
        return _open_aprs_pipe(self._gain)

    def feed_line(self, line):
        frame = self._aprs.parse_frame(line)
        if frame:
            rep = self._aprs.decode(frame)
            if rep:
                self._stations.add(rep, time.time())

    def _contacts(self):
        return aprs_station_contacts(self._stations, time.time())


class AisSource(LeaseSource):
    """162 MHz AIS (rtl_ais -> AIVDM); ais.AivdmAssembler/decode/Vessels unchanged."""
    NAME = "ATLAS-AIS"

    def __init__(self, gain=0):
        super().__init__(gain)
        import ais
        self._assembler = ais.AivdmAssembler()
        self._vessels = ais.Vessels()

    def _open_pipe(self):
        return _open_ais_pipe(self._gain)

    def feed_line(self, line):
        msg = self._assembler.feed(line)
        if msg:
            self._vessels.ingest(msg, time.time())

    def _contacts(self):
        return ais_vessel_contacts(self._vessels, time.time())


class AtlasLiveWorker(Worker):
    """Live mode: wired sources publish real contacts; everything else stays at zero.
      - ADS-B: sky_app's readsb/dump1090 aircraft.json (no radio opened, no lease — readsb owns
        its radio; behaviour-preserving, autopilot undisturbed).
      - Remote-ID: dronewatch's OpenDroneID decoder over a BLE scan (BLE/Wi-Fi, NOT the SDR, so
        no lease). Publishes the drone AND its operator.
      - APRS: aprs's 144.39 decoder; the FIRST lease-using source. It holds the single-SDR lease
        ONLY while the APRS layer is active (acquire on layer-on, release on layer-off and close),
        so it coexists with the autopilot and never holds the radio permanently.
    Remaining layers (AIS/DF/balloons) are still stubbed. With no engine/beacons up, this
    publishes ZERO. Device-only bits (real RTL capture, Wi-Fi-monitor ODID) validate on the
    uConsole."""

    # CL5-fix2 (RA-CL5b N-a): a lease layer owns the dongle, so this worker must keep answering a
    # revoke / forced free while ATLAS is hidden. It is never paused; while hidden it only runs
    # the lease layers (and starts nothing else), which is what a paused worker used to cost.
    PAUSE_WHEN_HIDDEN = False

    def __init__(self, parent=None):
        super().__init__(demo=False, interval_ms=1000, parent=parent)
        self._hidden = False
        self._adsb = None
        self._adsb_tried = False
        self._rid = None
        self._rid_tried = False
        self._lease_srcs = {}        # kind -> LeaseSource, alive only while that layer is on
        self._wanted = set()         # lease-layer kinds toggled on (GUI thread); reconciled in step

    def _ensure_sources(self):
        if not self._adsb_tried:
            self._adsb_tried = True
            try:
                import sky_app
                srcs = sky_app.DEFAULT_SETTINGS.get("adsb_sources") or ["/run/readsb"]
                self._adsb = sky_app.AdsbFeed(list(srcs))
            except Exception as e:   # no engine / no deps: stay at zero, surface once
                self.error.emit("ADS-B engine unavailable: %s" % str(e)[:120])
                self._adsb = None
        # E3: the BLE scan is an explicit layer (DRONES) with an off switch; it is NOT started
        # merely because ATLAS opened. See _reconcile_rid().

    LEASE_LAYERS = {"station": AprsSource, "vessel": AisSource}

    def set_layer(self, kind, on):
        """Lease-layer toggle (GUI thread): want this capture on/off. Reconciled in step() so the
        arbiter request/release runs off the GUI thread."""
        if on:
            self._wanted.add(kind)
        else:
            self._wanted.discard(kind)

    def _reconcile_rid(self):
        want = "drone" in self._wanted
        if want and self._rid is None:
            try:
                self._rid = RidSource(on_fault=lambda m: self.error.emit(m))
                self._rid.start()
            except Exception as e:
                self.error.emit("Remote-ID (BLE) unavailable: %s" % str(e)[:120])
                self._rid = None
        elif not want and self._rid is not None:
            self._rid.stop()
            self._rid = None

    def _reconcile_leases(self):
        for kind, cls in self.LEASE_LAYERS.items():
            want = kind in self._wanted
            src = self._lease_srcs.get(kind)
            if want and src is None:
                try:
                    src = cls()
                    src.wake = self.poke
                    src.start()
                    self._lease_srcs[kind] = src
                except Exception as e:
                    self.error.emit("%s source unavailable: %s" % (kind, str(e)[:120]))
            elif not want and src is not None:
                src.stop()                   # releases the radio via the arbiter
                del self._lease_srcs[kind]

    def set_hidden(self, hidden):
        """GUI thread: the page was hidden / fronted. Flag only (the lease layers keep running)."""
        self._hidden = bool(hidden)
        self.poke()

    def step(self):
        self._reconcile_leases()
        if self._hidden:
            self._step_leases()                  # hidden: only the dongle owners, nothing new
            return
        self._ensure_sources()
        self._reconcile_rid()
        # ADS-B is the baseline (reads readsb's json). If a lease-layer holds the radio, readsb is
        # paused -> ADS-B is BUSY (the app shows it) and we publish no stale aircraft.
        if radio_arbiter.arbiter.owner() is None:
            for ev in self._adsb_contacts():
                eventbus.bus.publish(ev)
        if self._rid is not None:
            for ev in self._rid.contacts():
                eventbus.bus.publish(ev)
        for ev in balloon_contacts():        # radiosonde cache file; no lease (auto_rx service)
            eventbus.bus.publish(ev)
        for ev in df_contacts():             # KrakenSDR array (separate device); no lease
            eventbus.bus.publish(ev)
        self._step_leases()

    def _step_leases(self):
        for kind, src in list(self._lease_srcs.items()):
            for ev in src.poll():            # acquires if free; nothing while the radio is busy
                eventbus.bus.publish(ev)
            if src.given_back:               # revoke / PANIC: the layer is off — tell the page
                self.status.emit({"layer_off": kind, "why": src.given_back})
                src.stop()
                del self._lease_srcs[kind]
                self._wanted.discard(kind)
        acq = [k for k, src in self._lease_srcs.items() if src.acquiring()]
        self.status.emit({"acquiring_layers": acq})

    def hold_off(self, reason):
        """PANIC (GUI thread): every lease layer gives the radio back on the next step."""
        for src in list(self._lease_srcs.values()):
            src.hold_off(reason)
        self.poke()

    def _adsb_contacts(self):
        """E1: aircraft are published only while the feed is LIVE. A stale aircraft.json (readsb
        stopped writing it) or no answering source publishes nothing and says so, with the age of
        the last data — an hour-old file used to be republished as live, age 0 s."""
        if self._adsb is None:
            self.status.emit({"adsb": {"state": "none", "why": "no ADS-B engine"}})
            return []
        try:
            aircraft, _trails, status, _rcv = self._adsb.snapshot()
        except Exception as e:
            self.status.emit({"adsb": {"state": "none", "why": str(e)[:60]}})
            return []
        data_t = getattr(self._adsb, "data_t", None)
        age = (time.time() - data_t) if data_t else None
        if status != "live":
            self.status.emit({"adsb": {"state": "stale" if status == "stale" else "none",
                                       "age": age}})
            return []
        self.status.emit({"adsb": {"state": "live", "age": age, "n": len(aircraft)}})
        return adsb_contacts(aircraft)

    def run(self):
        super().run()
        if self._adsb is not None:
            self._adsb.stopped = True        # stop the ADS-B feed's poll thread on close
        if self._rid is not None:
            self._rid.stop()                 # stop the BLE scan thread on close
        for src in list(self._lease_srcs.values()):
            src.stop()                       # RELEASE the radio on page close (readsb resumes)
        self._lease_srcs.clear()


# ------------------------------------------------------------------ app
class AtlasApp(PalisadeApp):
    TITLE = "ATLAS"
    # ADS-B reads readsb's aircraft.json (readsb owns its radio); no 2nd radio, no lease.
    # A dongle-using layer (AIS on 162 MHz) will take the lease when it is wired.
    LEASE = None

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        self._contacts = {}
        self._selected = None
        self._layers = {k for k, _, _ in KINDS}      # all layers on by default
        self._busy_shown = set()
        if not self.demo:
            self._layers.discard("station")          # APRS + AIS hold the one SDR: opt-in in live
            self._layers.discard("vessel")
            self._layers.discard("drone")            # E3: the BLE scan is opt-in too

        body = QtWidgets.QWidget()
        split = QtWidgets.QHBoxLayout(body)
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(10)

        home = eventbus.home() or (self.demo and eventbus.DEMO_HOME) or (None, None)
        self.map = MapPanel(span_nm=80, mode=self.mode, home_lat=home[0], home_lon=home[1])
        self.map.set_home(None, None, known=eventbus.home_set())
        # N26: no HOME (live) -> no range picture at all: rings, basemap and positions would be
        # measured from a guessed origin. The list still shows what is heard.
        self._home_cover = Cover(self.map, "offline", "HOME NOT SET",
                                 "Range rings and the map need your position. "
                                 "Set HOME in SYSTEM › SETTINGS. Contacts are listed at right.")
        self._home_cover.show(not self.demo and not eventbus.home_set())
        self._adsb_health = None                     # E1 / H10: the ADS-B feed's own state
        split.addWidget(self.map, 3)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._legend())
        self._busy_label = QtWidgets.QLabel("")       # "RADIO BUSY — held by X" (live only)
        self._busy_label.setProperty("class", "note")
        self._busy_label.setStyleSheet("color:%s;" % self._tok["warn"])
        self._busy_label.setWordWrap(True)
        self._busy_label.hide()
        right.addWidget(self._busy_label)
        # TYPE is not a column: it is on the map (colour + label), the layer chips and the detail
        # card. Four columns did not fit 1280x720 and cut altitudes off at the edge (RA-CL1b N1);
        # the three that remain always fit, and a value too wide elides with its full text as tooltip
        self.feed = FeedTable([("label", "CONTACT"), ("rng", "NM"), ("alt", "ALT")],
                              fit_viewport=True)
        self.feed.selected.connect(self._show)
        right.addWidget(self.feed, 3)
        self.detail = DetailCard("CONTACT")
        self.detail.set_hero("—", "select a contact")
        right.addWidget(self.detail, 2)
        split.addLayout(right, 2)

        eventbus.bus.published.connect(self._on_event)
        eventbus.bus.home_changed.connect(self._on_home_changed)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._render)
        self._timer.start(700)
        return body

    def _legend(self):
        f = QtWidgets.QFrame()
        f.setProperty("class", "card2")
        lay = QtWidgets.QGridLayout(f)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setHorizontalSpacing(6)
        lay.setVerticalSpacing(6)
        self._layer_btns = {}
        for i, (k, lbl, tok) in enumerate(KINDS):
            b = QtWidgets.QPushButton(lbl)
            b.setCheckable(True)
            b.setChecked(k in self._layers)      # APRS starts off in live (opt-in lease)
            # a layer that is ON is filled; OFF is a dashed outline with the name struck out by
            # colour AND shape, so on/off never rests on colour alone (D4/D9)
            b.setStyleSheet("QPushButton { color:%s; padding:2px 8px; font-size:%dpx; min-height:24px;"
                            " border:%s solid %s; border-radius:5px; background:%s; }"
                            " QPushButton:!checked { color:%s; border:%s dashed %s;"
                            " background:transparent; }"
                            " QPushButton:focus { border:%s solid %s; }"
                            % (self._tok[tok], theme.FONT_STATUS, self._tok["bw"], self._tok[tok],
                               self._tok["p2"], self._tok["disabled"], self._tok["bw"],
                               self._tok["disabled"], self._tok["focus_w"], self._tok["focus"]))
            b.setFocusPolicy(QtCore.Qt.TabFocus)
            b.clicked.connect(lambda on, kk=k: self._toggle(kk, on))
            lay.addWidget(b, i // 4, i % 4)
            self._layer_btns[k] = b
        return f

    LEASE_NAME = {"station": "ATLAS-APRS", "vessel": "ATLAS-AIS"}

    def _toggle(self, kind, on):
        self._layers.add(kind) if on else self._layers.discard(kind)
        if (kind in self.LEASE_NAME or kind == "drone") and not self.demo \
                and self._worker is not None and hasattr(self._worker, "set_layer"):
            self._worker.set_layer(kind, on)     # SDR layers via the arbiter; DRONES = BLE scan
        self._render()

    def make_worker(self):
        if self.demo:
            return AtlasDemoWorker()
        w = AtlasLiveWorker()
        w._hidden = not self._active             # started while hidden: run as hidden
        return w

    def set_active(self, active):
        super().set_active(active)
        w = self._worker
        if w is not None and hasattr(w, "set_hidden"):
            w.set_hidden(not active)

    def on_error(self, msg):
        """CL5-fix 10: a source fault (the BLE Remote-ID scanner, an engine that is missing) is
        shown on the page, not only printed to stderr."""
        super().on_error(msg)
        self.set_chip("fault", str(msg)[:70], state="alert")

    def on_status(self, status):
        super().on_status(status)
        kind = status.get("layer_off")
        if kind:                                 # a lease layer gave the radio back: untick it
            self._layers.discard(kind)
            b = self._layer_btns.get(kind)
            if b is not None and b.isChecked():
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            self.set_chip("layer", "%s OFF — %s" % (KIND_LABEL.get(kind, kind),
                                                    status.get("why", "radio given back")),
                          state="warn")
            self._render()
        if "acquiring_layers" in status:
            self._acquiring = set(status["acquiring_layers"])
            self._update_busy()
        if "adsb" in status:
            self._adsb_health = status["adsb"]

    def _on_home_changed(self):
        """H5: HOME was set in SETTINGS: re-centre now; positions re-project as contacts refresh."""
        h = eventbus.home()
        self._contacts = {}
        self.map.set_home(h[0] if h else None, h[1] if h else None, known=h is not None)
        self._render()

    def on_panic(self):
        """PANIC (CL5-fix 5): every lease layer gives the radio back and is unticked; the BLE
        Remote-ID scan (not the SDR) is left as it is."""
        if not self.demo and self._worker is not None and hasattr(self._worker, "hold_off"):
            self._worker.hold_off("PANIC")
        return []

    def _color(self, kind, severity, trust=None):
        if trust == "unconfirmed":                   # P3: never the drone red on one advert
            return self._tok["warn"]
        return self._tok["alert"] if severity == "alert" else self._tok[KIND_TOKEN.get(kind, "text")]

    def _on_event(self, ev):
        if ev["type"] != "contact":
            return
        pl = ev["payload"]
        x, y = eventbus.to_xy(pl["lat"], pl["lon"])
        known = eventbus.home_set()                  # H5: no range/bearing from a guessed HOME
        self._contacts[pl["id"]] = {
            "id": pl["id"], "label": pl.get("label", pl["id"]), "kind": pl.get("kind", "air"),
            "x": x, "y": y, "alt": pl.get("alt"), "spd": pl.get("spd"),
            "severity": ev["severity"], "_ts": ev["ts"],
            "source": ev.get("source"), "trust": pl.get("trust"), "adverts": pl.get("adverts"),
            "rng": math.hypot(x, y) if known else None,
            "brg": (math.degrees(math.atan2(x, y)) % 360) if known else None}

    def _render(self):
        now = time.time()
        self._contacts = {c["id"]: c for c in self._contacts.values() if now - c["_ts"] < STALE_S}
        shown = [c for c in self._contacts.values() if c["kind"] in self._layers]
        no_home = not self.demo and not eventbus.home_set()
        self._home_cover.show(no_home)
        plotted = [] if no_home else shown
        self.map.set_contacts([(c["x"], c["y"]) for c in plotted],
                              labels=[c["label"] for c in plotted],
                              colors=[self._color(c["kind"], c["severity"], c.get("trust"))
                                      for c in plotted])
        rows = []
        for c in sorted(shown, key=lambda c: (c["rng"] is None, c["rng"] or 0, c["label"])):
            rows.append({"_id": c["id"], "label": c["label"],
                         "kind": KIND_LABEL.get(c["kind"], c["kind"]),
                         "rng": "%.0f" % c["rng"] if c["rng"] is not None else "—",
                         "alt": "%d" % c["alt"] if c["alt"] else "—",
                         "_src": c, "_colors": {"rng": self._color(c["kind"], c["severity"],
                                                                   c.get("trust"))}})
        self.feed.model.set_rows(rows)
        if self._selected is not None and self._selected not in {c["id"] for c in shown}:
            self._show_lost()
        text, state = self._layer_summary(shown)
        self.set_chip("sdr", text, state=state)
        if not rows:                                   # D4: the list says why it is empty
            live = self.demo or (self._adsb_health or {}).get("state") == "live"
            self.feed.set_empty("watching" if live else "offline",
                                "no contacts" if live else "NO LIVE LAYER", text)
        if not eventbus.home_set():
            self.set_chip("home", "HOME NOT SET — range/bearing hidden (SYSTEM › SETTINGS)",
                          state="warn")
        else:
            self._last_status.pop("home", None)
        self._update_busy()

    def _layer_summary(self, shown):
        """H10: per-layer health instead of one total that let a live APRS station hide a dead
        ADS-B feed. Every layer that is ON says its own count or state."""
        counts = {}
        for c in shown:
            counts[c["kind"]] = counts.get(c["kind"], 0) + 1
        parts, worst = [], "neutral"
        rank = {"neutral": 0, "warn": 1, "alert": 2}
        for k, lbl, _tok in KINDS:
            if k not in self._layers or k == "operator":
                continue
            n = counts.get(k, 0)
            word = "%s %d" % (lbl, n)
            st = "neutral"
            if k == "aircraft" and not self.demo:
                h = self._adsb_health or {}
                if h.get("state") == "stale":
                    age = h.get("age")
                    word = "ADS-B STALE%s" % (" %ds" % age if age is not None else "")
                    st = "alert"
                elif h.get("state") == "none":
                    word, st = "ADS-B NO FEED", "warn"
                elif not h:
                    word = "ADS-B —"
            elif n == 0 and not self.demo:
                word = "%s —" % lbl
            parts.append(word)
            if rank[st] > rank[worst]:
                worst = st
        return (" · ".join(parts) if parts else "NO LAYERS ON"), worst

    def _update_busy(self):
        """Derive RADIO BUSY from the single arbiter: a toggled-on lease-layer (or ADS-B) that the
        radio owner isn't shows BUSY — on the map rail and, edge-triggered, on the OPS alert strip."""
        if self.demo:
            return
        owner = radio_arbiter.arbiter.owner()
        ownerlbl = radio_arbiter.owner_label() or owner or "?"
        msgs, busy_now = [], set()
        for kind in sorted(set(getattr(self, "_acquiring", ())) & self._layers):
            msgs.append("%s: ACQUIRING — pausing readsb" % KIND_LABEL.get(kind, kind))
        for kind in ("station", "vessel"):
            if kind in self._layers and owner and owner != self.LEASE_NAME[kind]:
                msgs.append("%s: RADIO BUSY — held by %s" % (KIND_LABEL[kind], ownerlbl))
                busy_now.add(kind)
        if "aircraft" in self._layers and owner:
            msgs.append("ADS-B paused — radio held by %s" % ownerlbl)
            busy_now.add("aircraft")
        if msgs:
            self._busy_label.setText("  ·  ".join(msgs))
            self._busy_label.show()
        else:
            self._busy_label.hide()
        for kind in busy_now - self._busy_shown:     # OPS tile: alert when a layer becomes busy
            eventbus.bus.publish(eventbus.alert(
                "ATLAS", "%s RADIO BUSY — held by %s" % (KIND_LABEL.get(kind, kind), ownerlbl),
                severity="warn"))
        self._busy_shown = busy_now

    def _show(self, row):
        c = row.get("_src", {})
        self._selected = c.get("id")
        self.detail.set_hero(c.get("label", "—"), KIND_LABEL.get(c.get("kind"), ""))
        self.detail.set_rows([
            ("TYPE", KIND_LABEL.get(c.get("kind"), "—")),
            ("ALTITUDE", "%d ft" % c["alt"] if c.get("alt") else "—"),
            ("SPEED", "%d kt" % c["spd"] if c.get("spd") else "—"),
            ("RANGE", "%.0f nm" % c["rng"] if c.get("rng") is not None else "— (HOME NOT SET)"),
            ("BEARING", "%03d°" % c["brg"] if c.get("brg") is not None else "—")] + (
            [("SOURCE", SOURCE_TRUST[c["source"]])] if c.get("source") in SOURCE_TRUST else []) + (
            [("STATUS", "UNCONFIRMED · %s advert%s" % (
                c.get("adverts") or 0, "" if c.get("adverts") == 1 else "s"))]
            if c.get("trust") == "unconfirmed"
            else []))

    def _show_lost(self):
        """The selected contact is gone (stale or its layer hidden): say so, and drop its last fix
        so the card never reads as a current position (RA-CL1c F4)."""
        label = self.detail.hero.text()
        self._selected = None
        self.detail.set_hero(label, "LOST · no longer reported")
        self.detail.set_rows([("STATUS", "LOST")])

    def stop(self):
        try:
            eventbus.bus.published.disconnect(self._on_event)
        except (RuntimeError, TypeError):
            pass
        try:
            eventbus.bus.home_changed.disconnect(self._on_home_changed)
        except (RuntimeError, TypeError):
            pass
        if hasattr(self, "_timer"):
            self._timer.stop()
        super().stop()
