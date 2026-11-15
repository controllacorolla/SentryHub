"""RECON — survey + assess: Wi-Fi / BLE / network (key 6).

Since CL1 the counter-surveillance detectors live on their own page (SWEEP, sweep.py — the
DetectorWorker class stays here and is imported there, unchanged) and ENGAGE is global chrome: the
ENGAGEMENT slot in the top strip opens panels.EngagePanel.

Two tiers, wired to the legacy engines AS-IS:

  * PASSIVE (no gate): wifisurvey, blescan, rffinger, scout — receive-only, ungated by design.
  * ACTIVE (gated): wifipent, blepent, netpent, passaudit — every action goes through the engine's
    `prepare(...)` which calls `engagement.authorize_action(...)`. The gate is enforced by the
    ENGINE, not this UI: with no active engagement (or an out-of-scope target) prepare() returns no
    argv. This UI only reflects gate state and passes the shared evidence chain through — it NEVER
    routes around the gate, and it wires no new TX/attack path.

The ENGAGEMENT panel is the governance keystone: operator identity (opprofile), engagement scope
(engagement.start/end), the authorized-action trail, and the tamper-evident evidence chain.

Honesty: passive tools show real scan results or an honest standby when no adapter is present;
live never fabricates (demo is the only synthetic path, flagged SDR/SCAN-DEMO). Offscreen/offline
seams mean tests never open a real adapter or spawn a scan.
"""
import os
import random
import shutil
import subprocess
import sys

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp, _retain
from . import theme, eventbus
from .kit import ControlBar, FeedTable, micro, card
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SUBTABS = ("WIFI", "BLE", "NET", "RF")


def _offscreen():
    return bool(os.environ.get("PALISADE_OFFLINE") or
                os.environ.get("QT_QPA_PLATFORM") == "offscreen")


def _run_cmd(argv, timeout=12):
    """Run a passive scan command and return stdout text, or None under offscreen/offline or when
    the tool is absent — so tests/CI never spawn a real scan."""
    if _offscreen() or not argv:
        return None
    if not shutil.which(argv[0]):
        return None
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return None


# ======================= shared engagement gate =======================

def _engagement():
    import engagement
    return engagement


class GatedTool(QtWidgets.QFrame):
    """A card for one ACTIVE tool. It calls the engine's prepare() (which enforces
    engagement.authorize_action); it never bypasses the gate. With no engagement it shows
    'REQUIRES ENGAGEMENT'. Execution of any produced argv is device-only, behind a hermetic seam."""

    def __init__(self, title, domain, prepare_fn, actions, app, tok, target_hint="target", parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self._prepare = prepare_fn
        self._app = app
        self._tok = tok
        self._domain = domain
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lay.addWidget(micro("%s · gated" % title))
        self.state = QtWidgets.QLabel("")
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        row = QtWidgets.QHBoxLayout()
        self.target = QtWidgets.QLineEdit()
        self.target.setPlaceholderText(target_hint)
        row.addWidget(self.target, 1)
        lay.addLayout(row)
        self._btns = []
        brow = QtWidgets.QHBoxLayout()
        for act in actions:
            b = QtWidgets.QPushButton(act.upper())
            b.clicked.connect(lambda _=False, a=act: self._authorize(a))
            brow.addWidget(b)
            self._btns.append(b)
        brow.addStretch(1)
        lay.addLayout(brow)
        self.result = QtWidgets.QLabel("")
        self.result.setProperty("class", "note")
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(self.result)
        self.refresh()

    def refresh(self):
        active = _engagement().is_active()
        for b in self._btns:
            b.setEnabled(active)
        self.target.setEnabled(active)
        if active:
            info = _engagement().info()
            self.state.setStyleSheet("color:%s;" % self._tok["warn"])     # amber: armed, not healthy
            self.state.setText("◆ authorized scope: %s" % ", ".join(info["scope"][:4]))
        else:
            self.state.setStyleSheet("color:%s;" % self._tok["muted"])
            self.state.setText("○ REQUIRES ENGAGEMENT — open ENGAGEMENT in the top strip (E)")
            self.result.setText("")

    def _authorize(self, action):
        target = self.target.text().strip()
        if not target:
            self.result.setText("enter a %s first" % self._domain)
            return
        # the ENGINE gates this (engagement.authorize_action); we pass the shared evidence chain
        ok, why, argv = self._prepare(action, target, evidence_chain=self._app.evidence)
        if not ok:
            self.result.setStyleSheet("color:%s;" % self._tok["muted"])
            self.result.setText("DENIED: %s" % why)
            return
        self.result.setStyleSheet("color:%s;" % self._tok["warn"])        # AUTHORIZED is amber (D9)
        self.result.setText("AUTHORIZED: %s\n$ %s" % (why, " ".join(argv)))
        self._app.on_authorized(self._domain, action, target, argv)


# ======================= passive scan workers =======================

class WifiScanWorker(Worker):
    """wifisurvey: passive AP scan (iw scan -> parse_iw_scan). No gate, no TX."""

    def __init__(self, demo=True, iface="wlan0", parent=None):
        super().__init__(demo=demo, interval_ms=4000, parent=parent)
        self.iface = iface

    def step(self):
        import wifisurvey
        if self.demo:
            self.row.emit({"aps": _demo_aps(), "demo": True})
            return
        out = _run_cmd(wifisurvey.scan_argv(self.iface))
        if out is None:                     # no iw / no adapter / offscreen: honest standby
            self.status.emit({"standby": True, "sdr": {"text": "WIFI STANDBY — no adapter/iw",
                                                       "ok": False}})
            return
        aps = wifisurvey.parse_iw_scan(out)
        self.row.emit({"aps": aps})


class BleScanWorker(Worker):
    """blescan: passive BLE enumeration. No gate, no TX. Live needs bleak + an adapter; absent ->
    honest standby. The bleak scan is behind a seam so tests never open a real adapter."""

    def __init__(self, demo=True, parent=None):
        super().__init__(demo=demo, interval_ms=3000, parent=parent)

    def _scan_adverts(self):
        if _offscreen():
            return None
        import importlib.util
        if importlib.util.find_spec("bleak") is None:
            return None
        return None            # real bleak wiring is device-only; dev host returns no feed

    def step(self):
        import blescan
        if self.demo:
            self.row.emit({"devs": _demo_ble(blescan), "demo": True})
            return
        adverts = self._scan_adverts()
        if adverts is None:
            self.status.emit({"standby": True, "sdr": {"text": "BLE STANDBY — no bleak/adapter",
                                                       "ok": False}})
            return
        devs = blescan.Devices()
        for adv in adverts:
            devs.ingest(adv)
        self.row.emit({"devs": [_ble_row(d) for d in devs.active()]})


class DetectorWorker(Worker):
    """COUNTER detectors (bugsweep / jammer / imsicatch / gnss): receive-only. Live needs a feed
    (SDR sweep / modem / gpsd); with none it reports honest standby. Demo synthesises a feed, runs
    the real detector AS-IS, and raises alerts. NO TX / jam / attack path anywhere."""

    def __init__(self, demo=True, kind="jammer", parent=None):
        super().__init__(demo=demo, interval_ms=1500, parent=parent)
        self.kind = kind
        self._det = None
        self._n = 0

    def step(self):
        if not self.demo:
            self.status.emit({"standby": True,
                              "sdr": {"text": "%s STANDBY — no feed" % self.kind.upper(),
                                      "ok": False}})
            return
        alert = self._demo_detect()
        self._n += 1
        self.row.emit({"kind": self.kind, "n": self._n, "alert": alert, "demo": True})

    def _demo_sweep(self, emitter):
        """A synthetic rtl_power-style sweep: list of (freq_hz, power_db), as the detectors expect
        (freqs in the 430 MHz UHF band so bugsweep's suspect-band filter can match)."""
        bins = [(430_000_000 + i * 100_000, -100 + 3 * random.gauss(0, 1)) for i in range(64)]
        if emitter:
            c = random.randint(5, 58)
            for j in range(c, c + 3):
                bins[j] = (bins[j][0], bins[j][1] + random.randint(20, 45))
        return bins

    def _demo_detect(self):
        if self.kind in ("bugsweep", "jammer"):
            mod = __import__(self.kind)
            if self._det is None:
                self._det = (mod.Sweeper() if self.kind == "bugsweep"
                             else mod.JammingDetector())
                for _ in range(4):
                    self._det.learn(self._demo_sweep(False))
            if self.kind == "bugsweep":              # sweep() -> suspect list
                sus = mod.find_suspects(self._det.sweep(self._demo_sweep(random.random() < 0.3)))
                return ("bug", "%d suspect emitter(s)" % len(sus)) if sus else None
            # jammer: feed() returns a sustained-interference alert STRING (or None) directly
            alert = self._det.feed(self._demo_sweep(random.random() < 0.5))
            return ("jam", alert) if alert else None
        if self.kind == "imsicatch":
            import imsicatch
            base = {"cid": 123, "lac": 1, "mcc": 310, "mnc": 260, "rxlevel": -70, "arfcn": 128}
            if self._det is None:
                self._det = imsicatch.IMSICatcherDetector()
                self._det.learn(base)
            obs = dict(base)
            if random.random() < 0.3:
                obs.update(cid=66613, rxlevel=-35, lac=999)       # a suspicious new cell
            flags = self._det.observe(obs)                        # -> [(name, text, severity), ...]
            if flags:
                return ("imsi", "; ".join(f[1] for f in flags))
            return None
        if self.kind == "gnss":
            import gnss
            sats = [{"cn0": 38 + random.randint(-3, 3)} for _ in range(8)]
            if random.random() < 0.2:
                sats = [{"cn0": 12} for _ in range(2)]            # degraded -> jamming suspected
            jammed, _score, reason = gnss.jamming_check(sats)
            return ("gnss", reason) if jammed else None
        return None


# ---- demo data (synthetic, flagged) ----
def _demo_aps():
    secs = ["WPA2/3", "WPA2/3", "open", "WPA", "WPA2/3"]
    names = ["Cafe-Guest", "HOME-5G", "xfinitywifi", "Acme-Corp", "Pixel_1234"]
    out = []
    for i, (n, s) in enumerate(zip(names, secs)):
        out.append({"bssid": "aa:bb:cc:%02x:%02x:%02x" % (i, i * 7 % 256, i * 13 % 256),
                    "ssid": n, "channel": random.choice([1, 6, 11, 36, 44]),
                    "signal": -random.randint(38, 86), "security": s})
    return out


def _demo_ble(blescan):
    out = []
    for i, (n, kind) in enumerate([("Fitbit", "wearable"), ("", "beacon"),
                                   ("Keyboard", "hid"), ("Tile", "tracker"), ("", "unknown")]):
        out.append({"address": "11:22:33:%02x:%02x:%02x" % (i, i * 9 % 256, i * 3 % 256),
                    "name": n or "—", "vendor": blescan.oui_vendor("11:22:33:00:00:00") or "unknown",
                    "kind": kind, "rssi": -random.randint(40, 92)})
    return out


def _ble_row(d):
    return {"address": d.get("address", ""), "name": d.get("name") or "—",
            "vendor": d.get("vendor") or "unknown", "kind": d.get("kind", ""),
            "rssi": d.get("rssi", "")}


# ======================= the app =======================

class ReconApp(PalisadeApp):
    TITLE = "RECON"
    LEASE = None          # RECON uses wifi/BLE/network adapters, not the SDR dongle

    SUBTABS = SUBTABS

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._subtab = "WIFI"
        self._gated = []                                 # cards to refresh on gate change
        import evidence
        self.evidence = evidence.EvidenceChain()        # one tamper-evident chain per session
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    def current_subtab(self):
        return self._subtab

    def switch_subtab(self, name):
        self._switch(name)

    def on_gate_changed(self):
        self._refresh_gate()             # the ENGAGEMENT panel (or PANIC) changed the gate

    # ---- layout ----
    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.stack = QtWidgets.QStackedWidget()
        self._pages = {
            "WIFI": self._wifi_page(), "BLE": self._ble_page(), "NET": self._net_page(),
            "RF": self._rf_page()}
        for t in SUBTABS:
            self.stack.addWidget(self._pages[t])
        lay.addWidget(self.stack, 1)
        self._sync_tabs()
        return body

    # a passive scan page: a feed + a worker started on show
    def _scan_page(self, columns, note):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        bar = ControlBar()
        bar.add_stretch()
        bar.lay.addWidget(micro(note))
        pl.addWidget(bar)
        feed = FeedTable(columns)
        pl.addWidget(feed, 1)
        page._feed = feed
        return page

    def _wifi_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(micro("WIFISURVEY · passive · no deauth/inject"))
        self.wifi_feed = FeedTable([("ssid", "SSID"), ("bssid", "BSSID"),
                                    ("ch", "CH"), ("sig", "dBm"), ("sec", "SEC")])
        left.addWidget(self.wifi_feed, 1)
        split.addLayout(left, 3)
        import wifipent
        self.wifi_gated = GatedTool("WIFIPENT", "BSSID", wifipent.prepare,
                                    ["deauth", "pmkid", "handshake"], self, self._tok,
                                    "target BSSID (aa:bb:cc:dd:ee:ff)")
        self._gated.append(self.wifi_gated)
        split.addWidget(self.wifi_gated, 2)
        pl.addLayout(split, 1)
        return page

    def _ble_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(micro("BLESCAN · passive enumeration"))
        self.ble_feed = FeedTable([("name", "NAME"), ("address", "ADDRESS"),
                                   ("vendor", "VENDOR"), ("kind", "KIND"), ("rssi", "dBm")])
        left.addWidget(self.ble_feed, 1)
        split.addLayout(left, 3)
        import blepent
        # only the ops that need no per-characteristic handle/value input (read/write need a handle
        # + value the single target field can't supply, so they'd be dead buttons) — device-only
        self.ble_gated = GatedTool("BLEPENT", "address", blepent.prepare,
                                   ["enum", "characteristics"], self, self._tok,
                                   "target BLE address")
        self._gated.append(self.ble_gated)
        split.addWidget(self.ble_gated, 2)
        pl.addLayout(split, 1)
        return page

    def _net_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        import netpent
        import passaudit
        self.net_gated = GatedTool("NETPENT", "target", netpent.prepare,
                                   ["discover", "portscan", "services"], self, self._tok,
                                   "target IP / host / CIDR")
        self.pass_gated = GatedTool("PASSAUDIT", "target", passaudit.prepare,
                                    ["convert", "hashcat", "aircrack"], self, self._tok,
                                    "capture / hash target")
        self._gated += [self.net_gated, self.pass_gated]
        pl.addWidget(self.net_gated)
        pl.addWidget(self.pass_gated)
        pl.addStretch(1)
        return page

    def _rf_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        c = card(2)
        cl = QtWidgets.QVBoxLayout(c)
        cl.addWidget(micro("RFFINGER · RF device fingerprinting (passive)"))
        self.rf_note = QtWidgets.QLabel("No capture feed — fingerprinting runs on IQ from PRISM / a "
                                        "capture file. Standby until a feed is wired on-device.")
        self.rf_note.setProperty("class", "note")
        self.rf_note.setWordWrap(True)
        cl.addWidget(self.rf_note)
        pl.addWidget(c)
        c2 = card(2)
        c2l = QtWidgets.QVBoxLayout(c2)
        c2l.addWidget(micro("SCOUT · site survey (passive)"))
        self.scout_note = QtWidgets.QLabel("Network / Wi-Fi site survey (own-subnet probing only). "
                                           "Device-only; standby on the dev host.")
        self.scout_note.setProperty("class", "note")
        self.scout_note.setWordWrap(True)
        c2l.addWidget(self.scout_note)
        pl.addWidget(c2)
        pl.addStretch(1)
        return page

    def _refresh_gate(self):
        for g in self._gated:
            g.refresh()

    def on_authorized(self, domain, action, target, argv):
        """An active tool produced an authorized command. Announce it; the trail is in the
        ENGAGEMENT panel. Execution of the argv is device-only; nothing is spawned here."""
        eventbus.bus.publish(eventbus.alert(
            "RECON", "authorized %s:%s on %s" % (domain, action, target), severity="warn",
            action=action, target=target))
        self.request.emit("gate_changed", None)

    # ---- sub-tab switching ----
    def _switch(self, tab):
        self._subtab = tab
        self.stack.setCurrentWidget(self._pages[tab])
        self._sync_tabs()

    def _sync_tabs(self):
        self._sync_rail()

    # ---- lifecycle: passive scan + counter detector workers ----
    def start(self):
        if self._started:
            return
        super().start()        # base starts make_worker() (None here) + lease (none)
        # RECON runs the passive wifi/ble scans (the detectors moved to SWEEP with CL1)
        self._workers = []
        self._workers.append(self._spawn(WifiScanWorker(demo=self.demo), self._on_wifi))
        self._workers.append(self._spawn(BleScanWorker(demo=self.demo), self._on_ble))
        self._refresh_gate()

    def _spawn(self, worker, on_row):
        worker.row.connect(on_row)
        worker.status.connect(self.on_status)
        worker.error.connect(self.on_error)
        worker.start()
        return worker

    def stop(self):
        if self._stopped:
            return
        for w in getattr(self, "_workers", []):
            w.stop()
            w.quit()
            w.wait(3000)
            _retain(w)
        self._workers = []
        super().stop()

    # ---- passive results -> feed + event bus ----
    def _on_wifi(self, msg):
        aps = msg.get("aps", [])
        live = not msg.get("demo")                     # synthetic demo stays local, off the OPS bus
        rows = []
        for ap in aps:
            rows.append({"ssid": ap.get("ssid") or "<hidden>", "bssid": ap.get("bssid", ""),
                         "ch": str(ap.get("channel") or "—"), "sig": str(int(ap["signal"]))
                         if ap.get("signal") is not None else "—",
                         "sec": ap.get("security", "")})
            if live and ap.get("security") == "open":  # real open network -> OPS alert
                eventbus.bus.publish(eventbus.alert(
                    "RECON", "open Wi-Fi: %s" % (ap.get("ssid") or ap.get("bssid")),
                    severity="warn"))
        self.wifi_feed.model.set_rows(rows)
        if live:
            for ap in aps:                             # real scan results on the bus (decode)
                eventbus.bus.publish(eventbus.decode("RECON", "WIFI", ap.get("bssid", ""),
                                                     ap.get("ssid") or "<hidden>"))
        self.header.set_chip("sdr", "%d AP" % len(rows), state="neutral")

    def _on_ble(self, msg):
        devs = msg.get("devs", [])
        self.ble_feed.model.set_rows([{"name": d["name"], "address": d["address"],
                                       "vendor": d["vendor"], "kind": d["kind"],
                                       "rssi": str(d["rssi"])} for d in devs])
        if not msg.get("demo"):                        # real decodes only on the bus
            for d in devs:
                eventbus.bus.publish(eventbus.decode("RECON", "BLE", d["address"], d["name"]))
