"""CL2-fix2 — regression tests for RA-CL2b R1, R2, R4, R6. Each PoC test fails on 18770be.

No test radiates: spawns go to a sleeper stand-in, writes to an in-memory port.
"""
import ast
import os
import subprocess
import sys

import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

import engagement as E  # noqa: E402
import executor  # noqa: E402
import txguard as G  # noqa: E402

OP = "KD0ABC"
TXS = {"tx_enabled": True, "callsign": OP, "bench_conducted_ack": True}
H1090 = ["-t", "x.iq", "-f", "1090000000", "-x", "47"]

# This test module is itself an engagement.issue caller: it declares the tools it may run, so the
# bypass tests below prove the ALLOWLIST refuses them (not merely a missing declaration).
ALLOWED_PROGRAMS = frozenset(("nmap", "gatttool"))


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


def _arm():
    G.arm(True)
    G.unlock_session(True)


def _sleeper(calls):
    def spawn(argv, **kw):
        calls.append(list(argv))
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    return spawn


# ---------------------------------------------------------------- R1: allowlist, not blocklist
RA_BYPASSES = {
    "bash -c empty-quote split": ["bash", "-c", "hackrf_trans''fer " + " ".join(H1090)],
    "bash -c glob": ["bash", "-c", "/usr/bin/hackrf_tr?nsfer " + " ".join(H1090)],
    "bash -c ANSI-C": ["bash", "-c", "$'\\x68ackrf_transfer' " + " ".join(H1090)],
    "bash -c ${var}": ["bash", "-c", "a=hackrf; ${a}_transfer " + " ".join(H1090)],
    "python -c concat": ["python3", "-c", "import os; os.execvp('hackrf_'+'transfer', ['x'])"],
    "python3.13 -c": ["python3.13", "-c", "pass"],
    "perl -e": ["perl", "-e", "exec 'hackrf_'.'transfer'"],
    "env wrapper": ["env", "nmap", "10.0.0.5"],
    "sudo wrapper": ["sudo", "nmap", "10.0.0.5"],
    "xargs wrapper": ["xargs", "nmap"],
    "renamed / symlinked binary": ["/home/pi/bin/htx"] + H1090,
    "declared name via a path": ["/tmp/evil/nmap", "10.0.0.5"],
    "Cyrillic look-alike": ["hackrf_transfеr"] + H1090,
    "rpitx tune": ["tune", "-f", "1090000000"],
    "rpitx sendook": ["sendook", "-f", "433920000", "0101"],
    "UHD tx_waveforms": ["tx_waveforms", "--freq", "1090e6"],
    "URH urh_cli": ["urh_cli", "-tx", "-f", "1090e6"],
    "GNU Radio flowgraph": ["python3", "/home/pi/flowgraphs/adsb_tx.py"],
    "trailing-space name": ["nmap ", "10.0.0.5"],
    "empty argv[0]": ["", "10.0.0.5"],
}


@pytest.mark.parametrize("name", sorted(RA_BYPASSES))
def test_r1_every_ra_bypass_refused_through_the_engagement_gate_poc(name):
    """PoC (RA-CL2b n1_issue): each of these was minted by engagement.issue on 18770be."""
    assert E.start("job", "ROE-1", ["BADGE-7", "10.0.0.0/24"], OP)[0]
    _arm()
    ok, why, t = E.issue("x:run", "BADGE-7", argv=RA_BYPASSES[name], kind="label")
    assert not ok and t is None, (name, why)
    assert E.actions() == [], "a refused command must not be recorded as authorized"


def test_r1_a_module_cannot_declare_a_shell_or_interpreter():
    """Even a module that lists bash / python3 in ALLOWED_PROGRAMS cannot run them."""
    assert E.start("job", "ROE-1", ["BADGE-7"], OP)[0]
    _arm()
    ns = {"__name__": "rogue_module", "E": E,
          "ALLOWED_PROGRAMS": frozenset(("bash", "python3", "env", "sudo", "busybox", "nmap"))}
    code = "def go(argv):\n    return E.issue('x', 'BADGE-7', argv=argv, kind='label')\n"
    exec(compile(code, "rogue_module.py", "exec"), ns)
    for argv in (["bash", "-c", "true"], ["python3", "-c", "pass"], ["env", "nmap"],
                 ["sudo", "nmap"], ["busybox", "sh"]):
        ok, why, t = ns["go"](argv)
        assert not ok and "shell, interpreter or wrapper" in why, (argv, why)
    assert ns["go"](["nmap", "-sn", "10.0.0.0/24"])[0] is True          # its declared tool runs


def test_r1_undeclared_module_runs_nothing():
    assert E.start("job", "ROE-1", ["BADGE-7"], OP)[0]
    _arm()
    ns = {"__name__": "undeclared_module", "E": E}
    exec(compile("def go(a):\n    return E.issue('x', 'BADGE-7', argv=a, kind='label')\n",
                 "undeclared_module.py", "exec"), ns)
    ok, why, t = ns["go"](["nmap", "10.0.0.5"])
    assert not ok and "ALLOWED_PROGRAMS" in why, why
    # a device payload (no argv) is not a program: unaffected by the allowlist
    ok, why, t = E.issue("x", "BADGE-7", payload=b"STRING hi\n", kind="label")
    assert ok, why


def test_r1_this_modules_declared_tool_still_issues():
    assert E.start("job", "ROE-1", ["10.0.0.0/24"], OP)[0]
    ok, why, t = E.issue("net:x", "10.0.0.5", argv=["nmap", "-sT", "10.0.0.5"], kind="ip")
    assert ok and t.argv[0] == "nmap", why


def test_r1_every_shipped_module_real_commands_still_issue(monkeypatch, tmp_path):
    import blepent
    import buslab
    import canbus
    import netpent
    import passaudit
    import proxmark
    import wifipent
    import zigbee
    import zwave
    assert E.start("job", "ROE-1", ["AA:BB:CC:DD:EE:FF", "12:22:33:44:55:66", "pan:0x1A2B@15",
                                    "NODE-5", "uid:DEADBEEF", "10.0.0.0/24", "can0:0x700-0x7FF",
                                    "ROUTER-1", "LAB-CAP"], OP)[0]
    _arm()
    rd = lambda: "DEADBEEF"   # noqa: E731
    cases = {
        "wifipent handshake": lambda: wifipent.prepare("handshake", "AA:BB:CC:DD:EE:FF"),
        "wifipent pmkid": lambda: wifipent.prepare("pmkid", "AA:BB:CC:DD:EE:FF",
                                                   out=str(tmp_path / "cap")),
        "wifipent deauth": lambda: wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF",
                                                    client="12:22:33:44:55:66"),
        "blepent write": lambda: blepent.prepare("write", "AA:BB:CC:DD:EE:FF", handle="0x1",
                                                 value="ff"),
        "zigbee discover": lambda: zigbee.prepare("discover", channel=15),
        "zigbee inject": lambda: zigbee.prepare("inject", pan=0x1A2B, channel=15),
        "zwave query": lambda: zwave.prepare("query", target="NODE-5", node_id=5),
        "zwave map": lambda: zwave.prepare("map", target="NODE-5"),
        "proxmark sim": lambda: proxmark.prepare("hf_mf_sim", "uid:DEADBEEF", read_uid=rd,
                                                 uid="DEADBEEF"),
        "netpent portscan": lambda: netpent.prepare("portscan", "10.0.0.5"),
        "netpent discover": lambda: netpent.prepare("discover", "10.0.0.0/24"),
        "canbus send": lambda: canbus.prepare_send("can0", 0x7DF, b"\x02\x01\x00"),
        "buslab flash write": lambda: buslab.prepare_flash_write("ch341a_spi", "fw.bin",
                                                                 target="ROUTER-1"),
        "buslab jtag": lambda: buslab.prepare_jtag_write("interface/stlink.cfg", "halt",
                                                         target="ROUTER-1"),
        "passaudit hashcat": lambda: passaudit.prepare("hashcat", "LAB-CAP"),
    }
    failed = {}
    for name, fn in cases.items():
        ok, why, t = fn()
        if not ok or t is None:
            failed[name] = why
    assert not failed, failed


def test_r1_static_every_argv_issuer_declares_allowed_programs():
    """A module that hands engagement.issue an argv must declare ALLOWED_PROGRAMS; and every
    string literal that starts an argv list in it ([\"prog\", ...]) handed to issue is declared."""
    missing = []
    for fn in sorted(os.listdir(SUITE_DIR)):
        if not fn.endswith(".py") or fn in ("engagement.py",):
            continue
        src = open(os.path.join(SUITE_DIR, fn), encoding="utf-8").read()
        if "engagement.issue(" not in src:
            continue
        tree = ast.parse(src)
        uses_argv = any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "issue" and
                        any(k.arg == "argv" for k in n.keywords) for n in ast.walk(tree))
        if not uses_argv:
            continue
        declared = None
        for n in tree.body:
            if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ALLOWED_PROGRAMS"
                                                 for t in n.targets):
                declared = {c.value for c in ast.walk(n.value)
                            if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        if not declared:
            missing.append(fn)
    assert not missing, "argv issuers without ALLOWED_PROGRAMS: %s" % missing


# ---------------------------------------------------------------- R1: DEVTERM SSH never this device
HACK_SSH = "hackrf_trans''fer " + " ".join(H1090)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.8.9.10", "::1", "localhost", "LOCALHOST.",
                                  "::ffff:127.0.0.1", "0.0.0.0", "[::1]"])
def test_r1_ssh_to_loopback_refused_at_issue_poc(host):
    """PoC (RA-CL2b n1_ssh): 127.0.0.1 in scope + hackrf_trans''fer was issued and spawned."""
    import devterm
    assert E.start("job", "ROE-1", ["127.0.0.0/8", "10.0.0.0/24"], OP)[0]
    _arm()
    ok, why, t = devterm.prepare_ssh(host, HACK_SSH)
    assert not ok and t is None and "this device" in why, (host, why)
    assert devterm.authorize_ssh_host(host)[0] is False


def test_r1_ssh_to_an_own_interface_address_refused(monkeypatch):
    import ipaddress
    import devterm
    monkeypatch.setattr(devterm, "own_addresses",
                        lambda: {ipaddress.ip_address("10.0.0.7"), ipaddress.ip_address("::1")})
    assert E.start("job", "ROE-1", ["10.0.0.0/24"], OP)[0]
    ok, why, t = devterm.prepare_ssh("10.0.0.7", "uname -a")
    assert not ok and "this device" in why, why
    monkeypatch.setattr(E, "_resolve", lambda h: ["10.0.0.7"])          # a NAME that is us
    ok, why, t = devterm.prepare_ssh("me.lan", "uname -a")
    assert not ok and "this device" in why, why
    monkeypatch.setattr(E, "_resolve", lambda h: ["10.0.0.9", "10.0.0.7"])   # any address is us
    ok, why, t = devterm.prepare_ssh("both.lan", "uname -a")
    assert not ok and "this device" in why, why


def test_r1_ssh_fails_closed_when_own_addresses_unknown(monkeypatch):
    import devterm

    def boom():
        raise OSError("no getifaddrs")
    monkeypatch.setattr(devterm, "own_addresses", boom)
    assert E.start("job", "ROE-1", ["10.0.0.0/24"], OP)[0]
    ok, why, t = devterm.prepare_ssh("10.0.0.8", "uname -a")
    assert not ok and "fail closed" in why, why


def test_r1_ssh_remote_host_is_pinned_label_only_and_not_rf_locked(monkeypatch):
    import ipaddress
    import devterm
    monkeypatch.setattr(devterm, "own_addresses", lambda: {ipaddress.ip_address("10.0.0.7")})
    monkeypatch.setattr(E, "_resolve", lambda h: ["10.0.0.8"])
    assert E.start("job", "ROE-1", ["10.0.0.0/24"], OP)[0]
    monkeypatch.setenv("SUITE_TX_LOCK", "1")       # owner: remote commands are not this device's RF
    ok, why, t = devterm.prepare_ssh("nas.lan", "aireplay-ng --deauth 0 -a AA:BB:CC:DD:EE:FF wlan0")
    assert ok and "label-only" in why, why
    a = list(t.argv)
    assert a[0] == "ssh" and "HostName=10.0.0.8" in a and "ProxyCommand=none" in a \
        and "ProxyJump=none" in a and a[-2] == "nas.lan"
    # defence in depth: a literal SDR transmitter in the remote command is still refused
    ok, why, t = devterm.prepare_ssh("nas.lan", "hackrf_transfer " + " ".join(H1090))
    assert not ok and "txguard" in why.lower(), why


def test_r1_ssh_ra_poc_never_spawns():
    import devterm
    assert E.start("job", "ROE-1", ["127.0.0.1"], OP)[0]
    _arm()
    calls = []
    ok, why, t = devterm.prepare_ssh("127.0.0.1", HACK_SSH)
    assert not ok and t is None
    assert calls == []


# ---------------------------------------------------------------- R2: scope still discriminates
def test_r2_scope_refusals_hold_when_armed_and_unlocked():
    """The RA-CL2b mutation: with the RF gate open, an out-of-scope target is refused by SCOPE."""
    import blepent
    import proxmark
    import wifipent
    import zigbee
    assert E.start("job", "ROE-1", ["AA:BB:CC:DD:EE:FF", "12:22:33:44:55:66", "pan:0x1A2B@15",
                                    "uid:2006F623AE"], OP)[0]
    _arm()
    for ok, why, t in (
            wifipent.prepare("deauth", "99:99:99:99:99:99", client="12:22:33:44:55:66"),
            blepent.prepare("write", "99:99:99:99:99:99", handle="0x1", value="ff"),
            zigbee.prepare("inject", pan=0x9999, channel=15),
            proxmark.prepare("hf_mf_sim", "uid:DEADBEEF", uid="DEADBEEF",
                             read_uid=lambda: "DEADBEEF")):
        assert not ok and t is None and "not in the engagement scope" in why, why


# ---------------------------------------------------------------- R4: Flipper input is an emitter
@pytest.mark.parametrize("line", ["input send ok short", "input send up press",
                                  "loader open Sub-GHz", "js /ext/apps/Scripts/tx.js",
                                  "subghz tx 0 433920000", "nfc emulate", "rfid emulate H10301 0",
                                  "bt tx_carrier 2402 0"])
def test_r4_flipper_radio_driving_verbs_silenced_by_lock_and_disarm_poc(monkeypatch, line):
    """PoC (RA-CL2b n2_flipper_verbs): `input send ok short` was issued under SUITE_TX_LOCK=1."""
    import flipper
    import rfemit
    assert rfemit.classify(payload=(line + "\r\n").encode(), meta={"class": "flipper"}) \
        == "serial-rf"
    assert E.start("job", "ROE-1", ["usb:0483:5740"], OP)[0]
    ok, why, t = flipper.prepare_command(line, device="usb:0483:5740", kind="flipper")
    assert not ok and "silenced" in why.lower(), (line, why)          # disarmed
    _arm()
    monkeypatch.setenv("SUITE_TX_LOCK", "1")
    ok, why, t = flipper.prepare_command(line, device="usb:0483:5740", kind="flipper")
    assert not ok and "suite_tx_lock" in why.lower(), (line, why)     # hard lock
    monkeypatch.delenv("SUITE_TX_LOCK")
    ok, why, t = flipper.prepare_command(line, device="usb:0483:5740", kind="flipper")
    assert ok, (line, why)                                            # armed, in scope


def test_r4_input_not_in_non_rf_list():
    import rfemit
    assert "input" not in rfemit.FLIPPER_NON_RF
    for v in ("input", "loader", "js", "subghz", "nfc", "rfid", "bt"):
        assert v not in rfemit.FLIPPER_NON_RF


# ---------------------------------------------------------------- R6: argv frequency == authorized
def _hackrf(*extra, f="915000000"):
    return ["hackrf_transfer", "-t", "x.iq", "-f", f, "-s", "2000000", "-x", "0"] + list(extra)


def test_r6_argv_1090_on_a_915_authorization_refused_poc():
    """PoC (RA-CL2b n1_argv_freq): issue_ticket authorized 915 MHz for an argv keying 1090 MHz."""
    _arm()
    ok, why, t, _p = G.issue_ticket("replay", ["hackrf_transfer"] + H1090, 915_000_000,
                                    settings=dict(TXS))
    assert not ok and t is None and "1090000000" in why and "915" in why, why


@pytest.mark.parametrize("argv,frag", [
    (["hackrf_transfer", "-t", "x.iq", "-s", "2000000"], "exactly one -f"),
    (_hackrf("-f", "915000000"), "exactly one -f"),
    (["hackrf_transfer", "-t", "x.iq", "-f1090000000"], "cannot parse"),
    (_hackrf("-a", "1"), "cannot parse"),
    (_hackrf("-R", "-f"), "no value"),
    (_hackrf(f="915e6"), "whole number"),
    (_hackrf(f="٩١٥000000"), "whole number"),
    (["sudo"] + _hackrf(), "cannot verify"),
    (["/usr/bin/hackrf_transfer"] + _hackrf()[1:], "cannot verify"),
    (["sh", "-c", " ".join(_hackrf())], "cannot verify"),
    (["wsjtx"], "cannot verify"),
    ([], "cannot verify"),
])
def test_r6_unparseable_or_ambiguous_tx_argv_refused(argv, frag):
    _arm()
    ok, why, t, _p = G.issue_ticket("replay", argv, 915_000_000, settings=dict(TXS))
    assert not ok and t is None and frag in why, (argv, why)


def test_r6_matching_argv_still_issues_and_builders_agree():
    import replay
    _arm()
    ok, why, t, _p = G.issue_ticket("replay", _hackrf("-R"), 915_000_000, settings=dict(TXS))
    assert ok and t is not None, why
    ok, why, t = replay.prepare_replay("x.iq", 915e6, "2e6", True, settings=dict(TXS))
    assert ok and "915000000" in t.argv, why


# ---------------------------------------------------------------- R5: unbound writes say label-only
@pytest.mark.parametrize("op,params", [("lf_t55_write", {"block": "0", "data": "00148040"}),
                                       ("hf_mf_restore", {}), ("hf_iclass_clone", {})])
def test_r5_unbound_proxmark_writes_are_label_only_in_trail_ticket_and_ui(op, params):
    """Owner decision R5: allowed, marked label-only. On 18770be only the reason said so; the trail
    and the ticket recorded binding 'scoped', so FORGE showed no LABEL-ONLY tag."""
    import proxmark
    from palisade_qt import forge
    assert E.start("job", "ROE-1", ["uid:DEADBEEF"], OP)[0]
    _arm()
    ok, why, t = proxmark.prepare(op, "uid:DEADBEEF", read_uid=lambda: "DEADBEEF", **params)
    assert ok and "label-only" in why, why
    assert E.actions()[-1]["binding"] == "label-only"
    assert t.binding == "label-only"
    assert "LABEL-ONLY" in forge._ticket_text(t)


def test_r5_bound_proxmark_ops_are_not_marked_label_only():
    import proxmark
    assert E.start("job", "ROE-1", ["uid:DEADBEEF"], OP)[0]
    _arm()
    ok, why, t = proxmark.prepare("hf_mf_sim", "uid:DEADBEEF", read_uid=lambda: "DEADBEEF",
                                  uid="DEADBEEF")
    assert ok and t.binding != "label-only" and E.actions()[-1]["binding"] != "label-only"
