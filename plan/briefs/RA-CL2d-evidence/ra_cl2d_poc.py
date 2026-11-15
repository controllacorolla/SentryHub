"""RA-CL2d probes. Run from repo root with the 3.12 venv. Nothing radiates; ssh targets are
unreachable (192.0.2.0/24 TEST-NET / foreign link-local); payloads are `touch` markers in /tmp."""
import json, os, socket, subprocess, sys
ROOT = os.getcwd(); sys.path.insert(0, ROOT)
import engagement as E, executor, txguard as G, devterm, rfemit
OP = "KD0ABC"; E._profile_operator = lambda: OP
OUT = {}
MK = "/tmp/ra_cl2d_x"; os.makedirs(MK, exist_ok=True)
def fresh(scope):
    os.environ.pop("SUITE_TX_LOCK", None); G.reset_session(); E.reset(); executor.reset()
    return E.start("job", "ROE-1", scope, OP)[0]
CFG = MK + "/cfg"
open(CFG, "w").write('Match exec "touch %s/F_marker"\n' % MK)
OPT_KEYS = ("knownhostscommand", "pkcs11provider", "localcommand", "proxycommand", "permitlocalcommand")

# ---- item 1: C1 ssh option parsing (real OpenSSH)
cmds = {
 "-oKnownHostsCommand": "-oKnownHostsCommand=/usr/bin/touch %s/K_marker" % MK,
 "space -F": " -F" + CFG, "tab -F": "\t-F" + CFG, "newline -F": "\n-F" + CFG, "CR -F": "\r-F" + CFG,
 "NBSP -F": " -F" + CFG, "--": "--", "-- -F": "-- -F" + CFG,
 "en dash": "–F" + CFG, "minus sign": "−F" + CFG, "fullwidth": "－F" + CFG,
 "cmd then -F": "uname -F" + CFG, "cmd newline -F": "uname\n-F" + CFG, "cmd CR -oKHC": "uname\r-oKnownHostsCommand=/usr/bin/touch",
 "-GoKHC": "-GoKnownHostsCommand=/usr/bin/true", "empty": "", "spaces": "   ",
}
fresh(["192.0.2.0/24"]); os.environ["SUITE_TX_LOCK"] = "1"
res = {}
for name, c in cmds.items():
    for f in ("F_marker", "K_marker"):
        try: os.remove(MK + "/" + f)
        except OSError: pass
    ok, why, t = devterm.prepare_ssh("192.0.2.10", c)
    row = {"issued": ok, "why": why[:90]}
    if ok:
        argv = list(t.argv); row["argv_tail"] = argv[-3:]
        g = subprocess.run(["ssh", "-G"] + argv[1:], capture_output=True, text=True, timeout=20)
        conf = {l.split(" ", 1)[0]: l.split(" ", 1)[1] for l in g.stdout.splitlines() if " " in l}
        row["ssh_G_rc"] = g.returncode
        row["ssh_G_injected"] = {k: conf[k] for k in OPT_KEYS if k in conf and conf[k] not in ("none", "no")}
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        row["real_rc"] = r.returncode
        row["local_marker"] = any(os.path.exists(MK + "/" + f) for f in ("F_marker", "K_marker"))
    res[name] = row
OUT["c1_cmd"] = res
hosts = ["-x", " -F" + CFG, "a@b.example", "b.example:22", "%h.example", "ssh://b.example",
         "–oFoo", "192.0.2.10%x", "[192.0.2.10]", "192.0.2.10", "fe80::2%;touch$IFS.m",
         "fe80::2%en0|touch", "b.example\n-F" + CFG]
OUT["c1_host"] = {h: devterm._self_target(h)[1] or "PASSES self-target" for h in hosts}

# ---- devterm ssh_open (xterm/lxterminal one-string path, devterm.py:768) — new finding D1
fresh(["fe80::/64"])
d1 = {}
for h in ["fe80::2%;touch$IFS.ra_cl2d_marker", "fe80::2%`touch$IFS.m`", "fe80::2%$(touch$IFS.m)", "fe80::2%en0&&touch$IFS.m"]:
    d1[h] = devterm.authorize_ssh_host(h)
try: os.remove(MK + "/.ra_cl2d_marker")
except OSError: pass
s = "ssh %s" % "fe80::2%;touch$IFS.ra_cl2d_marker"
subprocess.run(["/bin/sh", "-c", s], cwd=MK, capture_output=True, timeout=20, stdin=subprocess.DEVNULL)
d1["xterm fallback sh -c %r -> marker" % s] = os.path.exists(MK + "/.ra_cl2d_marker")
OUT["d1_ssh_open"] = d1

# ---- item 2: C2/C3
mine = sorted(map(str, devterm.own_addresses()))
OUT["own_addresses_count"] = len(mine)
OUT["own_addresses_scoped_forms"] = [a for a in mine if "%" in a]
OUT["own_v6_linklocal_count"] = sum(a.startswith("fe80") for a in mine)
ifc = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
lls, v4s = [], []
for line in ifc.splitlines():
    p = line.split()
    if len(p) > 1 and p[0] == "inet6" and p[1].startswith("fe80"): lls.append(p[1])
    if len(p) > 1 and p[0] == "inet" and not p[1].startswith("127."): v4s.append(p[1])
own4 = v4s[0] if v4s else "10.0.0.1"
x4 = "%02x%02x:%02x%02x" % tuple(int(o) for o in own4.split("."))
cands = {}
for ll in lls:
    cands["own scoped LL"] = ll; cands["own LL unscoped"] = ll.split("%")[0]
    cands["own LL wrong scope"] = ll.split("%")[0] + "%lo0"
    cands["own LL [scoped]"] = "[" + ll + "]"
cands.update({
 "::127.0.0.1": "::127.0.0.1", "::7f00:1": "::7f00:1", "::own4": "::" + own4, "::8.8.8.8 (compat)": "::8.8.8.8",
 "::ffff:0:127.0.0.1": "::ffff:0:127.0.0.1", "::ffff:0:own4": "::ffff:0:" + own4, "::ffff:0:8.8.8.8": "::ffff:0:8.8.8.8",
 "64:ff9b::127.0.0.1": "64:ff9b::127.0.0.1", "64:ff9b::own4": "64:ff9b::" + x4, "64:ff9b::0.0.0.0": "64:ff9b::",
 "::ffff:127.0.0.1": "::ffff:127.0.0.1", "::ffff:own4": "::ffff:" + own4,
 "64:ff9b::8.8.8.8 (real NAT64)": "64:ff9b::808:808", "64:ff9b:1::127.0.0.1 (local-use NAT64)": "64:ff9b:1::7f00:1",
 "fe80::2 foreign": "fe80::2%en0", "localhost": "localhost", "hostname": socket.gethostname(),
})
OUT["c2c3"] = {k: ("REFUSED" if devterm._self_target(v)[1] else "passes") for k, v in cands.items()}

# ---- item 3: C4 Flipper payloads
fl = {}
for name, p in {
 "plain read 'device_info'": b"device_info\r\n", "plain 'led r 0'": b"led r 0\r", "storage list": b"storage list /ext\r\n",
 "subghz tx": b"subghz tx 0 433920000 0 0\r\n",
 "CR chain": b"led r 0\rsubghz tx 0 433920000\r", "LF chain": b"led r 0\nsubghz tx\r\n", "NUL": b"led r 0\x00subghz tx",
 "TAB": b"led\tr 0", "ESC": b"\x1bsubghz", "DEL": b"led r 0\x7f", "leading CR": b"\rsubghz tx",
 "leading LF then read": b"\ndevice_info", "trailing \\r\\n\\r\\n": b"device_info\r\n\r\n",
 "trailing CR then verb": b"device_info\r\r\nsubghz tx", "Ctrl-C prefix": b"\x03subghz tx",
 "NEL U+0085": "led r 0\u0085subghz tx".encode(), "LS U+2028": "led r 0 subghz tx".encode(),
 "C1 0x85 raw": b"led r 0\x85subghz tx", "0x9b CSI raw": b"led\x9br 0",
}.items():
    fl[name] = rfemit.classify(payload=p, meta={"class": "flipper"})
OUT["c4"] = fl
json.dump(OUT, open(os.path.join(os.path.dirname(__file__), "ra_cl2d_poc.json"), "w"), indent=1, default=str)
print(json.dumps(OUT, indent=1, default=str))
