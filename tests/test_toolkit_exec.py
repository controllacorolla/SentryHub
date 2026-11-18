"""TOOLKIT — the internal-pentest toolkit (items 1-5) is wired and gated.

Items:
  1 capture.py      — passive tcpdump/tshark pcap/live. Ungated but LOGGED; argv cannot smuggle a
                      tcpdump -z postrotate command or a tshark option out of the filter box.
  2 netpent.discover_prepare — arp-scan / nbtscan / netdiscover. ACTIVE, engagement-gated like nmap.
  3 responder.py    — analyze_argv (passive, ungated) + poison_prepare (engagement-gated, scope-bound).
  4 adtools.py      — smbmap / netexec / enum4linux-ng / impacket. Engagement-gated; NO credential
                      ever on the argv (it is recorded in the chain).
  5 webtriage.py    — testssl / whatweb / nuclei. Engagement-gated; URL built from the pinned addr.

Gate tests assert: no engagement -> refused; out of scope -> refused; in scope -> the exact argv;
option-injection in a target or interface -> refused. A UI smoke test builds the CAPTURE and ENUM
pages, runs a passive capture and a gated tool through fake spawners, and stops them.
"""
import json
import os
import subprocess
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from PySide6 import QtWidgets  # noqa: E402

import chain  # noqa: E402
import engagement as E  # noqa: E402
import txguard as G  # noqa: E402
import executor  # noqa: E402
import capture  # noqa: E402
import responder  # noqa: E402
import adtools  # noqa: E402
import webtriage  # noqa: E402
import netpent  # noqa: E402

OP = "KD0ABC"


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    import suite
    from palisade_qt import chrome
    monkeypatch.setattr(suite, "DATA", str(tmp_path / "data"))
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    monkeypatch.delenv("PALISADE_GATE_STATE", raising=False)
    monkeypatch.setattr(E, "_profile_operator", lambda: OP, raising=False)
    # Responder is source-only; pretend the launcher is installed so the gate logic is exercised.
    monkeypatch.setattr(responder, "program", lambda: "responder", raising=False)
    G.reset_session()
    E.reset()
    executor.reset()
    chain.reset_for_tests()
    chrome.reset()
    yield
    executor.kill_all("test teardown")
    executor.reset()
    G.reset_session()
    E.reset()
    chain.reset_for_tests()
    chrome.reset()


def _start(scope):
    ok, why = E.start("job", "ROE-1", list(scope), OP)
    assert ok, why
    return E.chain_info()


def _recs(path):
    with open(path, "rb") as fh:
        return [json.loads(x) for x in fh.read().splitlines() if x.strip()]


# ============================================================ item 2: LAN discovery (gated)

def test_discovery_needs_an_engagement():
    ok, why, t = netpent.discover_prepare("arp", "10.0.0.0/24")
    assert not ok and t is None and "engagement" in why


def test_discovery_in_scope_builds_the_right_argv():
    _start(["10.0.0.0/24"])
    for action, head in (("arp", ["arp-scan", "-x", "-q"]),
                         ("nbt", ["nbtscan", "-q"]),
                         ("netdiscover", ["netdiscover", "-P", "-N", "-r"])):
        ok, why, t = netpent.discover_prepare(action, "10.0.0.0/24")
        assert ok, why
        assert list(t.argv)[:len(head)] == head
        assert "10.0.0.0/24" in t.argv


def test_discovery_out_of_scope_is_refused():
    _start(["10.0.0.0/24"])
    ok, why, t = netpent.discover_prepare("arp", "192.168.5.0/24")
    assert not ok and t is None and "scope" in why


def test_discovery_iface_cannot_inject_an_option():
    _start(["10.0.0.0/24"])
    ok, why, t = netpent.discover_prepare("arp", "10.0.0.0/24", iface="--localnet")
    assert not ok and t is None


def test_discovery_option_like_target_is_refused():
    _start(["10.0.0.0/24"])
    ok, why, t = netpent.discover_prepare("arp", "-oG")
    assert not ok and t is None


# ============================================================ item 4: AD/SMB enum (gated)

def test_ad_enum_gate_and_argv():
    assert netpent  # imported
    ok, why, t = adtools.prepare("shares", "10.0.0.5")
    assert not ok and t is None                          # no engagement
    _start(["10.0.0.0/24"])
    ok, why, t = adtools.prepare("shares", "10.0.0.5")
    assert ok and list(t.argv) == ["smbmap", "-H", "10.0.0.5"]
    ok, why, t = adtools.prepare("enum", "10.0.0.5")
    assert ok and list(t.argv) == ["enum4linux-ng", "-A", "10.0.0.5"]
    ok, why, t = adtools.prepare("shares", "172.16.0.9")
    assert not ok and "scope" in why                     # out of scope


def test_ad_enum_never_puts_a_secret_on_the_argv():
    _start(["10.0.0.0/24"])
    for action in ("shares", "netexec", "enum", "samr", "rpc"):
        ok, why, t = adtools.prepare(action, "10.0.0.5")
        assert ok, why
        low = " ".join(t.argv).lower()
        assert "-p" not in t.argv and "password" not in low and "--pass" not in low


# ============================================================ item 5: web/TLS triage (gated)

def test_web_triage_gate_and_url():
    ok, why, t = webtriage.prepare("whatweb", "10.0.0.5")
    assert not ok and t is None                          # no engagement
    _start(["10.0.0.0/24"])
    ok, why, t = webtriage.prepare("whatweb", "10.0.0.5")
    assert ok and t.argv[-1] == "https://10.0.0.5"
    ok, why, t = webtriage.prepare("nuclei", "10.0.0.5", scheme="http", port=8080)
    assert ok and "-duc" in t.argv and t.argv[-1] == "http://10.0.0.5:8080"
    ok, why, t = webtriage.prepare("testssl", "10.0.0.5", port=8443)
    assert ok and t.argv[-1] == "10.0.0.5:8443"


def test_web_triage_bad_port_refused():
    _start(["10.0.0.0/24"])
    ok, why, t = webtriage.prepare("whatweb", "10.0.0.5", port="70000")
    assert not ok and t is None


# ============================================================ item 3: Responder

def test_responder_analyze_is_passive_argv():
    argv, err = responder.analyze_argv("eth0")
    assert err is None and argv == ["responder", "-I", "eth0", "-A"]


def test_responder_poison_is_gated_and_scope_bound():
    ok, why, t = responder.poison_prepare("eth0", "10.0.0.0/24")
    assert not ok and t is None                          # no engagement
    _start(["10.0.0.0/24"])
    ok, why, t = responder.poison_prepare("eth0", "10.0.0.0/24")
    assert ok and list(t.argv) == ["responder", "-I", "eth0"]
    ok, why, t = responder.poison_prepare("eth0", "192.168.9.0/24")
    assert not ok and "scope" in why                     # out of scope


def test_responder_poison_argv_carries_no_attack_flag():
    _start(["10.0.0.0/24"])
    ok, why, t = responder.poison_prepare("eth0", "10.0.0.0/24")
    assert ok and "-A" not in t.argv       # poison is the absence of -A; nothing extra is added


# ============================================================ item 1: passive capture builders

def test_capture_pcap_argv_and_filter():
    out = os.path.join(capture.pcap_dir(), "x.pcap")
    argv, err = capture.pcap_argv("eth0", out, "port 445 and host 10.0.0.1")
    assert err is None
    assert argv[:9] == ["tcpdump", "-i", "eth0", "-n", "-U", "-s", "0", "-w", out]
    assert argv[-5:] == ["port", "445", "and", "host", "10.0.0.1"]


def test_capture_filter_cannot_smuggle_a_postrotate_command():
    out = os.path.join(capture.pcap_dir(), "x.pcap")
    argv, err = capture.pcap_argv("eth0", out, "-z /bin/sh")
    assert argv is None and err and "'-'" in err
    # and we never build -z ourselves
    argv, err = capture.pcap_argv("eth0", out, "port 445")
    assert err is None and "-z" not in argv


def test_capture_out_must_be_in_the_captures_dir():
    argv, err = capture.pcap_argv("eth0", "/etc/passwd", "port 445")
    assert argv is None and "captures" in err


def test_capture_iface_must_be_plain():
    argv, err = capture.pcap_argv("--interface=x", os.path.join(capture.pcap_dir(), "x.pcap"))
    assert argv is None
    argv, err = capture.live_argv("eth0", "port 80")
    assert err is None and argv[:4] == ["tshark", "-i", "eth0", "-l"]


# ============================================================ UI smoke (CAPTURE + ENUM)

class _Spawns:
    def __init__(self, code="print('ok')"):
        self.code, self.calls, self.procs = code, [], []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        p = subprocess.Popen([sys.executable, "-u", "-c", self.code], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.procs.append(p)
        return p


def _recon(monkeypatch, sp):
    from palisade_qt import recon
    monkeypatch.setattr(recon.ReconApp, "_spawner", lambda self: sp)
    _app()
    p = recon.ReconApp(demo=False)
    _app().processEvents()
    return p


def _wait(pred, s=6.0):
    t = time.time()
    while time.time() - t < s:
        _app().processEvents()
        if pred():
            return True
        time.sleep(0.01)
    _app().processEvents()
    return pred()


def test_capture_page_runs_a_passive_capture_and_logs_it(monkeypatch):
    sp = _Spawns("print('capturing')")
    info = _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        # the capture group lives on the NET sub-tab (SUBTABS stay WIFI/BLE/NET/RF)
        net = p._pages["NET"]
        btns = net.findChildren(QtWidgets.QPushButton)
        pcap = [b for b in btns if b.text() == "PCAP"][0]
        pcap.click()
        _app().processEvents()
        # wait until the pane's poll timer has recorded the exit (not just the child dying)
        assert _wait(lambda: "passive.exit" in [r.get("event") for r in _recs(info["path"])])
        assert sp.calls and sp.calls[0][0] == "tcpdump"
        evs = [r.get("event") for r in _recs(info["path"])]
        assert "passive.start" in evs and "passive.exit" in evs
    finally:
        p.stop(); p.deleteLater(); _app().processEvents()


def test_enum_page_runs_a_gated_tool_through_the_executor(monkeypatch):
    sp = _Spawns("print('SMB shares')")
    info = _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        # find the AD/SMB card and run 'shares' against an in-scope host
        ad = [c for c in p._gated if getattr(c, "_domain", None) == "target"
              and c._prepare is adtools.prepare][0]
        ad.target.setText("10.0.0.5")
        i = [b.text() for b in ad._btns].index("SHARES")
        ad._btns[i].click()
        _app().processEvents()
        assert _wait(lambda: sp.calls)
        assert sp.calls[0] == ["smbmap", "-H", "10.0.0.5"]
        recs = _recs(info["path"])
        assert any(r.get("event") == "spawn" for r in recs)
    finally:
        p.stop(); p.deleteLater(); _app().processEvents()


def test_out_of_scope_enum_in_ui_spawns_nothing(monkeypatch):
    sp = _Spawns()
    _start(["10.0.0.0/24"])
    p = _recon(monkeypatch, sp)
    try:
        ad = [c for c in p._gated if c._prepare is adtools.prepare][0]
        ad.target.setText("172.16.9.9")
        i = [b.text() for b in ad._btns].index("SHARES")
        ad._btns[i].click()
        _app().processEvents()
        time.sleep(0.2)
        _app().processEvents()
        assert sp.calls == []
        assert "DENIED" in ad.result.text()
    finally:
        p.stop(); p.deleteLater(); _app().processEvents()
