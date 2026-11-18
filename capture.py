#!/usr/bin/env python3
"""capture.py — passive packet capture (tcpdump / tshark).

Capture is RECEIVE-ONLY: it reads frames the interface already sees and writes a pcap or a readable
line view. It radiates nothing and touches no target, so it is UNGATED by design (CLAUDE.md: passive
tools are ungated) — but every capture is still LOGGED to the evidence/session chain (start, the
pcap path, stop), so a report can cite where the evidence came from.

This module only BUILDS and validates the argv; the process is spawned, tracked and stopped by the
passive runner in the UI (palisade_qt/recon_tools.py), the same way the live Wi-Fi/BLE scans run —
NOT through the engagement executor, because there is no gate to re-check. The capture tools need
root or cap_net_raw; the installer grants the capability (owner decision 2026-11-18), else the tool
exits with a clear permission error the pane shows.

Safety of the built argv:
  * the program is tcpdump or tshark only (bare name, on PATH);
  * the interface is a plain token (never an option);
  * the BPF filter is split into tokens and any token that looks like an option is refused, so a
    capture can never grow a tcpdump `-z <cmd>` (postrotate command) or a tshark `-X`/`-z` out of
    the operator's filter box. We also never build those flags ourselves. A BPF expression itself
    is parsed by libpcap, not a shell, so `port 445 and host 10.0.0.1` is data, not code.
"""
import os
import re
import shutil

_IFACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
# a BPF primitive token: words, numbers, dotted/sliced addresses, the operators libpcap allows.
_BPF_TOK = re.compile(r"^[A-Za-z0-9:./_\[\]()!<>=&|-]+$")


def _iface_ok(iface):
    return bool(_IFACE.match(str(iface or "").strip()))


def _filter_tokens(bpf):
    """(tokens, error): split a BPF filter into argv tokens, or refuse. A leading '-' on any token
    is refused (option injection), so the filter box can never introduce tcpdump -z / tshark -X."""
    s = str(bpf or "").strip()
    if not s:
        return [], None
    toks = s.split()
    for t in toks:
        if t.startswith("-"):
            return None, "a filter term may not start with '-' (%r)" % t
        if not _BPF_TOK.match(t):
            return None, "unexpected character in filter term %r" % t
    return toks, None


def capture_program(use_tshark=False):
    """The bare program name to run, or None if it is not installed."""
    name = "tshark" if use_tshark else "tcpdump"
    return name if shutil.which(name) else None


def pcap_dir():
    import suite
    return os.path.join(suite.DATA, "captures")


def pcap_argv(iface, out, bpf=None):
    """(argv, error) for a tcpdump capture that WRITES a pcap to `out` (under the captures dir).
    -n no name lookups, -U pack each packet to the file at once (a clean file if stopped), -s0 full
    frames. The BPF filter is appended as validated trailing tokens."""
    if not _iface_ok(iface):
        return None, "interface %r is not a plain interface name" % (iface,)
    o = str(out or "")
    cap = os.path.realpath(pcap_dir())
    if not o or o.startswith("-") or os.path.dirname(os.path.realpath(o)) != cap:
        return None, "output path %r is not a file in the captures folder" % (out,)
    toks, err = _filter_tokens(bpf)
    if err:
        return None, err
    return ["tcpdump", "-i", str(iface).strip(), "-n", "-U", "-s", "0", "-w", o] + toks, None


def live_argv(iface, bpf=None):
    """(argv, error) for a readable live view (tshark, line-buffered, no file). -l line-buffered,
    -n no name lookups. The BPF filter goes through tshark's -f capture filter (one libpcap
    string), so no trailing option can slip in."""
    if not _iface_ok(iface):
        return None, "interface %r is not a plain interface name" % (iface,)
    toks, err = _filter_tokens(bpf)
    if err:
        return None, err
    argv = ["tshark", "-i", str(iface).strip(), "-l", "-n"]
    if toks:
        argv += ["-f", " ".join(toks)]
    return argv, None
