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
        from palisade_qt import chrome, panels
        chrome.reset()
        panels.reset_alert_store()
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


def test_base_class_never_touches_the_dongle(monkeypatch):
    """CL5/A5: the base-class daemon-thread lease path is gone; the SDR is owned only through
    radio_arbiter. A LEASE attribute is inert in demo AND live."""
    _app()
    import suite
    from palisade_qt.app import PalisadeApp
    touched = []
    monkeypatch.setattr(suite, "RtlLease", lambda name: touched.append(name) or None)

    class RadioApp(PalisadeApp):
        TITLE = "RADIO"
        LEASE = "TestLease"

    for demo in (True, False):
        a = RadioApp(demo=demo, mode="dark")
        a.start()
        _pump(50)
        a.stop()
    assert touched == [] and not hasattr(PalisadeApp, "_acquire_lease")


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


# the seven page keys besides OPS, plus the four callsigns CL1 folded into them (still openable by
# their old names: they land on their new page's sub-tab)
PAGE_KEYS = ["ATLAS", "PRISM", "PROWL", "SWEEP", "RECON", "FORGE", "SYSTEM"]
FOLDED_CALLSIGNS = ["OVERWATCH", "BABEL", "BENCH", "MORE"]
ALL_CALLSIGNS = PAGE_KEYS + FOLDED_CALLSIGNS


@pytest.mark.parametrize("name", ALL_CALLSIGNS)
def test_every_callsign_opens_pumps_closes_clean(name, monkeypatch):
    monkeypatch.setenv("PALISADE_SHOW_HIDDEN", "1")  # CL8 v0.1: SWEEP is hidden but still built
    _app()
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=True, mode="dark")
    hub.show()
    page = hub.page_app(name)           # the app behind the key (or behind the folded callsign)
    _pump(600)
    assert name in hub.pages
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


def test_hub_soak_open_all_callsigns_then_close_no_leaks(monkeypatch):
    """Back-test: one hub, open every callsign in sequence, pump, close -> zero running QThreads."""
    from PySide6 import QtCore
    _app()
    from palisade_qt.shell import PalisadeHub, QT_PAGES
    monkeypatch.setenv("PALISADE_SHOW_HIDDEN", "1")  # CL8 v0.1: SWEEP hidden, still soaked
    before = QtCore.QThread.__subclasses__()  # noqa: F841 (kept for clarity)
    hub = PalisadeHub(demo=True, mode="dark")
    hub.show()
    workers = []
    for name in ALL_CALLSIGNS:
        w = hub.page_app(name)._worker
        _pump(250)
        if w is not None:
            workers.append((name, w))
    assert hub.stack.count() == len(QT_PAGES) + 1       # one stacked page per key (+OPS)
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
        assert set(e) == {"type", "source", "severity", "ts", "payload", "demo"}   # H7: demo flag
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
        atlas = hub.page_app("ATLAS")
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
    # CL8 P3: one advert is an unauthenticated claim -> amber UNCONFIRMED, never the red alert
    assert drone["source"] == "RID" and drone["severity"] == "warn"
    assert drone["payload"]["trust"] == "unconfirmed"
    for c in rs._drones.by_addr.values():
        c["first"] -= 3.0                     # heard for 3 s …
    for _ in range(3):                        # … and several adverts: confirmed, red
        for addr, payload, rssi in demo.adverts():
            rs.ingest_payload(addr, payload, rssi)
    evs = rs.contacts()
    drone = next(e for e in evs if e["payload"]["kind"] == "drone")
    assert drone["severity"] == "alert" and drone["payload"]["trust"] == "confirmed"
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


def test_balloon_contacts_reads_sondes_cache(tmp_path):
    from palisade_qt import atlas
    import json
    p = tmp_path / "sondes.json"
    p.write_text(json.dumps({"t": 0, "sondes": [
        {"id": "V1234567", "lat": 47.7, "lon": -122.4, "alt": 18000.0, "vel_h": 12.0, "model": "RS41"},
        {"id": "NOPOS", "alt": 1000.0}]}))      # second has no position -> dropped
    evs = atlas.balloon_contacts(str(p))
    assert len(evs) == 1
    pl = evs[0]["payload"]
    assert pl["kind"] == "balloon" and pl["id"] == "V1234567" and evs[0]["source"] == "SONDE"
    assert pl["alt"] == 59055            # 18000 m -> ft
    assert atlas.balloon_contacts(str(tmp_path / "missing.json")) == []   # no file -> zero


def test_df_contacts_zero_without_kraken():
    from palisade_qt import atlas
    assert atlas.df_contacts() == []     # no KrakenSDR array -> honest zero


def test_atlas_live_balloon_reaches_ops(monkeypatch, tmp_path):
    _app()
    from palisade_qt import atlas, eventbus
    import json
    eventbus.bus.clear()
    p = tmp_path / "sondes.json"
    p.write_text(json.dumps({"sondes": [{"id": "V7", "lat": 47.65, "lon": -122.35, "alt": 9000.0}]}))
    monkeypatch.setattr(atlas, "_SONDES_PATH", str(p))
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=False, mode="dark")
    try:
        hub.show()
        hub.open_callsign("ATLAS")
        _pump(1300)
        assert any(c["kind"] == "balloon" for c in hub.page_app("ATLAS")._contacts.values())
        assert "V7" in hub.ops._contacts   # the same balloon reached the OPS PPI (one stream)
    finally:
        hub.close()
        _pump(200)
def test_prism_sweep_assembler_assembles_rtl_power():
    from palisade_qt.prism import _SweepAssembler
    a = _SweepAssembler()
    rows = ["d,t,430000000,435000000,10000,100,-100,-98,-45",     # segment 1
            "d,t,435000000,440000000,10000,100,-96,-95,-94",      # segment 2
            "d,t,430000000,435000000,10000,100,-100,-98,-45"]     # wrap -> emit the pass
    done = [o for o in (a.feed(r) for r in rows) if o is not None]
    assert done, "a full rtl_power pass must assemble into one sweep"
    f, p = done[0]
    assert len(f) == 6 and abs(float(p.max()) - (-45)) < 0.1


def test_prism_live_holds_radio_only_while_active(monkeypatch):
    _app()
    from palisade_qt import prism, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    monkeypatch.setattr(prism, "_open_rtl_power", lambda lo, hi, g: None)   # no real radio
    w = prism.SweepWorker(demo=False, lo=430, hi=440)
    w.set_active(True)
    w.step()
    assert ra.arbiter.owner() == "PRISM"          # active -> PRISM takes the radio
    w.set_active(False)
    w.step()
    assert ra.arbiter.owner() is None             # page left -> release
    w.set_active(True)
    w.step()
    assert ra.arbiter.owner() == "PRISM"
    w.stop()
    w.run()                                        # close -> release
    assert ra.arbiter.owner() is None


def test_prism_shows_busy_when_radio_held_by_atlas(monkeypatch):
    _app()
    from palisade_qt import prism, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    monkeypatch.setattr(prism, "_open_rtl_power", lambda lo, hi, g: None)
    assert ra.arbiter.request("ATLAS-APRS") is True      # ATLAS holds the radio
    w = prism.SweepWorker(demo=False, lo=430, hi=440)
    seen = []
    w.status.connect(seen.append)
    w.set_active(True)
    w.step()
    assert ra.arbiter.owner() == "ATLAS-APRS"            # PRISM did NOT grab it
    assert any(s.get("busy") == "APRS" for s in seen), "PRISM must report RADIO BUSY"
    ra.arbiter.release("ATLAS-APRS")


def test_prism_live_no_rtl_power_shows_standby_not_synth(monkeypatch):
    """Live + no rtl_power: PRISM holds the radio (seam-nulled here) but emits NO synthetic sweep
    and reports STANDBY — the scope stays empty, nothing is fabricated."""
    from palisade_qt import prism, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    monkeypatch.setattr(prism, "_open_rtl_power", lambda lo, hi, g: None)
    monkeypatch.setattr(prism.shutil, "which", lambda b: None)      # rtl_power absent
    w = prism.SweepWorker(demo=False, lo=430, hi=440)
    rows, seen = [], []
    w.row.connect(lambda r: rows.append(r))
    w.status.connect(lambda s: seen.append(s))
    w.set_active(True)
    w.step()
    assert rows == [], "live mode must not synthesise a sweep when rtl_power is absent"
    assert any(s.get("standby") for s in seen), "PRISM must report STANDBY without rtl_power"
    w.set_active(False)
    w.step()
    assert ra.arbiter.owner() is None, "leaving PRISM releases the radio"
def test_prowl_freqdb_allocation_and_panel():
    _app()
    from palisade_qt.prowl import ProwlApp, _describe_mhz
    assert "NOAA Weather Radio" in _describe_mhz("162.400")
    assert _describe_mhz("not-a-freq") == "—"
    p = ProwlApp(demo=True, mode="dark")
    p.fdb_input.setText("162.45")                 # numeric -> lookup/describe
    assert "NOAA Weather Radio" in p.fdb_results.text()
    p.fdb_input.setText("marine")                 # text -> search
    assert p.fdb_results.text() and "no match" not in p.fdb_results.text().lower()
    p.fdb_input.setText("")
    assert p.fdb_results.text() == ""


def test_prowl_live_no_rtl_fm_shows_standby_not_synth(monkeypatch):
    """Live mode without rtl_fm must list the bank's channels all-quiet and publish NO fabricated
    hits — live shows only real activity (honest standby), demo is the only synthetic path."""
    _app()
    from palisade_qt import prowl
    monkeypatch.setattr(prowl.shutil, "which", lambda b: None)     # no rtl_fm on PATH
    w = prowl.ScanWorker(demo=False, bank="NOAA Wx")
    rows, status = [], []
    w.status.connect(lambda s: status.append(s))
    w.row.connect(lambda m: (rows.append(m), setattr(w, "_stop", True)))   # one pass, then stop
    w._run_standby()
    assert rows, "standby must still show the channel plan"
    assert rows[0]["active"] is None
    assert all(not r.get("_hot") for r in rows[0]["rows"]), "no fabricated hot channels in standby"
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
    ra.arbiter.reset_for_tests()
    # CL5 (B1): BABEL only takes the radio while RUN is on and the page is active (wants_radio)
    monkeypatch.setitem(babel._LIVE_RUNNERS, "AIS",
                        lambda worker: (seen.append(ra.arbiter.owner()),
                                        setattr(worker, "_stop", True)))
    w = babel.DecoderWorker(demo=False, mode="AIS")
    w._running, w._active = True, True
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


# ---- PROWL PR2: FM + NWR sub-modes, all leased through the shared arbiter ----

def _hold(w):
    """CL5-fix 1: a holder is granted at once but only HOLDS the radio (and may start its
    decoder) once the arbiter's acquire finished — step until then."""
    from palisade_qt import radio_arbiter as ra
    w._ensure_lease()
    assert ra.wait_held(w.NAME, 3.0)
    return w._ensure_lease()


def _finish(w):
    """CL5-fix 6: stop() only sets flags on the GUI thread; the worker's run() reaps its
    pipeline and THEN releases. A test that drives step() by hand finishes the same way."""
    w.stop()
    w.run()


def test_prowl_off_base_lease_and_submode_labels():
    from palisade_qt.prowl import ProwlApp
    from palisade_qt import radio_arbiter as ra
    assert ProwlApp.LEASE is None                 # no base lease; each sub-mode leases per-run
    for n in ("PROWL-SCAN", "PROWL-FM", "PROWL-NWR"):
        assert n in ra.OWNER_LABELS


def test_prowl_scan_leases_and_releases_via_arbiter(monkeypatch):
    from palisade_qt import prowl, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    w = prowl.ScanWorker(demo=False, bank="NOAA Wx")
    assert _hold(w) is True
    assert ra.arbiter.owner() == "PROWL-SCAN"
    _finish(w)
    assert ra.arbiter.owner() is None, "stop() must release the scanner's SDR lease"


def test_prowl_submodes_mutually_exclusive_on_the_radio(monkeypatch):
    """One SDR: while SCAN holds the dongle, NWR is denied and shows BUSY; only one owner ever."""
    from palisade_qt import prowl, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    scan, nwr_w = prowl.ScanWorker(demo=False), prowl.NwrWorker(demo=False)
    assert _hold(scan) is True and ra.arbiter.owner() == "PROWL-SCAN"
    seen = []
    nwr_w.status.connect(lambda s: seen.append(s))
    assert nwr_w._ensure_lease() is False                 # SCAN holds it
    assert any(s.get("busy") for s in seen), "denied sub-mode must report RADIO BUSY"
    _finish(scan)
    assert ra.arbiter.owner() is None
    assert _hold(nwr_w) is True and ra.arbiter.owner() == "PROWL-NWR"
    _finish(nwr_w)
    assert ra.arbiter.owner() is None


def test_prowl_fm_step_leases_but_opens_no_radio_offscreen(monkeypatch):
    from palisade_qt import prowl, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    monkeypatch.setattr(prowl.shutil, "which", lambda b: "/usr/bin/" + b)   # rtl_fm "present"
    w = prowl.FmWorker(demo=False, freq=97.3)
    rows = []
    w.row.connect(lambda r: rows.append(r))
    w.step()                                       # requests (ACQUIRING): nothing spawned yet
    assert ra.wait_held("PROWL-FM", 3.0)
    w.step()
    assert ra.arbiter.owner() == "PROWL-FM"
    assert w._pipe is None, "offscreen seam must open no real radio"
    assert rows and rows[-1]["kind"] == "fm" and rows[-1]["audio"] is False
    _finish(w)
    assert ra.arbiter.owner() is None


def test_prowl_fm_no_rtl_fm_shows_standby_no_lease(monkeypatch):
    from palisade_qt import prowl, radio_arbiter as ra
    monkeypatch.setattr(prowl.shutil, "which", lambda b: None)
    w = prowl.FmWorker(demo=False)
    seen = []
    w.status.connect(lambda s: seen.append(s))
    w.step()
    assert ra.arbiter.owner() is None, "no device -> never grab the radio"
    assert any(s.get("standby") for s in seen)


def test_prowl_nwr_decodes_same_and_publishes_alert(monkeypatch):
    from palisade_qt import prowl, eventbus
    import nwr
    monkeypatch.setattr(prowl.shutil, "which", lambda b: "/usr/bin/" + b)
    eventbus.bus.clear()
    alerts = []
    eventbus.bus.published.connect(lambda e: alerts.append(e) if e["type"] == "alert" else None)
    w = prowl.NwrWorker(demo=False)
    rows = []
    w.row.connect(lambda r: rows.append(r))
    line = [ln for ln in nwr.Demo.LINES if "TOR" in ln][0]      # a real urgent SAME header
    w._handle_line(line)
    w._drain()
    assert rows and rows[-1]["kind"] == "nwr" and rows[-1]["event"]
    assert rows[-1]["urgent"] is True
    assert alerts and alerts[0]["source"] == "PROWL" and alerts[0]["severity"] == "alert"


def test_prowl_nwr_skips_non_same_lines_zero_fabrication(monkeypatch):
    from palisade_qt import prowl
    monkeypatch.setattr(prowl.shutil, "which", lambda b: "/usr/bin/" + b)
    w = prowl.NwrWorker(demo=False)
    rows = []
    w.row.connect(lambda r: rows.append(r))
    w._handle_line("multimon-ng: some chatter, not a SAME header\n")
    w._drain()
    assert rows == [], "non-SAME stdout must produce no rows"


def test_prowl_nwr_no_binary_standby(monkeypatch):
    from palisade_qt import prowl, radio_arbiter as ra
    monkeypatch.setattr(prowl.shutil, "which", lambda b: None)
    w = prowl.NwrWorker(demo=False)
    seen = []
    w.status.connect(lambda s: seen.append(s))
    w.step()
    assert ra.arbiter.owner() is None
    assert any(s.get("standby") for s in seen)


def test_prowl_backgrounded_releases_the_radio(monkeypatch):
    from palisade_qt import prowl, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda name: None)
    monkeypatch.setattr(prowl.shutil, "which", lambda b: "/usr/bin/" + b)
    w = prowl.FmWorker(demo=False)
    w.step()
    assert ra.arbiter.owner() == "PROWL-FM"
    w.set_active(False)
    w.step()
    assert ra.arbiter.owner() is None, "backgrounding PROWL frees the dongle for ATLAS/PRISM"
    w.stop()


def test_prowl_submode_switch_updates_stack_and_worker_type():
    _app()
    from palisade_qt.prowl import ProwlApp, FmWorker, NwrWorker, ScanWorker
    p = ProwlApp(demo=True, mode="dark")
    assert p._submode == "SCAN" and isinstance(p.make_worker(), ScanWorker)
    p._switch_submode("FM")
    assert p._submode == "FM" and p.stack.currentWidget() is p._pages["FM"]
    assert isinstance(p.make_worker(), FmWorker)
    p._switch_submode("NWR")
    assert isinstance(p.make_worker(), NwrWorker)
    p._switch_submode("SCAN")
    assert isinstance(p.make_worker(), ScanWorker)


def test_prowl_open_pump_close_no_leaked_lease():
    _app()
    from palisade_qt.prowl import ProwlApp
    from palisade_qt import radio_arbiter as ra
    p = ProwlApp(demo=False, mode="dark")
    p.start()
    _pump(200)
    p.stop()
    assert ra.arbiter.owner() is None, "closing PROWL must leave the SDR free"


# ---- PROWL PR2 review fixes: interruptible SCAN, hermetic SCAN, race guards, fatal surfacing ----

def test_prowl_scan_stop_interrupts_blocking_listen_channel(monkeypatch):
    """A continuous carrier makes scanner.listen_channel block; stop() must set scan['on']=False
    so it exits and the QThread joins (no orphaned thread / rtl_fm, no leaked lease)."""
    import scanner
    import time as _t
    from palisade_qt import prowl, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    monkeypatch.setattr(prowl, "_offscreen", lambda: False)           # exercise the live loop
    monkeypatch.setattr(prowl.shutil, "which", lambda b: "/usr/bin/" + b)

    def blocking_listen(freq, mode, s, scan, post, **k):             # held channel: never returns
        while scan["on"] and not scan.get("pause"):
            _t.sleep(0.01)
        return False
    monkeypatch.setattr(scanner, "listen_channel", blocking_listen)

    w = prowl.ScanWorker(demo=False, bank="NOAA Wx")
    w.start()
    t0 = _t.time()
    while ra.arbiter.owner() != "PROWL-SCAN" and _t.time() - t0 < 3:
        _t.sleep(0.01)
    assert ra.arbiter.owner() == "PROWL-SCAN"
    w.stop()
    w.quit()
    assert w.wait(3000), "stop() must interrupt the blocking listen_channel and join the thread"
    assert ra.arbiter.owner() is None


def test_prowl_scan_offscreen_routes_to_standby_never_spawns(monkeypatch):
    """Even with rtl_fm 'present', offscreen must route SCAN to standby — never call the engine."""
    import scanner
    from palisade_qt import prowl
    monkeypatch.setattr(prowl.shutil, "which", lambda b: "/usr/bin/" + b)
    called = []
    monkeypatch.setattr(scanner, "listen_channel", lambda *a, **k: called.append(1))
    w = prowl.ScanWorker(demo=False)
    flag = {}
    monkeypatch.setattr(w, "_run_standby", lambda: flag.setdefault("standby", True))
    monkeypatch.setattr(w, "_run_live", lambda: flag.setdefault("live", True))
    w.run()                                   # QT_QPA_PLATFORM=offscreen is set -> _offscreen() True
    assert flag.get("standby") and not flag.get("live")
    assert called == [], "offscreen must never spawn the scanner engine"


def test_prowl_scan_fatal_is_surfaced(monkeypatch):
    from palisade_qt import prowl
    w = prowl.ScanWorker(demo=False)
    errs = []
    w.error.connect(lambda e: errs.append(e))
    post = w._make_post(162.4, "WX2", {})
    post(("fatal", "rtl_fm not found — install it"))
    assert w._fatal is True and errs and "rtl_fm" in errs[0]


def test_prowl_fm_spawn_after_stop_drops_the_pipe(monkeypatch):
    """Race guard: a pipe spawned by the worker thread after stop() won the race is torn down,
    never left holding the radio."""
    from palisade_qt import prowl

    class FakePipe:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True
    fake = FakePipe()
    monkeypatch.setattr(prowl, "_open_fm_pipe", lambda *a, **k: fake)
    w = prowl.FmWorker(demo=False)
    w._stop = True                             # stop() already happened on the GUI thread
    w._spawn()
    assert w._pipe is None and fake.stopped, "a pipe spawned after stop() must be stopped"


def test_prowl_nwr_spawn_after_stop_drops_the_proc(monkeypatch):
    from palisade_qt import prowl

    class FakeProc:
        pid = -1

        def poll(self):
            return None
    fake = FakeProc()
    killed = []
    monkeypatch.setattr(prowl, "_open_nwr_pipe", lambda cmd: fake)
    monkeypatch.setattr(prowl.NwrWorker, "_terminate", staticmethod(lambda p: killed.append(p)))
    w = prowl.NwrWorker(demo=False)
    w._stop = True
    w._spawn()
    assert w._proc is None and killed == [fake], "a proc spawned after stop() must be terminated"
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
        pid = 2147483646
        stdout = [line, "not json, rtl_433 chatter\n"]

        def poll(self):
            return 0

        def terminate(self):
            return True
    monkeypatch.setattr(babel, "_open_pipe", lambda *a, **k: FakeProc())
    from palisade_qt import radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    w = babel.DecoderWorker(demo=False, mode="TPMS")
    w._running = True                    # CL5-fix 1/5: a runner keeps its decoder only while
    ra.arbiter.request(babel.LEASE_NAME)  # RUN is on and the arbiter says HELD
    assert ra.wait_held(babel.LEASE_NAME, 3.0)
    rows = []
    w.row.connect(lambda r: rows.append(r))
    babel._run_tpms(w)
    ra.arbiter.release(babel.LEASE_NAME)
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


class _FakeRec:
    """A Recorder stand-in: 25 s of (silent) audio in its in-memory window."""
    level = 120.0
    err = ""

    def __init__(self, secs=25.0, err=""):
        import sstv
        self.err = err
        self._n = int(secs * sstv.RATE)
        self.stopped = 0

    def seconds(self):
        return self._n / 24000.0

    def total_samples(self):
        return self._n

    def samples_since(self, abs_sample):
        start = max(0, int(abs_sample))
        return b"\x00\x00" * max(0, self._n - start), start

    def stop(self):
        self.stopped += 1


def _sstv_live(monkeypatch):
    from palisade_qt import babel, radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    monkeypatch.setattr(babel.shutil, "which", lambda b: "/usr/bin/" + b)   # rtl_fm "present"
    w = babel.SstvWorker(demo=False)
    w.set_running(True)                          # R1 / CL5-fix 3: only on RUN
    return babel, ra, w


def test_babel_sstv_live_leases_and_decodes(monkeypatch):
    import numpy as np
    babel, ra, w = _sstv_live(monkeypatch)
    w._make_recorder = lambda path: _FakeRec()
    w._decode = lambda x, fs: {"image": np.zeros((8, 8, 3), np.uint8), "mode": "PD120",
                               "lines": 496, "slant_ppm": 2, "start": 100, "t0": 100,
                               "period": 12000.0}
    rows = []
    w.row.connect(lambda r: rows.append(r))
    app = _app()
    w.step()                                     # requests the radio (ACQUIRING)
    assert ra.wait_held("BABEL-SSTV", 3.0)
    w.step()                                     # HELD: recorder + the (daemon) decode
    assert ra.arbiter.owner() == "BABEL-SSTV"
    import time as _t
    t0 = _t.time()
    while not rows and _t.time() - t0 < 3:       # decode runs off the step thread -> await it
        app.processEvents()
        _t.sleep(0.02)
    img = [r for r in rows if r.get("kind") == "sstv"]
    assert img and img[0]["mode"] == "PD120" and img[0]["image"].shape == (8, 8, 3)
    _finish(w)
    assert ra.arbiter.owner() is None, "closing SSTV releases the SDR"


def test_babel_sstv_stop_joins_during_a_slow_decode(monkeypatch):
    """The HIGH fix: the decode runs on a disposable daemon thread, so a slow decode never blocks
    the worker QThread — stop()/wait() joins promptly instead of orphaning the thread."""
    import time as _t
    import numpy as np
    babel, ra, w = _sstv_live(monkeypatch)
    w._make_recorder = lambda path: _FakeRec()

    def slow_decode(x, fs):
        _t.sleep(5)                              # longer than wait(3000)
        return {"image": np.zeros((4, 4, 3), np.uint8), "mode": "PD120", "lines": 4,
                "slant_ppm": 0, "start": 0, "t0": 0, "period": 12000.0}
    w._decode = slow_decode
    w.start()
    t0 = _t.time()
    while not w._decoding and _t.time() - t0 < 4:
        _t.sleep(0.02)
    assert w._decoding, "a decode should be in flight"
    t1 = _t.time()
    w.stop()
    w.quit()
    assert w.wait(3000), "worker must join within 3s even though the decode is still running"
    assert _t.time() - t1 < 3.0
    assert ra.arbiter.owner() is None


def test_babel_sstv_rtl_fm_death_reaps_and_retries(monkeypatch):
    """The MED fix: a dead rtl_fm (rec.err) reaps the Recorder so the next step can restart,
    instead of latching forever while holding the lease."""
    babel, ra, w = _sstv_live(monkeypatch)
    dead = _FakeRec(secs=5.0, err="rtl_fm stopped - is the SDR free?")
    w._make_recorder = lambda path: dead
    w.step()
    assert ra.wait_held("BABEL-SSTV", 3.0)
    w.step()                                      # makes the recorder, sees err -> reaps it
    assert ra.arbiter.owner() == "BABEL-SSTV"     # lease kept so the next step can restart
    assert w._rec is None and dead.stopped, "dead recorder must be stopped/cleared, not latched"
    _finish(w)
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
    w.set_running(True)                      # R1: the radio is taken only on RUN
    w.step()
    assert ra.wait_held("BABEL-SSTV", 3.0)
    w.step()                                 # real _make_recorder returns None under offscreen
    assert w._rec is None and ra.arbiter.owner() == "BABEL-SSTV"
    _finish(w)
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
    engagement.start("Op", "ROE-7", ["aa:bb:cc:*"], "KD0ABC")
    p._refresh_gate()
    g = p.wifi_gated
    assert all(b.isEnabled() for b in g._btns), "unlocked under an active engagement"
    g.target.setText("aa:bb:cc:dd:ee:ff")
    g._authorize("handshake")
    assert "AUTHORIZED" in g.result.text() and "wifi:handshake" in g.result.text()
    assert "--bssid" in g.result.text()                 # the capture is bound to the BSSID (G5)
    assert any(a["action"] == "wifi:handshake" for a in engagement.actions()), "logged to the trail"
    g._authorize("deauth")                              # no client field: never a broadcast (G5)
    assert "DENIED" in g.result.text() and "client" in g.result.text()
    g.target.setText("99:99:99:99:99:99")               # out of scope
    g._authorize("handshake")
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
    from palisade_qt import eventbus
    eventbus.bus.clear()
    alerts = []
    eventbus.bus.published.connect(lambda e: alerts.append(e) if e["type"] == "alert" else None)
    from palisade_qt.sweep import SweepApp          # CL1: COUNTER promoted to its own page (key 5)
    p = SweepApp(demo=True, mode="dark")
    p._on_counter({"kind": "gnss", "alert": ("gnss", "GPS jamming suspected (low C/N0)")})
    assert p.counter_feed.model.rowCount() == 1
    assert alerts and alerts[-1]["source"] == "SWEEP" and alerts[-1]["severity"] == "alert"


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
    from palisade_qt.panels import EngagePanel       # CL1: ENGAGE is shell chrome, not a RECON tab
    p = EngagePanel("dark")
    p.eng_name.setText("NightWatch")
    p.eng_auth.setText("ROE-42")
    p.eng_scope.setText("10.0.0.*, Corp-*")            # globs: refused (CL2/G4)
    p._activate()
    assert not engagement.is_active() and "REFUSED" in p.eng_msg.text()
    p.eng_scope.setText("10.0.0.0/24, Corp-1")
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
    from palisade_qt.sweep import SweepApp
    SweepApp(demo=True, mode="dark")._on_counter(
        {"kind": "bugsweep", "alert": ("bug", "2 suspect"), "demo": True})
    assert evs == [], "demo synthetic RECON data must not publish to the shared bus"


def test_recon_passaudit_hashcat_authorizes_in_scope():
    _app()
    _reset_engagement()
    import engagement
    from palisade_qt.recon import ReconApp
    p = ReconApp(demo=False, mode="dark")
    engagement.start("Op", "ROE-9", ["cap-01"], "KD0ABC")
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
    # in-scope engagement (interface + ID range, G5) -> authorized, a ticket from the engine
    engagement.start("Op", "ROE", ["can0:0x700-0x7FF"], "KD0ABC")
    ok, why, t = p._can_send(canbus, {"id": "7DF", "data": "0201", "target": "can0"}, p.evidence)
    assert ok is True and t.argv[0] == "cansend"
    # out of scope (ID / interface) -> denied
    ok, why, argv = p._can_send(canbus, {"id": "100", "data": "0201", "target": "can0"}, p.evidence)
    assert ok is False and argv is None
    ok, why, argv = p._can_send(canbus, {"id": "7DF", "data": "0201", "target": "can1"}, p.evidence)
    assert ok is False and argv is None
    _reset_engagement()


def test_forge_proxmark_write_gated_and_reads_are_not():
    _app()
    _reset_engagement()
    import engagement, proxmark
    from palisade_qt.forge import ForgeApp
    p = ForgeApp(demo=True, mode="dark")          # demo: the synthetic card 04A22B3C is read back
    active = [o for o, v in proxmark.OPS.items() if v[0] and "{" not in v[1]][0]  # no-param op
    ok, why, cmd = p._pm_write(proxmark, {"op": active, "target": "uid:04A22B3C"}, p.evidence)
    assert ok is False and cmd is None, "write op gated without engagement"
    engagement.start("Op", "ROE", ["uid:04A22B3C"], "KD0ABC")
    import txguard
    ok, why, cmd = p._pm_write(proxmark, {"op": active, "target": "uid:04A22B3C"}, p.evidence)
    assert ok is False and cmd is None and "silenced" in why.lower()    # CL2-fix N2: disarmed
    txguard.arm(True)
    ok, why, cmd = p._pm_write(proxmark, {"op": active, "target": "uid:04A22B3C"}, p.evidence)
    txguard.reset_session()
    assert ok is True and cmd
    ok, why, cmd = p._pm_write(proxmark, {"op": active, "target": "uid:DEADBEEF"}, p.evidence)
    assert ok is False and cmd is None                  # not the card on the antenna / scope
    live = ForgeApp(demo=False, mode="dark")       # live: no read-back path wired -> refused
    ok, why, cmd = live._pm_write(proxmark, {"op": active, "target": "uid:04A22B3C"}, live.evidence)
    assert ok is False and "read-back" in why
    live.stop()
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


# ---- OVERWATCH: sky dome (sun/moon always live), passes (hermetic TLE), radio director ----

def test_overwatch_sky_sun_moon_always_live():
    from palisade_qt import overwatch
    w = overwatch.SkyWorker(demo=True)
    rows = []
    w.row.connect(lambda m: rows.append(m))
    w.step()
    assert rows and len(rows[0]["sun"]) == 2 and len(rows[0]["moon"]) == 3
    assert rows[0]["daylight"] in ("day", "civil twilight", "nautical twilight",
                                   "astronomical twilight", "night")
    assert rows[0]["sats"], "demo shows a synthetic satellite"


def test_overwatch_passes_demo_and_no_tle_standby():
    from palisade_qt import overwatch
    # demo -> synthetic flagged passes
    w = overwatch.PassWorker(demo=True)
    got = []
    w.row.connect(lambda m: got.append(m))
    w.step()
    assert got and got[0]["status"] == "demo" and got[0]["passes"]
    assert all(p.get("demo") for p in got[0]["passes"])
    # live + a missing TLE path -> honest NO-TLE standby, no passes
    w2 = overwatch.PassWorker(demo=False, tle_path="/nonexistent/weather.tle")
    got2 = []
    w2.row.connect(lambda m: got2.append(m))
    w2.step()
    assert got2 and got2[0]["status"] == "no-tle" and got2[0]["passes"] == []


def test_overwatch_passes_predict_real_from_injected_tle(tmp_path):
    """Hermetic: inject a fake ISS TLE file and predict AS-IS via wxsat/skyfield — never network."""
    import pytest as _pt
    try:
        import skyfield  # noqa: F401
    except ImportError:
        _pt.skip("skyfield not installed")
    import sys
    sys.path.insert(0, "tests")
    from iss_tle_fixture import iss_tle
    from palisade_qt import overwatch
    tle = tmp_path / "iss.tle"
    tle.write_text(iss_tle())
    w = overwatch.PassWorker(demo=False, tle_path=str(tle))
    got = []
    w.row.connect(lambda m: got.append(m))
    w.step()
    assert got and got[0]["status"] == "live"
    assert any(p["sat"].startswith("ISS") for p in got[0]["passes"]), "real ISS passes predicted"
    p0 = got[0]["passes"][0]
    assert len(p0["track"]) == 41 and "aos" in p0 and "max" in p0


def test_overwatch_radio_director_tracks_arbiter_and_frees(monkeypatch):
    _app()
    from palisade_qt import panels, radio_arbiter as ra
    ra.arbiter._owner = None
    ra.arbiter._lease = None
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    p = panels.RadiosPanel("dark")      # CL1: OVERWATCH's RADIO view is the shell's RADIOS panel
    _pump(100)
    ra.arbiter.request("ATLAS-APRS")
    _pump(100)
    assert p.hist_feed.model.rowCount() >= 1
    assert "APRS" in p.holder.hero.text()
    # CL5 (A1): FREE RADIO asks the holder to release; the arbiter forces it only after the
    # revoke timeout when nobody acknowledges (no ATLAS page is listening here)
    monkeypatch.setattr(ra, "REVOKE_TIMEOUT_S", 0.05)
    asked = []
    ra.arbiter.revoked.connect(asked.append)
    p._free_radio()
    assert asked == ["ATLAS-APRS"]
    import time as _t
    deadline = _t.time() + 2.0
    while ra.arbiter.owner() is not None and _t.time() < deadline:
        _pump(20)
    ra.arbiter.revoked.disconnect(asked.append)
    assert ra.arbiter.owner() is None
    p.stop()
    ra.arbiter._owner = None


def test_overwatch_next_pass_alerts_ops_for_real_passes():
    _app()
    from palisade_qt import overwatch, eventbus
    eventbus.bus.clear()
    alerts = []
    eventbus.bus.published.connect(lambda e: alerts.append(e) if e["type"] == "alert" else None)
    p = overwatch.OverwatchApp(demo=False, mode="dark")
    import time as _t
    now = _t.time()
    real = [{"sat": "NOAA-19", "freq": 137.1, "aos": now + 600, "los": now + 1300, "max": 62.0,
             "track": [(0, 0)], "dir": "southbound"}]
    p._on_passes({"passes": real, "status": "live"})
    assert any(e["source"] == "OVERWATCH" and "next pass" in e["payload"]["text"] for e in alerts)
    # demo passes must NOT alert OPS
    alerts.clear()
    p._on_passes({"passes": overwatch._demo_passes(now), "status": "demo"})
    assert alerts == []


def test_overwatch_open_pump_close_no_leaked_threads():
    _app()
    from palisade_qt import overwatch, radio_arbiter as ra
    ra.arbiter._owner = None
    p = overwatch.OverwatchApp(demo=False, mode="dark")
    p.start()
    _pump(200)
    p.stop()
    assert all(not w.isRunning() for w in p._workers) if p._workers else True


def test_overwatch_passworker_repredicts_on_cadence():
    """Review fix: predict is not a one-shot — it re-runs on the hourly cadence."""
    from palisade_qt import overwatch
    w = overwatch.PassWorker(demo=True)
    got = []
    w.row.connect(lambda m: got.append(m))
    w.step()                                     # first predict
    assert len(got) == 1
    w.step()                                     # within the hour -> no re-predict
    assert len(got) == 1
    w._last_predict -= overwatch.PassWorker.RE_PREDICT_S + 1   # an hour elapses
    w.step()
    assert len(got) == 2, "PassWorker must re-predict after the cadence, not latch forever"


def test_overwatch_predict_error_shows_warn_standby():
    """Review fix: a predict failure/offscreen is surfaced as a warn standby, not a clean '0 passes'."""
    _app()
    from palisade_qt import overwatch
    p = overwatch.OverwatchApp(demo=False, mode="dark")
    for status in ("error", "offscreen"):
        p._on_passes({"passes": [], "status": status})
        assert p.pass_feed.model.rowCount() == 0
        assert "passes in the next" not in p.pass_note.text(), "%s must not read as a clear sky" % status


# ---- BENCH: conducted TX self-test (loopback software tests + txguard conducted gate) ----

def test_bench_gate_safe_with_ack_gated_without():
    _app()
    from palisade_qt.bench_app import BenchApp
    import txguard
    p = BenchApp(demo=False, mode="dark")
    p._saved = lambda: {"tx_enabled": True}            # the saved opt-in (never forced by the page)
    txguard.arm(True)
    txguard.unlock_session(True)                       # CL2/G1: the one chain, not the checkbox
    try:
        p.ack.setChecked(False)
        p._refresh_gate()
        assert "GATED" in p.gate.text() and not p.tx_btn.isEnabled()
        p.ack.setChecked(True)
        p._refresh_gate()
        # "TX SAFE" is retired (it meant two things); a passing gate reads PERMITTED (D4)
        assert "TX PERMITTED" in p.gate.text() and "SAFE" not in p.gate.text() and p.tx_btn.isEnabled()
    finally:
        txguard.reset_session()
        p.stop()


def test_bench_software_selftests_pass():
    """The pure encode->decode round-trips (CW/RTTY/AIS/OpenDroneID) run AS-IS and pass — no radio."""
    import loopback
    results = loopback.software_selftests()
    assert results and loopback.all_pass(results), "software self-tests must pass"
    _app()
    from palisade_qt.bench_app import BenchApp
    p = BenchApp(demo=False, mode="dark")
    p._on_results({"results": results, "all_pass": True})
    assert p.feed.model.rowCount() == len(results)
    assert all(r["ok"] == "PASS" for r in p.feed.model.rows)


def test_bench_conducted_tx_is_gated_and_hermetic():
    _app()
    from palisade_qt.bench_app import BenchApp
    import txguard
    p = BenchApp(demo=False, mode="dark")
    spawned = []
    import bench
    p._saved = lambda: {"tx_enabled": True}
    txguard.arm(True)
    txguard.unlock_session(True)
    try:
        # no conducted ack -> txguard blocks before any transmit; the spawner is never called
        p.ack.setChecked(False)
        ok, msg, code = bench.transmit(p._settings(), spawner=lambda a, **k: spawned.append(a))
        assert ok is False and "conducted" in msg.lower() and spawned == []
        # offscreen _tx never spawns regardless (no IQ file -> blocked; and the spawner refuses)
        p.ack.setChecked(True)
        p._tx()
        assert p.card.hero.text() == "BLOCKED" and spawned == []
    finally:
        txguard.reset_session()
        p.stop()


def test_bench_open_pump_close_no_leak():
    _app()
    from palisade_qt.bench_app import BenchApp
    p = BenchApp(demo=False, mode="dark")
    p.start()
    p._run_selftest()
    _pump(200)
    p.stop()
    stw = getattr(p, "_stw", None)
    assert stw is None or not stw.isRunning()


# ---- MORE / SYSTEM: settings, doctor, assistant (bus context), mesh, sitrep ----

def test_more_registered_as_a_callsign():
    from palisade_qt.shell import QT_PAGES
    from palisade_qt.ops import CALLSIGNS
    from palisade_qt.shell import FOLDED
    # CL1: MORE is folded into the SYSTEM key (8); the old callsign still resolves to it
    assert "SYSTEM" in QT_PAGES and any(n == "SYSTEM" for n, _ in CALLSIGNS)
    assert FOLDED["MORE"][0] == "SYSTEM" and FOLDED["BENCH"][0] == "SYSTEM"


def test_more_doctor_runs_checks_and_skips_network_offscreen(monkeypatch):
    import doctor
    monkeypatch.setattr(doctor, "CHECKS", [
        ("Software", [("t1", lambda: (True, "ok", "")), ("t2", lambda: (False, "bad", ""))]),
        ("Network", [("n1", lambda: (True, "net", ""))])])
    from palisade_qt.system import DoctorWorker
    rows = []
    w = DoctorWorker()
    w.row.connect(lambda m: rows.append(m))
    w.run()                                      # synchronous (plain method) -> deterministic
    secs = {r["section"] for r in rows}
    assert "Software" in secs and "Network" not in secs, "network checks skipped offscreen (hermetic)"
    assert any(r["ok"] is True for r in rows) and any(r["ok"] is False for r in rows)


def test_more_mesh_demo_nodes_and_live_standby():
    from palisade_qt import system
    w = system.MeshWorker(demo=True)
    rows = []
    w.row.connect(lambda m: rows.append(m))
    w.step()
    nodes = [m for m in rows if m["kind"] == "nodes"]
    assert nodes and len(nodes[0]["nodes"]) >= 3
    w.stop()
    w2 = system.MeshWorker(demo=False)
    seen, rows2 = [], []
    w2.status.connect(lambda s: seen.append(s))
    w2.row.connect(lambda m: rows2.append(m))
    w2.step()
    assert rows2 == [] and any(s.get("standby") for s in seen)


def test_more_assistant_answers_from_bus_and_offline_llm():
    _app()
    from palisade_qt import system, eventbus, panels
    eventbus.bus.clear()
    panels.reset_alert_store()
    panels.alert_store()             # CL4 H17: alerts are answered from the acknowledgement store
    eventbus.bus.publish(eventbus.alert("ATLAS", "drone inbound", severity="alert"))
    eventbus.bus.publish(eventbus.contact("ADS-B", "a1", 47.6, -122.3, kind="aircraft"))
    _pump(100)
    p = system.MoreApp(demo=True, mode="dark")
    assert "1 unacknowledged alert" in p._answer("any alerts?")
    assert "aircraft" in p._answer("what's on the map?")
    # CL4 H18: free-form is NOT IMPLEMENTED here (no LLM probe from the GUI thread)
    assert p._answer("write me a sonnet").startswith("NOT IMPLEMENTED")
    panels.reset_alert_store()


def test_more_sitrep_from_bus_state():
    _app()
    from palisade_qt import system, eventbus
    eventbus.bus.clear()
    eventbus.bus.publish(eventbus.decode("BABEL", "AIS", "1", "vessel"))
    p = system.MoreApp(demo=True, mode="dark")
    lines = p._sitrep_lines()
    assert lines[0].startswith("Situation report") and any("decode" in ln for ln in lines)
    eventbus.bus.clear()
    # CL4 H17: with no feed running SITREP must not say "All quiet" — it says nothing is watched
    text = " ".join(p._sitrep_lines())
    assert "All quiet" not in text and "No feed is running" in text


def test_more_open_pump_close_no_leaked_threads():
    _app()
    from palisade_qt.system import MoreApp
    p = MoreApp(demo=False, mode="dark")
    p.start()
    _pump(200)
    p.stop()
    assert all(not w.isRunning() for w in p._workers) if p._workers else True


def test_more_settings_persists_home_and_theme_no_false_save():
    """Review fix: SETTINGS must actually apply HOME (live geo frame) + persist theme, and must
    never report a bare 'saved' for fields it discards."""
    _app()
    from palisade_qt import system, eventbus
    orig_home = eventbus.HOME
    try:
        p = system.MoreApp(demo=True, mode="dark")
        captured = {}
        p._write_settings = lambda data: (captured.update(data), True)[1]   # capture + 'persisted'
        p.set_operator.setText("N0CALL")
        p.set_home.setText("40.0000, -105.0000")
        p.set_theme.setCurrentText("light")
        p._save_settings()
        assert eventbus.HOME == (40.0, -105.0), "HOME applied live to the shared geo frame"
        assert captured.get("home") == [40.0, -105.0], "HOME persisted"
        assert captured.get("theme") == "light", "Theme persisted (was silently discarded before)"
        assert "NOT persisted" not in p.set_msg.text()
        # invalid HOME -> honest rejection ("nothing saved"), never a false success
        p.set_home.setText("garbage")
        p._save_settings()
        assert "must be" in p.set_msg.text() and "nothing saved" in p.set_msg.text()
    finally:
        eventbus.HOME = orig_home


def test_more_doctor_stop_joins_during_a_blocking_check(monkeypatch):
    """Review fix: DOCTOR's worker must honor stop() mid-check (no QThread-destroyed-while-running):
    a 10 s blocking check must not stop stop()/wait() from joining within the lifetime budget."""
    import doctor
    import time as _t
    _app()
    from palisade_qt.system import DoctorWorker
    monkeypatch.setattr(doctor, "CHECKS",
                        [("Software", [("slow", lambda: (_t.sleep(10), (True, "done", ""))[1])])])
    w = DoctorWorker()
    w.start()
    t0 = _t.time()
    while not w.isRunning() and _t.time() - t0 < 2:
        _t.sleep(0.02)
    _t.sleep(0.2)                               # let it enter the blocking check
    t1 = _t.time()
    w.stop()
    w.quit()
    assert w.wait(3000), "DoctorWorker must join within 3s even though a check blocks for 10s"
    assert _t.time() - t1 < 3.0
