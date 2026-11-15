"""RA-CL2c PoC probes. Run from the repo root: python plan/briefs/RA-CL2c-evidence/ra_cl2c_poc.py
Nothing radiates: every spawn goes to a `sleep` stand-in; no SDR, no serial port."""
import ipaddress, json, os, socket, subprocess, sys
ROOT = os.getcwd(); sys.path.insert(0, ROOT)
import engagement as E, executor, txguard as G, devterm, rfemit  # noqa
OP = "KD0ABC"; E._profile_operator = lambda: OP
OUT = {}
H1090 = "-t x.iq -f 1090000000 -x 47"
def fresh(scope):
    os.environ.pop("SUITE_TX_LOCK", None); G.reset_session(); E.reset(); executor.reset()
    ok = E.start("job", "ROE-1", scope, OP); return ok[0], ok[1]
calls = []
def sleeper(argv, **kw):
    calls.append(list(argv))
    return subprocess.Popen(["sleep", "5"], start_new_session=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)

# ---- R1a: ssh option injection through the remote-command token (lock ON, disarmed)

real_own = devterm.own_addresses
res = {}
for name, cmd in {
    "KnownHostsCommand renamed binary": "-oKnownHostsCommand=/home/pi/bin/htx " + H1090,
    "KnownHostsCommand via sh, quoted name": "-oKnownHostsCommand=/bin/sh -c \"hackrf_trans''fer " + H1090 + "\"",
    "-F config (Match exec, pre-connect)": "-F/tmp/ra_cl2c_cfg",
    "PKCS11Provider local .so": "-oPKCS11Provider=/tmp/evil.so",
    "bundled -G proof": "-GoKnownHostsCommand=/usr/bin/true",
}.items():
    print(fresh(["192.0.2.0/24"]))
    os.environ["SUITE_TX_LOCK"] = "1"                   # hard lock ON; txguard never armed
    ok, why, t = devterm.prepare_ssh("192.0.2.10", cmd)
    spawned = None
    if ok:
        calls.clear(); h = executor.start(t, spawner=sleeper); spawned = calls[:1]
        executor.kill_all("poc")
    res[name] = {"issued": ok, "why": why, "argv": list(t.argv) if t else None, "spawned": spawned}
OUT["r1a_ssh_option_injection"] = res

# ---- R1b: self-target forms (after resolution)
try:
    mine = sorted(map(str, real_own())); OUT["own_addresses"] = mine
except OSError as e:
    mine = []; OUT["own_addresses"] = "OSError %s" % e
ll = [a for a in mine if a.startswith("fe80")]
cands = ["127.0.0.1", "127.1", "0x7f000001", "2130706433", "0177.0.0.1", "0", "0.0.0.0", "::",
         "::1", "[::1]", "::ffff:127.0.0.1", "::127.0.0.1", "::ffff:0:127.0.0.1", "64:ff9b::7f00:1",
         "fe80::1%lo0", "fe80::1", "localhost", "LocalHost.", socket.gethostname()]
ifc = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
for line in ifc.splitlines():
    p = line.split()
    if len(p) > 1 and p[0] == "inet6" and p[1].startswith("fe80") and "%" in p[1]:
        cands += [p[1], p[1].split("%")[0]]
    if len(p) > 1 and p[0] in ("inet", "inet6") and not p[1].startswith("fe80"):
        cands.append(p[1])
st = {}
for h in dict.fromkeys(cands):
    a, r = devterm._self_target(h)
    st[h] = {"refused": bool(r), "why": r or ("addrs=%s" % a)}
OUT["r1b_self_target"] = st

# ---- R1c: allowlist argv0 forms through each module's own frame
import types
def issue_from(modname, argv):
    g = {"ALLOWED_PROGRAMS": frozenset((modname,)), "__name__": "m", "E": E}
    exec("def f(a):\n return E.issue('net:x','192.0.2.10',argv=a,kind='ip')", g)
    return g["f"](argv)
fresh(["192.0.2.0/24"]); G.arm(True); G.unlock_session(True)
r1c = {}
for name, argv in {"nmap ok": ["nmap", "192.0.2.10"], "NMAP case": ["NMAP", "x"],
                   "nmap\\x00": ["nmap\x00", "x"], "nmap.exe": ["nmap.exe", "x"],
                   "./nmap": ["./nmap", "x"], "nmap\\u200b": ["nmap​", "x"],
                   "empty": [], "bytes argv0": [b"nmap", "x"]}.items():
    try:
        ok, why, t = issue_from("nmap", argv)
    except Exception as e:
        ok, why = "EXC", repr(e)
    r1c[name] = {"issued": ok, "why": why}
OUT["r1c_allowlist"] = r1c

# ---- R4: Flipper payloads straight to engagement.issue (defence in depth) and via prepare_command
import flipper
fresh(["port:ttyACM0"]); os.environ["SUITE_TX_LOCK"] = "1"
r4 = {}
for line in ["input send ok short", "INPUT send ok short", " input send ok short",
             "led r 0\rinput send ok short", "led r 0\rsubghz tx 0 433920000",
             "storage write /ext/subghz/x.sub", "update install /ext/x.tar"]:
    pc = flipper.prepare_command(line, device="port:ttyACM0", kind="flipper")
    cls = rfemit.classify(payload=(line + "\r\n").encode(), meta={"class": "flipper"})
    r4[repr(line)] = {"prepare_command_ok": pc[0], "why": pc[1], "rfemit": cls}
OUT["r4_flipper"] = r4

# ---- R6: txguard frequency binding
TXS = {"tx_enabled": True, "callsign": OP, "bench_conducted_ack": True}
r6 = {}
fresh([]); G.arm(True); G.unlock_session(True)
for name, argv in {
    "exact": ["hackrf_transfer", "-t", "x.iq", "-f", "915000000", "-s", "2000000", "-x", "20"],
    "1090 vs 915": ["hackrf_transfer", "-t", "x.iq", "-f", "1090000000", "-x", "47"],
    "attached -f1090": ["hackrf_transfer", "-t", "x.iq", "-f1090000000", "-f", "915000000"],
    "two -f": ["hackrf_transfer", "-f", "915000000", "-f", "1090000000"],
    "-t eats -f": ["hackrf_transfer", "-t", "-f", "-f", "915000000"],
    "leading zero": ["hackrf_transfer", "-f", "0915000000"],
    "+sign": ["hackrf_transfer", "-f", "+915000000"],
    "unicode digits": ["hackrf_transfer", "-f", "９１５000000"],
    "915e6": ["hackrf_transfer", "-f", "915e6"],
    "-- then -f": ["hackrf_transfer", "--", "-f", "1090000000"],
    "-a 1 amp": ["hackrf_transfer", "-f", "915000000", "-a", "1"],
    "--freq long": ["hackrf_transfer", "--freq=1090000000", "-f", "915000000"],
    "-x 47 over cap": ["hackrf_transfer", "-t", "x.iq", "-f", "915000000", "-x", "47"],
    "path argv0": ["/usr/bin/hackrf_transfer", "-f", "915000000"],
    "sudo": ["sudo", "hackrf_transfer", "-f", "915000000"],
    "trailing positional": ["hackrf_transfer", "-f", "915000000", "extra"],
    "-c CW": ["hackrf_transfer", "-f", "915000000", "-c", "127"],
}.items():
    try:
        ok, why, t, p = G.issue_ticket("replay", argv, freq_hz=915e6, power_dbm=0, settings=TXS,
                                       sample_rate=2e6, callsign=OP)
    except Exception as e:
        ok, why, p = "EXC", repr(e), None
    r6[name] = {"issued": ok, "why": why, "power": p}
OUT["r6_freq"] = r6

# ---- R5: label-only in trail + ticket
import proxmark
fresh(["uid:2006F623AE"]); 
r5 = {}
for op, kw in (("lf_t55_write", {"block": "1", "data": "00148040"}),
               ("hf_mf_restore", {"file": "dump.bin"}), ("hf_iclass_clone", {"file": "d.bin"})):
    try:
        ok, why, t = proxmark.prepare(op, "uid:2006F623AE", read_uid=lambda: "2006F623AE", **kw)
    except TypeError as e:
        ok, why, t = "EXC", repr(e), None
    r5[op] = {"issued": ok, "why": why, "ticket_binding": getattr(t, "binding", None),
              "trail_binding": (E.actions()[-1].get("binding") if E.actions() else None)}
OUT["r5_label_only"] = r5
json.dump(OUT, open(os.path.join(os.path.dirname(__file__), "ra_cl2c_poc.json"), "w"), indent=1,
          default=str)
print(json.dumps(OUT, indent=1, default=str))
