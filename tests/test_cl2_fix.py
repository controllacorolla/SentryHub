"""CL2-fix — regression tests for what RA-CL2 found (N1 N2 N3 N4 + Lows N5 N6 N8 N9a).

Each test is derived from the RA-CL2 PoC (plan/briefs/RA-CL2-evidence/) and fails on fix/cl2-gates
at dcb7c4f. Same ground rules as test_cl2_gates.py: nothing emits — spawners are injected (a harmless
`python -c sleep` stands in when a real process group must be killed), ports are recording fakes and
DNS is an injected resolver.
"""
import json
import os
import subprocess
import sys
import time

import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

import engagement as E  # noqa: E402
import executor  # noqa: E402
import txguard as G  # noqa: E402

OP = "KD0ABC"
TXS = {"tx_enabled": True, "callsign": OP, "bench_conducted_ack": True}
AP, CL = "AA:BB:CC:DD:EE:FF", "12:22:33:44:55:66"   # CL is a unicast station (I/G bit clear)
HACKRF_1090 = ["hackrf_transfer", "-t", "/tmp/x.iq", "-f", "1090000000", "-s", "2000000",
               "-x", "47"]


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    monkeypatch.delenv("PALISADE_GATE_STATE", raising=False)
    monkeypatch.delenv("PALISADE_GATE_NONCE", raising=False)
    monkeypatch.setattr(E, "_profile_operator", lambda: OP, raising=False)
    monkeypatch.setattr(executor, "SERIAL_LOG", str(tmp_path / "serial_tx.jsonl"))
    G.reset_session()
    E.reset()
    executor.reset()
    yield
    executor.kill_all("test teardown")
    executor.reset()
    G.reset_session()
    E.reset()


def _sleeper_spawner(calls):
    def spawn(argv, **kw):
        calls.append(list(argv))
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
    return spawn


def _wait_dead(proc, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return False


class _FakePort:
    def __init__(self):
        self.data = []

    def write(self, b):
        self.data.append(bytes(b))
        return len(b)


# ============================================================================ N1 — SDR TX is txguard's only
def test_n1_engagement_cannot_issue_hackrf_1090_poc():
    """PoC (ra_cl2_poc2 p5): engagement.issue minted a ticket for hackrf_transfer on 1090 MHz
    (ADS-B) against a label scope and the executor spawned it with no txguard check."""
    E.start("job", "ROE-1", ["BADGE-7"], OP)
    G.arm(True)
    calls = []
    ok, why, t = E.issue("x:tx", "BADGE-7", argv=HACKRF_1090, kind="label")
    assert not ok and t is None and "txguard" in why.lower(), why
    assert E.actions() == [], "a refused transmitter must not be recorded as authorized"
    assert calls == []


@pytest.mark.parametrize("argv", [
    ["/usr/local/bin/hackrf_transfer", "-t", "x.iq", "-f", "1090000000"],
    ["sudo", "hackrf_transfer", "-t", "x.iq"],
    ["sh", "-c", "hackrf_transfer -t x.iq -f 121500000"],
    ["env", "A=1", "rpitx", "-m", "RF"],
    ["osmocom_siggen_nogui", "-f", "1575420000"],
    ["uhd_siggen", "-f", "433e6"],
    ["sendiq", "-i", "x.iq"],
    ["my_custom_siggen_v2"],                       # unknown, but transmit-shaped: fails closed
])
def test_n1_wrapped_and_lookalike_transmitters_refused_at_issue(argv):
    E.start("job", "ROE-1", ["BADGE-7"], OP)
    G.arm(True)
    ok, why, t = E.issue("x:tx", "BADGE-7", argv=argv, kind="label")
    assert not ok and t is None, argv


def test_n1_executor_refuses_sdr_tx_from_every_issuer_but_txguard():
    """Structural: even a direct executor.issue from another permitted issuer is refused."""
    for issuer in ("engagement", "flipper"):
        ns = {"__name__": issuer}
        code = ("import executor\n"
                "executor.issue(argv=%r, recheck=lambda: (True, 'trust me'), label='x')"
                % (HACKRF_1090,))
        with pytest.raises(executor.TicketRefused):
            exec(compile(code, "<%s>" % issuer, "exec"), ns)
    assert executor.TX_ISSUERS == ("txguard",)


def test_n1_txguard_still_issues_sdr_tx_on_an_allowed_band():
    G.arm(True)
    G.unlock_session(True)
    ok, why, t, _p = G.issue_ticket("replay", ["hackrf_transfer", "-t", "x.iq", "-f", "915000000"],
                                    915_000_000, settings=dict(TXS))
    assert ok and t is not None, why
    ok, why, t, _p = G.issue_ticket("replay", HACKRF_1090, 1_090_000_000, settings=dict(TXS))
    assert not ok and t is None and "protected" in why.lower()


def test_n1_static_no_non_txguard_issuer_names_a_transmitter():
    """The one-gate test, extended: a module that mints tickets through the engagement gate (or
    directly through the executor) must not name an SDR transmitter anywhere in its string
    constants. A new transmitter wired via the wrong gate fails the suite."""
    import ast
    import rfemit
    import test_cl2_gates as C
    bad = []
    for path in C.GATED_MODULES:
        if path == "txguard.py":
            continue
        calls, src = C._calls(path)
        names = {n for _f, n, _l in calls}
        if not ({"engagement.issue", "E.issue", "executor.issue"} & names) and \
                path not in ("engagement.py",):
            continue
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for word in node.value.split():
                    if word in rfemit.SDR_TX_PROGRAMS:
                        bad.append("%s:%d names %r" % (path, node.lineno, word))
    assert not bad, "transmitter reachable through a non-txguard gate:\n" + "\n".join(bad)


# ============================================================================ N2 — hard lock + kill switch silence every emitter
def _scope_all():
    E.start("job", "ROE-1", [AP, CL, "pan:0x1A2B@15", "uid:DEADBEEF", "usb:0483:5740",
                             "usb:10c4:ea60", "NODE-5"], OP)


def _wifi_deauth():
    import wifipent
    return wifipent.prepare("deauth", AP, client=CL)


def _wifi_pmkid():
    import wifipent
    return wifipent.prepare("pmkid", AP, out="/tmp/cl2fix-cap")


def _zigbee_inject():
    import zigbee
    return zigbee.prepare("inject", pan=0x1A2B, channel=15)


def _zigbee_discover():
    import zigbee
    return zigbee.prepare("discover", channel=15)


def _ble_write():
    import blepent
    return blepent.prepare("write", AP, handle="0x0025", value="01")


def _flipper_subghz():
    import flipper
    return flipper.prepare_command("subghz tx 0 433920000", device="usb:0483:5740",
                                   kind="flipper")


def _esp32_line():
    import flipper
    return flipper.prepare_command("attack -t deauth", device="usb:10c4:ea60", kind="esp32")


def _proxmark_sim():
    import proxmark
    return proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="DEADBEEF",
                            read_uid=lambda: "DEADBEEF")


def _zwave_query():
    import zwave
    return zwave.prepare("query", target="NODE-5", node_id=5)


EMITTERS = [_wifi_deauth, _wifi_pmkid, _zigbee_inject, _zigbee_discover, _ble_write,
            _flipper_subghz, _esp32_line, _proxmark_sim, _zwave_query]


@pytest.mark.parametrize("make", EMITTERS, ids=lambda f: f.__name__)
def test_n2_kill_switch_off_refuses_every_emitter_at_issue_poc(make):
    """PoC (ra_cl2_poc2 p1-p3): disarmed, tickets were still issued for deauth / Zigbee inject /
    BLE write / Flipper subghz tx."""
    _scope_all()
    ok, why, t = make()
    assert not ok and t is None and "silenced" in why.lower(), why


@pytest.mark.parametrize("make", EMITTERS, ids=lambda f: f.__name__)
def test_n2_env_hard_lock_refuses_every_emitter_at_issue_poc(make, monkeypatch):
    _scope_all()
    G.arm(True)
    monkeypatch.setenv("SUITE_TX_LOCK", "1")
    ok, why, t = make()
    assert not ok and t is None and "SUITE_TX_LOCK" in why, why


@pytest.mark.parametrize("make", EMITTERS, ids=lambda f: f.__name__)
def test_n2_every_emitter_refused_at_spawn_after_disarm_or_lock(make, monkeypatch):
    _scope_all()
    for close in ("disarm", "lock"):
        G.arm(True)
        monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
        ok, why, t = make()
        assert ok and t is not None, why                  # armed: the engagement decides
        if close == "disarm":
            G.arm(False)
        else:
            monkeypatch.setenv("SUITE_TX_LOCK", "1")
        calls = []
        with pytest.raises(executor.TicketRefused):
            if t.kind == "proc":
                executor.start(t, spawner=_sleeper_spawner(calls))
            else:
                executor.write(t, _FakePort())
        assert calls == []


def test_n2_disarm_kills_a_running_deauth_poc():
    """PoC: DISARM did not kill a running deauth (only END / PANIC did)."""
    _scope_all()
    G.arm(True)
    ok, why, t = _wifi_deauth()
    assert ok, why
    h = executor.start(t, spawner=_sleeper_spawner([]))
    assert h.proc.poll() is None
    G.arm(False)
    assert _wait_dead(h.proc), "disarm left the deauth running"
    assert h.stopped and "silenced" in h.stopped.lower()


def test_n2_env_lock_mid_run_kills_a_running_emitter(monkeypatch):
    _scope_all()
    G.arm(True)
    ok, why, t = _zigbee_inject()
    assert ok, why
    h = executor.start(t, spawner=_sleeper_spawner([]))
    monkeypatch.setenv("SUITE_TX_LOCK", "1")              # no notification: the monitor sees it
    assert _wait_dead(h.proc), "SUITE_TX_LOCK left the emitter running"


def test_n2_wired_tools_do_not_need_the_kill_switch():
    """Not an over-broad classifier: wired / network tools keep their engagement-only gate."""
    import canbus
    import netpent
    import usbhid
    E.start("job", "ROE-1", ["10.0.0.0/24", "can0:0x700-0x7FF", "LAPTOP-7"], OP)
    assert netpent.prepare("portscan", "10.0.0.5")[0] is True
    assert canbus.prepare_send("can0", 0x7DF, b"\x02\x01\x0c")[0] is True
    assert usbhid.prepare("STRING hi", "LAPTOP-7")[0] is True


def test_n2_classifier_table():
    import rfemit
    C = rfemit.classify
    assert C(argv=["aireplay-ng", "--deauth", "3"]) == "wifi"
    assert C(argv=["sudo", "-u", "x", "aireplay-ng"]) == "wifi"
    assert C(argv=["sh", "-c", "zbreplay -c 15"]) == "zigbee"
    assert C(argv=["pm3", "-p", "/dev/ttyACM0", "-c", "hf mf sim"]) == "rfid"
    assert C(argv=["zwave-map", "-f", "908420000"]) == "zwave"
    assert C(argv=["zbdump", "-c", "15"]) is None                       # receive-only
    assert C(argv=["zwave-sniffer"]) is None
    assert C(argv=["nmap", "-sS", "zb.lan"]) is None                   # a hostname is not a program
    assert C(argv=["hackrf_transfer", "-t", "x"]) == rfemit.SDR_TX
    fl = {"class": "flipper"}
    assert C(payload=b"subghz tx 0 1\r\n", meta=fl) == "serial-rf"
    assert C(payload=b"loader open Sub-GHz\r\n", meta=fl) == "serial-rf"   # unknown verb: closed
    assert C(payload=b"subghz rx 433920000\r\n", meta=fl) is None         # allowlisted read
    assert C(payload=b"gpio set pa7 1\r\n", meta=fl) is None
    assert C(payload=b"AT\r\n", meta={"class": "esp32"}) == "serial-rf"
    assert C(payload=b"AT\r\n", meta={"class": "unknown"}) == "serial-rf"
    assert C(payload=b"t7DF\r", meta={"class": "slcan"}) is None
    assert C(payload=b"\x00\x04", meta=None) is None                    # USB-HID report


# ============================================================================ N3 — hub identity in the gate-state file
def _write_state(path, **obj):
    base = {"pid": os.getpid(), "nonce": "n" * 32, "start": None, "t": time.time(),
            "armed": True, "unlocked": True, "engagement": None}
    base.update(obj)
    with open(path, "w") as fh:
        json.dump(base, fh)
    os.chmod(path, 0o600)


def _sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])


def test_n3_live_pid_with_wrong_start_time_is_locked_recycled_pid(tmp_path):
    """A file whose pid now belongs to a different (live) process — a recycled pid."""
    import gatestate
    p = _sleeper()
    try:
        path = str(tmp_path / "gate.json")
        me = gatestate.proc_start(os.getpid())
        assert me is not None, "process start time must be readable on this platform"
        _write_state(path, pid=p.pid, start=me)                 # recorded start != p's start
        assert gatestate.read(path, nonce="n" * 32) is None
        _write_state(path, pid=p.pid, start=gatestate.proc_start(p.pid))
        assert gatestate.read(path, nonce="n" * 32) is not None   # the check is precise
    finally:
        p.kill()
        p.wait()


def test_n3_stale_file_after_hub_crash_is_locked(tmp_path):
    import gatestate
    p = _sleeper()
    start = gatestate.proc_start(p.pid)
    p.kill()
    p.wait()
    path = str(tmp_path / "gate.json")
    _write_state(path, pid=p.pid, start=start)
    assert gatestate.read(path, nonce="n" * 32) is None


def test_n3_file_from_another_hub_is_locked(tmp_path):
    import gatestate
    pub = gatestate.Publisher(str(tmp_path / "ours.json"))
    try:
        other = str(tmp_path / "other.json")
        _write_state(other, nonce="x" * 32, start=gatestate.proc_start(os.getpid()))
        assert gatestate.read(other, nonce=pub.nonce) is None        # another hub's file
        assert gatestate.read(pub.path, nonce=pub.nonce) is not None  # our own is trusted
        assert gatestate.read(pub.path, nonce="") is None             # no nonce: nothing trusted
        env = gatestate.child_env(other, base={})
        assert gatestate.NONCE_ENV not in env and env.get("SUITE_TX_LOCK") == "1"
        env = gatestate.child_env(pub.path, base={gatestate.NONCE_ENV: "spoofed"})
        assert env[gatestate.NONCE_ENV] == pub.nonce
    finally:
        pub.close()


def test_n3_missing_start_time_is_locked(tmp_path):
    import gatestate
    path = str(tmp_path / "gate.json")
    _write_state(path, start=None)
    assert gatestate.read(path, nonce="n" * 32) is None


_CHILD = r"""
import json, sys
sys.path.insert(0, %r)
import txguard, engagement
print(json.dumps({"armed": txguard.is_armed(), "eng": engagement.is_active(),
                  "tx": txguard.authorize("replay", 915000000, settings={"tx_enabled": True})[0]}))
"""


def test_n3_forged_file_naming_a_live_pid_is_not_trusted_by_a_child_poc(tmp_path):
    """PoC (ra_cl2_poc l1_forged): a child read armed / engaged / tx_authorized=True from a file
    that names a live process (here: this test process) it was never bound to."""
    path = str(tmp_path / "forged.json")
    eng = {"name": "j", "authorization": "a", "scope": ["10.0.0.0/24"], "operator": OP,
           "started": time.time(), "expires": time.time() + 3600,
           "entries": [{"kind": "ip", "text": "10.0.0.0/24",
                        "data": {"lo": "10.0.0.0", "hi": "10.0.0.255"}}]}
    _write_state(path, engagement=eng)
    env = dict(os.environ)
    env.pop("SUITE_TX_LOCK", None)
    env["PALISADE_GATE_STATE"] = path
    env["PALISADE_GATE_NONCE"] = "n" * 32          # even with the right nonce: no start time
    out = subprocess.run([sys.executable, "-c", _CHILD % SUITE_DIR], env=env, capture_output=True,
                         text=True, timeout=60)
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r == {"armed": False, "eng": False, "tx": False}, r


def test_n3_real_child_of_a_real_publisher_still_follows_the_hub(tmp_path):
    import gatestate
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    try:
        G.arm(True)
        G.unlock_session(True)
        env = gatestate.child_env(pub.path, base=dict(os.environ))
        env.pop("SUITE_TX_LOCK", None)
        out = subprocess.run([sys.executable, "-c", _CHILD % SUITE_DIR], env=env,
                             capture_output=True, text=True, timeout=60)
        r = json.loads(out.stdout.strip().splitlines()[-1])
        assert r["armed"] is True and r["tx"] is True, (r, out.stderr[-400:])
    finally:
        pub.close()


# ============================================================================ N4 — Proxmark emulated / written identity
def test_n4_sim_out_of_scope_emulated_id_refused_poc():
    """PoC (ra_cl2_poc g5_pm_param): `hf mf sim -u CAFEBABE` was authorized while the scope and
    the card on the antenna were both DEADBEEF."""
    import proxmark
    E.start("job", "ROE-1", ["uid:DEADBEEF"], OP)
    G.arm(True)
    ok, why, t = proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="CAFEBABE",
                                  read_uid=lambda: "DEADBEEF")
    assert not ok and t is None and "CAFEBABE" in why.upper(), why


def test_n4_clone_out_of_scope_written_id_refused():
    import proxmark
    E.start("job", "ROE-1", ["uid:2006F623AE"], OP)
    G.arm(True)
    ok, why, t = proxmark.prepare("lf_hid_clone", target="uid:2006F623AE", id="1111111111",
                                  read_uid=lambda: "2006F623AE")
    assert not ok and t is None


def test_n4_in_scope_emulated_id_allowed_and_bound_into_the_command():
    import proxmark
    E.start("job", "ROE-1", ["uid:DEADBEEF", "uid:CAFEBABE"], OP)
    G.arm(True)
    ok, why, t = proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="ca:fe:ba:be",
                                  read_uid=lambda: "DEADBEEF")
    assert ok and t.argv[-1] == "hf mf sim --1k -u CAFEBABE", (why, t and t.argv)


def test_n4_second_pm3_command_cannot_be_smuggled_in_a_parameter():
    import proxmark
    E.start("job", "ROE-1", ["uid:2006F623AE"], OP)
    G.arm(True)
    ok, why, t = proxmark.prepare("lf_t55_write", target="uid:2006F623AE", block="0",
                                  data="00107060; lf hid clone -r 1111111111",
                                  read_uid=lambda: "2006F623AE")
    assert not ok and t is None
    ok, why, t = proxmark.prepare("lf_t55_write", target="uid:2006F623AE", block="0",
                                  data="00107060", read_uid=lambda: "2006F623AE")
    assert ok and "not bound to the scope" in why


# ============================================================================ Lows
def test_n5_hostname_target_is_pinned_to_its_checked_address_poc(monkeypatch):
    """PoC (ra_cl2_poc g4_rebind): netpent put `nas.lan` in the argv; nmap did its own lookup."""
    import netpent
    table = {"nas.lan": ["10.0.0.5"]}
    monkeypatch.setattr(E, "_resolve", lambda h: list(table[h]))
    E.start("job", "ROE-1", ["10.0.0.0/24"], OP)
    ok, why, t = netpent.prepare("portscan", "nas.lan")
    assert ok and "nas.lan" not in t.argv and t.argv[-1] == "10.0.0.5", t and t.argv
    table["nas.lan"] = ["6.6.6.6"]                         # rebinding after the check
    calls = []
    executor.start(t, spawner=_sleeper_spawner(calls))
    assert calls[0][-1] == "10.0.0.5"


def test_n5_every_resolved_address_is_pinned_and_checked(monkeypatch):
    import netpent
    table = {"nas.lan": ["10.0.0.5", "10.0.0.6"], "split.lan": ["10.0.0.7", "8.8.8.8"]}
    monkeypatch.setattr(E, "_resolve", lambda h: list(table[h]))
    E.start("job", "ROE-1", ["10.0.0.0/24"], OP)
    ok, why, t = netpent.prepare("services", "nas.lan")
    assert ok and t.argv[-2:] == ("10.0.0.5", "10.0.0.6")
    ok, why, t = netpent.prepare("services", "split.lan")
    assert not ok and t is None


def test_n6_float_format_sample_rate_does_not_crash_and_is_bounded_poc():
    """PoC (ra_cl2_poc3): sample_rate="2e6" passed the gate, then int("2e6") crashed."""
    import replay
    G.arm(True)
    G.unlock_session(True)
    ok, why, t = replay.prepare_replay("x.iq", 915_000_000, "2e6", True, settings=dict(TXS))
    assert ok, why
    argv = list(t.argv)
    assert argv[argv.index("-s") + 1] == "2000000"
    for bad in ("2e9", "nan", "inf", "1e3"):
        ok, why, t = replay.prepare_replay("x.iq", 915_000_000, bad, True, settings=dict(TXS))
        assert not ok and t is None, bad


def test_n8_recheck_reads_live_settings_not_a_snapshot_poc():
    """PoC (ra_cl2_poc g11_settings_snapshot): clearing tx_enabled mid-transmission did not stop
    it — the re-check used a copy of the settings."""
    import replay
    G.arm(True)
    G.unlock_session(True)
    s = dict(TXS)
    ok, why, t = replay.prepare_replay("x.iq", 915_000_000, 2_000_000, True, settings=s)
    assert ok, why
    h = executor.start(t, spawner=_sleeper_spawner([]))
    s["tx_enabled"] = False
    assert _wait_dead(h.proc), "clearing tx_enabled left the transmitter running"


def test_n8_bench_saved_opt_in_is_live(tmp_path, monkeypatch):
    import bench
    monkeypatch.setattr(bench, "TX_LOG", str(tmp_path / "bench.log"))
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 64)
    G.arm(True)
    G.unlock_session(True)
    saved = {"on": True}
    ok, why, h = bench.start_transmit(dict(TXS, freq_hz=915_000_000, iq_file=str(iq)),
                                      spawner=_sleeper_spawner([]), opt_in=lambda: saved["on"])
    assert ok, why
    saved["on"] = False                                    # tx_enabled cleared in saved settings
    assert _wait_dead(h.proc)


def test_n9a_demo_ticket_only_writes_to_the_synthetic_port():
    import flipper
    import hwlab
    ok, why, t = flipper.prepare_command("anything at all", kind="demo")
    assert ok
    with pytest.raises(executor.TicketRefused):
        executor.write(t, _FakePort())                     # a real (non-synthetic) port
    ok, why, t = flipper.prepare_command("help", kind="demo")
    assert executor.write(t, hwlab.DemoSerial()) > 0
