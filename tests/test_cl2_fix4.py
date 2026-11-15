"""CL2-fix4 — close RA-CL2d D1 (blocking), D2, D3.

D1  DEVTERM "open terminal" handed xterm/lxterminal ONE string `ssh <host>`; xterm falls back to
    `$SHELL -c <string>`, and Python's ipaddress accepts almost anything as an IPv6 scope id, so an
    in-scope `fe80::2%;touch$IFS.m` ran a local program on this device.
D2  `64:ff9b:1::/48` (local-use NAT64) embedding loopback passed the self check.
D3  A scoped HostName= was percent-expanded by OpenSSH (functional, failed closed).
"""
import ipaddress
import os
import shlex
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


def _ll(monkeypatch):
    import devterm
    monkeypatch.setattr(devterm, "own_addresses", lambda: {ipaddress.ip_address("fe80::1")})
    monkeypatch.setattr(E, "pin_host", lambda h: None)
    assert E.start("job", "ROE-1", ["fe80::/64", "192.0.2.0/24"], OP)[0]
    return devterm


# ------------------------------------------------------------------ D1: host token hygiene
D1_HOSTS = ["fe80::2%;touch$IFS.m", "fe80::2%`touch .m`", "fe80::2%$(touch .m)",
            "fe80::2%en0&&touch .m", "fe80::2%en0|id", "fe80::2%en0;id", "fe80::2%'en0'",
            "fe80::2%\"en0\"", "fe80::2%en0>x", "fe80::2%en0<x", "fe80::2%e*0", "fe80::2%(en0)",
            "fe80::2%" + "e" * 16, "192.0.2.10;id", "192.0.2.10$(id)", "192.0.2.10`id`",
            "192.0.2.10|id", "192.0.2.10&", "host.lan;id", "host.lan$HOME", "192.0.2.10\\", "fe80::2%"]


@pytest.mark.parametrize("host", D1_HOSTS)
def test_d1_shell_metacharacters_in_the_host_are_refused_at_issue_poc(monkeypatch, host):
    devterm = _ll(monkeypatch)
    ok, why = devterm.authorize_ssh_host(host)
    assert not ok, (host, why)
    ok, why, t = devterm.prepare_ssh(host, "uname")
    assert not ok and t is None, (host, why)
    assert E.actions() == []                      # nothing authorized, nothing in the trail


@pytest.mark.parametrize("host", ["fe80::2%en0", "fe80::2%eth0.100", "fe80::2%wlan_1", "fe80::2%3",
                                  "192.0.2.10"])
def test_d1_legitimate_hosts_still_authorize(monkeypatch, host):
    devterm = _ll(monkeypatch)
    ok, why = devterm.authorize_ssh_host(host)
    assert ok, (host, why)


def test_d1_terminal_launch_is_never_one_command_string():
    import devterm
    for term in ("xterm", "lxterminal", "kitty", "x-terminal-emulator", "gnome-terminal"):
        a = devterm._terminal_argv(term, "fe80::2%en0")
        assert a[0] == term and a[1] == "-e"
        if term == "lxterminal":                  # parses its -e string: must be shell-quoted
            parts = shlex.split(a[2])
            assert parts == ["ssh", "--", "fe80::2%en0"], parts
        else:
            assert a[2:] == ["ssh", "--", "fe80::2%en0"], a
            assert len(a) > 3


def test_d1_xterm_fallback_shell_would_see_no_metacharacters(monkeypatch):
    """Belt and braces: even if a hostile host reached the terminal launcher, the argv form means
    xterm execs `ssh` directly (argc > 1), never `$SHELL -c`. Simulate xterm's fallback rule on the
    lxterminal string: shlex.split must yield exactly 3 words with the host intact."""
    import devterm
    host = "fe80::2%en0"
    a = devterm._terminal_argv("lxterminal", host)
    assert shlex.split(a[2]) == ["ssh", "--", host]


def test_d1_open_terminal_path_uses_the_argv_builder(monkeypatch):
    """The Tk 'open terminal' button goes through _terminal_argv (static check: no other
    f'ssh %s' launch string remains in devterm)."""
    src = open(os.path.join(SUITE_DIR, "devterm.py")).read()
    assert '"ssh %s" % host] if term' not in src
    assert "_terminal_argv(term, host)" in src


# ------------------------------------------------------------------ D2: local-use NAT64
@pytest.mark.parametrize("lit", ["64:ff9b:1::7f00:1", "64:ff9b:1:ffff::7f00:1", "64:ff9b:1::"])
def test_d2_local_nat64_embedding_loopback_is_this_device(monkeypatch, lit):
    devterm = _ll(monkeypatch)
    ok, why, t = devterm.prepare_ssh(lit, "uname")
    assert not ok and "this device" in why, (lit, why)


def test_d2_local_nat64_with_a_foreign_v4_still_passes(monkeypatch):
    devterm = _ll(monkeypatch)
    E.end()
    assert E.start("job", "ROE-1", ["64:ff9b:1::/48"], OP)[0]
    ok, why, t = devterm.prepare_ssh("64:ff9b:1::c000:20a", "uname")
    assert ok, why


# ------------------------------------------------------------------ D3: HostName percent escape
def test_d3_scoped_hostname_is_percent_escaped(monkeypatch):
    devterm = _ll(monkeypatch)
    ok, why, t = devterm.prepare_ssh("fe80::2%en0", "uname")
    assert ok, why
    a = list(t.argv)
    assert "HostName=fe80::2%%en0" in a, a
    assert "--" in a and a[a.index("--") + 1] == "fe80::2%en0"


@pytest.mark.skipif(shutil.which("ssh") is None, reason="OpenSSH not installed")
def test_d3_openssh_accepts_the_escaped_scoped_hostname(monkeypatch):
    devterm = _ll(monkeypatch)
    ok, why, t = devterm.prepare_ssh("fe80::2%en0", "uname")
    assert ok, why
    argv = list(t.argv)
    i = argv.index("--")
    r = subprocess.run(argv[:i] + ["-G"] + argv[i:], capture_output=True, text=True, timeout=20)
    assert "percent_expand" not in (r.stderr or ""), r.stderr
    assert "hostname fe80::2%en0" in r.stdout.lower(), r.stdout
