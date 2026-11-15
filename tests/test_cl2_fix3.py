"""CL2-fix3 — close RA-CL2c C1 (blocking), C2, C3, C4.

C1  OpenSSH re-parses tokens after the destination as options unless `--` precedes it. The RA PoC
    issued and spawned `ssh … 192.0.2.10 -oKnownHostsCommand=<anything>` under the hard lock, and
    `-F<file>` with `Match exec` ran a program on THIS device before any connection.
C2  A scoped own link-local (fe80::x%en0) was compared unscoped and passed the self check.
C3  IPv4 embedded in ::/96, ::ffff:0:0:0/96, 64:ff9b::/96 was not treated as loopback / own.
C4  rfemit classified a multi-line Flipper payload by its first verb only.

Nothing here spawns a real ssh: the argv is inspected, and `ssh -G` is used only where OpenSSH is
installed, to prove the option is no longer parsed.
"""
import ipaddress
import os
import shutil
import subprocess
import sys

import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

import engagement as E  # noqa: E402
import txguard as G  # noqa: E402

OP = "KD0ABC"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    monkeypatch.delenv("PALISADE_GATE_STATE", raising=False)
    monkeypatch.setattr(E, "_profile_operator", lambda: OP, raising=False)
    G.reset_session()
    E.reset()
    import executor
    executor.reset()
    yield
    executor.kill_all("test teardown")
    executor.reset()
    G.reset_session()
    E.reset()


def _remote(monkeypatch, own=("10.0.0.7",), resolve=("192.0.2.10",)):
    import devterm
    monkeypatch.setattr(devterm, "own_addresses",
                        lambda: {ipaddress.ip_address(a) for a in own})
    monkeypatch.setattr(E, "_resolve", lambda h: list(resolve))
    assert E.start("job", "ROE-1", ["192.0.2.0/24", "10.0.0.0/24"], OP)[0]
    return devterm


# ------------------------------------------------------------------ C1: ssh option injection
C1_POCS = [
    "-oKnownHostsCommand=/bin/sh -c 'hackrf_trans''fer -f 1090000000 -x 47 -t /tmp/x'",
    "-F/tmp/cfg",
    "-oPKCS11Provider=/tmp/evil.so",
    "-GoKnownHostsCommand=touch /tmp/marker",
    "  -oProxyCommand=sh",
    "-",
]


@pytest.mark.parametrize("cmd", C1_POCS)
def test_c1_remote_command_starting_with_dash_is_refused_poc(monkeypatch, cmd):
    devterm = _remote(monkeypatch)
    monkeypatch.setenv("SUITE_TX_LOCK", "1")
    ok, why, t = devterm.prepare_ssh("192.0.2.10", cmd)
    assert not ok and t is None and "'-'" in why, (cmd, why)


def test_c1_empty_remote_command_is_refused(monkeypatch):
    devterm = _remote(monkeypatch)
    ok, why, t = devterm.prepare_ssh("192.0.2.10", "   ")
    assert not ok and t is None


def test_c1_argv_ends_option_parsing_before_the_host(monkeypatch):
    """`--` sits immediately before the destination, so neither the host token nor the command can
    ever be parsed as an ssh option, whatever they contain."""
    devterm = _remote(monkeypatch)
    ok, why, t = devterm.prepare_ssh("192.0.2.10", "uname -a")
    assert ok, why
    a = list(t.argv)
    assert a[0] == "ssh" and a[-3] == "--" and a[-2] == "192.0.2.10" and a[-1] == "uname -a"
    # every option comes before the `--`, none after it
    i = a.index("--")
    assert all(not tok.startswith("-") for tok in a[i + 1:])
    assert "HostName=192.0.2.10" in a[:i] and "ProxyJump=none" in a[:i]


def test_c1_a_dash_token_after_the_host_is_impossible_by_construction(monkeypatch):
    """Even a hostname-shaped token that starts with '-' never reaches ssh: _self_target refuses it
    before issue, and the command path refuses a leading '-'."""
    devterm = _remote(monkeypatch)
    ok, why, t = devterm.prepare_ssh("-oProxyCommand=sh", "uname")
    assert not ok and t is None
    ok, why, t = devterm.prepare_ssh("192.0.2.10", "-oProxyCommand=sh")
    assert not ok and t is None


@pytest.mark.skipif(shutil.which("ssh") is None, reason="OpenSSH not installed")
def test_c1_openssh_does_not_parse_the_command_as_an_option(monkeypatch, tmp_path):
    """Ground truth against the real OpenSSH parser: with `--` before the destination, `ssh -G`
    (print config, never connect) shows no knownhostscommand for the injected token. A command
    starting with '-' is already refused at issue, so the argv under test is the `--` shape with a
    hostile-looking but legal command; the KnownHostsCommand token is appended by the test to
    model what an operator could type, and it must land as the remote command, not an option."""
    devterm = _remote(monkeypatch)
    ok, why, t = devterm.prepare_ssh("192.0.2.10", "uname -a")
    assert ok, why
    argv = list(t.argv)
    i = argv.index("--")
    probe = argv[:i] + ["-G"] + argv[i:] + ["-oKnownHostsCommand=touch %s" % (tmp_path / "m")]
    out = subprocess.run(probe, capture_output=True, text=True, timeout=20).stdout.lower()
    assert "knownhostscommand" not in out or "knownhostscommand none" in out, out
    assert not (tmp_path / "m").exists()


# ------------------------------------------------------------------ C2: scoped own link-local
def test_c2_scoped_own_link_local_is_this_device(monkeypatch):
    devterm = _remote(monkeypatch, own=("fe80::1234:5678:9abc:def0",),
                      resolve=("fe80::1234:5678:9abc:def0%en0",))
    ok, why, t = devterm.prepare_ssh("mine.local", "uname")
    assert not ok and "this device" in why, why


def test_c2_scoped_literal_is_this_device(monkeypatch):
    devterm = _remote(monkeypatch, own=("fe80::1",))
    monkeypatch.setattr(E, "pin_host", lambda h: None)
    ok, why, t = devterm.prepare_ssh("[fe80::1%en0]", "uname")
    assert not ok and "this device" in why, why


# ------------------------------------------------------------------ C3: embedded IPv4
@pytest.mark.parametrize("lit", ["::127.0.0.1", "::ffff:0:127.0.0.1", "64:ff9b::7f00:1",
                                 "::ffff:0:0a00:0007", "64:ff9b::a00:7", "::", "::0a00:0007"])
def test_c3_embedded_loopback_or_own_v4_is_this_device(monkeypatch, lit):
    devterm = _remote(monkeypatch, own=("10.0.0.7",))
    monkeypatch.setattr(E, "pin_host", lambda h: None)
    ok, why, t = devterm.prepare_ssh(lit, "uname")
    assert not ok and "this device" in why, (lit, why)


def test_c3_a_real_nat64_remote_still_passes(monkeypatch):
    """64:ff9b:: embedding a foreign IPv4 is a legitimate NAT64 remote."""
    devterm = _remote(monkeypatch, own=("10.0.0.7",), resolve=("64:ff9b::c000:20a",))
    E.end()
    assert E.start("job", "ROE-1", ["64:ff9b::/96"], OP)[0]
    ok, why, t = devterm.prepare_ssh("nat64.lan", "uname")
    assert ok, why


# ------------------------------------------------------------------ C4: multi-line Flipper payload
@pytest.mark.parametrize("payload", [b"led r 0\rsubghz tx 433920000\r\n", b"help\nsubghz tx 1\r\n",
                                     b"date\x00subghz tx\r\n", b"uptime\x7fsubghz tx\r\n"])
def test_c4_control_characters_in_a_flipper_payload_fail_closed(payload):
    import rfemit
    assert rfemit.classify(payload=payload, meta={"class": "flipper"}) == "serial-rf"


def test_c4_plain_read_line_is_still_non_rf():
    import rfemit
    assert rfemit.classify(payload=b"device_info\r\n", meta={"class": "flipper"}) is None
    assert rfemit.classify(payload=b"led r 0\r\n", meta={"class": "flipper"}) is None
