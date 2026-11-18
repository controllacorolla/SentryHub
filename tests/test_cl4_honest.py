"""CL4 — honest state (UI side). One regression test (or group) per audit finding:
H1 H2 H3 H4 H5 H6 H7 H8 H10 H11 H12 H13 H14 H15 H16 H17 H18 H19 · E1 E4 · D4 (empty state) · L5
· N11. The gate/evidence findings carried from CL3 are in test_cl4_gates.py.

Nothing here opens a radio, a Wi-Fi adapter or the network: seams are patched, Qt is offscreen.
"""
import inspect
import os
import sys
import time
import types
from collections import deque

import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _wait(pred, s=5.0):
    app, t = _app(), time.time()
    while time.time() - t < s:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _app()
    from palisade_qt import radio_arbiter as ra, eventbus, panels
    ra.arbiter.reset_for_tests()
    eventbus.bus.clear()
    eventbus.set_home(None)
    panels.reset_alert_store()
    yield
    ra.arbiter.reset_for_tests()
    eventbus.bus.clear()
    eventbus.set_home(None)
    panels.reset_alert_store()


def _close(page):
    page.stop()
    page.deleteLater()
    _app().processEvents()


# ----------------------------------------------------------------- H1 SWEEP: one row per detector

def test_h1_sweep_has_a_fixed_row_per_detector_and_says_offline_not_blank():
    from palisade_qt.sweep import SweepApp, DETECTORS
    from palisade_qt.recon import DetectorWorker
    p = SweepApp(demo=False)
    for k in DETECTORS:
        w = DetectorWorker(demo=False, kind=k)
        got = []
        w.row.connect(got.append)
        w.step()
        assert w.stopping, "a live detector with no feed must stop polling"
        p._on_counter(got[0])
    rows = p.det_feed.model.rows
    assert [r["det"] for r in rows] == [k.upper() for k in DETECTORS]
    assert all(r["state"] == "OFFLINE" and "NOT IMPLEMENTED" in r["note"] for r in rows)
    assert p.counter_feed.showing_empty() and p.counter_feed.empty.state == "offline"
    assert "not mean all clear" in p.counter_feed.empty.text()
    _close(p)


def test_h1_detector_status_never_goes_to_the_shared_chip():
    from palisade_qt.recon import DetectorWorker
    w = DetectorWorker(demo=False, kind="jammer")
    st = []
    w.status.connect(st.append)
    w.step()
    assert st == [], "per-detector state must not overwrite the shared SDR chip"


def test_h1_demo_detector_goes_learning_then_watching_with_count_and_age():
    from palisade_qt.sweep import SweepApp
    from palisade_qt.recon import DetectorWorker
    p = SweepApp(demo=True)
    w = DetectorWorker(demo=True, kind="gnss")
    got = []
    w.row.connect(got.append)
    w.step()
    p._on_counter(got[-1])
    assert p.det_feed.model.rows[3]["state"] == "LEARNING"
    for _ in range(DetectorWorker.LEARN_SAMPLES):
        w.step()
    p._on_counter(got[-1])
    row = p.det_feed.model.rows[3]
    assert row["state"] == "WATCHING" and row["n"] == str(DetectorWorker.LEARN_SAMPLES + 1)
    assert row["age"].endswith("s")
    # a watching detector with no new sample goes STALE (red), not "watching"
    p._det["gnss"]["ts"] = time.time() - 60
    p._render_detectors()
    assert p.det_feed.model.rows[3]["state"] == "STALE"
    _close(p)


# ----------------------------------------------------------------- H2 PRISM live only when fresh

def test_h2_prism_live_only_with_a_recent_sweep():
    from palisade_qt import prism
    w = prism.SweepWorker(demo=False)
    now = 1000.0
    w._spawned_at, w._last_sweep = now - 1, None
    assert w._live_status(now)[1] == "warn"                       # starting
    w._spawned_at = now - prism.STALE_AFTER_S - 1
    assert "STALE" in w._live_status(now)[0]                      # never produced a sweep
    w._last_sweep = now - 1
    assert w._live_status(now) == ("SDR PRISM", "live")
    w._last_sweep = now - prism.STALE_AFTER_S - 1
    text, state = w._live_status(now)
    assert "STALE" in text and state == "alert"


def test_h2_prism_dead_rtl_power_is_a_fault_with_its_stderr(monkeypatch):
    from palisade_qt import prism, radio_arbiter as ra
    w = prism.SweepWorker(demo=False)
    w._active, w._has_radio = True, True
    monkeypatch.setattr(ra.arbiter, "state", lambda: ("HELD", prism.NAME))

    class Dead:
        stdout = iter(())

        def poll(self):
            return 1

        def terminate(self):
            pass
    w._proc, w._asm = Dead(), object()
    w._err_tail = ["usb_claim_interface error -6"]
    st = []
    w.status.connect(st.append)
    w.step()
    assert st and "SDR FAULT" in st[-1]["sdr"]["text"] and "-6" in st[-1]["sdr"]["text"]
    assert st[-1]["sdr"]["state"] == "alert"


# ----------------------------------------------------------------- H3 Wi-Fi scan honesty

def test_h3_scan_is_passive():
    import wifisurvey
    assert wifisurvey.scan_argv("wlan0")[-2:] == ["scan", "passive"]


def test_h3_failed_scan_is_not_zero_aps(monkeypatch):
    from palisade_qt import recon
    monkeypatch.setattr(recon, "_offscreen", lambda: False)
    out, why = recon._run_scan([sys.executable, "-c",
                                "import sys; sys.stderr.write('Operation not permitted'); "
                                "sys.exit(255)"])
    assert out is None and "exit 255" in why and "not permitted" in why
    assert recon._run_cmd([sys.executable, "-c", "import sys; sys.exit(1)"]) is None
    monkeypatch.setattr(recon, "_run_scan", lambda argv, timeout=12, **k: (None, "exit 255 — denied"))
    w = recon.WifiScanWorker(demo=False)
    st, rows = [], []
    w.status.connect(st.append)
    w.row.connect(rows.append)
    w.step()
    assert rows == [] and st[-1]["sdr"]["text"].startswith("WIFI SCAN FAILED")


def test_h3_wifi_scan_pauses_when_not_on_screen():
    from palisade_qt.recon import ReconApp, WifiScanWorker
    p = ReconApp(demo=True)
    p.start()
    w = next(x for x in p._workers if isinstance(x, WifiScanWorker))
    assert WifiScanWorker.INTERVAL_MS >= 15000
    p.set_active(False)
    assert w.paused
    p.set_active(True)
    assert not w.paused
    p._switch("BLE")
    assert w.paused, "the Wi-Fi scan must not run while BLE is on screen"
    p._switch("WIFI")
    assert not w.paused
    _close(p)


def test_h3_open_network_alerts_once_per_bssid_not_per_scan():
    from palisade_qt import eventbus
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False)
    alerts = []
    eventbus.bus.published.connect(lambda e: alerts.append(e) if e["type"] == "alert" else None)
    ap = {"bssid": "aa:bb", "ssid": "Cafe", "channel": 6, "signal": -50, "security": "open"}
    for _ in range(3):
        p._on_wifi({"aps": [ap]})
    _wait(lambda: alerts, 1)
    assert len(alerts) == 1
    _close(p)


# ----------------------------------------------------------------- H4 a failed lease is not a grant

def test_h4_failed_acquire_is_not_granted_and_says_why(monkeypatch):
    import suite
    from palisade_qt import radio_arbiter as ra

    class Refuses:
        released = 0

        def __init__(self, name):
            pass

        def acquire(self):
            raise RuntimeError("readsb would not stop")

        def release(self):
            Refuses.released += 1
    monkeypatch.setattr(suite, "RtlLease", Refuses, raising=False)
    with pytest.raises(ra.LeaseFailed):
        ra._make_lease("PRISM")
    assert Refuses.released == 1, "a failed acquire puts back what it paused"
    failed = []
    ra.arbiter.failed.connect(lambda n, why: failed.append((n, why)))
    assert ra.arbiter.request("PRISM")                 # ACQUIRING …
    assert _wait(lambda: failed, 3)
    assert ra.arbiter.state() == ("FREE", None), "never HELD after a failed acquire"
    assert "readsb would not stop" in ra.arbiter.failure("PRISM")
    assert ra.busy_text("PRISM").startswith("RADIO FAILED")
    assert not ra.arbiter.request("PRISM"), "backs off instead of retrying every tick"


def test_h4_no_lease_module_still_grants(monkeypatch):
    import suite
    from palisade_qt import radio_arbiter as ra
    monkeypatch.delattr(suite, "RtlLease", raising=False)
    assert ra._make_lease("PRISM") is None


# ----------------------------------------------------------------- H5 no silent default HOME

def test_h5_home_is_unset_unless_saved_or_demo():
    from palisade_qt import eventbus
    assert eventbus.load_home(demo=False, loader=lambda: None) is None
    assert eventbus.home() is None and not eventbus.home_set()
    assert eventbus.load_home(demo=True, loader=lambda: None) == "demo"
    assert eventbus.home() == eventbus.DEMO_HOME
    assert eventbus.load_home(demo=False, loader=lambda: [40.0, -105.0]) == "settings"
    assert eventbus.home() == (40.0, -105.0)


def test_h5_settings_show_not_set_and_save_live(monkeypatch):
    from palisade_qt import eventbus
    from palisade_qt.system import MoreApp
    p = MoreApp(demo=False)
    assert p.set_home.text() == "" and "HOME NOT SET" in p.set_home.placeholderText()
    saved = {}
    monkeypatch.setattr(p, "_write_settings", lambda d: saved.update(d) or True)
    fired = []
    eventbus.bus.home_changed.connect(lambda: fired.append(1))
    p.set_home.setText("39.7, -104.9")
    p._save_settings()
    assert eventbus.home() == (39.7, -104.9) and eventbus.HOME_SOURCE == "settings"
    assert fired and saved["home"] == [39.7, -104.9]
    _close(p)


def test_h5_demo_home_is_never_persisted_as_the_operators(monkeypatch):
    from palisade_qt import eventbus
    from palisade_qt.system import MoreApp
    eventbus.set_home(eventbus.DEMO_HOME, "demo")
    p = MoreApp(demo=True)
    assert p.set_home.text() == ""
    saved = {}
    monkeypatch.setattr(p, "_write_settings", lambda d: saved.update(d) or True)
    p._save_settings()
    assert saved["home"] is None
    _close(p)


def test_h5_ops_shows_home_not_set_instead_of_a_range():
    from palisade_qt.ops import OpsHome
    p = OpsHome(demo=False)
    p._contacts = {"A": {"id": "A", "_ts": time.time(), "rng": 4.0, "x": 1.0, "y": 1.0,
                         "severity": "info", "label": "A"}}
    p._refresh_ppi()
    assert "HOME NOT SET" in p.sub.text() and "NM" not in p.sub.text()
    _close(p)


# ----------------------------------------------------------------- H6 SDR chip from the kernel

def _fake_sys(tmp_path, driver):
    dev = tmp_path / "bus" / "usb" / "devices" / "1-1"
    dev.mkdir(parents=True)
    (dev / "idVendor").write_text("0bda\n")
    (dev / "idProduct").write_text("2838\n")
    drv = tmp_path / "bus" / "usb" / "drivers" / driver
    drv.mkdir(parents=True)
    iface = tmp_path / "bus" / "usb" / "devices" / "1-1:1.0"
    iface.mkdir()
    (iface / "driver").symlink_to(drv)
    return str(tmp_path)


def test_h6_dvb_driver_bound_reads_blocked_not_ok(tmp_path):
    from palisade_qt import ops, radios
    root = _fake_sys(tmp_path, "dvb_usb_rtl28xxu")
    st = radios.sdr_state(root)
    assert st["present"] and st["usable"] is False and st["driver"] == "dvb_usb_rtl28xxu"
    chip = ops.sdr_chip(root)
    assert chip["text"].startswith("SDR BLOCKED") and chip["state"] == "alert"


def test_h6_free_dongle_absent_and_unknown(tmp_path):
    from palisade_qt import ops
    assert ops.sdr_chip(_fake_sys(tmp_path / "a", "usbfs"))["text"] == "SDR PRESENT"
    empty = tmp_path / "b" / "bus" / "usb" / "devices"
    empty.mkdir(parents=True)
    assert ops.sdr_chip(str(tmp_path / "b"))["text"] == "SDR ABSENT"
    assert ops.sdr_chip(str(tmp_path / "nosys"))["text"] == "SDR ?"


# ----------------------------------------------------------------- H7 live by default, demo flagged

@pytest.mark.parametrize("modname", ["overwatch", "prism", "system", "forge", "babel", "recon",
                                     "prowl"])
def test_h7_workers_default_to_live_not_demo(modname):
    import importlib
    from palisade_qt.worker import Worker
    mod = importlib.import_module("palisade_qt." + modname)
    for name, cls in vars(mod).items():
        if isinstance(cls, type) and issubclass(cls, Worker) and cls.__module__ == mod.__name__:
            p = inspect.signature(cls.__init__).parameters.get("demo")
            if p is not None and p.default is not inspect.Parameter.empty:
                assert p.default is False, "%s.%s defaults to demo" % (modname, name)


def test_h7_events_carry_a_demo_flag():
    from palisade_qt import eventbus
    assert eventbus.contact("X", "1", 1, 1)["demo"] is False
    assert eventbus.decode("X", "P", "1", "s", demo=True)["demo"] is True


# ----------------------------------------------------------------- H8 BENCH keyed only if it stays up

class _Handle:
    def __init__(self, running, code=None, stopped=None):
        self._running, self.exit_code, self.stopped, self.lines = running, code, stopped, []

    def running(self):
        return self._running

    def stop(self, why):
        self._running, self.stopped = False, why


def test_h8_bench_says_starting_then_keyed_and_failed_to_key():
    from palisade_qt import bench_app
    p = bench_app.BenchApp(demo=False)
    p._handle, p._keyed, p._keyed_at = _Handle(True), False, time.monotonic() + 60
    p.card.set_hero("STARTING")
    p._check_handle()
    assert p.card.hero.text() == "STARTING"
    p._keyed_at = time.monotonic() - 1
    p._check_handle()
    assert p.card.hero.text() == "KEYED"
    # a runner that exits non-zero before it was ever keyed never showed KEYED
    p._handle, p._keyed, p._keyed_at = _Handle(False, code=1), False, time.monotonic() + 60
    p._check_handle()
    assert p.card.hero.text() == "FAILED TO KEY"
    _close(p)


def test_h8_power_spinbox_reaches_the_tx_gate():
    from palisade_qt import bench_app
    p = bench_app.BenchApp(demo=False)
    p.power.setValue(-17)
    assert p._settings()["power_dbm"] == -17
    _close(p)


# ----------------------------------------------------------------- H10 per-layer ATLAS health

def test_h10_atlas_layer_summary_shows_a_dead_adsb_feed():
    from palisade_qt.atlas import AtlasApp
    p = AtlasApp(demo=False)
    p._layers = {"aircraft", "station"}
    p._adsb_health = {"state": "stale", "age": 3600}
    text, state = p._layer_summary([{"kind": "station"}])
    assert "ADS-B STALE" in text and state == "alert"
    p._adsb_health = {"state": "none"}
    text, state = p._layer_summary([{"kind": "station"}])
    assert "ADS-B NO FEED" in text
    _close(p)


# ----------------------------------------------------------------- H11 H12 H13 levels and peaks

def test_h11_prowl_shows_a_unitless_level_not_dbm():
    from palisade_qt import prowl
    assert prowl._level_text(None) == "" and prowl._level_text(42) == "42%"
    assert "dBm" not in prowl._level_text(80)
    src = inspect.getsource(prowl.ProwlApp)
    assert '("sig", "LEVEL")' in src and '"dBm"' not in src


def test_h12_peak_hold_decays_down_in_db():
    from palisade_qt.kit.scope import ScopePanel
    import numpy as np
    s = ScopePanel(bins=16)
    floor = np.full(16, -105.0, dtype=np.float32)
    s.push(np.linspace(430, 440, 16), np.full(16, -40.0, dtype=np.float32))
    for _ in range(200):
        s.push(np.linspace(430, 440, 16), floor)
    assert float(s.peak_hold.max()) == pytest.approx(-105.0), "decays to the floor, never up"


def test_h13_prism_readout_is_relative():
    from palisade_qt import prism
    src = inspect.getsource(prism)
    assert "dB rel" in src and "dBm" not in src


# ----------------------------------------------------------------- H14 H15 OPS counts

def test_h14_decode_rate_counts_the_last_minute():
    from palisade_qt.ops import OpsHome
    stub = types.SimpleNamespace(_decode_times=deque([100.0]))
    assert OpsHome.decode_rate(stub, now=110.0) == 1          # one decode is 1, not "6/min"
    assert OpsHome.decode_rate(stub, now=200.0) == 0


def test_h15_military_count_only_in_demo():
    from palisade_qt import eventbus
    from palisade_qt.ops import OpsHome
    eventbus.set_home((40.0, -105.0))
    p = OpsHome(demo=False)
    p._contacts = {"A": {"id": "A", "_ts": time.time(), "rng": 4.0, "mil": True, "x": 1.0,
                         "y": 1.0, "severity": "info", "label": "A"}}
    p._refresh_ppi()
    assert "military" not in p.sub.text() and "NM" in p.sub.text()
    _close(p)


# ----------------------------------------------------------------- H16 every decode on the bus

def test_h16_babel_runners_publish_their_decodes():
    from palisade_qt import babel, eventbus
    got = []
    eventbus.bus.published.connect(got.append)
    babel._publish_decode("BABEL", {"proto": "AIS", "id": 366123456, "summary": "pos"})
    assert _wait(lambda: got, 1) and got[0]["type"] == "decode" and got[0]["payload"]
    src = inspect.getsource(babel)
    for proto in ("AIS", "ACARS", "POCSAG", "RDS"):
        assert src.count("_publish_decode(") >= 5, proto


# ----------------------------------------------------------------- H17 bus store + SITREP

def test_h17_map_traffic_does_not_evict_alerts():
    from palisade_qt import eventbus
    eventbus.bus.publish(eventbus.alert("NWR", "Tornado Warning", severity="alert"))
    for i in range(3000):
        eventbus.bus.publish(eventbus.contact("ATLAS", "AC%d" % (i % 30), 1.0, 1.0))
    assert [a["payload"]["text"] for a in eventbus.bus.recent(10, "alert")] == ["Tornado Warning"]
    assert len(eventbus.bus.contacts()) == 30, "latest state per contact id"


def test_h17_contacts_store_prunes_by_age(monkeypatch):
    from palisade_qt import eventbus
    ev = eventbus.contact("ATLAS", "OLD", 1.0, 1.0)
    ev["ts"] = time.time() - eventbus.CONTACT_TTL_S - 5
    eventbus.bus.publish(ev)
    eventbus.bus.publish(eventbus.contact("ATLAS", "NEW", 1.0, 1.0))
    assert [c["payload"]["id"] for c in eventbus.bus.contacts()] == ["NEW"]


def test_h17_assistant_reads_alerts_from_the_ack_store():
    from palisade_qt import eventbus, panels
    from palisade_qt.system import MoreApp
    panels.alert_store()
    p = MoreApp(demo=False)
    eventbus.bus.publish(eventbus.alert("NWR", "Tornado Warning", severity="alert"))
    _wait(lambda: panels.alert_store().items, 1)
    for i in range(1500):
        eventbus.bus.publish(eventbus.contact("ATLAS", "AC%d" % i, 1.0, 1.0))
    assert "Tornado Warning" in p._answer("any alerts?")
    _close(p)


def test_h17_sitrep_never_says_all_quiet_with_no_feed():
    from palisade_qt.system import MoreApp
    p = MoreApp(demo=False)
    text = " ".join(p._sitrep_lines())
    assert "All quiet" not in text and "No feed is running" in text and "not an all-clear" in text
    _close(p)


def test_h17_sitrep_with_a_feed_names_what_it_watched():
    from palisade_qt import eventbus
    from palisade_qt.system import MoreApp
    eventbus.bus.publish(eventbus.decode("PROWL", "NWR", "KEC61", "routine"))
    p = MoreApp(demo=False)
    text = " ".join(p._sitrep_lines())
    assert "No feed is running" not in text and "PROWL" in text
    _close(p)


# ----------------------------------------------------------------- H18 assistant

def test_h18_no_default_remote_host():
    import assistant
    for h in assistant.DEFAULTS["hosts"]:
        assert assistant.is_local(h["url"]), h


def test_h18_freeform_goes_to_the_worker_and_probes_nothing_on_the_gui_thread(monkeypatch):
    """Since 2026-11-18 free-form questions go to a LOCAL model (AskWorker, off the GUI thread);
    the GUI-thread built-in answer path still probes nothing."""
    import assistant
    from palisade_qt.system import MoreApp
    monkeypatch.setattr(assistant, "pick_host",
                        lambda *a, **k: pytest.fail("no network probe on the GUI thread"))
    monkeypatch.setattr(assistant, "http_json",
                        lambda *a, **k: pytest.fail("no network probe on the GUI thread"))
    p = MoreApp(demo=False)
    assert p._answer("what's the weather like?") is None
    _close(p)


# ----------------------------------------------------------------- H19 one time base

def test_h19_zulu_everywhere():
    from palisade_qt.timebase import zulu
    assert zulu(0) == "00:00:00Z" and zulu(3600, secs=False) == "01:00Z"
    import glob
    for path in glob.glob(os.path.join(SUITE_DIR, "palisade_qt", "**", "*.py"), recursive=True):
        if path.endswith("timebase.py"):
            continue
        src = open(path).read()
        assert "localtime" not in src and 'strftime("%H:%M' not in src, path


# ----------------------------------------------------------------- E1 stale ADS-B is not live

def test_e1_stale_adsb_publishes_nothing():
    from palisade_qt.atlas import AtlasLiveWorker
    w = AtlasLiveWorker()
    w._adsb = types.SimpleNamespace(
        snapshot=lambda: ([{"hex": "a1", "lat": 1.0, "lon": 1.0}], {}, "stale", None),
        data_t=time.time() - 3600)
    st = []
    w.status.connect(st.append)
    assert w._adsb_contacts() == []
    assert st[-1]["adsb"]["state"] == "stale" and st[-1]["adsb"]["age"] > 3000


# ----------------------------------------------------------------- E4 NOT IMPLEMENTED, not hardware

def test_e4_ble_no_backend_says_what_is_missing(monkeypatch):
    """SCAN-2 superseded "BLE NOT IMPLEMENTED": live BLE is wired (tests/test_scan_live.py).
    With neither bleak nor bluetoothctl the standby names both."""
    import importlib.util
    import shutil
    from palisade_qt.recon import BleScanWorker
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: None)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None)
    assert BleScanWorker.backend_available() is None
    assert "bleak" in BleScanWorker._no_feed_text() and "bluetoothctl" in BleScanWorker._no_feed_text()


def test_e4_can_and_sensors_present_say_not_implemented(monkeypatch):
    import shutil
    import canbus
    from palisade_qt import forge
    monkeypatch.setattr(forge, "_offscreen", lambda: False)
    monkeypatch.setattr(canbus, "detect", lambda *a, **k: True)
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/" + n)
    for cls in (forge.CanWorker, forge.SensorWorker):
        w = cls(demo=False)
        st = []
        w.status.connect(st.append)
        w.step()
        assert "NOT IMPLEMENTED" in st[-1]["sdr"]["text"], cls.__name__


def test_e4_mesh_without_a_link_says_so_and_detectors_say_not_implemented():
    """MESH is wired since 2026-11-18 (palisade_qt/mesh.py): with no link it says NO link and
    why, never a live mesh."""
    from palisade_qt.mesh import MeshLinkWorker
    from palisade_qt.recon import DetectorWorker
    w = MeshLinkWorker(demo=False)
    st = []
    w.status.connect(st.append)
    w.step()
    assert st[-1]["link"] == "none" and st[-1]["text"]
    assert DetectorWorker(kind="imsicatch").offline_reason().startswith("NOT IMPLEMENTED")


# ----------------------------------------------------------------- D4 one empty-state component

@pytest.mark.parametrize("state", ["offline", "watching", "stale"])
def test_d4_empty_state_has_three_looks(state):
    from palisade_qt.kit import EmptyState
    e = EmptyState(state=state, text="X", hint="why")
    assert e.state == state and "why" in e.text()
    with pytest.raises(ValueError):
        e.set_state("blank", "x")


def test_d4_a_feed_table_is_never_blank():
    from palisade_qt.kit import FeedTable
    t = FeedTable([("a", "A")])
    assert t.showing_empty() and t.empty.text()
    t.model.set_rows([{"a": 1}])
    assert not t.showing_empty()
    t.model.set_rows([])
    t.set_empty("watching", "nothing heard", "12 samples")
    assert t.showing_empty() and "WATCHING" in t.empty.text()


def test_d4_standby_reason_fills_the_recon_tables():
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False)
    p._feed_standby(p.wifi_feed, {"standby": True, "sdr": {"text": "WIFI SCAN FAILED — exit 1"}})
    assert p.wifi_feed.showing_empty() and "SCAN FAILED" in p.wifi_feed.empty.text()
    _close(p)


# ----------------------------------------------------------------- L5 Remote Mode providers

def test_l5_remote_mode_serves_real_adsb_contacts_when_live():
    pytest.importorskip("flask")
    import headless
    feed = types.SimpleNamespace(
        snapshot=lambda: ([{"hex": "a1b2c3", "flight": "UAL1 ", "lat": 1.0, "lon": 2.0},
                           {"hex": "nopos"}], {}, "live", None), data_t=time.time())
    app = headless.make_app(headless.adsb_providers(feed), token="t" * 24)   # C1 (CL8)
    c = app.test_client()
    c.environ_base["HTTP_AUTHORIZATION"] = "Bearer " + "t" * 24
    assert c.get("/api/contacts").get_json()["contacts"] == [
        {"id": "a1b2c3", "label": "UAL1", "type": "aircraft", "lat": 1.0, "lon": 2.0,
         "alt": None}]
    s = c.get("/api/status").get_json()
    assert s["active_contacts"] == 1 and s["feed"] == "ADS-B LIVE"


def test_l5_remote_mode_stale_or_absent_feed_serves_nothing_and_says_so():
    import headless
    feed = types.SimpleNamespace(snapshot=lambda: ([{"hex": "a", "lat": 1, "lon": 1}], {},
                                                   "stale", None), data_t=time.time() - 900)
    p = headless.adsb_providers(feed)
    assert p["contacts"]() == [] and p["status"]()["feed"].startswith("ADS-B STALE")
    assert headless.adsb_providers(None)["status"]()["feed"] == "ADS-B NO FEED"


def test_l5_dashboard_never_injects_contact_fields_as_html():
    import headless
    html = headless.dashboard_html()
    assert "innerHTML" not in html and "textContent" in html


# ----------------------------------------------------------------- N11 ENGAGEMENT trail fits

def test_n11_engagement_trail_fits_the_panel():
    from palisade_qt.panels import EngagePanel
    p = EngagePanel("dark")
    assert p.eng_actions._fit_viewport
    assert p.eng_actions.model.columns[0][1] == "TIME (Z)"


def test_h17_device_telemetry_is_not_a_feed_or_a_decode():
    from palisade_qt import eventbus
    from palisade_qt.system import MoreApp
    eventbus.bus.publish(eventbus.make_event("decode", "OPS", {"kind": "telemetry", "temp": 50}))
    assert eventbus.bus.feeds() == {}
    p = MoreApp(demo=False)
    text = " ".join(p._sitrep_lines())
    assert "No feed is running" in text and "decodes" not in text
    _close(p)


def test_d4_resumed_worker_steps_at_once_not_one_interval_later():
    from palisade_qt.worker import Worker

    class W(Worker):
        n = 0

        def step(self):
            W.n += 1
    w = W(demo=False, interval_ms=60000)
    w.pause(True)
    w.start()
    time.sleep(0.2)
    assert W.n == 0
    w.pause(False)
    assert _wait(lambda: W.n >= 1, 2), "a page shown after start must not wait a full interval"
    w.stop()
    w.quit()
    w.wait(3000)


def test_d4_atlas_and_engagement_empty_states_say_why():
    from palisade_qt.atlas import AtlasApp
    from palisade_qt.panels import EngagePanel
    a = AtlasApp(demo=False)
    a._adsb_health = {"state": "none"}
    a._render()
    assert a.feed.showing_empty() and "NO LIVE LAYER" in a.feed.empty.text()
    _close(a)
    p = EngagePanel("dark")
    p.render_actions()
    assert p.eng_actions.showing_empty() and p.eng_actions.empty.text()


# ================================================================ RA-CL4 fixes (N26–N32, E1 res.)

def test_n26_no_home_no_range_picture_on_ops_or_atlas():
    from palisade_qt.ops import OpsHome
    from palisade_qt.atlas import AtlasApp
    o = OpsHome(demo=False)
    o._contacts = {"A": {"id": "A", "_ts": time.time(), "rng": 4.0, "x": 1.0, "y": 1.0,
                         "severity": "info", "label": "A"}}
    plotted = []
    o.ppi.set_contacts = lambda c, selected=None, **_kw: plotted.append(list(c))
    o._refresh_ppi()
    assert o._home_cover.shown() and plotted[-1] == [], "no contact drawn on rings"
    assert "HOME NOT SET" in o._home_cover.empty.text()
    _close(o)
    a = AtlasApp(demo=False)
    assert not a.map._can_fetch, "never request tiles for a placeholder origin"
    a._render()
    assert a._home_cover.shown()
    _close(a)


def test_n26_home_set_draws_again_and_fetches_tiles():
    from palisade_qt import eventbus
    from palisade_qt.atlas import AtlasApp
    a = AtlasApp(demo=False)
    eventbus.set_home((40.0, -105.0))
    _app().processEvents()
    a._render()
    assert not a._home_cover.shown() and a.map._can_fetch
    assert (a.map._tiles.home_lat, a.map._tiles.home_lon) == (40.0, -105.0)
    _close(a)


def _engage(monkeypatch, **kw):
    import engagement
    from palisade_qt.panels import EngagePanel
    for k, v in kw.items():
        monkeypatch.setattr(engagement, k, v)
    p = EngagePanel("dark")
    p.render_actions()
    return p


def test_n27_tampered_trail_is_not_watching(monkeypatch):
    p = _engage(monkeypatch, chain_info=lambda: {"id": "c1", "records": 3, "verified": False,
                                                 "why": "hash mismatch at 2", "path": "x"},
                chain_states=lambda: [], chain_unreadable=lambda: None)
    assert p.eng_actions.empty.state == "stale" and "UNREADABLE" in p.eng_actions.empty.text()


def test_n28_active_engagement_with_unreadable_chain_is_not_no_engagement(monkeypatch):
    p = _engage(monkeypatch, chain_info=lambda: None, chain_states=lambda: [],
                chain_unreadable=lambda: "malformed head")
    assert "NO ENGAGEMENT" not in p.eng_actions.empty.text()
    assert "UNREADABLE" in p.eng_chain.text().upper() and "malformed head" in p.eng_chain.text()


def test_n28_chain_unreadable_reports_the_open_failure(monkeypatch):
    import engagement
    import chain
    monkeypatch.setattr(engagement, "current_chain_id", lambda: "c1")
    monkeypatch.setattr(chain, "for_id", lambda cid: (_ for _ in ()).throw(chain.ChainError("bad head")))
    assert "bad head" in engagement.chain_unreadable()
    monkeypatch.setattr(engagement, "current_chain_id", lambda: None)
    assert engagement.chain_unreadable() is None


def test_n29_alerts_and_predictions_are_not_a_running_feed():
    from palisade_qt import eventbus
    from palisade_qt.system import MoreApp
    eventbus.bus.publish(eventbus.alert("OVERWATCH", "next pass: ISS 12:00Z"))
    eventbus.bus.publish(eventbus.alert("ATLAS", "RADIO BUSY — held by PRISM"))
    assert eventbus.bus.feeds() == {}
    p = MoreApp(demo=False)
    text = " ".join(p._sitrep_lines())
    assert "No feed is running" in text and "Watching" not in text
    _close(p)


def test_n30_wifi_worker_is_paused_before_it_starts(monkeypatch):
    from palisade_qt import recon
    calls = []
    monkeypatch.setattr(recon, "_run_scan", lambda argv, timeout=12, **k: calls.append(1) or ("", None))
    for _ in range(10):
        p = recon.ReconApp(demo=False)
        p._subtab = "BLE"
        p.start()
        time.sleep(0.05)
        _close(p)
    assert calls == [], "no Wi-Fi scan while RECON › WIFI was never on screen"


def test_n31_an_orphan_that_exited_by_itself_is_not_recorded_as_killed():
    import subprocess
    import gatestate
    import engagement
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    ps = gatestate.proc_start(proc.pid)
    proc.wait()
    res = engagement._kill_orphans({"t": (proc.pid, ps or "x")})
    assert res["t"] == (False, "exited")
    assert "exited on its own" in engagement._ORPHAN_FAIL["exited"]


def test_n32_session_leader_and_ancestors_are_protected():
    import engagement
    prot = engagement._protected_pids()
    assert os.getsid(0) in prot and os.getppid() in prot and os.getpid() in prot
    assert engagement._identity(os.getsid(0), "anything") == "mismatch"


def test_e1_residual_missing_or_future_now_is_not_live(tmp_path):
    import json
    import sky_app
    d = tmp_path / "readsb"
    d.mkdir()
    f = d / "aircraft.json"
    f.write_text(json.dumps({"aircraft": [{"hex": "a1", "seen": 1}]}))
    old = time.time() - 3600
    os.utime(f, (old, old))
    feed = sky_app.AdsbFeed.__new__(sky_app.AdsbFeed)   # no poll thread: drive _tick directly
    import threading
    feed.sources, feed.aircraft, feed.receiver, feed.status = [str(d)], [], None, "none"
    feed.source, feed.updated, feed.data_t, feed.trails, feed.history = None, 0.0, None, {}, []
    feed._last_frame, feed._rcv_retry, feed.lock = 0.0, 0.0, threading.Lock()
    feed._tick([str(d)])
    assert feed.status == "stale", "no 'now' -> file mtime (an hour old) -> stale"
    f.write_text(json.dumps({"now": time.time() + 3600, "aircraft": []}))
    feed._tick([str(d)])
    assert feed.status == "stale", "a timestamp in the future is not live"
