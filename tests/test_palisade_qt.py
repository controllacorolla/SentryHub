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
