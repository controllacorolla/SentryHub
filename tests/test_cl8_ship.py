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
