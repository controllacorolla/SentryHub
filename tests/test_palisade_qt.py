"""Phase-2 acceptance test for the Qt kit + Hub shell + OPS.

The kit's whole promise: construct in demo -> pump -> close -> no leaked QThread, no exception,
in both themes. This encodes the R1/R3 lifecycle fix as "built on the kit."

Runs headless via Qt's offscreen platform; skipped cleanly if PySide6 isn't installed, so the
pure-logic suite on a bare env is unaffected.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6 import QtWidgets  # noqa: E402


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def _isolate_qt():
    """Keep the global event bus and Qt objects from leaking across tests: clear the bus and
    flush deleted widgets (deleteLater) after each test, so a destroyed page's slot can't fire
    into freed C++ during a later test (the full-suite soak segfault)."""
    yield
    try:
        from palisade_qt import eventbus
        eventbus.bus.clear()
        from palisade_qt import radio_arbiter
        radio_arbiter.arbiter._owner = None
        radio_arbiter.arbiter._lease = None
    except Exception:
        pass
    import gc
    gc.collect()
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.processEvents()
        app.sendPostedEvents(None, 52)   # QEvent.DeferredDelete
        app.processEvents()


def _pump(ms=800, step=10):
    import time
    app = _app()
    t = 0
    while t < ms:
        app.processEvents()
        time.sleep(step / 1000.0)
        t += step


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_ops_open_pump_close_no_leaked_thread(mode):
    _app()
    from palisade_qt.ops import OpsHome
    ops = OpsHome(demo=True, mode=mode)
    win = ops.standalone()
    win.show()
    _pump(900)
    worker = ops._worker
    assert worker is not None and worker.isRunning(), "worker should run while open"
    # OPS consumes the event bus; a contact published to the bus must reach the PPI
    from palisade_qt import eventbus
    eventbus.bus.publish(eventbus.contact("ATLAS", "TST1", 47.7, -122.4))
    _pump(120)
    assert "TST1" in ops._contacts, "a bus contact should reach the OPS PPI"
    win.close()
    _pump(200)
    assert ops._worker is None, "stop() must clear the worker"
    assert not worker.isRunning(), "worker QThread must be joined on close (no leak)"


def test_hub_builds_and_hosts_ops():
    _app()
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=True, mode="dark")
    hub.show()
    _pump(400)
    assert "OPS" in hub.pages
    assert hub.stack.currentWidget() is hub.ops
    ops_worker = hub.ops._worker
    hub.close()
    _pump(200)
    assert not (ops_worker and ops_worker.isRunning()), "hub close must stop its pages' workers"


def test_lease_skipped_in_demo():
    _app()
    from palisade_qt.app import PalisadeApp

    class RadioApp(PalisadeApp):
        TITLE = "RADIO"
        LEASE = "TestLease"      # would acquire the SDR if not demo

    a = RadioApp(demo=True, mode="dark")
    a.start()
    assert a._lease is None, "demo must never touch the dongle"
    a.stop()


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_prism_open_pump_close_no_leaked_thread(mode):
    _app()
    from palisade_qt.prism import PrismApp
    p = PrismApp(demo=True, mode=mode)
    win = p.standalone()
    win.show()
    _pump(700)
    worker = p._worker
    assert worker is not None and worker.isRunning()
    # the scope buffer should have advanced past its initial floor as sweeps arrive
    import numpy as np
    assert float(np.max(p.scope.buf)) > -115.0
    win.close()
    _pump(200)
    assert p._worker is None and not worker.isRunning()


def test_hub_embeds_prism_as_qt_page():
    _app()
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=True, mode="dark")
    hub.show()
    hub.open_callsign("PRISM")          # migrated -> builds + embeds, does NOT spawn a subprocess
    _pump(400)
    assert "PRISM" in hub.pages
    assert hub.stack.currentWidget() is hub.pages["PRISM"]
    prism_worker = hub.pages["PRISM"]._worker
    hub.close()
    _pump(200)
    assert not (prism_worker and prism_worker.isRunning())


ALL_CALLSIGNS = ["OVERWATCH", "ATLAS", "BABEL", "PRISM", "PROWL", "FORGE", "RECON", "BENCH"]


@pytest.mark.parametrize("name", ALL_CALLSIGNS)
def test_every_callsign_opens_pumps_closes_clean(name):
    _app()
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=True, mode="dark")
    hub.show()
    hub.open_callsign(name)             # migrated -> embedded Qt page, no subprocess
    _pump(600)
    assert name in hub.pages
    page = hub.pages[name]
    worker = page._worker
    assert worker is None or worker.isRunning(), "%s worker should be live if present" % name
    hub.close()
    _pump(200)
    assert not (worker and worker.isRunning()), "%s leaked a QThread" % name


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_all_callsigns_build_in_both_themes(mode):
    _app()
    from palisade_qt import shell
    for factory in shell.QT_PAGES.values():
        page = factory(demo=True, mode=mode)
        page.start()
        page.stop()


def test_hub_soak_open_all_callsigns_then_close_no_leaks():
    """Back-test: one hub, open every callsign in sequence, pump, close -> zero running QThreads."""
    from PySide6 import QtCore
    _app()
    from palisade_qt.shell import PalisadeHub, QT_PAGES
    before = QtCore.QThread.__subclasses__()  # noqa: F841 (kept for clarity)
    hub = PalisadeHub(demo=True, mode="dark")
    hub.show()
    workers = []
    for name in QT_PAGES:
        hub.open_callsign(name)
        _pump(250)
        w = hub.pages[name]._worker
        if w is not None:
            workers.append((name, w))
    assert len(hub.pages) == len(QT_PAGES) + 1          # +OPS
    running = [n for n, w in workers if w.isRunning()]
    assert running, "workers should be live while open"
    hub.close()
    _pump(400)
    leaked = [n for n, w in workers if w.isRunning()]
    assert not leaked, "leaked QThreads after hub close: %s" % leaked


def test_launcher_main_is_importable():
    # the entry points resolve without starting an event loop
    import palisade_qt.shell as s
    import palisade_qt.__main__ as m           # noqa: F401
    assert callable(s.main)


def test_eventbus_typed_contract():
    from palisade_qt import eventbus
    got = []
    eventbus.bus.published.connect(got.append)
    c = eventbus.contact("ATLAS", "UAL1", 47.5, -122.3, alt=34000, kind="air", mil=True)
    d = eventbus.decode("BABEL", "ADS-B", "A1", "FL340")
    a = eventbus.alert("RECON", "Open AP", severity="warn")
    for e in (c, d, a):
        eventbus.bus.publish(e)
    for e in (c, d, a):
        assert set(e) == {"type", "source", "severity", "ts", "payload"}
    assert c["type"] == "contact" and c["payload"]["lat"] == 47.5 and c["payload"]["lon"] == -122.3
    assert c["payload"]["kind"] == "air" and c["payload"]["mil"] is True
    assert d["type"] == "decode" and d["payload"]["proto"] == "ADS-B"
    assert a["type"] == "alert" and a["severity"] == "warn"
    assert eventbus.bus.recent(etype="alert")[-1]["payload"]["text"] == "Open AP"
    import pytest as _pt
    with _pt.raises(AssertionError):
        eventbus.make_event("bogus", "X", {})
    eventbus.bus.published.disconnect(got.append)


def test_ops_live_mode_shows_standby_not_fake_data():
    """Honesty: with no backend publishing, OPS cards stay on standby, no invented contacts."""
    _app()
    from palisade_qt import eventbus
    eventbus.bus.clear()
    from palisade_qt.ops import OpsHome
    ops = OpsHome(demo=False, mode="dark")
    win = ops.standalone()
    win.show()
    _pump(500)
    # PRISM card is standby until PRISM is up; no contacts invented in live mode
    assert ops.card_prism._live is False
    assert len(ops._contacts) == 0, "live OPS must not fabricate contacts"
    win.close()
    _pump(150)


def test_atlas_demo_contacts_reach_both_map_and_ops():
    """One stream, two views: ATLAS's demo feed populates its own map AND the OPS PPI."""
    _app()
    from palisade_qt import eventbus
    eventbus.bus.clear()
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=True, mode="dark")
    try:
        hub.show()
        hub.open_callsign("ATLAS")              # starts ATLAS's demo feed
        _pump(900)
        atlas = hub.pages["ATLAS"]
        assert len(atlas._contacts) > 0, "ATLAS demo feed should publish contacts"
        assert len(hub.ops._contacts) > 0, "the same contacts must reach the OPS PPI"
        kinds = {c["kind"] for c in atlas._contacts.values()}
        assert "drone" in kinds and "aircraft" in kinds   # drones first-class
        a_worker, o_worker = atlas._worker, hub.ops._worker
    finally:
        hub.close()                              # always stop workers, even on a failed assert
        _pump(200)
    assert not (a_worker and a_worker.isRunning())
    assert not (o_worker and o_worker.isRunning())


def test_atlas_live_mode_fabricates_zero_contacts():
    _app()
    from palisade_qt import eventbus
    eventbus.bus.clear()
    from palisade_qt.atlas import AtlasApp
    atlas = AtlasApp(demo=False, mode="dark")
    win = atlas.standalone()
    try:
        win.show()
        _pump(600)
        assert len(atlas._contacts) == 0, "live ATLAS with no backend must not invent contacts"
    finally:
        win.close()
        _pump(150)


def test_adsb_to_contact_shapes_a_real_aircraft():
    from palisade_qt.atlas import adsb_to_contact
    a = {"hex": "a1b2c3", "flight": "UAL123 ", "lat": 47.6, "lon": -122.3,
         "alt_baro": 34000, "gs": 420, "track": 270, "squawk": "1200"}
    ev = adsb_to_contact(a)
    assert ev["type"] == "contact" and ev["source"] == "ADS-B"
    p = ev["payload"]
    assert p["kind"] == "aircraft" and p["id"] == "UAL123" and p["lat"] == 47.6
    assert p["alt"] == 34000 and p["spd"] == 420 and ev["severity"] == "live"
    assert adsb_to_contact({"hex": "x", "flight": "Y"}) is None        # no position -> dropped
    assert adsb_to_contact(dict(a, squawk="7700"))["severity"] == "alert"   # emergency -> alert


def test_atlas_adsb_contacts_converts_a_snapshot():
    from palisade_qt.atlas import adsb_contacts
    snap = [{"hex": "a1", "flight": "ASA9", "lat": 47.7, "lon": -122.4, "alt_baro": 12000, "gs": 300},
            {"hex": "b2", "flight": "NOPOS"}]            # second has no position -> dropped
    evs = adsb_contacts(snap)
    assert len(evs) == 1 and evs[0]["payload"]["kind"] == "aircraft"
    assert evs[0]["payload"]["id"] == "ASA9" and evs[0]["source"] == "ADS-B"


def test_rid_source_decodes_drone_and_operator():
    """dronewatch's OpenDroneID decoder -> drone + operator contacts (operator = the RID differentiator)."""
    from palisade_qt.atlas import RidSource
    import dronewatch
    rs = RidSource()                       # no BLE scan (we feed real ODID payloads directly)
    demo = dronewatch.Demo({"lat": 47.6, "lon": -122.3})
    for addr, payload, rssi in demo.adverts():
        rs.ingest_payload(addr, payload, rssi)
    evs = rs.contacts()
    kinds = {e["payload"]["kind"] for e in evs}
    assert "drone" in kinds and "operator" in kinds, "RID must plot the drone AND its operator"
    drone = next(e for e in evs if e["payload"]["kind"] == "drone")
    assert drone["source"] == "RID" and drone["severity"] == "alert"
    op = next(e for e in evs if e["payload"]["kind"] == "operator")
    assert op["source"] == "RID"
    assert isinstance(op["payload"]["lat"], float) and isinstance(op["payload"]["lon"], float)
    rs.stop()


class _FakeLease:
    def __init__(self):
        self.acquired = False
        self.released = 0

    def acquire(self, keep=()):
        self.acquired = True

    def release(self, restart=True):
        self.released += 1


def test_aprs_source_acquires_via_arbiter_and_releases(monkeypatch):
    """APRS goes through the shared arbiter: poll() acquires, stop() releases; decode is aprs's."""
    from palisade_qt import atlas, radio_arbiter as ra
    rel = []
    monkeypatch.setattr(ra, "_make_lease", lambda name: type("L", (), {"release": lambda s, restart=True: rel.append(1)})())
    monkeypatch.setattr(atlas, "_open_aprs_pipe", lambda gain: None)   # no real radio in tests
    src = atlas.AprsSource()
    src.start()
    src.poll()                                       # deferred acquire happens on first poll
    assert ra.arbiter.owner() == "ATLAS-APRS"
    src.feed_line("APRS: K7ABC>APRS,WIDE1-1:!3758.00N/12221.00W>Mobile test")
    evs = src.poll()
    assert any(e["payload"]["kind"] == "station" and e["payload"]["id"] == "K7ABC" for e in evs)
    assert evs[0]["source"] == "APRS"
    src.stop()
    assert ra.arbiter.owner() is None and rel == [1], "stop() must release the SDR via the arbiter"


def test_atlas_live_aprs_layer_toggles_the_lease_and_release_on_close(monkeypatch):
    _app()
    from palisade_qt import atlas, radio_arbiter as ra
    rel = []
    monkeypatch.setattr(ra, "_make_lease", lambda name: type("L", (), {"release": lambda s, restart=True: rel.append(1)})())
    monkeypatch.setattr(atlas, "_open_aprs_pipe", lambda gain: None)
    w = atlas.AtlasLiveWorker()
    assert not w._lease_srcs                      # off by default -> no lease on open
    w.set_layer("station", True)
    w._reconcile_leases()
    w._lease_srcs["station"].poll()               # acquire on first poll
    assert ra.arbiter.owner() == "ATLAS-APRS"
    w.set_layer("station", False)
    w._reconcile_leases()
    assert "station" not in w._lease_srcs and ra.arbiter.owner() is None and rel == [1]
    # a close while active must release too
    w.set_layer("station", True)
    w._reconcile_leases()
    w._lease_srcs["station"].poll()
    w.stop()
    w.run()                                       # loop exits immediately -> releases
    assert ra.arbiter.owner() is None and len(rel) == 2, "page close must release the lease"


def test_atlas_live_default_has_aprs_layer_off():
    _app()
    from palisade_qt.atlas import AtlasApp
    live = AtlasApp(demo=False, mode="dark")
    assert "station" not in live._layers and "vessel" not in live._layers, \
        "APRS + AIS (radio) must be opt-in in live mode"
    demo = AtlasApp(demo=True, mode="dark")
    assert "station" in demo._layers, "demo shows APRS (no radio cost)"


def test_radio_arbiter_single_owner(monkeypatch):
    from palisade_qt import radio_arbiter as ra
    rel = []
    monkeypatch.setattr(ra, "_make_lease",
                        lambda name: type("L", (), {"release": lambda s, restart=True: rel.append(name)})())
    assert ra.arbiter.request("ATLAS-APRS") is True
    assert ra.arbiter.owner() == "ATLAS-APRS"
    assert ra.arbiter.request("ATLAS-AIS") is False       # radio busy -> denied
    assert ra.arbiter.owner() == "ATLAS-APRS"             # owner unchanged
    ra.arbiter.release("ATLAS-AIS")                       # not the owner -> no-op
    assert ra.arbiter.owner() == "ATLAS-APRS" and rel == []
    ra.arbiter.release("ATLAS-APRS")
    assert ra.arbiter.owner() is None and rel == ["ATLAS-APRS"]
    assert ra.arbiter.request("ATLAS-AIS") is True        # free again
    ra.arbiter.release("ATLAS-AIS")


def test_ais_source_decodes_vessels_via_arbiter(monkeypatch):
    from palisade_qt import atlas, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)       # no real radio
    monkeypatch.setattr(atlas, "_open_ais_pipe", lambda gain: None)
    import ais
    src = atlas.AisSource()
    src.start()
    src.poll()
    assert ra.arbiter.owner() == "ATLAS-AIS"
    for ln in ais.Demo().SENTENCES:
        src.feed_line(ln)
    evs = src.poll()
    assert any(e["payload"]["kind"] == "vessel" for e in evs) and evs[0]["source"] == "AIS"
    assert evs[0]["payload"]["mmsi"]
    src.stop()
    assert ra.arbiter.owner() is None


def test_arbiter_only_one_lease_layer_live_other_shows_busy(monkeypatch):
    """The DoD arbiter test: AIS-on while APRS holds the radio -> AIS shows BUSY, only one live."""
    _app()
    from palisade_qt import atlas, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    monkeypatch.setattr(atlas, "_open_aprs_pipe", lambda g: None)
    monkeypatch.setattr(atlas, "_open_ais_pipe", lambda g: None)
    w = atlas.AtlasLiveWorker()
    w.set_layer("station", True)
    w._reconcile_leases()
    w._lease_srcs["station"].poll()                 # APRS grabs the radio
    assert ra.arbiter.owner() == "ATLAS-APRS"
    w.set_layer("vessel", True)
    w._reconcile_leases()
    aprs, ais_src = w._lease_srcs["station"], w._lease_srcs["vessel"]
    aprs.poll()
    ais_src.poll()
    assert aprs.busy_owner() is None                # APRS holds it
    assert ais_src.busy_owner() == "ATLAS-APRS"     # AIS BUSY, held by APRS -> only one is live
    assert ra.arbiter.owner() == "ATLAS-APRS"       # still exactly one owner
    # release APRS -> AIS can take the radio
    w.set_layer("station", False)
    w._reconcile_leases()
    assert ra.arbiter.owner() is None
    ais_src.poll()
    assert ra.arbiter.owner() == "ATLAS-AIS" and ais_src.busy_owner() is None
    ais_src.stop()


def test_adsb_goes_busy_when_a_lease_layer_holds_the_radio(monkeypatch):
    """Fold ADS-B into the arbiter: while a lease-layer owns the radio, readsb is paused so ATLAS
    publishes no aircraft; it resumes when released."""
    _app()
    from palisade_qt import atlas, radio_arbiter as ra, eventbus
    eventbus.bus.clear()
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    monkeypatch.setattr(atlas, "_open_aprs_pipe", lambda g: None)

    class FakeAdsb:
        stopped = False

        def snapshot(self):
            return ([{"hex": "a1", "flight": "UAL1", "lat": 47.7, "lon": -122.4, "alt_baro": 30000}],
                    {}, "live", None)
    w = atlas.AtlasLiveWorker()
    w._adsb, w._adsb_tried, w._rid_tried = FakeAdsb(), True, True   # adsb up, skip rid
    got = []
    eventbus.bus.published.connect(lambda e: got.append(e) if e["type"] == "contact" else None)
    w.step()
    assert any(e["payload"].get("kind") == "aircraft" for e in got), "ADS-B live when radio free"
    got.clear()
    w.set_layer("station", True)
    w._reconcile_leases()
    w._lease_srcs["station"].poll()                 # APRS now owns the radio
    w.step()
    assert not any(e["payload"].get("kind") == "aircraft" for e in got), "ADS-B BUSY while held"
    for s in list(w._lease_srcs.values()):
        s.stop()


# ---- BABEL PR-B1: single-SDR via the arbiter (not the base-class lease) ----

def test_babel_app_leases_per_mode_not_via_base_class():
    """PR-B1: BabelApp must NOT hold the base-class lease — its radio modes go through the
    shared arbiter, so it coexists with ATLAS/PRISM under one SDR owner."""
    from palisade_qt.babel import BabelApp
    from palisade_qt import radio_arbiter as ra
    assert BabelApp.LEASE is None
    assert ra.OWNER_LABELS.get("BABEL") == "BABEL"


def test_babel_live_mode_acquires_and_releases_via_arbiter(monkeypatch):
    """A live radio mode takes the single SDR via the arbiter while decoding, then releases it."""
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)       # no real radio
    seen = []
    monkeypatch.setitem(babel._LIVE_RUNNERS, "AIS",
                        lambda worker: seen.append(ra.arbiter.owner()))
    w = babel.DecoderWorker(demo=False, mode="AIS")
    w._run_live("AIS")
    assert seen == ["BABEL"], "BABEL must own the radio while its decoder runs"
    assert ra.arbiter.owner() is None, "_run_live must release the SDR when the decoder returns"


def test_babel_live_mode_shows_busy_when_radio_held_elsewhere(monkeypatch):
    """Honest single-SDR: if another callsign owns the radio, BABEL shows RADIO BUSY and (being
    live) never opens the dongle or synthesises data."""
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    ran = []
    monkeypatch.setitem(babel._LIVE_RUNNERS, "AIS", lambda worker: ran.append(1))
    assert ra.arbiter.request("ATLAS-APRS") is True                # APRS holds the radio
    w = babel.DecoderWorker(demo=False, mode="AIS")
    w._mode_changed = True                                          # don't block on the retry sleep
    status = []
    w.status.connect(lambda s: status.append(s))
    w._run_live("AIS")
    assert ran == [], "BABEL must not decode while the radio is busy"
    assert ra.arbiter.owner() == "ATLAS-APRS", "the holder keeps the SDR; BABEL never took it"
    assert any(s.get("busy") for s in status), "BABEL must emit a RADIO BUSY status"
    ra.arbiter.release("ATLAS-APRS")


def test_babel_runners_never_open_a_real_radio_offscreen():
    """The _open_pipe seam returns None under offscreen/offline, so the live runners spawn no
    subprocess in tests/CI (QT_QPA_PLATFORM=offscreen is set at import)."""
    from palisade_qt import babel
    assert babel._open_pipe(["echo", "x"], shell=False) is None
    w = babel.DecoderWorker(demo=False, mode="AIS")
    babel._run_ais(w)                                              # returns immediately, no proc
    assert w._proc is None


def test_babel_open_close_no_leaked_thread_or_lease():
    from palisade_qt.babel import BabelApp
    from palisade_qt import radio_arbiter as ra
    _app()
    a = BabelApp(demo=False, mode="dark")
    a.start()
    _pump(200)
    a.stop()
    assert ra.arbiter.owner() is None, "closing BABEL must leave the SDR free"


def test_babel_live_no_binary_shows_standby_not_synth(monkeypatch):
    """Live mode with the decoder binary absent must show an honest STANDBY and emit NO rows —
    live never synthesises (that contract matches ATLAS/OPS)."""
    from palisade_qt import babel
    monkeypatch.setattr(babel, "_can_run", lambda mode: False)
    w = babel.DecoderWorker(demo=False, mode="AIS")
    w._mode_changed = True                               # exit the idle loop immediately
    rows, status = [], []
    w.row.connect(lambda r: rows.append(r))
    w.status.connect(lambda s: status.append(s))
    w._run_standby("AIS")
    assert rows == [], "live mode must not fabricate decoder rows when no hardware is present"
    assert any("STANDBY" in (s.get("sdr") or {}).get("text", "") for s in status)


# ---- BABEL PR-B2: TPMS decoder (rtl_433 JSON -> parse_tpms AS-IS, SDR lease, bus) ----

def test_babel_tpms_registered():
    from palisade_qt import babel
    assert "TPMS" in babel.MODES
    assert babel._MODE_BINARY.get("TPMS") == "rtl_433"
    assert "TPMS" in babel._LIVE_RUNNERS


def test_babel_tpms_decodes_and_publishes_to_bus(monkeypatch):
    from palisade_qt import babel, eventbus
    eventbus.bus.clear()
    decs = []
    eventbus.bus.published.connect(lambda e: decs.append(e) if e["type"] == "decode" else None)
    line = ('{"model":"Toyota","type":"TPMS","id":"3a1c","pressure_kPa":230.0,'
            '"temperature_C":21.0,"battery_ok":1,"rssi":-42.0}')

    class FakeProc:
        pid = 2147483646        # unused: poll()=0 makes _stop_proc early-return (no killpg)
        stdout = [line, "not json, rtl_433 chatter\n"]

        def poll(self):
            return 0
    monkeypatch.setattr(babel, "_open_pipe", lambda *a, **k: FakeProc())
    w = babel.DecoderWorker(demo=False, mode="TPMS")
    rows = []
    w.row.connect(lambda r: rows.append(r))
    babel._run_tpms(w)
    assert len(rows) == 1 and rows[0]["proto"] == "TPMS" and rows[0]["id"] == "3a1c"
    assert "230 kPa" in rows[0]["summary"]
    assert decs and decs[0]["source"] == "BABEL-TPMS" and decs[0]["payload"]["id"] == "3a1c"


def test_babel_tpms_live_no_rtl433_standby_not_synth(monkeypatch):
    """TPMS is a radio mode: no rtl_433 -> honest STANDBY, no fabricated rows."""
    from palisade_qt import babel
    monkeypatch.setattr(babel, "_can_run", lambda mode: False)
    w = babel.DecoderWorker(demo=False, mode="TPMS")
    w._mode_changed = True
    rows, status = [], []
    w.row.connect(lambda r: rows.append(r))
    w.status.connect(lambda s: status.append(s))
    w._run_standby("TPMS")
    assert rows == []
    assert any("STANDBY" in (s.get("sdr") or {}).get("text", "") and "rtl_433" in
               (s.get("sdr") or {}).get("text", "") for s in status)


def test_babel_tpms_offscreen_opens_no_radio():
    from palisade_qt import babel
    w = babel.DecoderWorker(demo=False, mode="TPMS")
    babel._run_tpms(w)                         # _open_pipe seam returns None offscreen
    assert w._proc is None


def test_babel_cw_rtty_no_live_synth_only_practice(monkeypatch):
    """CW/RTTY have no live RX backend; in LIVE mode they must publish zero rows and say
    'practice only' — never synthesise (demo is the only synthetic path)."""
    from palisade_qt import babel
    for mode in ("CW", "RTTY"):
        w = babel.DecoderWorker(demo=False, mode=mode)
        w._mode_changed = True
        rows, status = [], []
        w.row.connect(lambda r: rows.append(r))
        w.status.connect(lambda s: status.append(s))
        w._run_practice(mode)
        assert rows == [], "%s must not synthesise decodes in live mode" % mode
        assert any(s.get("practice") and "practice only" in (s.get("sdr") or {}).get("text", "")
                   for s in status)


# ---- BABEL PR-B3: SSTV image decoder (sstv.Recorder + sstvdec.decode_wav AS-IS) ----

def test_babel_sstv_registered():
    from palisade_qt import babel, radio_arbiter as ra
    assert "SSTV" in babel.MODES
    assert ra.OWNER_LABELS.get("BABEL-SSTV")


def test_babel_sstv_demo_emits_image():
    from palisade_qt import babel
    w = babel.SstvWorker(demo=True)
    rows = []
    w.row.connect(lambda r: rows.append(r))
    w.step()
    assert rows and rows[0]["kind"] == "sstv" and rows[0].get("demo")
    assert rows[0]["image"].shape[2] == 3


def test_babel_sstv_live_leases_and_decodes(monkeypatch):
    import numpy as np
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    monkeypatch.setattr(babel.shutil, "which", lambda b: "/usr/bin/" + b)   # rtl_fm "present"
    w = babel.SstvWorker(demo=False)

    class FakeRec:
        level = 120.0
        err = ""

        def seconds(self):
            return 25.0

        def stop(self):
            pass
    w._make_recorder = lambda path: FakeRec()
    w._decode = lambda path: {"image": np.zeros((8, 8, 3), np.uint8), "mode": "PD120",
                              "lines": 496, "slant_ppm": 2}
    rows = []
    w.row.connect(lambda r: rows.append(r))
    app = _app()
    w.step()                                     # leases + starts the (daemon) decode
    assert ra.arbiter.owner() == "BABEL-SSTV"
    import time as _t
    t0 = _t.time()
    while not rows and _t.time() - t0 < 3:       # decode runs off the step thread -> await it
        app.processEvents()
        _t.sleep(0.02)
    img = [r for r in rows if r.get("kind") == "sstv"]
    assert img and img[0]["mode"] == "PD120" and img[0]["image"].shape == (8, 8, 3)
    w.stop()
    assert ra.arbiter.owner() is None, "closing SSTV releases the SDR"


def test_babel_sstv_stop_joins_during_a_slow_decode(monkeypatch):
    """The HIGH fix: decode_wav runs on a disposable daemon thread, so a slow decode never blocks
    the worker QThread — stop()/wait() joins promptly instead of orphaning the thread."""
    import time as _t
    import numpy as np
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    monkeypatch.setattr(babel.shutil, "which", lambda b: "/usr/bin/" + b)
    w = babel.SstvWorker(demo=False)

    class FakeRec:
        level = 120.0
        err = ""

        def seconds(self):
            return 25.0

        def stop(self):
            pass
    w._make_recorder = lambda path: FakeRec()

    def slow_decode(path):
        _t.sleep(5)                              # longer than wait(3000)
        return {"image": np.zeros((4, 4, 3), np.uint8), "mode": "PD120", "lines": 4, "slant_ppm": 0}
    w._decode = slow_decode
    w.start()
    t0 = _t.time()
    while not w._decoding and _t.time() - t0 < 3:
        _t.sleep(0.02)
    assert w._decoding, "a decode should be in flight"
    t1 = _t.time()
    w.stop()
    w.quit()
    assert w.wait(3000), "worker must join within 3s even though decode_wav is still running"
    assert _t.time() - t1 < 3.0
    assert ra.arbiter.owner() is None


def test_babel_sstv_rtl_fm_death_reaps_and_retries(monkeypatch):
    """The MED fix: a dead rtl_fm (rec.err) reaps the Recorder so the next step can restart,
    instead of latching forever while holding the lease."""
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    monkeypatch.setattr(babel.shutil, "which", lambda b: "/usr/bin/" + b)
    w = babel.SstvWorker(demo=False)
    stopped = []

    class DeadRec:
        level = 0.0
        err = "rtl_fm stopped - is the SDR free?"

        def seconds(self):
            return 5.0

        def stop(self):
            stopped.append(1)
    w._make_recorder = lambda path: DeadRec()
    w.step()                                      # leases, makes the recorder, sees err -> reaps it
    assert ra.arbiter.owner() == "BABEL-SSTV"     # lease kept so the next step can restart
    assert w._rec is None and stopped, "dead recorder must be stopped/cleared, not latched forever"
    w.stop()
    assert ra.arbiter.owner() is None


def test_babel_mode_switch_clears_stale_sstv_frame():
    _app()
    import numpy as np
    from palisade_qt.babel import BabelApp
    p = BabelApp(demo=True, mode="dark")
    p.mode_combo.setCurrentText("SSTV")
    p.image_panel.show_image(np.zeros((8, 8, 3), np.uint8), "old frame")
    assert p.image_panel._buf is not None
    p.mode_combo.setCurrentText("AIS")
    p.mode_combo.setCurrentText("SSTV")
    assert p.image_panel._buf is None, "switching modes must clear the prior frame"


def test_babel_sstv_no_rtl_fm_standby_no_lease(monkeypatch):
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setattr(babel.shutil, "which", lambda b: None)
    w = babel.SstvWorker(demo=False)
    seen = []
    w.status.connect(lambda s: seen.append(s))
    w.step()
    assert ra.arbiter.owner() is None
    assert any(s.get("standby") and "rtl_fm" in (s.get("sdr") or {}).get("text", "") for s in seen)


def test_babel_sstv_offscreen_opens_no_recorder(monkeypatch):
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    monkeypatch.setattr(babel.shutil, "which", lambda b: "/usr/bin/" + b)
    w = babel.SstvWorker(demo=False)
    w.step()                                 # real _make_recorder returns None under offscreen
    assert w._rec is None and ra.arbiter.owner() == "BABEL-SSTV"
    w.stop()
    assert ra.arbiter.owner() is None


def test_sstv_image_panel_renders_ndarray():
    _app()
    import numpy as np
    from palisade_qt.babel import SstvImagePanel
    p = SstvImagePanel(mode="dark")
    p.show_image(np.zeros((16, 24, 3), np.uint8), "test frame")
    pm = p.view.pixmap()
    assert pm is not None and not pm.isNull()


def test_babel_switch_to_sstv_swaps_view_and_worker():
    _app()
    from palisade_qt.babel import BabelApp, SstvWorker, DecoderWorker
    p = BabelApp(demo=True, mode="dark")
    assert p.stack.currentIndex() == 0 and isinstance(p.make_worker(), DecoderWorker)
    p.mode_combo.setCurrentText("SSTV")
    assert p.stack.currentIndex() == 1 and isinstance(p.make_worker(), SstvWorker)
    p.mode_combo.setCurrentText("AIS")
    assert p.stack.currentIndex() == 0 and isinstance(p.make_worker(), DecoderWorker)


# ---- RECON: engagement-gated active tools + passive scans + counter detectors ----

def _reset_engagement():
    import engagement
    engagement.reset()


def test_recon_active_tools_locked_without_engagement():
    _app()
    _reset_engagement()
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False, mode="dark")
    for g in p._gated:
        assert all(not b.isEnabled() for b in g._btns), "active tools must be locked, no engagement"
    g = p.wifi_gated
    g.target.setText("aa:bb:cc:dd:ee:ff")
    g._authorize("deauth")
    assert "DENIED" in g.result.text() and "no active engagement" in g.result.text()
    _reset_engagement()


def test_recon_gate_authorizes_in_scope_denies_out_of_scope():
    _app()
    _reset_engagement()
    import engagement
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False, mode="dark")
    engagement.start("Op", "ROE-7", ["aa:bb:cc:*"], "N0CALL")
    p._refresh_gate()
    g = p.wifi_gated
    assert all(b.isEnabled() for b in g._btns), "unlocked under an active engagement"
    g.target.setText("aa:bb:cc:dd:ee:ff")
    g._authorize("deauth")
    assert "AUTHORIZED" in g.result.text() and "wifi:deauth" in g.result.text()
    assert any(a["action"] == "wifi:deauth" for a in engagement.actions()), "logged to the trail"
    g.target.setText("99:99:99:99:99:99")               # out of scope
    g._authorize("deauth")
    assert "DENIED" in g.result.text() and "scope" in g.result.text()
    _reset_engagement()


def test_recon_wifi_passive_demo_and_standby(monkeypatch):
    from palisade_qt import recon
    w = recon.WifiScanWorker(demo=True)
    rows = []
    w.row.connect(lambda m: rows.append(m))
    w.step()
    assert rows and rows[0].get("demo") and rows[0]["aps"], "demo shows synthetic APs"
    # live with no adapter/iw -> honest standby, no fabrication
    w2 = recon.WifiScanWorker(demo=False)
    seen, rows2 = [], []
    w2.status.connect(lambda s: seen.append(s))
    w2.row.connect(lambda m: rows2.append(m))
    w2.step()                                            # offscreen -> _run_cmd None -> standby
    assert rows2 == [] and any(s.get("standby") for s in seen)


def test_recon_counter_alert_reaches_bus_and_feed():
    _app()
    from palisade_qt import recon, eventbus
    eventbus.bus.clear()
    alerts = []
    eventbus.bus.published.connect(lambda e: alerts.append(e) if e["type"] == "alert" else None)
    p = recon.ReconApp(demo=True, mode="dark")
    p._on_counter({"kind": "gnss", "alert": ("gnss", "GPS jamming suspected (low C/N0)")})
    assert p.counter_feed.model.rowCount() == 1
    assert alerts and alerts[-1]["source"] == "RECON" and alerts[-1]["severity"] == "alert"


def test_recon_demo_detectors_run_and_can_alert():
    """All four real detector engines run AS-IS over a persistent synthetic feed and surface a
    finding (with a human-readable text) — exercising the reuse path without any radio."""
    from palisade_qt import recon
    for kind in ("bugsweep", "jammer", "imsicatch", "gnss"):
        w = recon.DetectorWorker(demo=True, kind=kind)     # persistent _det accumulates
        got = [a for a in (w._demo_detect() for _ in range(200)) if a]
        assert got, "demo %s should surface at least one finding over many cycles" % kind
        det, text = got[0]
        assert det and isinstance(text, str) and text, "%s finding needs readable text" % kind


def test_recon_counter_detectors_have_no_tx_path():
    """Guardrail: the counter modules are receive-only detectors — no transmit/jam/attack."""
    import inspect
    import bugsweep, jammer, imsicatch, gnss
    for mod in (bugsweep, jammer, imsicatch, gnss):
        src = inspect.getsource(mod)
        low = src.lower()
        for bad in ("txrequest", "txguard.authorize", "subprocess.popen", "deauth", "transmit("):
            assert bad not in low, "%s must stay a passive detector (found %r)" % (mod.__name__, bad)


def test_recon_engage_activate_deactivate_and_trail():
    _app()
    _reset_engagement()
    import engagement
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False, mode="dark")
    p.eng_name.setText("NightWatch")
    p.eng_auth.setText("ROE-42")
    p.eng_scope.setText("10.0.0.*, Corp-*")
    p.eng_operator.setText("N0CALL")
    p._activate()
    assert engagement.is_active() and "NightWatch" in p.eng_detail.hero.text()
    p._deactivate()
    assert not engagement.is_active()
    _reset_engagement()


def test_recon_open_pump_close_no_leaked_threads():
    _app()
    _reset_engagement()
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False, mode="dark")
    p.start()
    _pump(200)
    p.stop()
    assert all(not w.isRunning() for w in p._workers) if p._workers else True
    _reset_engagement()


def test_recon_demo_stays_off_the_shared_bus():
    """Honesty: synthetic demo RECON data is shown locally but must NOT pollute the OPS event bus."""
    _app()
    from palisade_qt import recon, eventbus
    eventbus.bus.clear()
    evs = []
    eventbus.bus.published.connect(lambda e: evs.append(e))
    p = recon.ReconApp(demo=True, mode="dark")
    p._on_wifi({"aps": recon._demo_aps(), "demo": True})
    p._on_ble({"devs": [{"address": "a", "name": "x", "vendor": "v", "kind": "k", "rssi": -50}],
               "demo": True})
    p._on_counter({"kind": "bugsweep", "alert": ("bug", "2 suspect"), "demo": True})
    assert evs == [], "demo synthetic RECON data must not publish to the shared bus"


def test_recon_passaudit_hashcat_authorizes_in_scope():
    _app()
    _reset_engagement()
    import engagement
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False, mode="dark")
    engagement.start("Op", "ROE-9", ["cap-*"], "N0CALL")
    p._refresh_gate()
    g = p.pass_gated
    g.target.setText("cap-01")
    g._authorize("hashcat")                            # a real passaudit op (was the dead 'crack')
    assert "AUTHORIZED" in g.result.text() and "passaudit:hashcat" in g.result.text()
    _reset_engagement()


# ---- FORGE: hardware bench — engagement + txguard gates, console, honest standby ----

def test_forge_engagement_tools_locked_without_engagement():
    _app()
    _reset_engagement()
    from palisade_qt.forge import ForgeApp, EngagementCard
    p = ForgeApp(demo=False, mode="dark")
    eng_cards = [c for c in p._cards if isinstance(c, EngagementCard)]
    assert eng_cards, "FORGE has engagement-gated cards"
    for c in eng_cards:
        assert not c._btn.isEnabled(), "gated tool locked with no engagement"
    _reset_engagement()


def test_forge_canbus_tx_gated_by_engagement():
    _app()
    _reset_engagement()
    import engagement, canbus
    from palisade_qt.forge import ForgeApp
    p = ForgeApp(demo=False, mode="dark")
    # no engagement -> denied, no argv
    ok, why, argv = p._can_send(canbus, {"id": "7DF", "data": "0201", "target": "ecu-1"}, p.evidence)
    assert ok is False and argv is None and "engagement" in why.lower()
    # in-scope engagement -> authorized + argv produced by the engine
    engagement.start("Op", "ROE", ["ecu-*"], "N0CALL")
    ok, why, argv = p._can_send(canbus, {"id": "7DF", "data": "0201", "target": "ecu-1"}, p.evidence)
    assert ok is True and argv and argv[0] == "cansend"
    # out of scope -> denied
    ok, why, argv = p._can_send(canbus, {"id": "7DF", "data": "0201", "target": "other"}, p.evidence)
    assert ok is False and argv is None
    _reset_engagement()


def test_forge_proxmark_write_gated_and_reads_are_not():
    _app()
    _reset_engagement()
    import engagement, proxmark
    from palisade_qt.forge import ForgeApp
    p = ForgeApp(demo=False, mode="dark")
    active = [o for o, v in proxmark.OPS.items() if v[0] and "{" not in v[1]][0]  # no-param op
    ok, why, cmd = p._pm_write(proxmark, {"op": active, "target": "badge-1"}, p.evidence)
    assert ok is False and cmd is None, "write op gated without engagement"
    engagement.start("Op", "ROE", ["badge-*"], "N0CALL")
    ok, why, cmd = p._pm_write(proxmark, {"op": active, "target": "badge-1"}, p.evidence)
    assert ok is True and cmd
    # a read op is NOT gated
    ok, why, cmd = p._pm_write(proxmark, {"op": "lf_search", "target": ""}, p.evidence)
    assert ok is True and "ungated" in why
    _reset_engagement()


def test_forge_replay_is_txguard_gated():
    _app()
    import txguard
    from palisade_qt.forge import ForgeApp
    p = ForgeApp(demo=False, mode="dark")
    txguard.arm(False)
    p.replay_card.refresh()
    assert "TX GATED" in p.replay_card.state.text()
    # confirm but TX not armed -> denied, no argv
    p.replay_card.confirm.setChecked(True)
    p.replay_card._run()
    assert "DENIED" in p.replay_card.result.text()


def test_forge_serial_console_demo_populates_and_live_standby():
    from palisade_qt import forge
    w = forge.SerialWorker(demo=True)
    rows = []
    w.row.connect(lambda m: rows.append(m))
    w.step()
    w.step()
    assert any(r.get("kind") == "rx" for r in rows), "demo serial yields console output"
    w.stop()
    # live with no port -> NO DEVICE standby, no fabrication
    w2 = forge.SerialWorker(demo=False, port=None)
    seen, rows2 = [], []
    w2.status.connect(lambda s: seen.append(s))
    w2.row.connect(lambda m: rows2.append(m))
    w2.step()
    assert rows2 == [] and any(s.get("standby") for s in seen)


def test_forge_can_monitor_demo_decodes():
    from palisade_qt import forge
    w = forge.CanWorker(demo=True)
    rows = []
    w.row.connect(lambda m: rows.append(m))
    w.step()
    assert rows and "frame" in rows[0] and rows[0].get("demo")


def test_forge_open_pump_close_no_leaked_threads():
    _app()
    _reset_engagement()
    from palisade_qt.forge import ForgeApp
    p = ForgeApp(demo=False, mode="dark")
    p.start()
    _pump(200)
    p.stop()
    assert all(not w.isRunning() for w in p._workers) if p._workers else True
    _reset_engagement()


def test_forge_serial_stop_does_not_reopen_reader():
    """Review fix: a worker shutting down must not re-open (leak) the serial port in step()."""
    from palisade_qt import forge
    w = forge.SerialWorker(demo=True)
    w.step()                                     # opens DemoSerial
    assert w._reader is not None
    w.stop()                                     # not running (direct-step) -> closes the reader
    assert w._reader is None
    w.step()                                     # _stop is set -> must NOT re-open
    assert w._reader is None


def test_forge_serial_write_queue_drains_atomically():
    from palisade_qt import forge
    w = forge.SerialWorker(demo=True)
    w.step()                                     # connect
    w.write("AT")
    with w._lock:
        assert w._pending == ["AT"]
    w.step()                                     # locked drain -> no lost keystroke
    assert w._pending == []
    w.stop()
