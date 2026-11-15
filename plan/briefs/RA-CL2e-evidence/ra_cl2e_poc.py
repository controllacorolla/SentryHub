"""RA-CL2e probes. Run from repo root with the 3.12 venv:  python ra_cl2e_poc.py [GSPLIT]
GSPLIT = a binary that prints g_shell_parse_argv(argv[1]) one token per line (real GLib).
Nothing radiates; no ssh is connected (ssh -G only); payloads are `touch` markers in /tmp."""
import json, os, re, subprocess, sys
ROOT = os.getcwd(); sys.path.insert(0, ROOT)
import engagement as E, executor, txguard as G, devterm
OP = "KD0ABC"; E._profile_operator = lambda: OP
GSPLIT = sys.argv[1] if len(sys.argv) > 1 else None
MK = "/tmp/ra_cl2e_x"; os.makedirs(MK, exist_ok=True)
OUT = {}
SAFE = re.compile(r"^\[?[A-Za-z0-9.:%_-]+\]?$")


def fresh(scope):
    os.environ.pop("SUITE_TX_LOCK", None); G.reset_session(); E.reset(); executor.reset()
    return E.start("job", "ROE-1", scope, OP)[0]


def gsplit(s):
    return subprocess.run([GSPLIT, s], capture_output=True, text=True).stdout.splitlines()


# ---- item 1: D1 — every character in every host position, scope fe80::/64 + TEST-NET
fresh(["fe80::/64", "192.0.2.0/24"])
chars = [chr(i) for i in range(0, 0x80)] + ["\u0085", " ", " ", "−", "＄", "；",
                                             "٠", "²", "ı", "K", "０"]
templates = {"scope": "fe80::2%en{c}0", "scope-head": "fe80::2%{c}", "scope-tail": "fe80::2%en0{c}",
             "bracket-scope": "[fe80::2%en0{c}]", "v4-tail": "192.0.2.10{c}", "v4-head": "{c}192.0.2.10",
             "hostname": "h{c}x.invalid", "after-bracket": "[fe80::2]{c}"}
allowed, bad_allowed = [], []
for tname, t in templates.items():
    for c in chars:
        h = t.format(c=c)
        ok, why = devterm.authorize_ssh_host(h)
        okp = devterm.prepare_ssh(h, "uname")[0]
        if ok or okp:
            allowed.append((tname, h))
            if not SAFE.match(h) or any(ord(x) > 0x7e or ord(x) < 0x21 for x in h):
                bad_allowed.append((tname, repr(h), ok, okp))
OUT["d1_fuzz_hosts_tried"] = len(templates) * len(chars)
OUT["d1_fuzz_allowed"] = [repr(h) for _, h in allowed]
OUT["d1_fuzz_allowed_with_non_whitelist_char"] = bad_allowed
named = ["fe80::2%;touch$IFS.m", "fe80::2%`touch$IFS.m`", "fe80::2%$(touch$IFS.m)", "fe80::2%en0&&touch$IFS.m",
         "fe80::2%en0|x", "fe80::2%en0>x", "fe80::2%en0<x", "fe80::2%'x'", 'fe80::2%"x"', "fe80::2%en0\nid",
         "fe80::2%en0\n", "fe80::2%\\x", "fe80::2%*", "fe80::2%?", "fe80::2%~", "fe80::2%{a,b}",
         "fe80::2%en0#", "fe80::2%!x", "fe80::2%=x", "fe80::2%en0%x", "fe80::2%", "fe80::2%%en0",
         "fe80::2%abcdefghijklmno", "fe80::2%abcdefghijklmnop", "fe80::2%-oProxyCommand", "fe80::2%-F",
         "[[fe80::2]]", "[fe80::2%en0]", "fe80::2%en0", "fe80::2%7", "fe80::2%en0.5", "192.0.2.10"]
OUT["d1_named"] = {h: (devterm.authorize_ssh_host(h)[0], devterm.prepare_ssh(h, "uname")[0]) for h in named}

# terminal argv for every allowed host: xterm argc>1 after -e; lxterminal survives real g_shell_parse_argv;
# and (belt and braces) even `sh -c` of the joined string makes no marker / changes no token.
term_rows = {"xterm_argc_after_e_min": None, "xterm_bad": [], "lx_bad": [], "sh_bad": []}
argcs = []
for _, h in allowed + [(None, "[fe80::2%en0]"), (None, "fe80::2%-oProxyCommand")]:
    for term in ("xterm", "kitty", "x-terminal-emulator", "konsole", "alacritty", "gnome-terminal", "xfce4-terminal"):
        a = devterm._terminal_argv(term, h)
        rest = a[a.index("-e") + 1:]
        argcs.append(len(rest))
        if rest != ["ssh", "--", h]:
            term_rows["xterm_bad"].append((term, h, a))
    lx = devterm._terminal_argv("lxterminal", h)
    if len(lx) != 3 or (GSPLIT and gsplit(lx[2]) != ["ssh", "--", h]):
        term_rows["lx_bad"].append((h, lx, gsplit(lx[2]) if GSPLIT else None))
    for f in os.listdir(MK):
        os.remove(os.path.join(MK, f))
    r = subprocess.run(["/bin/sh", "-c", 'for a in ssh %s; do printf "%%s\\n" "$a"; done' % " ".join(["--", h])],
                       cwd=MK, capture_output=True, text=True, timeout=10)
    if r.stdout.splitlines()[1:] != ["--", h] or os.listdir(MK):
        term_rows["sh_bad"].append((h, r.stdout, os.listdir(MK)))
term_rows["xterm_argc_after_e_min"] = min(argcs)
OUT["d1_terminal"] = term_rows
OUT["d1_lx_example"] = {h: (devterm._terminal_argv("lxterminal", h)[2], gsplit(devterm._terminal_argv("lxterminal", h)[2]) if GSPLIT else None)
                        for h in ("[fe80::2%en0]", "fe80::2%en0", "192.0.2.10")}

# ---- item 2: D2 local-use NAT64 + D3 ssh -G on a scoped HostName
ifc = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
v4s = [l.split()[1] for l in ifc.splitlines() if l.split()[:1] == ["inet"] and not l.split()[1].startswith("127.")]
own4 = v4s[0] if v4s else "10.0.0.1"
x4 = "%02x%02x:%02x%02x" % tuple(int(o) for o in own4.split("."))
fresh(["64:ff9b:1::/48", "64:ff9b::/96"])
d2 = {"64:ff9b:1::127.0.0.1": "64:ff9b:1::7f00:1", "64:ff9b:1::0.0.0.0": "64:ff9b:1::",
      "64:ff9b:1::own4": "64:ff9b:1::" + x4, "64:ff9b:1:ffff:ffff::127.0.0.1": "64:ff9b:1:ffff:ffff::7f00:1",
      "64:ff9b:1::8.8.8.8 (foreign)": "64:ff9b:1::808:808", "64:ff9b:1::192.0.2.10 (foreign)": "64:ff9b:1::c000:20a",
      "[64:ff9b:1::7f00:1]": "[64:ff9b:1::7f00:1]", "64:ff9b:1::7f00:1%en0": "64:ff9b:1::7f00:1%en0",
      "64:ff9b:1:7f00:0:100:: (RFC6052 /48 layout of 127.0.0.1)": "64:ff9b:1:7f00:0:100::",
      "64:ff9b::127.0.0.1 (regression)": "64:ff9b::7f00:1", "64:ff9b::8.8.8.8 (regression)": "64:ff9b::808:808"}
OUT["d2"] = {k: ("issued" if devterm.prepare_ssh(v, "uname")[0] else "REFUSED")
             + " / open:" + ("allowed" if devterm.authorize_ssh_host(v)[0] else "REFUSED") for k, v in d2.items()}
fresh(["fe80::/64"])
d3 = {}
for h in ("fe80::2%en0", "[fe80::2%en0]", "fe80::2%lo0", "fe80::2%7"):
    ok, why, t = devterm.prepare_ssh(h, "uname")
    row = {"issued": ok}
    if ok:
        argv = list(t.argv); row["hostname_opt"] = [x for x in argv if x.startswith("HostName=")]
        g = subprocess.run(["ssh", "-G"] + argv[1:], capture_output=True, text=True, timeout=20)
        row["ssh_G_rc"] = g.returncode
        row["ssh_G_hostname"] = [l for l in g.stdout.splitlines() if l.startswith("hostname ")]
        row["ssh_G_err"] = g.stderr.strip()[:120]
    d3[h] = row
OUT["d3"] = d3
OUT["ssh_version"] = subprocess.run(["ssh", "-V"], capture_output=True, text=True).stderr.strip()
json.dump(OUT, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ra_cl2e_poc.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in OUT.items() if k != "d1_fuzz_allowed"}, indent=1, default=str))
