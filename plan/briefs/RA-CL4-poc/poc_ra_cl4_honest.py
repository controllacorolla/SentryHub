"""RA-CL4 PoCs, honest-state side (fix/cl4-honest-state @ 461f5e2).
FIXED_* / OK_* = the fix holds (test passes). DEFECT_* = the defect reproduces (test passes when it does).
Tests that need a real subprocess (fake `iw`, fake `rtl_power` on PATH) switch the pages' offline
check off for that test only; nothing opens a real radio, adapter or network.
Run: SUITE=<worktree> QT_QPA_PLATFORM=offscreen xvfb-run -a pytest -q poc_ra_cl4_honest.py"""
import json
import os
import stat
import sys
import time

import pytest

SUITE_DIR = os.environ["SUITE"]
sys.path.insert(0, SUITE_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _pump(ms=200):
    app, t = _app(), time.time()
    while time.time() - t < ms / 1000:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    _app()
    import suite
    from palisade_qt import radio_arbiter as ra, eventbus, panels
    monkeypatch.setattr(suite, "DATA", str(tmp_path / "data"))
    ra.arbiter.reset_for_tests(); eventbus.bus.clear(); eventbus.set_home(None)
    panels.reset_alert_store()
    yield
    ra.arbiter.reset_for_tests(); eventbus.bus.clear(); eventbus.set_home(None)
    panels.reset_alert_store()


def _close(p):
    p.stop(); p.deleteLater(); _app().processEvents()


def _fakebin(tmp_path, name, body):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return str(d)


def _online(monkeypatch, bindir):
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb-not-offscreen")   # the pages read it at call time
    monkeypatch.delenv("PALISADE_OFFLINE", raising=False)
    monkeypatch.setenv("PATH", bindir + os.pathsep + os.environ["PATH"])


# ============================================================ ENGAGEMENT panel empty state (D4)
def _engagement(monkeypatch):
    import engagement as E, txguard as G, chain, executor
    monkeypatch.setattr(E, "_profile_operator", lambda: "KD0ABC", raising=False)
    G.reset_session(); E.reset(); executor.reset(); chain.reset_for_tests()
    ok, why = E.start("job", "ROE-1", ["10.0.0.0/24"], "KD0ABC")
    assert ok, why
    return E, chain, E.chain_info()


def test_DEFECT_engagement_trail_says_nothing_authorized_when_the_chain_is_tampered(monkeypatch):
    """A tampered chain: chain_info() says NOT VERIFIED, chain_states() returns [] — and the new
    D4 empty state paints the trail green "WATCHING — nothing authorized yet". Before CL4 the
    table was blank under the NOT VERIFIED caption. The trail now asserts something it cannot know."""
    from palisade_qt import panels
    E, chain, info = _engagement(monkeypatch)
    assert E.authorize_action("net:portscan", "10.0.0.5", kind="ip")[0]
    raw = open(info["path"], "rb").read().replace(b"10.0.0.5", b"10.0.0.6")
    with open(info["path"], "wb") as fh:
        fh.write(raw)
    host = QtWidgets.QWidget()
    p = panels.EngagePanel("dark", host)
    p.render_actions()
    print("caption:", p.eng_chain.text(), "| table:", p.eng_actions.empty.text().replace("\n", " / "),
          "| look:", p.eng_actions.empty.state, "| rows:", len(p.eng_actions.model.rows))
    try:
        assert "NOT VERIFIED" in p.eng_chain.text() or "none open" in p.eng_chain.text()
        assert p.eng_actions.showing_empty()
        assert p.eng_actions.empty.state == "watching"
        assert "nothing authorized yet" in p.eng_actions.empty.text()
    finally:
        E.reset(); chain.reset_for_tests()


def test_DEFECT_engagement_panel_says_no_engagement_when_the_active_chain_is_unreadable(monkeypatch):
    """N12 made _active_chain() fail closed on ANY error (correct for the gate). The panel reads
    chain_info() is None as "no engagement": with an engagement ACTIVE and its chain head
    malformed, the trail says OFFLINE "NO ENGAGEMENT" / "Evidence chain — none open"."""
    from palisade_qt import panels
    E, chain, info = _engagement(monkeypatch)
    with open(info["path"][:-len(".jsonl")] + ".head", "wb") as fh:
        fh.write(b"garbage")
    chain.reset_for_tests()
    host = QtWidgets.QWidget()
    p = panels.EngagePanel("dark", host)
    p.render_actions()
    print("active:", E.active() if hasattr(E, "active") else E._eng().get("name"),
          "| caption:", p.eng_chain.text(), "| table:", p.eng_actions.empty.text().replace("\n", " / "))
    try:
        assert E._eng().get("name") == "job"                        # still active
        assert not E.authorize_action("net:portscan", "10.0.0.5", kind="ip")[0]   # gate: closed
        assert "none open" in p.eng_chain.text()
        assert "NO ENGAGEMENT" in p.eng_actions.empty.text()
    finally:
        E.reset(); chain.reset_for_tests()


# ============================================================ H5 HOME unset: geometry from a guess
def test_DEFECT_atlas_without_home_draws_live_contacts_over_a_0_0_basemap_with_nm_rings():
    """HOME unset (live). The table hides range/bearing and a HOME NOT SET chip shows — but the
    map still draws range rings labelled in nm around a provisional origin (the FIRST contact
    seen) and asks for basemap tiles at lat 0, lon 0 (Gulf of Guinea). Real aircraft over Seattle
    are drawn over open ocean with distance rings that are not from the operator."""
    from palisade_qt import eventbus
    from palisade_qt.atlas import AtlasApp
    p = AtlasApp(demo=False)
    for i, (la, lo) in enumerate([(47.60, -122.30), (47.90, -122.10), (47.30, -122.60)]):
        eventbus.bus.publish(eventbus.contact("ADS-B", "a%d" % i, la, lo, kind="aircraft"))
    _pump(900)
    p._render()
    pts = p.map.scatter.data
    tiles = (p.map._tiles.home_lat, p.map._tiles.home_lon)
    rings = [r.isVisible() for r in p.map._rings]
    print("tiles centre", tiles, "| points", len(pts), "| rings visible", rings,
          "| home marker", p.map.home.isVisible(), "| rng col", [r["rng"] for r in p.feed.model.rows])
    try:
        assert not eventbus.home_set()
        assert len(pts) == 3 and tiles == (0.0, 0.0) and all(rings)
        assert all(r["rng"] == "—" for r in p.feed.model.rows)          # the table is honest
    finally:
        _close(p)


def test_DEFECT_ops_ppi_without_home_plots_contacts_around_a_provisional_origin():
    from palisade_qt import eventbus
    from palisade_qt.ops import OpsHome
    p = OpsHome(demo=False)
    for i, (la, lo) in enumerate([(47.60, -122.30), (47.90, -122.10)]):
        eventbus.bus.publish(eventbus.contact("ADS-B", "o%d" % i, la, lo, kind="aircraft"))
    _pump(900)
    xy = [(round(c["x"], 1), round(c["y"], 1)) for c in p._contacts.values()]
    print("PPI xy (nm from 'centre'):", xy, "| sub:", p.sub.text())
    try:
        assert (0.0, 0.0) in xy                     # the first contact sits on the operator's spot
        assert "HOME NOT SET" in p.sub.text()
    finally:
        _close(p)


# ============================================================ H17 SITREP / assistant
def test_OK_h17_thirty_aircraft_do_not_evict_an_alert_from_sitrep_or_assistant():
    from palisade_qt import eventbus, panels, system
    panels.alert_store()
    eventbus.bus.publish(eventbus.alert("PROWL", "NWR: Tornado Warning", severity="alert"))
    for k in range(40):
        for i in range(30):
            eventbus.bus.publish(eventbus.contact("ADS-B", "x%d" % i, 47.6, -122.3 + i / 100,
                                                  kind="aircraft"))
    _pump(300)
    p = system.MoreApp(demo=False)
    try:
        ans = p._answer("any alerts?")
        sit = " ".join(p._sitrep_lines())
        print(ans, "|", sit)
        assert "Tornado" in ans and "Tornado" in sit and "30 contacts" in sit
    finally:
        _close(p)


def test_DEFECT_sitrep_calls_a_pass_prediction_alert_a_feed_and_reports_nothing_found():
    """feeds() counts ANY source that published ANYTHING in 2 min. With no sensor running, an
    acknowledged OVERWATCH 'next pass' alert (a TLE prediction, not a receiver) makes SITREP say
    "Watching OVERWATCH: no contacts, decodes, or open alerts." — the all-clear phrasing H17 was
    meant to stop, backed by no feed."""
    from palisade_qt import eventbus, panels, system
    st = panels.alert_store()
    eventbus.bus.publish(eventbus.alert("OVERWATCH", "next pass: NOAA 19 at 14:02Z", severity="info"))
    _pump(200)
    for a in st.items:
        a["acked"] = True
    p = system.MoreApp(demo=False)
    try:
        sit = " ".join(p._sitrep_lines())
        print(sit)
        assert "No feed is running" not in sit
        assert "Watching OVERWATCH: no contacts, decodes, or open alerts." in sit
    finally:
        _close(p)


# ============================================================ E1 / L5 stale aircraft.json (real file)
def test_FIXED_e1_l5_hour_old_aircraft_json_is_stale_on_atlas_and_remote_mode(tmp_path):
    import headless
    import sky_app
    d = tmp_path / "readsb"
    d.mkdir()
    (d / "aircraft.json").write_text(json.dumps({"now": time.time() - 3600, "aircraft": [
        {"hex": "abc123", "flight": "<img src=x onerror=alert(1)>", "lat": 47.6, "lon": -122.3,
         "seen": 1, "seen_pos": 1}]}))
    feed = sky_app.AdsbFeed([str(d)])
    try:
        t = time.time()
        while feed.status == "none" and time.time() - t < 4:
            time.sleep(0.1)
        prov = headless.adsb_providers(feed)
        s = prov["status"]()
        print("feed", feed.status, "| remote status", s, "| contacts", prov["contacts"]())
        assert feed.status == "stale" and prov["contacts"]() == []
        assert s["active_contacts"] == 0 and s["feed"].startswith("ADS-B STALE (last data 36")
        # ATLAS worker path
        from palisade_qt.atlas import AtlasLiveWorker
        w = AtlasLiveWorker.__new__(AtlasLiveWorker)
        got = []
        w._adsb = feed
        w.status = type("S", (), {"emit": lambda self, m: got.append(m)})()
        assert AtlasLiveWorker._adsb_contacts(w) == [] and got[-1]["adsb"]["state"] == "stale"
        # now make it live: served, and the hostile callsign is data, never markup
        (d / "aircraft.json").write_text(json.dumps({"now": time.time(), "aircraft": [
            {"hex": "abc123", "flight": "<img src=x onerror=alert(1)>", "lat": 47.6,
             "lon": -122.3, "seen": 1, "seen_pos": 1}]}))
        t = time.time()
        while feed.status != "live" and time.time() - t < 4:
            time.sleep(0.1)
        app = headless.make_app(prov)
        c = app.test_client()
        js = c.get("/api/contacts")
        html = c.get("/").get_data(as_text=True)
        print(js.content_type, js.get_json())
        assert js.content_type.startswith("application/json")
        assert js.get_json()["contacts"][0]["label"] == "<img src=x onerror=alert(1)>"
        assert "innerHTML" not in html and "textContent" in html
    finally:
        feed.stopped = True


# ============================================================ H3 Wi-Fi scan (real fake `iw`)
def test_FIXED_h3_failed_iw_scan_is_scan_failed_not_zero_ap(tmp_path, monkeypatch):
    from palisade_qt import recon
    bindir = _fakebin(tmp_path, "iw", 'echo "command failed: Device or resource busy (-16)" >&2; exit 240')
    _online(monkeypatch, bindir)
    w = recon.WifiScanWorker(demo=False)
    st, rows = [], []
    w.status.connect(st.append)
    w.row.connect(rows.append)
    w.step()
    print(st)
    assert rows == [] and "WIFI SCAN FAILED — exit 240" in st[-1]["sdr"]["text"]


def test_OK_h3_scan_argv_is_passive_and_scan_does_not_run_while_wifi_is_hidden(tmp_path, monkeypatch):
    from palisade_qt import recon
    log = tmp_path / "iw.log"
    bindir = _fakebin(tmp_path, "iw", 'echo "$@" >> %s; exit 0' % log)
    _online(monkeypatch, bindir)
    monkeypatch.setattr(recon.WifiScanWorker, "INTERVAL_MS", 300)
    p = recon.ReconApp(demo=False)
    p.set_active(True)
    p.start()
    _pump(1200)
    n_shown = len(log.read_text().splitlines()) if log.exists() else 0
    p.switch_subtab("BLE")
    _pump(400)
    a = len(log.read_text().splitlines()) if log.exists() else 0
    _pump(1500)
    b = len(log.read_text().splitlines()) if log.exists() else 0
    p.set_active(False)
    print("scans while WIFI shown:", n_shown, "| while BLE shown: %d -> %d" % (a, b),
          "| argv:", log.read_text().splitlines()[:1] if log.exists() else None)
    try:
        assert n_shown >= 1 and b == a
        assert log.read_text().splitlines()[0] == "dev wlan0 scan passive"
    finally:
        _close(p)


# ============================================================ H2 PRISM (real fake rtl_power)
def _prism_worker(monkeypatch):
    from palisade_qt import prism, radio_arbiter
    monkeypatch.setattr(radio_arbiter, "_make_lease", lambda name: None)
    w = prism.SweepWorker(demo=False)
    w._active = True
    st = []
    w.status.connect(st.append)
    return w, st


def _step_until(w, st, pred, s=6.0):
    t = time.time()
    while time.time() - t < s:
        w.step()
        _app().processEvents()
        if st and pred(st[-1]):
            return True
        time.sleep(0.1)
    return False


def test_FIXED_h2_prism_dead_rtl_power_is_fault_never_live(tmp_path, monkeypatch):
    bindir = _fakebin(tmp_path, "rtl_power",
                      'echo "usb_claim_interface error -6" >&2; exit 1')
    _online(monkeypatch, bindir)
    w, st = _prism_worker(monkeypatch)
    try:
        assert _step_until(w, st, lambda m: "FAULT" in m.get("sdr", {}).get("text", ""))
        print([m.get("sdr", {}).get("text") for m in st][-4:])
        assert not any(m.get("sdr", {}).get("state") == "live" for m in st)
    finally:
        w._kill_rtl()


def test_FIXED_h2_prism_silent_rtl_power_goes_stale_never_live(tmp_path, monkeypatch):
    from palisade_qt import prism
    monkeypatch.setattr(prism, "STALE_AFTER_S", 1.0)
    bindir = _fakebin(tmp_path, "rtl_power", "exec sleep 30")
    _online(monkeypatch, bindir)
    w, st = _prism_worker(monkeypatch)
    try:
        assert _step_until(w, st, lambda m: "STALE" in m.get("sdr", {}).get("text", ""))
        print([m.get("sdr", {}).get("text") for m in st][-3:])
        assert not any(m.get("sdr", {}).get("state") == "live" for m in st)
    finally:
        w._kill_rtl()


# ============================================================ H4 failed lease (real arbiter thread)
def test_FIXED_h4_failed_rtl_lease_never_held_and_page_retries_after_backoff(monkeypatch):
    import suite
    from palisade_qt import prism, radio_arbiter as ra

    class Lease:
        def __init__(self, name):
            pass

        def acquire(self):
            raise RuntimeError("readsb would not stop")

        def release(self):
            pass
    monkeypatch.setattr(suite, "RtlLease", Lease, raising=False)
    monkeypatch.setattr(ra, "FAIL_RETRY_S", 1.0)
    held = []
    ra.arbiter.transition.connect(lambda ev, o, n: held.append(ev))
    w = prism.SweepWorker(demo=False)
    w._active = True
    st = []
    w.status.connect(st.append)
    t = time.time()
    while time.time() - t < 3.5:
        w.step()
        _app().processEvents()
        w._held_off = False; w._active = True          # operator keeps the page on
        time.sleep(0.05)
    texts = [m.get("sdr", {}).get("text") for m in st]
    print("transitions", held[:6], "| texts", sorted(set(texts)))
    assert "HELD" not in held and held.count("ACQUIRING") >= 2      # retried after the backoff
    assert ra.arbiter.state() in (("FREE", None), ("ACQUIRING", "PRISM"))
    assert any("acquire failed" in (x or "") or "RADIO FAILED" in (x or "") for x in texts)
