#!/usr/bin/env python3
"""RA-CL2b — independent probes against CL2-fix (N1-N6, N8, N9a). Run from the fix/cl2-gates
worktree root with a venv python. Every spawn uses a sleeper stand-in; nothing radiates.
Each probe prints HOLD (the fix held) or BREAK (the fix was bypassed / regressed) + detail."""
import json
import os
import socket
import subprocess
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
import engagement as E  # noqa: E402
import executor as X  # noqa: E402
import gatestate as GS  # noqa: E402
import rfemit  # noqa: E402
import txguard as G  # noqa: E402

OP = "KD0ABC"
E._profile_operator = lambda: OP
TXS = {"tx_enabled": True, "callsign": OP, "region": "US"}
RESULTS = []


def sleeper(calls=None):
    def spawn(argv, **kw):
        if calls is not None:
            calls.append(list(argv))
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    return spawn


def dead(p, t=3.0):
    t0 = time.time()
    while p.poll() is None and time.time() - t0 < t:
        time.sleep(0.02)
    return p.poll() is not None


def reset():
    os.environ.pop("SUITE_TX_LOCK", None)
    os.environ.pop(GS.ENV, None)
    os.environ.pop(GS.NONCE_ENV, None)
    X.kill_all("reset")
    X.reset()
    G.reset_session()
    E.reset()


def probe(tag):
    def deco(fn):
        reset()
        try:
            hold, detail = fn()
        except Exception:
            hold, detail = False, traceback.format_exc().strip().splitlines()[-1]
        RESULTS.append({"probe": tag, "hold": bool(hold), "detail": str(detail)})
        print("%s  %s\n      %s" % ("HOLD " if hold else "BREAK", tag, detail))
        reset()
        return fn
    return deco


def arm():
    G.arm(True)
    G.unlock_session(True)


# ------------------------------------------------------------------ N1: SDR TX via a non-txguard gate
H1090 = "-t x.iq -f 1090000000 -x 47"
N1_VARIANTS = {
    "plain": ["hackrf_transfer"] + H1090.split(),
    "abs path": ["/usr/local/bin/hackrf_transfer"] + H1090.split(),
    "upper": ["HACKRF_TRANSFER"] + H1090.split(),
    "sudo": ["sudo", "-n", "hackrf_transfer"] + H1090.split(),
    "env": ["env", "A=1", "hackrf_transfer"] + H1090.split(),
    "sh -c": ["sh", "-c", "hackrf_transfer " + H1090],
    "busybox sh -c": ["busybox", "sh", "-c", "hackrf_transfer " + H1090],
    "bash -c empty-quote split": ["bash", "-c", "hackrf_trans''fer " + H1090],
    "bash -c glob": ["bash", "-c", "/usr/bin/hackrf_tr?nsfer " + H1090],
    "bash -c ANSI-C": ["bash", "-c", "$'\\x68ackrf_transfer' " + H1090],
    "bash -c var concat": ["bash", "-c", "a=hackrf; ${a}_transfer " + H1090],
    "python -c concat": ["python3", "-c", "import os; os.execvp('hackrf_'+'transfer', "
                         "['hackrf_transfer','-f','1090000000'])"],
    "unicode look-alike (Cyrillic e)": ["hackrf_transfеr"] + H1090.split(),
    "renamed/symlinked binary": ["/home/pi/bin/htx"] + H1090.split(),
    "rpitx family: tune": ["tune", "-f", "1090000000"],
    "rpitx family: sendook": ["sendook", "-f", "433920000", "0101"],
    "UHD example tx_waveforms": ["tx_waveforms", "--freq", "1090e6", "--gain", "60"],
    "URH CLI": ["urh_cli", "-tx", "-d", "HackRF", "-f", "1090e6"],
    "GNU Radio flowgraph": ["python3", "/home/pi/flowgraphs/adsb_tx.py"],
    "SDRangel server": ["sdrangelsrv"],
    "GPS-SDR-SIM pipe": ["sh", "-c", "gps-sdr-sim -e brdc -o - | hackrf_tr\\ansfer -t - -f 1575420000"],
}


@probe("N1 E.issue refuses SDR TX in every argv shape (string-level classifier)")
def n1_issue():
    E.start("j", "ROE", ["BADGE-7"], OP)
    arm()
    minted = {}
    for name, argv in N1_VARIANTS.items():
        ok, why, t = E.issue("x:tx", "BADGE-7", argv=argv, kind="label")
        if ok:
            minted[name] = rfemit.classify(argv=argv)
    return not minted, "engagement minted tickets for: %s" % json.dumps(minted)


@probe("N1 DEVTERM SSH (shipped, free-text cmd) to an in-scope self address runs SDR TX")
def n1_ssh():
    import devterm
    E.start("j", "ROE", ["127.0.0.1", "192.168.1.0/24"], OP)
    arm()
    out = {}
    for cmd in ("hackrf_transfer " + H1090, "hackrf_trans''fer " + H1090):
        ok, why, t = devterm.prepare_ssh("127.0.0.1", cmd)
        spawned = False
        if ok:
            calls = []
            h = X.start(t, spawner=sleeper(calls))
            spawned = True
            h.stop("poc")
        out[cmd.split()[0]] = {"issued": ok, "spawned": spawned, "why": why[:70]}
    return not any(v["issued"] for v in out.values()), json.dumps(out)


@probe("N1 DEVTERM SSH remote deauth ignores the RF hard lock (classified non-emitter)")
def n1_ssh_lock():
    import devterm
    E.start("j", "ROE", ["192.168.1.0/24"], OP)
    os.environ["SUITE_TX_LOCK"] = "1"
    ok, why, t = devterm.prepare_ssh("192.168.1.20", "aireplay-ng --deauth 0 -a AA:BB:CC:DD:EE:FF wlan0")
    return not ok, "issued under SUITE_TX_LOCK=1 + disarmed: %s (%s)" % (ok, why[:60])


@probe("N1 txguard ticket: argv -f differs from the authorized freq_hz")
def n1_argv_freq():
    arm()
    ok, why, t, _p = G.issue_ticket("replay", ["hackrf_transfer"] + H1090.split(), 915_000_000,
                                    settings=dict(TXS))
    return not ok, "issue_ticket authorized freq=915 MHz for an argv keying 1090 MHz: %s" % ok


@probe("N1 executor.issue direct from a non-gate module refused")
def n1_direct():
    try:
        X.issue(argv=["hackrf_transfer", "-f", "1090000000"], recheck=lambda: (True, ""))
        return False, "minted"
    except X.TicketRefused as e:
        return True, str(e)[:80]


# ------------------------------------------------------------------ N2: every emitter class silenced
def _scope():
    E.start("j", "ROE", ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66", "pan:0x1A2B@15",
                         "usb:0483:5740", "usb:10c4:ea60", "uid:DEADBEEF", "ZW-LAB", "BADGE-7"], OP)


def emitters():
    import blepent
    import flipper
    import proxmark
    import wifipent
    import zigbee
    import zwave
    out = {}
    out["wifi deauth"] = lambda: wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF", client="11:22:33:44:55:66")
    out["wifi pmkid"] = lambda: wifipent.prepare("pmkid", "AA:BB:CC:DD:EE:FF")
    out["zigbee inject"] = lambda: zigbee.prepare("inject", pan=0x1A2B, channel=15)
    out["zigbee discover"] = lambda: zigbee.prepare("discover", channel=15)
    out["zwave query"] = lambda: zwave.prepare("query", "ZW-LAB", node_id=2)
    out["zwave map"] = lambda: zwave.prepare("map", "ZW-LAB")
    out["ble write"] = lambda: blepent.prepare("write", "AA:BB:CC:DD:EE:FF", handle="0x1", value="ff")
    out["flipper subghz"] = lambda: flipper.prepare_command("subghz tx 0 433920000", device="usb:0483:5740", kind="flipper")
    out["esp32 line"] = lambda: flipper.prepare_command("attack -t deauth", device="usb:10c4:ea60", kind="esp32")
    out["proxmark sim"] = lambda: proxmark.prepare("hf_mf_sim", "uid:DEADBEEF", read_uid=lambda *a, **k: "DEADBEEF", uid="DEADBEEF")
    out["proxmark clone"] = lambda: proxmark.prepare("lf_hid_clone", "uid:DEADBEEF", read_uid=lambda *a, **k: "DEADBEEF", id="DEADBEEF")
    return out


def _try(fn):
    try:
        return fn()
    except TypeError as e:            # signature drift in a probe: report, don't hide
        return (None, "probe-signature: %s" % e, None)


@probe("N2 issue refused under SUITE_TX_LOCK=1 (armed+unlocked otherwise) for every emitter class")
def n2_issue_lock():
    _scope()
    arm()
    os.environ["SUITE_TX_LOCK"] = "1"
    res = {k: _try(fn) for k, fn in emitters().items()}
    leaked = {k: v[1][:60] for k, v in res.items() if v[0]}
    bad = {k: v[1][:60] for k, v in res.items() if v[0] is None}
    return not leaked and not bad, "leaked=%s probe-errors=%s" % (leaked, bad)


@probe("N2 issue refused while disarmed (kill switch OFF) for every emitter class")
def n2_issue_disarm():
    _scope()
    res = {k: _try(fn) for k, fn in emitters().items()}
    leaked = {k: v[1][:60] for k, v in res.items() if v[0]}
    return not leaked, "leaked=%s" % leaked


@probe("N2 issued armed, then lock/disarm before spawn: refused at spawn for every class")
def n2_spawn():
    out = {}
    for flip in ("lock", "disarm"):
        reset()
        _scope()
        arm()
        res = {k: _try(fn) for k, fn in emitters().items()}
        if flip == "lock":
            os.environ["SUITE_TX_LOCK"] = "1"
        else:
            G.arm(False)
        for k, (ok, why, t) in res.items():
            if not ok or t is None:
                out["%s/%s" % (flip, k)] = "NOT ISSUED armed: %s" % why[:60]
                continue
            try:
                if t.kind == "proc":
                    X.start(t, spawner=sleeper()).stop("poc")
                else:
                    class P:
                        def write(self, d):
                            return len(d)
                    X.write(t, P())
                out["%s/%s" % (flip, k)] = "RAN"
            except X.TicketRefused:
                pass
    return not out, "ran or failed to issue: %s" % out


@probe("N2 disarm kills a running emitter (deauth, zigbee inject, proxmark sim)")
def n2_disarm_kill():
    _scope()
    arm()
    em = emitters()
    hs = {}
    for k in ("wifi deauth", "zigbee inject", "proxmark sim"):
        ok, why, t = em[k]()
        hs[k] = X.start(t, spawner=sleeper())
    G.arm(False)
    st = {k: dead(h.proc, 2.0) for k, h in hs.items()}
    for h in hs.values():
        h.stop("cleanup")
    return all(st.values()), "killed by disarm: %s" % st


@probe("N2 SUITE_TX_LOCK set mid-run kills a running deauth (monitor poll)")
def n2_envlock_kill():
    _scope()
    arm()
    ok, why, t = emitters()["wifi deauth"]()
    h = X.start(t, spawner=sleeper())
    os.environ["SUITE_TX_LOCK"] = "1"
    d = dead(h.proc, X.MONITOR_INTERVAL_S + 2.0)
    h.stop("cleanup")
    return d, "killed within %.1fs: %s" % (X.MONITOR_INTERVAL_S + 2.0, d)


@probe("N2 wired tools are NOT silenced by the RF lock (no over-blocking): nmap, CAN, USB-HID")
def n2_wired():
    import netpent
    import usbhid
    E.start("j", "ROE", ["10.0.0.0/24", "BADGE-7"], OP)
    os.environ["SUITE_TX_LOCK"] = "1"
    a = netpent.prepare("portscan", "10.0.0.5")
    try:
        b = usbhid.prepare("STRING a", "BADGE-7")
    except Exception as e:
        b = (None, "probe: %s" % e, None)
    return bool(a[0]) and bool(b[0]), "nmap issued=%s · usbhid=%s %s" % (a[0], b[0], str(b[1])[:50])


RF_MISSES = {
    "rpitx tune": ["tune", "-f", "434000000"], "rpitx sendook": ["sendook"],
    "rpitx pocsag": ["pocsag"], "rpitx pisstv": ["pisstv"], "rpitx pichirp": ["pichirp"],
    "rpitx spectrumpaint": ["spectrumpaint"], "UHD tx_waveforms": ["tx_waveforms"],
    "UHD tx_bursts": ["tx_bursts"], "URH urh_cli": ["urh_cli", "-tx"],
    "SDRangel sdrangelsrv": ["sdrangelsrv"], "meshtastic CLI": ["meshtastic", "--sendtext", "x"],
    "l2ping (BT)": ["l2ping", "AA:BB:CC:DD:EE:FF"], "rfcomm (BT)": ["rfcomm", "connect", "0"],
    "hciconfig (BT adv)": ["hciconfig", "hci0", "leadv"], "btlejuice": ["btlejuice"],
    "ubertooth-btle": ["ubertooth-btle", "-f"], "jackit (nRF24)": ["jackit"],
    "crazyradio/mousejack": ["mousejack"], "wpa_supplicant": ["wpa_supplicant"],
    "airgeddon": ["airgeddon"], "eaphammer": ["eaphammer"], "wifiphisher": ["wifiphisher"],
    "minimodem --tx (rig audio)": ["minimodem", "--tx"], "direwolf (APRS TX)": ["direwolf"],
    "gps-sdr-sim | hackrf (pipe)": ["sh", "-c", "gps-sdr-sim | hackrf_transfer -t -"],
    "nfc-mfsetuid": ["nfc-mfsetuid"], "mfoc": ["mfoc"], "nfc-relay-picc": ["nfc-relay-picc"],
}


@probe("N2 rfemit misses real RF emitters (default non-RF for unknown programs)")
def n2_misses():
    miss = sorted(k for k, a in RF_MISSES.items() if rfemit.classify(argv=a) is None)
    return not miss, "classified as NOT an emitter: %s" % miss


@probe("N2 Flipper verbs the RF lock lets through that can still key RF")
def n2_flipper_verbs():
    _scope()
    arm()
    os.environ["SUITE_TX_LOCK"] = "1"
    import flipper
    leaked = []
    for line in ("input send ok short", "loader open Sub-GHz",
                 "js /ext/apps/Scripts/subghz_tx.js"):
        ok, why, t = flipper.prepare_command(line, device="usb:0483:5740", kind="flipper")
        if ok:
            leaked.append(line)
    return not leaked, "issued under SUITE_TX_LOCK=1: %s" % leaked


# ------------------------------------------------------------------ N3: gatestate hub identity
def _hubfile(tmp, pid, nonce, start, armed=True):
    p = os.path.join(tmp, "gate-%s.json" % pid)
    GS._write(p, {"pid": pid, "nonce": nonce, "start": start, "t": time.time(), "armed": armed,
                  "unlocked": armed, "engagement": None})
    return p


@probe("N3 recycled pid / crash-stale / other hub / forged nonce all read as STALE")
def n3_identity():
    import tempfile
    tmp = tempfile.mkdtemp(dir=GS.runtime_dir())
    me = os.getpid()
    good = GS.proc_start(me)
    if good is None:
        return False, "proc_start(self) is None on %s — every bound child would be STALE" % sys.platform
    r = {}
    p = _hubfile(tmp, me, "N" * 32, good)
    r["genuine"] = GS.read(p, nonce="N" * 32) is not None
    r["recycled pid (start differs)"] = GS.read(_hubfile(tmp, me, "N" * 32, good + "1"), nonce="N" * 32) is None
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    r["crash-stale (pid dead)"] = GS.read(_hubfile(tmp, child.pid, "N" * 32, good), nonce="N" * 32) is None
    r["other hub (nonce mismatch)"] = GS.read(p, nonce="M" * 32) is None
    r["no nonce in env"] = GS.read(p, nonce="") is None
    par = os.getppid()
    r["forged: parent pid + its real start, wrong nonce"] = GS.read(
        _hubfile(tmp, par, "F" * 32, GS.proc_start(par) or "x"), nonce="N" * 32) is None
    os.chmod(p, 0o666)
    r["group/other-writable"] = GS.read(p, nonce="N" * 32) is None
    r["start differs by pid (distinct)"] = GS.proc_start(par) not in (None, good)
    ok = r.pop("genuine") and all(r.values())
    return ok, json.dumps(r)


@probe("N3 bound child end-to-end: hub armed -> child armed; hub gone -> child STALE/locked")
def n3_child():
    G.arm(True)
    pub = GS.Publisher()
    env = GS.child_env()
    code = ("import sys; sys.path.insert(0, %r); import txguard as G, gatestate as S;"
            "print(G.is_armed(), G.emit_allowed()[0], S.shared_state().get('stale'))" % os.getcwd())
    a = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.strip()
    env2 = dict(env, **{GS.NONCE_ENV: "0" * 32})
    b = subprocess.run([sys.executable, "-c", code], env=env2, capture_output=True, text=True).stdout.strip()
    pub.close()
    c = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.strip()
    return (a == "True True False" and b == "False False True" and c == "False False True"), \
        "genuine=%r forged-nonce=%r hub-closed=%r" % (a, b, c)


@probe("N3 Linux /proc/<pid>/stat parser picks field 22 (starttime), comm with ') ' inside")
def n3_linux_parse():
    import builtins
    import io
    fields = ["S"] + [str(i) for i in range(4, 53)]          # fields 3..52; field 22 -> "22"
    raw = "4242 (evil) S 1 (x) " + " ".join(fields) + "\n"
    real = builtins.open

    def fake(path, *a, **k):
        if str(path) == "/proc/4242/stat":
            return io.StringIO(raw)
        return real(path, *a, **k)
    builtins.open = fake
    try:
        got = GS._linux_start(4242)
    finally:
        builtins.open = real
    return got == "linux:22", "parsed %r from a comm containing ') ' (want 'linux:22')" % got


# ------------------------------------------------------------------ N4: Proxmark identity
@probe("N4 Proxmark sim/clone: out-of-scope identity, ';' chaining, other separators")
def n4():
    import proxmark
    E.start("j", "ROE", ["uid:DEADBEEF"], OP)
    arm()
    rd = lambda *a, **k: "DEADBEEF"   # noqa: E731
    cases = {
        "sim out-of-scope uid": ("hf_mf_sim", {"uid": "CAFEBABE"}),
        "clone out-of-scope id": ("lf_hid_clone", {"id": "CAFEBABE"}),
        "sim ';' chain": ("hf_mf_sim", {"uid": "DEADBEEF; hf mf sim -u CAFEBABE"}),
        "sim ';' no space": ("hf_mf_sim", {"uid": "DEADBEEF;hw tune"}),
        "sim newline": ("hf_mf_sim", {"uid": "DEADBEEF\nhf mf sim -u CAFEBABE"}),
        "sim flag smuggle": ("hf_mf_sim", {"uid": "--4k"}),
        "sim missing uid": ("hf_mf_sim", {}),
        "t55 write data ';'": ("lf_t55_write", {"block": "0", "data": "00;hf mf sim -u CAFEBABE"}),
        "clone id with '.' (allowed by _PARAM_RE)": ("lf_hid_clone", {"id": "DEAD.BEEF"}),
    }
    leaked = {}
    for name, (op, params) in cases.items():
        try:
            ok, why, t = proxmark.prepare(op, "uid:DEADBEEF", read_uid=rd, **params)
        except Exception as e:
            ok, why, t = False, "raised %s" % type(e).__name__, None
        if ok:
            leaked[name] = t.display()
    ok_in, why_in, t_in = proxmark.prepare("hf_mf_sim", "uid:DEADBEEF", read_uid=rd, uid="de:ad:be:ef")
    return not leaked and ok_in, "leaked=%s · in-scope sim ok=%s (%s)" % (
        leaked, ok_in, t_in.display() if t_in else why_in)


@probe("N4 sim scope revoked mid-run (END) kills it; out-of-scope also re-checked at spawn")
def n4_recheck():
    import proxmark
    E.start("j", "ROE", ["uid:DEADBEEF", "uid:CAFEBABE"], OP)
    arm()
    ok, why, t = proxmark.prepare("hf_mf_sim", "uid:DEADBEEF", read_uid=lambda *a, **k: "DEADBEEF",
                                  uid="CAFEBABE")
    if not ok:
        return False, "in-scope sim refused: %s" % why
    E.end()
    E.start("j2", "ROE", ["uid:DEADBEEF"], OP)        # new engagement: CAFEBABE dropped
    try:
        X.start(t, spawner=sleeper()).stop("poc")
        return False, "spawned after the emulated ID left scope"
    except X.TicketRefused as e:
        return True, str(e)[:90]


# ------------------------------------------------------------------ N5 / N6 / N8 / N9a
@probe("N5 hostname pinned: nmap argv carries the checked address only (DNS change is moot)")
def n5():
    import netpent
    E.start("j", "ROE", ["10.0.0.0/24"], OP)
    orig = E._resolve
    E._resolve = lambda h: ["10.0.0.7"]
    try:
        ok, why, t = netpent.prepare("portscan", "nas.lan")
        argv = list(t.argv) if t else None
        E._resolve = lambda h: ["93.184.216.34"]
        try:
            X.start(t, spawner=sleeper()).stop("poc")
            rebind = "SPAWNED"
        except X.TicketRefused:
            rebind = "refused"
    finally:
        E._resolve = orig
    has_name = argv is not None and any("nas.lan" in a for a in argv)
    return ok and not has_name and argv[-1] == "10.0.0.7", "argv=%s · after DNS change: %s" % (argv, rebind)


@probe("N5 multi-address name: one address out of scope refuses the whole scan")
def n5_multi():
    import netpent
    E.start("j", "ROE", ["10.0.0.0/24"], OP)
    orig = E._resolve
    E._resolve = lambda h: ["10.0.0.7", "8.8.8.8"]
    try:
        ok, why, t = netpent.prepare("portscan", "nas.lan")
    finally:
        E._resolve = orig
    return not ok, "issued=%s %s" % (ok, why[:70])


@probe("N6 sample rate as text: '2e6' builds, 'nan'/'inf'/'1e400'/True refused cleanly")
def n6():
    import replay
    arm()
    out = {}
    for sr in ("2e6", "2.5e6", "nan", "inf", "1e400", True, "0x200000"):
        try:
            ok, why, t = replay.prepare_replay("x.iq", 915_000_000, sr, True, settings=dict(TXS))
            out[str(sr)] = (ok, t.argv[t.argv.index("-s") + 1] if t else why[:40])
        except Exception as e:
            out[str(sr)] = ("CRASH", type(e).__name__)
    good = out["2e6"] == (True, "2000000") and out["2.5e6"][0] is True and \
        all(out[k][0] is False for k in ("nan", "inf", "1e400", "True", "0x200000"))
    return good, json.dumps(out)


@probe("N8 clearing tx_enabled in the LIVE settings kills a running replay; bench opt_in too")
def n8():
    import bench
    import replay
    arm()
    s = dict(TXS)
    ok, why, t = replay.prepare_replay("x.iq", 915_000_000, 2_000_000, True, settings=s)
    h = X.start(t, spawner=sleeper())
    s["tx_enabled"] = False
    a = dead(h.proc, X.MONITOR_INTERVAL_S + 2.0)
    h.stop("cleanup")
    reset()
    arm()
    saved = {"tx_enabled": True}
    import tempfile
    iq = tempfile.NamedTemporaryFile(suffix=".iq", delete=False).name
    bs = dict(TXS, iq_file=iq, freq_hz=915_000_000, sample_rate=2_000_000, bench_conducted_ack=True)
    ok2, why2, h2 = bench.start_transmit(bs, spawner=sleeper(), opt_in=lambda: saved["tx_enabled"])
    b = None
    if ok2:
        saved["tx_enabled"] = False
        b = dead(h2.proc, X.MONITOR_INTERVAL_S + 2.0)
        h2.stop("cleanup")
    return a and b is True, "replay killed=%s · bench issued=%s (%s) killed=%s" % (a, ok2, why2[:50], b)


@probe("N9a demo ticket refused on a real port; written to DemoSerial")
def n9a():
    import flipper
    import hwlab
    ok, why, t = flipper.prepare_command("subghz tx 0 433920000", kind="demo")

    class Port:
        w = []

        def write(self, d):
            Port.w.append(d)
            return len(d)
    try:
        X.write(t, Port(), port_name="/dev/ttyACM0")
        real = "WROTE"
    except X.TicketRefused:
        real = "refused"
    ok2, _w, t2 = flipper.prepare_command("help", kind="demo")
    try:
        n = X.write(t2, hwlab.DemoSerial())
    except Exception as e:
        n = "err %s" % e
    return real == "refused" and isinstance(n, int) and n > 0, "real port: %s · DemoSerial wrote %s" % (real, n)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ra_cl2b_poc.json")
    with open(out, "w") as fh:
        json.dump(RESULTS, fh, indent=1)
    X.kill_all("exit")
