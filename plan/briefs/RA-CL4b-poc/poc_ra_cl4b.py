"""RA-CL4b PoCs: attacks on CL4-fix (fix/cl4-honest-state @ f8172a2+).
FIXED_* / OK_* = the fix holds (test passes). DEFECT_* = the defect reproduces (test passes when it does).
Real chains, real processes, real HTTP server on 127.0.0.1; nothing opens a radio or the internet.
Run: SUITE=<worktree> QT_QPA_PLATFORM=offscreen xvfb-run -a pytest -q poc_ra_cl4b.py   (Linux)"""
import http.server
import json
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

SUITE_DIR = os.environ["SUITE"]
sys.path.insert(0, SUITE_DIR)
sys.path.insert(0, os.path.join(SUITE_DIR, "plan", "briefs", "RA-CL3d-poc"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402

import chain  # noqa: E402
import engagement as E  # noqa: E402
import gatestate  # noqa: E402
import txguard as G  # noqa: E402
import poc_ra_cl3d as D  # noqa: E402


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
    import executor
    from palisade_qt import radio_arbiter as ra, eventbus, panels
    monkeypatch.setattr(suite, "DATA", str(tmp_path / "data"))
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    monkeypatch.delenv("PALISADE_GATE_STATE", raising=False)
    monkeypatch.setattr(E, "_profile_operator", lambda: D.OP, raising=False)
    G.reset_session(); E.reset(); executor.reset(); chain.reset_for_tests()
    ra.arbiter.reset_for_tests(); eventbus.bus.clear(); eventbus.set_home(None)
    panels.reset_alert_store()
    yield
    executor.kill_all("teardown")
    executor.reset(); G.reset_session(); E.reset(); chain.reset_for_tests()
    ra.arbiter.reset_for_tests(); eventbus.bus.clear(); eventbus.set_home(None)
    panels.reset_alert_store()


def _close(p):
    p.stop(); p.deleteLater(); _app().processEvents()


# ============================================================ N26 — range picture without HOME
@pytest.fixture
def fetches(monkeypatch):
    from palisade_qt.kit import tiles
    calls = []
    monkeypatch.setattr(tiles.TileLayer, "fetch",
                        lambda self, style: calls.append((style, self.home_lat, self.home_lon)))
    return calls


def test_FIXED_n26_atlas_home_unset_draws_nothing_and_fetches_no_tile(fetches):
    from palisade_qt import eventbus
    from palisade_qt.atlas import AtlasApp
    a = AtlasApp(demo=False)
    a.resize(1100, 640); a.show()
    for i, (la, lo) in enumerate([(47.60, -122.30), (47.90, -122.10)]):
        eventbus.bus.publish(eventbus.contact("ADS-B", "a%d" % i, la, lo, kind="aircraft"))
    _pump(600)
    a._render()
    a.map._combo.setCurrentIndex(1)                      # operator flips to satellite
    a.map._combo.setCurrentIndex(0)
    _pump(100)
    try:
        assert fetches == [], fetches
        assert len(a.map.scatter.data) == 0
        assert a._home_cover.shown() and a._home_cover.empty.geometry() == a.map.rect()
        assert not a.map.home.isVisible()
        assert all(r["rng"] == "—" for r in a.feed.model.rows)
        a._show(a.feed.model.rows[0])                      # detail card: no range either
        assert a._contacts[a._selected]["rng"] is None
    finally:
        _close(a)


def test_FIXED_n26_atlas_home_set_live_recentres_and_fetches_for_home(fetches):
    from palisade_qt import eventbus
    from palisade_qt.atlas import AtlasApp
    a = AtlasApp(demo=False)
    a.resize(1100, 640); a.show()
    eventbus.bus.publish(eventbus.contact("ADS-B", "p0", 47.60, -122.30, kind="aircraft"))
    _pump(300)
    eventbus.set_home((47.60, -122.30))                   # SETTINGS, no restart
    _pump(200)
    eventbus.bus.publish(eventbus.contact("ADS-B", "p1", 47.90, -122.30, kind="aircraft"))
    _pump(300)
    a._render()
    try:
        assert fetches and fetches[-1][1:] == (47.60, -122.30), fetches
        assert not a._home_cover.shown() and a.map.home.isVisible()
        pts = a.map.scatter.data
        assert len(pts) == 1                               # p0 (provisional frame) was dropped
        x, y = pts[0]["x"], pts[0]["y"]
        assert abs(x) < 0.1 and 17.5 < y < 18.5            # 0.3° north of HOME = ~18 nm
    finally:
        _close(a)


def test_FIXED_n26_ops_home_unset_ppi_draws_nothing(monkeypatch):
    from palisade_qt import eventbus
    from palisade_qt.ops import OpsHome
    o = OpsHome(demo=False)
    o.resize(1280, 640); o.show()
    drawn = []
    real = o.ppi.set_contacts
    o.ppi.set_contacts = lambda c, selected=None: (drawn.append(list(c)), real(c, selected=selected))
    for i, (la, lo) in enumerate([(47.60, -122.30), (47.90, -122.10)]):
        eventbus.bus.publish(eventbus.contact("ADS-B", "o%d" % i, la, lo, kind="aircraft"))
    _pump(600)
    o._refresh_ppi()
    try:
        assert drawn and all(d == [] for d in drawn)
        assert o._home_cover.shown() and o._home_cover.empty.geometry() == o.ppi.rect()
        assert "HOME NOT SET" in o.sub.text() and "NM" not in o.sub.text()
    finally:
        _close(o)


def test_DEFECT_ops_after_home_set_shows_nearest_range_from_the_guessed_origin():
    """OPS keeps the x/y/rng it computed from the provisional origin (the FIRST contact) when HOME
    is set live: it has no home_changed handler (ATLAS clears its contacts; OPS does not). For up to
    STALE_S (12 s), until each contact is heard again, the cover is lifted and the PPI plots those
    contacts around HOME with the first one dead centre, and the sub-line reads "nearest 0 NM" for
    an aircraft ~880 nm away."""
    from palisade_qt import eventbus
    from palisade_qt.ops import OpsHome
    o = OpsHome(demo=False)
    drawn = []
    o.ppi.set_contacts = lambda c, selected=None: drawn.append([(round(x["x"], 1), round(x["y"], 1))
                                                               for x in c])
    eventbus.bus.publish(eventbus.contact("ADS-B", "SEA1", 47.60, -122.30, kind="aircraft"))
    _pump(400)
    eventbus.set_home((39.74, -104.99))                   # Denver, set in SETTINGS
    _pump(200)
    o._refresh_ppi()
    print("sub:", o.sub.text(), "| drawn:", drawn[-1], "| cover:", o._home_cover.shown())
    try:
        assert not o._home_cover.shown()
        assert drawn[-1] == [(0.0, 0.0)]                   # Seattle drawn on top of Denver
        assert "nearest 0 NM" in o.sub.text()
    finally:
        _close(o)


# ============================================================ N27 / N28 — trail states, real chains
def _start_eng():
    ok, why = E.start("job", "ROE-1", ["10.0.0.0/24"], D.OP)
    assert ok, why
    return E.chain_info()


def _panel():
    from palisade_qt import panels
    host = QtWidgets.QWidget()
    p = panels.EngagePanel("dark", host)
    p._host = host
    p.render_actions()
    return p


def test_FIXED_n27_tampered_real_chain_is_unreadable_not_watching():
    info = _start_eng()
    assert E.authorize_action("net:portscan", "10.0.0.5", kind="ip")[0]
    raw = open(info["path"], "rb").read().replace(b"10.0.0.5", b"10.0.0.6")
    open(info["path"], "wb").write(raw)
    p = _panel()
    print(p.eng_chain.text(), "|", p.eng_actions.empty.text().replace("\n", " / "))
    assert "NOT VERIFIED" in p.eng_chain.text()
    assert p.eng_actions.empty.state == "stale" and "UNREADABLE" in p.eng_actions.empty.text()
    assert "nothing authorized" not in p.eng_actions.empty.text()


def test_FIXED_n28_malformed_head_with_engagement_active_is_unreadable_not_no_engagement():
    info = _start_eng()
    with open(info["path"][:-len(".jsonl")] + ".head", "wb") as fh:
        fh.write(b"garbage")
    chain.reset_for_tests()
    p = _panel()
    print(p.eng_chain.text(), "|", p.eng_actions.empty.text().replace("\n", " / "))
    assert "UNREADABLE" in p.eng_chain.text() and "NO ENGAGEMENT" not in p.eng_actions.empty.text()
    assert not E.authorize_action("net:portscan", "10.0.0.5", kind="ip")[0]


def test_FIXED_n28_rollback_refused_in_session_is_not_nothing_authorized():
    """R1: a chain replaced by an older snapshot while the hub has it open."""
    info = _start_eng()
    snap = open(info["path"], "rb").read()
    head = info["path"][:-len(".jsonl")] + ".head"
    hsnap = open(head, "rb").read()
    assert E.authorize_action("net:portscan", "10.0.0.5", kind="ip")[0]
    open(info["path"], "wb").write(snap); open(head, "wb").write(hsnap)
    p = _panel()
    print(p.eng_chain.text(), "|", p.eng_actions.empty.text().replace("\n", " / "))
    assert "nothing authorized" not in p.eng_actions.empty.text()


def test_OK_no_engagement_says_no_engagement():
    p = _panel()
    assert "NO ENGAGEMENT" in p.eng_actions.empty.text() and "none open" in p.eng_chain.text()


# ============================================================ N29 — what counts as a feed
def test_FIXED_n29_alert_only_sources_are_not_feeds():
    from palisade_qt import eventbus, system
    eventbus.bus.publish(eventbus.alert("OVERWATCH", "next pass: NOAA 19", severity="info"))
    eventbus.bus.publish(eventbus.alert("ATLAS", "AIS RADIO BUSY — held by PRISM"))
    eventbus.bus.publish(eventbus.make_event("decode", "OPS", {"kind": "telemetry", "batt": 80},
                                             severity="info"))
    assert eventbus.bus.feeds() == {}
    p = system.MoreApp(demo=False)
    try:
        assert "Watching" not in " ".join(p._sitrep_lines())
    finally:
        _close(p)


def test_DEFECT_n29_forge_serial_connect_counts_as_a_running_feed():
    """FORGE publishes a `decode` "serial device connected" when a serial port opens. That is not a
    receiver output, but bus.feeds() now lists FORGE, so SITREP drops "No feed is running … not an
    all-clear" and the assistant drops "nothing is being watched". It never says "Watching"
    (the decode itself is in the 10-min decode window). Low."""
    from palisade_qt import eventbus, system
    eventbus.bus.publish(eventbus.decode("FORGE", "SERIAL", "/dev/ttyACM0", "serial device connected"))
    p = system.MoreApp(demo=False)
    try:
        sit = " ".join(p._sitrep_lines())
        print(sit, "| feeds:", eventbus.bus.feeds(), "| note:", repr(p._feed_note()))
        assert "FORGE" in eventbus.bus.feeds() and "No feed is running" not in sit
        assert p._feed_note() == ""
    finally:
        _close(p)


# ============================================================ N30 — Wi-Fi scan while hidden
@pytest.mark.parametrize("subtab", ["WIFI", "BLE"])
def test_FIXED_n30_recon_started_hidden_never_scans(monkeypatch, subtab):
    from palisade_qt import recon
    calls = []
    monkeypatch.setattr(recon, "_run_scan",
                        lambda argv, timeout=12: calls.append(list(argv)) or ("", None))
    for _ in range(15):
        p = recon.ReconApp(demo=False)
        p._subtab = subtab
        p.start()
        time.sleep(0.03)
        _close(p)
    assert calls == []


# ============================================================ N31 / N32 — END identity
def test_FIXED_n31_exited_between_match_and_kill_is_unconfirmed_no_signal(monkeypatch):
    info = D._start()
    v = subprocess.Popen(["sleep", "30"], start_new_session=True)
    time.sleep(0.05)
    tid = D._forge_spawn(info, "10.0.0.71", v.pid, gatestate.proc_start(v.pid))
    real, n = E._identity, {"n": 0}
    real_kill = os.kill

    def ident(pid, pstart):
        n["n"] += 1
        r = real(pid, pstart)
        if pid == v.pid and n["n"] == 1:
            real_kill(v.pid, signal.SIGKILL); v.wait()
        return r
    monkeypatch.setattr(E, "_identity", ident)
    spy = D._Spy(monkeypatch)
    E.end()
    recs = [r for r in D._recs(info["path"]) if r.get("ticket") == tid and r.get("by") == "end"]
    print([(r["event"], r.get("reason")) for r in recs])
    assert spy.to(v.pid) == [] and [r["event"] for r in recs] == ["unconfirmed"]
    assert "exited on its own" in recs[0]["reason"]


def test_DEFECT_n31_leader_exits_before_kill_live_group_member_survives_end(monkeypatch):
    """The orphan's leader exits between _settle_tickets' match and _kill_orphans; a member of its
    process group (SIGTERM-ignoring helper) is still running. _kill_orphans sees no match, sends
    nothing to the group, and records `unconfirmed` "exited on its own before END signalled it".
    END leaves a live process of the gated tool running although its pgid is safe to signal (a pgid
    with live members cannot be reused). Honest record, but END is the kill path. The same holds
    without the race when the leader is already gone/zombie at END (_settle_tickets, ident != match)."""
    info = D._start()
    v = subprocess.Popen("%s -c '%s' & exec sleep 30" % (sys.executable, D.IGN), shell=True,
                         start_new_session=True)
    time.sleep(0.6)
    pg = v.pid
    tid = D._forge_spawn(info, "10.0.0.72", v.pid, gatestate.proc_start(v.pid))
    real, n = E._identity, {"n": 0}
    real_kill = os.kill

    def ident(pid, pstart):
        n["n"] += 1
        r = real(pid, pstart)
        if pid == v.pid and n["n"] == 1:
            real_kill(v.pid, signal.SIGKILL); v.wait()     # leader gone, member lives
        return r
    monkeypatch.setattr(E, "_identity", ident)
    E.end()
    alive = gatestate.group_alive(pg)
    recs = [r for r in D._recs(info["path"]) if r.get("ticket") == tid and r.get("by") == "end"]
    print("group alive after END:", alive, [(r["event"], r.get("reason")) for r in recs])
    try:
        assert alive
        assert [r["event"] for r in recs] == ["unconfirmed"]
        assert "exited on its own" in recs[0]["reason"]
    finally:
        try:
            os.killpg(pg, signal.SIGKILL)
        except OSError:
            pass


def test_FIXED_n32_session_leader_and_grandparent_are_never_signalled(monkeypatch):
    sid = os.getsid(0)
    info = D._start()
    targets = []
    if sid > 1 and sid not in (os.getpid(), os.getppid(), os.getpgrp()):
        targets.append(sid)
    with open("/proc/%d/stat" % os.getppid()) as f:
        gp = int(f.read().rsplit(")", 1)[1].split()[1])
    if gp > 1:
        targets.append(gp)
    if not targets:
        pytest.skip("no ancestor beyond ppid here")
    for i, pid in enumerate(targets):
        D._forge_spawn(info, "10.0.0.%d" % (80 + i), pid, gatestate.proc_start(pid))
    spy = D._Spy(monkeypatch, guard=set(targets))
    E.end()
    print("targets", targets, "signals", [spy.to(t) for t in targets])
    assert all(spy.to(t) == [] for t in targets)


# ============================================================ E1 residual — aircraft.json age
def _feed(src):
    import sky_app
    f = sky_app.AdsbFeed.__new__(sky_app.AdsbFeed)
    f.sources, f.aircraft, f.receiver, f.status = [src], [], None, "none"
    f.source, f.updated, f.data_t, f.trails, f.history = None, 0.0, None, {}, []
    f._last_frame, f._rcv_retry, f.lock = 0.0, 0.0, threading.Lock()
    return f


def _serve(body_fn):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            b = json.dumps(body_fn()).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b)

        def log_message(self, *a):
            pass
    s = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, "http://127.0.0.1:%d" % s.server_address[1]


@pytest.mark.parametrize("now", ["absent", "future", "string", "nan", "bool"])
def test_FIXED_e1_http_without_a_usable_now_is_never_live(now):
    def body():
        d = {"aircraft": [{"hex": "a1b2c3", "seen": 1, "lat": 47.6, "lon": -122.3}]}
        if now == "future":
            d["now"] = time.time() + 3600
        elif now == "string":
            d["now"] = str(time.time())
        elif now == "nan":
            d["now"] = float("nan")
        elif now == "bool":
            d["now"] = True
        return d
    s, url = _serve(body)
    try:
        f = _feed(url)
        f._tick([url])
        print(now, f.status)
        assert f.status == "stale"
    finally:
        s.shutdown()


def test_OK_e1_http_with_current_now_is_live():
    s, url = _serve(lambda: {"now": time.time(), "aircraft": []})
    try:
        f = _feed(url)
        f._tick([url])
        assert f.status == "live"
    finally:
        s.shutdown()


def test_OK_e1_file_without_now_fresh_mtime_is_live_old_is_stale(tmp_path):
    d = tmp_path / "readsb"; d.mkdir()
    p = d / "aircraft.json"
    p.write_text(json.dumps({"aircraft": []}))
    f = _feed(str(d)); f._tick([str(d)])
    assert f.status == "live"
    old = time.time() - 120
    os.utime(p, (old, old))
    f._tick([str(d)])
    assert f.status == "stale"
