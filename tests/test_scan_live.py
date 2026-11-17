"""SCAN-1 / SCAN-2 — RECON's Wi-Fi and BLE surveys do a real live scan on the device as installed.

SCAN-1: `iw dev wlan0 scan passive` is refused for a normal user ("Operation not permitted", needs
        CAP_NET_ADMIN), so the Wi-Fi tab was empty as shipped. RECON now falls back to
        NetworkManager (nmcli) and labels that path ACTIVE (NM probes), never passive.
SCAN-2: the BLE tab said "BLE NOT IMPLEMENTED". It now scans live via bleak (BlueZ D-Bus) or, when
        bleak is missing, `bluetoothctl scan on`: address, name, RSSI, updating every second.
        Listen only — no connect, no pair.

No real adapter is opened: scans go through patched seams or a fake `bluetoothctl` on PATH.
"""
import os
import stat
import sys
import textwrap
import time
import types

import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402

import blescan  # noqa: E402
import doctor  # noqa: E402
import wifisurvey  # noqa: E402


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _close(p):
    p.stop()
    p.deleteLater()


# ============================================================ SCAN-1 Wi-Fi: nmcli fallback

NMCLI_OUT = textwrap.dedent("""\
    Cafe\\:Guest:AA\\:BB\\:CC\\:DD\\:EE\\:01:6:78:
    HOME-5G:AA\\:BB\\:CC\\:DD\\:EE\\:02:36:55:WPA2
    :AA\\:BB\\:CC\\:DD\\:EE\\:03:11:40:WPA2 802.1X
    Mixed:AA\\:BB\\:CC\\:DD\\:EE\\:04:1:30:WPA2 WPA3
    Enhanced:AA\\:BB\\:CC\\:DD\\:EE\\:05:149:20:OWE
    garbage line
    """)


def test_scan1_parse_nmcli_terse_escapes_and_security():
    aps = wifisurvey.parse_nmcli(NMCLI_OUT)
    assert [a["bssid"] for a in aps] == ["aa:bb:cc:dd:ee:0%d" % i for i in range(1, 6)]
    assert aps[0]["ssid"] == "Cafe:Guest" and aps[0]["channel"] == 6
    assert [a["security"] for a in aps] == ["open", "WPA2-PSK", "WPA2-EAP", "WPA2/WPA3", "OWE"]
    # NM's SIGNAL is a 0-100 quality, never passed off as dBm
    assert aps[0]["signal"] is None and aps[0]["quality"] == 78


@pytest.mark.parametrize("sec,want", [
    ("", "open"), ("--", "open"), ("WEP", "WEP"), ("WPA1", "WPA"), ("WPA1 WPA2", "WPA2-PSK"),
    ("WPA3", "WPA3-SAE"), ("WPA3 802.1X", "WPA3-EAP"), ("OWE_TRANSITION", "OWE"),
    ("FOO", "FOO")])
def test_scan1_nm_security_only_empty_is_open(sec, want):
    assert wifisurvey.nm_security(sec) == want


def test_scan1_nmcli_argv_is_a_list_scan_on_the_interface():
    argv = wifisurvey.nmcli_scan_argv("wlan1")
    assert argv[:2] == ["nmcli", "-t"] and argv[-2:] == ["ifname", "wlan1"]
    assert "list" in argv and "connect" not in argv


def _fake_scans(monkeypatch, results):
    from palisade_qt import recon
    calls = []

    def fake(argv, timeout=12):
        calls.append(argv[0])
        return results[argv[0]]
    monkeypatch.setattr(recon, "_run_scan", fake)
    return calls


def _run_wifi_step():
    from palisade_qt.recon import WifiScanWorker
    w = WifiScanWorker(demo=False)
    rows, st = [], []
    w.row.connect(rows.append)
    w.status.connect(st.append)
    w.step()
    return rows, st


def test_scan1_iw_refused_falls_back_to_nmcli(monkeypatch):
    calls = _fake_scans(monkeypatch, {
        "iw": (None, "exit 255 — command failed: Operation not permitted (-1)"),
        "nmcli": (NMCLI_OUT, None)})
    rows, st = _run_wifi_step()
    assert calls == ["iw", "nmcli"]
    assert rows and rows[-1]["path"] == "nmcli" and len(rows[-1]["aps"]) == 5
    assert "not permitted" in rows[-1]["iw_refused"] and not st


def test_scan1_iw_success_stays_passive_and_never_runs_nmcli(monkeypatch):
    calls = _fake_scans(monkeypatch, {"iw": ("BSS aa:bb:cc:dd:ee:ff(on wlan0)\n\tSSID: X\n", None)})
    rows, _st = _run_wifi_step()
    assert calls == ["iw"] and rows[-1]["path"] == "iw" and rows[-1]["aps"][0]["ssid"] == "X"


def test_scan1_both_fail_is_scan_failed_with_both_reasons(monkeypatch):
    _fake_scans(monkeypatch, {"iw": (None, "exit 255 — Operation not permitted"),
                              "nmcli": (None, "exit 8 — Error: NetworkManager is not running.")})
    rows, st = _run_wifi_step()
    assert rows == []
    txt = st[-1]["sdr"]["text"]
    assert txt.startswith("WIFI SCAN FAILED") and "not permitted" in txt and "NetworkManager" in txt


def test_scan1_neither_tool_is_standby_not_failure(monkeypatch):
    _fake_scans(monkeypatch, {"iw": (None, "iw not installed"),
                              "nmcli": (None, "nmcli not installed")})
    _rows, st = _run_wifi_step()
    assert st[-1]["sdr"]["text"].startswith("WIFI STANDBY")


def test_scan1_offline_never_runs_nmcli(monkeypatch):
    calls = _fake_scans(monkeypatch, {"iw": (None, "offline")})
    _rows, st = _run_wifi_step()
    assert calls == ["iw"] and "STANDBY" in st[-1]["sdr"]["text"]


def test_scan1_page_labels_the_nmcli_path_active_and_shows_percent():
    _app()
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False)
    p._on_wifi({"aps": wifisurvey.parse_nmcli(NMCLI_OUT), "path": "nmcli"})
    mode = p.wifi_mode.text().lower()          # micro() upper-cases
    assert "active scan" in mode and "passive (iw" not in mode
    p._on_wifi({"aps": [{"bssid": "aa:bb:cc:dd:ee:ff", "ssid": "X", "channel": 6,
                         "signal": -61.0, "security": "WPA2-PSK"}], "path": "iw"})
    mode = p.wifi_mode.text().lower()
    assert "passive (iw" in mode and "active" not in mode
    _close(p)


def test_scan1_signal_column_formats():
    _app()
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False)
    seen = []
    orig = p.wifi_feed.model.set_rows
    p.wifi_feed.model.set_rows = lambda rows: (seen.append(rows), orig(rows))
    p._on_wifi({"aps": [{"bssid": "a", "ssid": "N", "channel": 1, "signal": None, "quality": 64,
                         "security": "open"},
                        {"bssid": "b", "ssid": "I", "channel": 1, "signal": -70.0,
                         "security": "open"}], "path": "nmcli"})
    assert [r["sig"] for r in seen[-1]] == ["64%", "-70 dBm"]
    _close(p)


# ============================================================ SCAN-2 BLE: bluetoothctl parser

@pytest.mark.parametrize("line,want", [
    ("[NEW] Device AA:BB:CC:DD:EE:01 Pixel Buds", ("AA:BB:CC:DD:EE:01", {"new": True,
                                                                         "name": "Pixel Buds"})),
    ("[NEW] Device aa:bb:cc:dd:ee:02 AA-BB-CC-DD-EE-02", ("AA:BB:CC:DD:EE:02", {"new": True})),
    ("[CHG] Device AA:BB:CC:DD:EE:03 RSSI: -67", ("AA:BB:CC:DD:EE:03", {"rssi": -67})),
    ("[CHG] Device AA:BB:CC:DD:EE:03 RSSI: 0xffffffbd (-67)", ("AA:BB:CC:DD:EE:03", {"rssi": -67})),
    ("\x1b[0;93m[CHG]\x1b[0m Device AA:BB:CC:DD:EE:04 Name: Tile",
     ("AA:BB:CC:DD:EE:04", {"name": "Tile"})),
    ("[bluetooth]# [CHG] Device AA:BB:CC:DD:EE:05 ManufacturerData Key: 0x004c",
     ("AA:BB:CC:DD:EE:05", {"mfr": 0x4C})),
    ("[CHG] Device AA:BB:CC:DD:EE:06 UUIDs: 0000fffa-0000-1000-8000-00805f9b34fb",
     ("AA:BB:CC:DD:EE:06", {"uuid": "0000fffa-0000-1000-8000-00805f9b34fb"})),
    ("[NEW] Device AA:BB:CC:DD:EE:07 Access denied", ("AA:BB:CC:DD:EE:07",
                                                       {"new": True, "name": "Access denied"})),
    ("[DEL] Device AA:BB:CC:DD:EE:08 gone", None),
    ("[CHG] Device AA:BB:CC:DD:EE:09 TxPower: 4", None),
    ("Discovery started", ("+", None)),
    ("[CHG] Controller 00:11:22:33:44:55 Discovering: yes", ("+", None)),
    ("Failed to start discovery: org.bluez.Error.NotReady", ("!", "adapter is powered off")),
    ("No default controller available", ("!", "no Bluetooth adapter")),
    ("Failed to start discovery: org.bluez.Error.NotAuthorized",
     ("!", "not authorized by BlueZ (D-Bus policy)")),
    ("", None),
])
def test_scan2_bluetoothctl_line_parser(line, want):
    assert blescan.parse_bluetoothctl_line(line) == want


def test_scan2_devices_listing_names():
    names = blescan.parse_bluetoothctl_devices(
        "Device AA:BB:CC:DD:EE:01 Fitbit\nDevice AA:BB:CC:DD:EE:02 AA-BB-CC-DD-EE-02\njunk\n")
    assert names == {"AA:BB:CC:DD:EE:01": "Fitbit"}


def test_scan2_scan_argv_listens_only():
    argv = blescan.bluetoothctl_scan_argv(8)
    assert argv == ["bluetoothctl", "--timeout", "8", "scan", "on"]
    assert not {"pair", "connect", "trust"} & set(argv)


# ============================================================ SCAN-2 BLE worker (fake bluetoothctl)

FAKE_BTCTL = r'''#!/usr/bin/env python3
import os, sys, time
log = os.environ["FAKE_BTCTL_LOG"]
with open(log, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
mode = os.environ.get("FAKE_BTCTL_MODE", "ok")
if sys.argv[1:] == ["devices"]:
    print("Device AA:BB:CC:00:00:01 Fitbit Charge")
    print("Device AA:BB:CC:00:00:09 Old Headphones")
    sys.exit(0)
def out(s):
    print(s, flush=True)
if mode == "notready":
    out("Failed to start discovery: org.bluez.Error.NotReady")
    sys.exit(1)
out("[NEW] Controller 00:11:22:33:44:55 uconsole [default]")
out("[NEW] Device AA:BB:CC:00:00:09 Old Headphones")          # cached, NOT heard
out("Discovery started")
out("[CHG] Controller 00:11:22:33:44:55 Discovering: yes")
out("[NEW] Device AA:BB:CC:00:00:02 Tile")                    # newly heard
out("[CHG] Device AA:BB:CC:00:00:01 RSSI: 0xffffffc4 (-60)")  # cached name, heard now
out("[CHG] Device AA:BB:CC:00:00:03 ManufacturerData Key: 0x004c")
out("[CHG] Device AA:BB:CC:00:00:03 RSSI: -75")
if mode == "hang":
    time.sleep(60)
time.sleep(0.6)
out("[CHG] Device AA:BB:CC:00:00:01 RSSI: -58")
time.sleep(0.6)
'''


@pytest.fixture
def fake_btctl(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    exe = d / "bluetoothctl"
    exe.write_text(FAKE_BTCTL.replace("#!/usr/bin/env python3", "#!" + sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "argv.log"
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("FAKE_BTCTL_LOG", str(log))
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda n, *a: None if n == "bleak" else real(n, *a))
    from palisade_qt import recon
    monkeypatch.setattr(recon, "_offscreen", lambda: False)
    monkeypatch.setattr(recon.BleScanWorker, "WINDOW_S", 3)
    monkeypatch.setattr(recon.BleScanWorker, "EMIT_MS", 200)
    monkeypatch.setattr(recon.BleScanWorker, "RETRY_MS", 50)
    return log


def test_scan2_bluetoothctl_backend_lists_heard_devices_live(fake_btctl):
    from palisade_qt.recon import BleScanWorker
    w = BleScanWorker(demo=False)
    rows, st = [], []
    w.row.connect(rows.append)
    w.status.connect(st.append)
    w.step()
    assert w.backend == "bluetoothctl" and not st
    assert len(rows) >= 3                                  # the table updates during the window
    last = {d["address"]: d for d in rows[-1]["devs"]}
    assert "AA:BB:CC:00:00:09" not in last                 # cached-only device: not a sighting
    assert last["AA:BB:CC:00:00:01"]["name"] == "Fitbit Charge"
    assert last["AA:BB:CC:00:00:01"]["rssi"] == -58        # latest RSSI wins
    assert last["AA:BB:CC:00:00:02"]["name"] == "Tile" and last["AA:BB:CC:00:00:02"]["rssi"] is None
    assert last["AA:BB:CC:00:00:03"]["kind"] == "apple"
    calls = fake_btctl.read_text().split("\n")
    assert all(not ({"pair", "connect", "trust"} & set(c.split())) for c in calls)


def test_scan2_adapter_off_is_scan_failed_with_the_reason(fake_btctl, monkeypatch):
    monkeypatch.setenv("FAKE_BTCTL_MODE", "notready")
    from palisade_qt.recon import BleScanWorker
    w = BleScanWorker(demo=False)
    st = []
    w.status.connect(st.append)
    w.step()
    assert st and st[-1]["sdr"]["text"] == "BLE SCAN FAILED — adapter is powered off"


def test_scan2_stop_mid_window_kills_bluetoothctl_quickly(fake_btctl, monkeypatch):
    monkeypatch.setenv("FAKE_BTCTL_MODE", "hang")
    from palisade_qt import recon
    monkeypatch.setattr(recon.BleScanWorker, "WINDOW_S", 60)
    import subprocess
    procs = []
    real = subprocess.Popen

    def spy(*a, **k):
        p = real(*a, **k)
        procs.append(p)
        return p
    monkeypatch.setattr(recon.subprocess, "Popen", spy)
    w = recon.BleScanWorker(demo=False)
    w.start()
    t = time.time()
    while not procs and time.time() - t < 5:
        time.sleep(0.05)
    time.sleep(0.5)
    t0 = time.monotonic()
    w.stop()
    assert w.wait(4000)
    assert time.monotonic() - t0 < 3.5
    assert procs and procs[0].poll() is not None           # bluetoothctl is gone


def test_scan2_pause_ends_the_window(fake_btctl, monkeypatch):
    monkeypatch.setenv("FAKE_BTCTL_MODE", "hang")
    from palisade_qt import recon
    monkeypatch.setattr(recon.BleScanWorker, "WINDOW_S", 60)
    w = recon.BleScanWorker(demo=False)
    w.start()
    time.sleep(1.0)
    t0 = time.monotonic()
    w.pause(True)
    time.sleep(2.5)
    # the window ended on pause: the worker is idle in its paused wait, not in a scan
    w.stop()
    assert w.wait(3000) and time.monotonic() - t0 < 6


# ============================================================ SCAN-2 BLE worker (fake bleak)

def test_scan2_bleak_backend_active_scan_rows(monkeypatch):
    from palisade_qt import recon
    made = {}

    class Dev:
        def __init__(self, a, n):
            self.address, self.name = a, n

    class Adv:
        def __init__(self, rssi, name=None, uuids=(), mfr=None):
            self.rssi, self.local_name = rssi, name
            self.service_uuids, self.manufacturer_data = list(uuids), mfr or {}

    class FakeScanner:
        def __init__(self, detection_callback=None, **kw):
            made.update(kw)
            self.cb = detection_callback

        async def start(self):
            self.cb(Dev("aa:bb:cc:00:00:11", None), Adv(-50, "Keyboard"))
            self.cb(Dev("aa:bb:cc:00:00:12", None),
                    Adv(-80, uuids=["0000fffa-0000-1000-8000-00805f9b34fb"]))
            self.cb(Dev("aa:bb:cc:00:00:11", None), Adv(-49))     # no name: keeps "Keyboard"

        async def stop(self):
            made["stopped"] = True

    fake = types.ModuleType("bleak")
    fake.BleakScanner = FakeScanner
    monkeypatch.setitem(sys.modules, "bleak", fake)
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda n, *a: object() if n == "bleak" else real(n, *a))
    monkeypatch.setattr(recon, "_offscreen", lambda: False)
    monkeypatch.setattr(recon.BleScanWorker, "WINDOW_S", 0.5)
    monkeypatch.setattr(recon.BleScanWorker, "EMIT_MS", 100)
    w = recon.BleScanWorker(demo=False)
    rows, st = [], []
    w.row.connect(rows.append)
    w.status.connect(st.append)
    w.step()
    assert made.get("scanning_mode") == "active" and made.get("stopped") and not st
    last = {d["address"]: d for d in rows[-1]["devs"]}
    assert last["AA:BB:CC:00:00:11"]["name"] == "Keyboard" and last["AA:BB:CC:00:00:11"]["rssi"] == -49
    assert last["AA:BB:CC:00:00:12"]["kind"] == "drone"
    assert rows[-1]["devs"][0]["address"] == "AA:BB:CC:00:00:11"       # strongest first


def test_scan2_bleak_error_maps_to_a_reason(monkeypatch):
    from palisade_qt import recon

    class FakeScanner:
        def __init__(self, **kw):
            pass

        async def start(self):
            raise RuntimeError("[org.bluez.Error.NotReady] Resource Not Ready")

        async def stop(self):
            pass
    fake = types.ModuleType("bleak")
    fake.BleakScanner = FakeScanner
    monkeypatch.setitem(sys.modules, "bleak", fake)
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda n, *a: object() if n == "bleak" else real(n, *a))
    monkeypatch.setattr(recon, "_offscreen", lambda: False)
    monkeypatch.setattr(recon.BleScanWorker, "RETRY_MS", 10)
    w = recon.BleScanWorker(demo=False)
    st = []
    w.status.connect(st.append)
    w.step()
    assert st[-1]["sdr"]["text"].startswith("BLE SCAN FAILED — adapter is powered off")


def test_scan2_offscreen_never_opens_an_adapter():
    from palisade_qt.recon import BleScanWorker
    w = BleScanWorker(demo=False)
    st = []
    w.status.connect(st.append)
    w.step()
    assert "STANDBY" in st[-1]["sdr"]["text"] and w.stopping


def test_scan2_ble_scan_pauses_off_the_ble_tab():
    _app()
    from palisade_qt.recon import ReconApp, BleScanWorker
    p = ReconApp(demo=True)
    p.set_active(True)
    p.start()
    w = next(x for x in p._workers if isinstance(x, BleScanWorker))
    assert w.paused                       # WIFI is the first sub-tab
    p._switch("BLE")
    assert not w.paused
    p.set_active(False)
    assert w.paused
    _close(p)


def test_scan2_page_label_says_active_discovery_listen_only():
    _app()
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False)
    t = p.ble_mode.text().lower()
    assert "active" in t and "no connect/pair" in t and "passive" not in t
    p._on_ble({"devs": [{"address": "AA", "name": "—", "vendor": "unknown", "kind": "",
                         "rssi": None}], "backend": "bluetoothctl"})
    p._on_ble({"devs": [{"address": "AA", "name": "—", "vendor": "unknown", "kind": "",
                         "rssi": -70}], "backend": "bluetoothctl"})
    assert p._ble_published == {"AA"}     # one bus decode per device, not one per second
    _close(p)


# ============================================================ doctor reports the scan paths

def _run(table):
    def run(argv, timeout=10):
        return table.get(argv[0], (1, ""))
    return run


def test_scan1_doctor_wifi_paths():
    which = {"iw": "/usr/sbin/iw", "getcap": "/usr/sbin/getcap", "nmcli": "/usr/bin/nmcli"}.get
    ok, detail, _ = doctor.chk_wifi_scan(run=_run({"getcap": (0, "/usr/sbin/iw cap_net_admin=ep")}),
                                         which=which, euid=1000)
    assert ok is True and "passive" in detail
    ok, detail, fix = doctor.chk_wifi_scan(run=_run({"getcap": (0, ""), "nmcli": (0, "running")}),
                                           which=which, euid=1000)
    assert ok is None and "ACTIVE" in detail and "NetworkManager" in detail
    assert "setcap cap_net_admin+ep" in fix and "owner decision" in fix
    ok, detail, _ = doctor.chk_wifi_scan(run=_run({"nmcli": (8, "not running")}), which=which,
                                         euid=1000)
    assert ok is False
    ok, _d, _f = doctor.chk_wifi_scan(run=_run({}), which=which, euid=0)
    assert ok is True


def test_scan2_doctor_ble(tmp_path):
    sysfs = tmp_path / "bt"
    sysfs.mkdir()
    which = {"bluetoothctl": "/usr/bin/bluetoothctl"}.get
    ok, d, _ = doctor.chk_ble_scan(run=_run({}), which=which, find=lambda m: False, sysfs=str(sysfs))
    assert ok is False and "adapter" in d
    (sysfs / "hci0").mkdir()
    ok, d, fix = doctor.chk_ble_scan(run=_run({"bluetoothctl": (0, "Powered: no")}), which=which,
                                     find=lambda m: False, sysfs=str(sysfs))
    assert ok is None and "powered off" in d and "power on" in fix
    ok, d, _ = doctor.chk_ble_scan(run=_run({"bluetoothctl": (0, "Powered: yes")}), which=which,
                                   find=lambda m: m == "bleak", sysfs=str(sysfs))
    assert ok is True and d.startswith("bleak")
    ok, d, _ = doctor.chk_ble_scan(run=_run({}), which=lambda n: None, find=lambda m: False,
                                   sysfs=str(sysfs))
    assert ok is False and "backend" in d


def test_doctor_lists_both_scan_checks():
    names = [n for _, rows in doctor.CHECKS for n, _ in rows]
    assert "Wi-Fi scan" in names and "BLE scan" in names


# ============================================================ SCAN-3 ATLAS Remote-ID without --experimental

def test_scan3_remote_id_falls_back_to_active_when_bluez_has_no_monitor(monkeypatch):
    from palisade_qt import atlas
    made = []

    class FakeScanner:
        def __init__(self, detection_callback=None, **kw):
            made.append(kw)
            self.kw = kw

        async def start(self):
            if self.kw.get("scanning_mode") == "passive":
                raise RuntimeError("passive scanning on Linux requires BlueZ >= 5.56 with "
                                   "--experimental enabled and Linux kernel >= 5.10")

        async def stop(self):
            pass
    fake = types.ModuleType("bleak")
    fake.BleakScanner = FakeScanner
    monkeypatch.setitem(sys.modules, "bleak", fake)
    monkeypatch.setattr(atlas, "_seam_offscreen", lambda: False)
    faults = []
    src = atlas.RidSource(on_fault=faults.append)
    src._on = True
    import threading
    th = threading.Thread(target=src._scan_ble, daemon=True)
    th.start()
    t = time.time()
    while src.state != "scanning" and time.time() - t < 3:
        time.sleep(0.02)
    src.stop()
    th.join(3)
    assert [k.get("scanning_mode") for k in made] == ["passive", "active"]
    assert src.mode == "active" and faults and "ACTIVE" in faults[0] and "experimental" in faults[0]


def test_scan3_other_bleak_errors_still_fault():
    from palisade_qt import atlas
    assert not atlas.RidSource.passive_unsupported(RuntimeError("org.bluez.Error.NotReady"))
    assert atlas.RidSource.passive_unsupported(RuntimeError(
        "passive scanning on Linux requires BlueZ >= 5.56 with --experimental enabled"))


def test_scan3_doctor_names_the_experimental_flag(tmp_path):
    sysfs = tmp_path / "bt"
    (sysfs / "hci0").mkdir(parents=True)
    which = {"bluetoothctl": "/usr/bin/bluetoothctl", "pgrep": "/usr/bin/pgrep"}.get
    ok, d, fix = doctor.chk_ble_scan(
        run=_run({"bluetoothctl": (0, "Powered: yes"),
                  "pgrep": (0, "612 /usr/libexec/bluetooth/bluetoothd")}),
        which=which, find=lambda m: True, sysfs=str(sysfs))
    assert ok is True and "ACTIVE" in d and "--experimental" in fix and "owner decision" in fix
    ok, d, fix = doctor.chk_ble_scan(
        run=_run({"bluetoothctl": (0, "Powered: yes"),
                  "pgrep": (0, "612 /usr/libexec/bluetooth/bluetoothd --experimental")}),
        which=which, find=lambda m: True, sysfs=str(sysfs))
    assert ok is True and fix == ""


# ============================================================ SCAN-4 installer ships the scan tools

def test_scan4_installer_installs_the_scan_tools():
    """PRISM sweeps need rtl_power and PROWL needs rtl_fm (both from Debian's rtl-sdr package);
    the installer only checked for them at the end. bluez + bleak back RECON BLE."""
    src = open(os.path.join(SUITE_DIR, "install_head.sh")).read()
    lists = [ln for ln in src.splitlines() if ln.startswith("for pkg in ") and "bluez" in ln]
    assert len(lists) == 2
    for ln in lists:
        pkgs = ln.split(" in ", 1)[1].split(";")[0].split()
        assert {"rtl-sdr", "bluez", "iw"} <= set(pkgs)
    assert "$PIP bleak" in src
