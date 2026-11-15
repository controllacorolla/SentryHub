#!/usr/bin/env python3
"""RA-CL2 — auditor's independent PoC set, re-derived from the PDF (§4 gates, §15.1).

Run from the fix/cl2-gates worktree:  QT_QPA_PLATFORM=offscreen python ra_cl2_poc.py
Each probe prints  PASS  (gate held / finding no longer reproduces) or  FAIL  (PoC still
reproduces, or a new hole) with detail. Probes tagged [NEW] are adversarial checks beyond the 93.
Nothing here emits: spawners are harmless `python -c` stand-ins, ports/HID are recording fakes,
DNS is an injected resolver.
"""
import json
import os
import subprocess
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.getcwd()
sys.path.insert(0, REPO)

import engagement as E  # noqa: E402
import txguard as G  # noqa: E402
import executor as X  # noqa: E402

OP = "KD0ABC"
TXS = {"tx_enabled": True, "callsign": OP, "bench_conducted_ack": True}
RESULTS = []


def reset():
    os.environ.pop("SUITE_TX_LOCK", None)
    os.environ.pop("PALISADE_GATE_STATE", None)
    E._profile_operator = lambda: OP
    try:
        X.kill_all("poc reset")
    except Exception:
        pass
    X.reset()
    G.reset_session()
    E.reset()


def probe(tag):
    def deco(fn):
        reset()
        try:
            ok, detail = fn()
        except Exception:
            ok, detail = False, "EXCEPTION:\n" + traceback.format_exc()
        RESULTS.append((tag, ok, detail))
        print("%s  %-60s %s" % ("PASS" if ok else "FAIL", tag, detail if len(str(detail)) < 160 else str(detail)[:157] + "..."))
        return fn
    return deco


def sleeper(calls):
    def spawn(argv, **kw):
        calls.append(list(argv))
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    return spawn


def exiter(calls, code):
    def spawn(argv, **kw):
        calls.append(list(argv))
        return subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(%d)" % code],
                                start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    return spawn


def wait_dead(proc, t=5.0):
    t0 = time.time()
    while proc.poll() is None and time.time() - t0 < t:
        time.sleep(0.02)
    return proc.poll() is not None


def arm():
    G.arm(True)
    G.unlock_session(True)


def qapp():
    from PySide6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def pump(ms=80):
    app = qapp()
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.005)


class FakePort:
    def __init__(self):
        self.writes = []

    def write(self, d):
        self.writes.append(bytes(d))
        return len(d)

    def read_lines(self):
        return []

    def close(self):
        pass


# ============================================================ G1
@probe("G1 PoC: disarmed + default saved settings, checkbox alone must not enable TX")
def g1_checkbox():
    qapp()
    import bench
    from palisade_qt.bench_app import BenchApp
    p = BenchApp(demo=False, mode="dark")
    try:
        p._saved = lambda: dict(bench.DEFAULTS)
        p.ack.setChecked(True)
        p._refresh_gate()
        enabled = p.tx_btn.isEnabled()
        s = p._settings()
        s["iq_file"] = __file__
        calls = []
        res = bench.transmit(s, spawner=sleeper(calls))
        return (not enabled and s["tx_enabled"] is False and res[0] is False and calls == []), \
            "btn_enabled=%s tx_enabled=%r transmit=%s calls=%d" % (enabled, s["tx_enabled"], res[0], len(calls))
    finally:
        p.stop()


@probe("G1: 121.5 MHz preset removed")
def g1_preset():
    from palisade_qt import bench_app
    return all(f != 121_500_000 and "121.5" not in lbl for lbl, f in bench_app.BANDS), str(bench_app.BANDS)


@probe("G1/owner-1: conducted bench on 121.5 / 1090 / GPS denied even armed+unlocked+ack")
def g1_protected():
    arm()
    out = {}
    for f in (121_500_000, 1_090_000_000, 1_575_420_000, 978_000_000):
        out[f] = G.authorize("bench", f, settings=TXS)[0]
    ok915 = G.authorize("bench", 915_000_000, settings=TXS)[0]
    return (not any(out.values())) and ok915, "protected=%s 915=%s" % (out, ok915)


@probe("G1: bench reports the runner's real exit code, not a synthetic success")
def g1_exit():
    import bench
    bench.TX_LOG = "/dev/null"
    arm()
    calls = []
    s = dict(TXS, freq_hz=915_000_000, iq_file=__file__)
    bad = bench.transmit(s, spawner=exiter(calls, 7))
    good = bench.transmit(s, spawner=exiter(calls, 0))
    return bad[0] is False and bad[2] == 7 and good[0] is True and good[2] == 0 and len(calls) == 2, \
        "bad=%s good=%s" % (bad[:3], good[:3])


# ============================================================ G2 / G3
EMIT = ["subghz chat 433920000", "ir universal tv power", "loader open Sub-GHz", "input send ok short",
        "js /ext/apps/x.js", "rfid raw_emulate /ext/r", "storage remove /ext/x",
        "device_info\rsubghz tx 0 433920000", "device_info\nsubghz tx_from_file /ext/g.sub",
        "subghz tx 1 433920000", "badusb run /ext/x.txt", "gpio set PA7 1", "nfc emulate",
        "ibutton emulate", "ir tx /ext/x.ir", "storage write /ext/x", "update install",
        "power off", "power reboot", "bt hci_set_name x", "subghz rx 433920000 0 extra",
        "device_info subghz tx 0 433920000", "device_info\ttx", ""]


@probe("G3 PoC: every audit emit example classifies as emit (allowlist, not denylist)")
def g3_classify():
    import flipper
    bad = [c for c in EMIT if flipper.classify_command(c) != "emit"]
    reads = [c for c in ("device_info", "storage list /ext", "power info", "help", "subghz rx 433920000 0", "nfc detect")
             if flipper.classify_command(c) != "read"]
    return not bad and not reads, "misclassified_emit=%r misclassified_read=%r" % (bad, reads)


@probe("G3: emit commands refused without engagement; CR/LF refused even with one")
def g3_gate():
    import flipper
    refused = all(flipper.prepare_command(c, device="usb:0483:5740", kind="flipper")[0] is False for c in EMIT)
    E.start("j", "ROE", ["usb:0483:5740"], OP)
    crlf = all(flipper.prepare_command(c, device="usb:0483:5740", kind="flipper")[0] is False
               for c in ("device_info\rsubghz tx 0 1", "a\nb", "x\x1b[A"))
    emit_ok = flipper.prepare_command("subghz tx 0 433920000", device="usb:0483:5740", kind="flipper")
    return refused and crlf and emit_ok[0] and emit_ok[2].binding == "label-only", \
        "refused=%s crlf_refused=%s emit_with_eng=%s/%s" % (refused, crlf, emit_ok[0], emit_ok[2] and emit_ok[2].binding)


@probe("G2 PoC: Qt SERIAL tab writes nothing ungated; unknown device read-only until engagement")
def g2_serial():
    qapp()
    import flipper
    from palisade_qt import forge
    out = {}
    for cls, dev in (("flipper", "usb:0483:5740"), ("unknown", "port:ttyS0"), ("esp32", "usb:10c4:ea60")):
        flipper.identify_port = (lambda c, d: (lambda port, sys_root="/sys": (c, d)))(cls, dev)
        w = forge.SerialWorker(demo=False, port="/dev/ttyACM0")
        fake = FakePort()
        w._open = lambda: fake
        w.write("subghz chat 433920000")
        w.write("AT+RF=1")
        w.write("device_info")
        w.step()
        pump()
        out[cls] = list(fake.writes)
        w.stop()
    ok = out["flipper"] == [b"device_info\r\n"] and out["unknown"] == [] and out["esp32"] == []
    return ok, repr(out)


@probe("G2: every line written through the executor is logged with port + device")
def g2_log(tmp="/tmp/ra_cl2_serial.jsonl"):
    import flipper
    X.SERIAL_LOG = tmp
    if os.path.exists(tmp):
        os.remove(tmp)
    port = FakePort()
    ok, why, t = flipper.prepare_command("device_info", device="usb:0483:5740", kind="flipper")
    X.write(t, port, port_name="/dev/ttyACM0")
    rec = json.loads(open(tmp).read().splitlines()[-1])
    return rec["line"] == "device_info" and rec["port"] == "/dev/ttyACM0" and rec["device"] == "usb:0483:5740", str(rec)


@probe("[NEW] G2: a ticket for device A can be written to port B (device not bound at write)")
def g2_port_binding():
    import flipper
    E.start("j", "ROE", ["usb:10c4:ea60"], OP)                 # engagement names the ESP32 only
    ok, why, t = flipper.prepare_command("AT+TX", device="usb:10c4:ea60", kind="esp32")
    port = FakePort()
    n = X.write(t, port, port_name="/dev/ttyACM9-the-flipper")  # a different port object/name
    # expectation for a bound write would be a refusal; observe what happens
    return n == 0, "wrote %d bytes to a different port_name with an ESP32-scoped ticket (label-only, by design?)" % n


# ============================================================ G4
def resolver(table):
    def r(host):
        if host not in table:
            raise OSError("NXDOMAIN")
        return list(table[host])
    return r


@probe("G4 PoC: glob / wildcard / string / too-wide scopes are refused")
def g4_scope():
    bad = [["192.168.1.*"], ["*"], ["192.168.1.1/0"], ["0.0.0.0/0"], ["::/0"], ["192.168.1.0-255.0-255"],
           ["[ab]c"], ["Net-*"], ["10.0.0.0/4"], ["", "x"], [None], "192.168.1.0/24", ["192.168.1.0/24 "],
           ["１９２.168.1.0/24"], ["192.168.001.0/24"], ["10.0.0.1-10.255.255.255"], [["10.0.0.1"]]]
    acc = []
    for b in bad:
        ok, why = E.start("j", "ROE", b, OP)
        if ok or E.is_active():
            acc.append(b)
        E.reset()
    return not acc, "accepted=%r" % acc


@probe("G4 PoC: netpent with scope 192.168.1.0/24 refuses the audit's targets + adversarial forms")
def g4_targets():
    import netpent
    E._resolve = resolver({"192.168.1.evil.example.com": ["203.0.113.9"], "nas.lan": ["192.168.1.40"],
                           "split.lan": ["192.168.1.41", "8.8.8.8"], "v6.lan": ["::ffff:192.168.1.41"]})
    assert E.start("j", "ROE", ["192.168.1.0/24"], OP)[0]
    deny = ["192.168.1.1/0", "192.168.1.0-255.0-255", "192.168.1.evil.example.com", "192.168.0.0/16",
            "192.168.2.1", "split.lan", "nx.example", "*", "192.168.1.*", "::ffff:192.168.1.5",
            "::ffff:c0a8:105", "１92.168.1.5", " 192.168.1.5", "192.168.1.5 ", "192.168.1.5\t",
            "192.168.001.005", "3232235781", "0.0.0.0/0", "192.168.1.5,8.8.8.8", "192.168.1.1-20",
            "-sS", "v6.lan", "192.168.1.5%eth0", "192.168.1.5:80", "ip:8.8.8.8", "host:split.lan",
            "0x7f000001", "192.168.1", "192.168.1.5/31", 3232235781, None, "", ("192.168.1.5",)]
    allow = ["192.168.1.10", "192.168.1.0/25", "192.168.1.10-192.168.1.20", "nas.lan", "IP:192.168.1.5",
             "192.168.1.5/32", "192.168.1.0/24"]
    leaked = [t for t in deny if netpent.prepare("portscan", t)[0]]
    blocked = [t for t in allow if not netpent.prepare("portscan", t)[0]]
    return not leaked and not blocked, "leaked=%r wrongly_blocked=%r" % (leaked, blocked)


@probe("[NEW] G4: hostname target is re-resolved by nmap at spawn (DNS rebinding window)")
def g4_rebind():
    import netpent
    table = {"nas.lan": ["192.168.1.40"]}
    E._resolve = resolver(table)
    assert E.start("j", "ROE", ["192.168.1.0/24"], OP)[0]
    ok, why, t = netpent.prepare("portscan", "nas.lan")
    argv = list(t.argv)
    # the ticket carries the NAME, not the pinned address: nmap resolves again on its own
    carries_name = "nas.lan" in argv and "192.168.1.40" not in argv
    # and the recheck at spawn re-resolves: flip DNS between check and spawn -> recheck denies (good)
    table["nas.lan"] = ["8.8.8.8"]
    try:
        X.run(t, spawner=exiter([], 0))
        rechecked = False
    except X.TicketRefused:
        rechecked = True
    return (not carries_name) or False, "argv=%s recheck_denies_after_dns_flip=%s (argv carries hostname: nmap's own lookup after the recheck is unchecked)" % (argv, rechecked)


# ============================================================ G5
@probe("G5 PoC: pmkid carries a BSSID filter list; deauth needs an in-scope client, never broadcast")
def g5_wifi():
    import wifipent
    E.start("j", "ROE", ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"], OP)
    ok, why, t = wifipent.prepare("pmkid", "AA:BB:CC:DD:EE:FF", out="cap")
    argv = list(t.argv)
    fpath = [a.split("=", 1)[1] for a in argv if a.startswith("--filterlist_ap=")]
    pmkid_ok = ok and fpath and "--filtermode=2" in argv and t.files[fpath[0]].strip().upper() == "AABBCCDDEEFF"
    d0 = wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF")[0]
    d1 = wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF", client="99:99:99:99:99:99")[0]
    d2 = wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF", client="FF:FF:FF:FF:FF:FF")[0]
    ok3, _, t3 = wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF", client="11:22:33:44:55:66", count=9999)
    return bool(pmkid_ok) and not d0 and not d1 and not d2 and ok3 and "-c" in t3.argv and t3.argv[2] == str(wifipent.DEAUTH_MAX), \
        "pmkid=%s deauth(no client)=%s (oos client)=%s (bcast)=%s ok=%s argv=%s" % (pmkid_ok, d0, d1, d2, ok3, t3 and t3.argv)


@probe("G5: CAN scope = interface + ID range; Zigbee = PAN@channel; Proxmark reads back the UID")
def g5_bound():
    import canbus
    import zigbee
    import proxmark
    E.start("j", "ROE", ["can0:0x700-0x7FF", "pan:0x1A2B@15", "uid:DEADBEEF"], OP)
    c = (canbus.prepare_send("can0", 0x7DF, b"\x02")[0], canbus.prepare_send("can0", 0x100, b"\x00")[0],
         canbus.prepare_send("can1", 0x7DF, b"\x00")[0], canbus.prepare_send("can0", 0x7DF, b"\x00" * 9)[0])
    z = (zigbee.prepare("inject", pan=0x1A2B, channel=15)[0], zigbee.prepare("inject", pan=0x1A2B, channel=20)[0],
         zigbee.prepare("inject", pan=0x9999, channel=15)[0], zigbee.prepare("inject", channel=15)[0])
    p = (proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="DEADBEEF", read_uid=lambda: "DEADBEEF")[0],
         proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="DEADBEEF", read_uid=lambda: "04A22B3C")[0],
         proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="DEADBEEF", read_uid=None)[0],
         proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="DEADBEEF", read_uid=lambda: (_ for _ in ()).throw(OSError("no pm3")))[0])
    ok = c == (True, False, False, False) and z == (True, False, False, False) and p == (True, False, False, False)
    return ok, "can=%s zigbee=%s proxmark=%s" % (c, z, p)


@probe("[NEW] G5: proxmark sim/clone PARAMETER (emulated UID) is not checked against scope")
def g5_pm_param():
    import proxmark
    E.start("j", "ROE", ["uid:DEADBEEF"], OP)
    ok, why, t = proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="CAFEBABE", read_uid=lambda: "DEADBEEF")
    return not ok, "authorized=%s argv=%s (emulates CAFEBABE while scope/card is DEADBEEF)" % (ok, t and t.argv)


@probe("G5: unbindable tools (USB-HID, flash, Z-Wave, Flipper) say label-only in reason + trail")
def g5_label():
    import buslab, usbhid, zwave
    E.start("j", "ROE", ["LAPTOP-7", "ROUTER-1", "NODE-5"], OP)
    res = [usbhid.prepare("STRING hi", "LAPTOP-7"), buslab.prepare_flash_write("ch341a_spi", "fw.bin", target="ROUTER-1"),
           zwave.prepare("query", target="NODE-5", node_id=5)]
    ok = all(r[0] and "label-only" in r[1] and r[2].binding == "label-only" for r in res)
    ok = ok and all(a["binding"] == "label-only" for a in E.actions())
    return ok, "%s" % [(r[0], r[2] and r[2].binding) for r in res]


# ============================================================ G8
@probe("G8 PoC: decide() gone; service=lora cannot pass at any frequency without the chain")
def g8_lora():
    has_decide = hasattr(G, "decide")
    r = [G.authorize("lora", 1_090_000_000, settings={"tx_enabled": False})[0],
         G.authorize("lora", 915_000_000, settings={"tx_enabled": True})[0]]       # disarmed
    arm()
    r += [G.authorize("lora", 1_090_000_000, settings={"tx_enabled": True})[0],
          G.authorize("lora", 915_000_000, settings={"tx_enabled": False})[0],
          G.authorize("lora", None, settings={"tx_enabled": True})[0]]
    good = G.authorize("lora", 915_000_000, settings={"tx_enabled": True})[0]
    return not has_decide and not any(r) and good and G.EXEMPT_SERVICES == (), "decide=%s denials=%s armed_ok=%s" % (has_decide, r, good)


@probe("G8: every public TX entry refuses while disarmed / locked (bench replay digimodes loopback radio mesh cw rtty)")
def g8_entries():
    import bench, digimodes, loopback, mesh_dash, radio, replay
    calls = []
    dev = [{"id": "hackrf", "name": "HackRF", "tx": True, "freq_hz": (1e6, 6e9), "power_dbm_max": 15}]
    r = {
        "bench": bench.transmit(dict(TXS, freq_hz=915_000_000, iq_file=__file__), spawner=sleeper(calls))[0],
        "replay": replay.prepare_replay(__file__, 915_000_000, 2_000_000, True, settings=TXS)[0],
        "digimodes": digimodes.prepare("ft8", callsign=OP, settings=TXS, which=lambda t: "/bin/" + t)[0],
        "loopback": loopback.hardware_loopback_plan("aprs", 144_390_000, TXS, devices=dev)[0],
        "radio": radio.TxRequest("aprs", 144_390_000, callsign=OP, settings=TXS).authorize(devices=dev)[0],
        "mesh": mesh_dash.authorize_send({"tx_enabled": True, "lora_region": "US"})[0],
    }
    G.arm(True)                                           # armed but NOT unlocked
    r["mesh_armed_locked"] = mesh_dash.authorize_send({"tx_enabled": True, "lora_region": "US"})[0]
    r["bench_armed_locked"] = bench.transmit(dict(TXS, freq_hz=915_000_000, iq_file=__file__), spawner=sleeper(calls))[0]
    return not any(r.values()) and calls == [], "%s calls=%d" % (r, len(calls))


@probe("[NEW] G8: the Tk hub has an ARM control but no UNLOCK control (Tk TX permanently refused)")
def g8_tk_unlock():
    src = open(os.path.join(REPO, "hub.py")).read()
    tk_files = [f for f in os.listdir(REPO) if f.endswith(".py")]
    callers = [f for f in tk_files if "unlock_session(" in open(os.path.join(REPO, f)).read() and f != "txguard.py"]
    return bool(callers), "hub.py arm()=%s; non-Qt callers of unlock_session: %s" % ("_TXG.arm(" in src, callers)


# ============================================================ G9
@probe("G9 PoC: replay -x 47 / 999 under a 10 dBm cap must come back CLAMPED (and authorized)")
def g9_gain():
    import replay
    arm()
    cap = G.gain_for_power(G.TX_PROFILES["replay"]["power_dbm_max"])
    out = {}
    for asked in (47, 999, 20, 0):
        ok, why, t = replay.prepare_replay("b.iq", 915_000_000, 2_000_000, True, settings={"tx_enabled": True}, tx_gain=asked)
        out[asked] = (ok, ok and int(t.argv[t.argv.index("-x") + 1]))
    bad = {}
    for b in (float("nan"), float("inf"), "nan", -1, 3.5, True, "47"):
        ok, why, t = replay.prepare_replay("b.iq", 915_000_000, 2_000_000, True, settings={"tx_enabled": True}, tx_gain=b)
        bad[repr(b)] = ok
    good = all(out[a][0] and out[a][1] <= cap for a in (47, 999, 20)) and out[0] == (True, 0)
    return good and not any(v for k, v in bad.items() if k not in ("'47'",)), "cap=%d out=%s bad=%s" % (cap, out, bad)


@probe("G9: non-finite power, bad sample rate, bool power denied; power clamped to the mode cap")
def g9_power():
    import replay
    arm()
    s = {"tx_enabled": True}
    p = [G.authorize("replay", 915_000_000, power_dbm=v, settings=s)[0] for v in (float("nan"), float("inf"), "x", True, -200)]
    sr = [replay.prepare_replay("b.iq", 915_000_000, v, True, settings=s)[0] for v in (100_000_000, 0, -1, float("nan"), 1_000, "2e6")]
    ok, why, pw = G.authorize("replay", 915_000_000, power_dbm=40, settings=s)
    return not any(p) and not any(sr) and ok and pw == 10, "power_denials=%s sr_denials=%s cap=%s" % (p, sr, pw)


# ============================================================ G10
@probe("G10 PoC: tx_enabled truthy-but-not-True locks; any truthy SUITE_TX_LOCK locks; 433.92 is ham in US")
def g10():
    locks = all(G.tx_locked({"tx_enabled": v})[0] for v in ("yes", 1, "true", "True", [1], 1.0))
    arm()
    env = {}
    for v in ("1", "true", "TRUE", "yes", "on", "x", " 1 "):
        os.environ["SUITE_TX_LOCK"] = v
        env[v] = G.authorize("aprs", 144_390_000, callsign=OP, settings=TXS)[0]
    os.environ.pop("SUITE_TX_LOCK")
    band = (G.classify(433_920_000, "US"), G.classify(433_920_000, "EU"),
            G.authorize("replay", 433_920_000, settings={"tx_enabled": True})[0],
            G.authorize("replay", 433_920_000, settings={"tx_enabled": True, "tx_region": "MARS"})[0],
            G.authorize("aprs", 433_920_000, callsign=OP, settings={"tx_enabled": True})[0])
    return locks and not any(env.values()) and band == ("ham", "ism", False, False, True), "locks=%s env=%s band=%s" % (locks, env, band)


# ============================================================ G11
def net_ticket():
    import netpent
    E.start("j", "ROE", ["10.0.0.0/24"], OP)
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    assert ok
    return t


@probe("G11 PoC: ticket single-use, argv-bound, expiring, forged refused, re-checked at spawn")
def g11_ticket():
    out = {}
    t = net_ticket()
    calls = []
    X.run(t, spawner=exiter(calls, 0))
    try:
        X.run(t, spawner=exiter(calls, 0)); out["reuse"] = "ALLOWED"
    except X.TicketRefused:
        out["reuse"] = "refused"
    t = net_ticket()
    try:
        X.run(t, argv=["nmap", "-sS", "-p", "1-1024", "8.8.8.8"], spawner=exiter(calls, 0)); out["altered"] = "ALLOWED"
    except X.TicketRefused:
        out["altered"] = "refused"
    try:
        object.__setattr__(t, "_argv", ("nmap", "8.8.8.8")); X.run(t, spawner=exiter(calls, 0)); out["mutated"] = "ALLOWED"
    except X.TicketRefused:
        out["mutated"] = "refused"
    t = net_ticket()
    real = X._mono
    X._mono = lambda: real() + X.TICKET_TTL_S + 1
    try:
        X.run(t, spawner=exiter(calls, 0)); out["expired"] = "ALLOWED"
    except X.TicketRefused:
        out["expired"] = "refused"
    X._mono = real
    fake = X.Ticket.__new__(X.Ticket)
    try:
        X.run(fake, spawner=exiter(calls, 0)); out["forged"] = "ALLOWED"
    except X.TicketRefused:
        out["forged"] = "refused"
    try:
        X.run(["nmap", "10.0.0.5"], spawner=exiter(calls, 0)); out["bare_argv"] = "ALLOWED"
    except X.TicketRefused:
        out["bare_argv"] = "refused"
    t = net_ticket()
    E.end()
    try:
        X.run(t, spawner=exiter(calls, 0)); out["after_end"] = "ALLOWED"
    except X.TicketRefused:
        out["after_end"] = "refused"
    try:
        X.issue(argv=["nmap", "8.8.8.8"], recheck=lambda: (True, "trust me")); out["non_gate_issue"] = "ALLOWED"
    except X.TicketRefused:
        out["non_gate_issue"] = "refused"
    return all(v == "refused" for v in out.values()) and len(calls) == 1, "%s calls=%d" % (out, len(calls))


@probe("G11 PoC: END and disarm kill a RUNNING authorized process (process group)")
def g11_kill():
    import bench
    bench.TX_LOG = "/dev/null"
    t = net_ticket()
    h = X.start(t, spawner=sleeper([]))
    E.end()
    end_killed = wait_dead(h.proc)
    reset()
    arm()
    ok, why, h2 = bench.start_transmit(dict(TXS, freq_hz=915_000_000, iq_file=__file__), spawner=sleeper([]))
    G.arm(False)
    disarm_killed = wait_dead(h2.proc)
    return end_killed and disarm_killed and X.running() == [], "end_killed=%s disarm_killed=%s" % (end_killed, disarm_killed)


@probe("[NEW] G11: race — END fires INSIDE spawn (after redeem, before register): child must still die")
def g11_race():
    t = net_ticket()

    def racing_spawner(argv, **kw):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
        E.end()                                   # the gate closes while the process is being born
        return p
    h = X.start(t, spawner=racing_spawner)
    return wait_dead(h.proc), "child dead=%s stopped=%r" % (h.proc.poll() is not None, h.stopped)


@probe("[NEW] G11: expiry of a running engagement kills its process without any UI call")
def g11_expiry_kill():
    t0 = time.time()
    E._now = lambda: t0
    E.start("j", "ROE", ["10.0.0.0/24"], OP, hours=1)
    import netpent
    ok, why, t = netpent.prepare("portscan", "10.0.0.5")
    h = X.start(t, spawner=sleeper([]))
    E._now = lambda: t0 + 3601
    dead = wait_dead(h.proc, 3.0)                 # monitor thread sweeps every 0.25 s
    E._now = time.time
    return dead, "dead=%s stopped=%r" % (dead, h.stopped)


@probe("[NEW] G11: tx_enabled flipped to False in settings mid-run does NOT stop the process (snapshot)")
def g11_settings_snapshot():
    import bench
    bench.TX_LOG = "/dev/null"
    arm()
    s = dict(TXS, freq_hz=915_000_000, iq_file=__file__)
    ok, why, h = bench.start_transmit(s, spawner=sleeper([]))
    s["tx_enabled"] = False
    X._sweep()
    time.sleep(0.6)
    alive = h.proc.poll() is None
    h.stop()
    return not alive, "still running after tx_enabled=False: %s (recheck uses a settings snapshot)" % alive


# ============================================================ G12
@probe("G12 PoC: TX slot / ENGAGEMENT slot follow the engines with the poll timer stopped")
def g12_slots():
    qapp()
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=False, mode="dark")
    try:
        hub._list_children = lambda: []
        hub.state._timer.stop()
        G.arm(True); pump()
        a = hub.topbar.slots["tx"].text()
        G.unlock_session(True); pump()
        b = hub.topbar.slots["tx"].text()
        E.start("j", "ROE", ["10.0.0.1"], OP); pump()
        c = hub.topbar.slots["engagement"].text()
        G.arm(False); E.end(); pump()
        d = (hub.topbar.slots["tx"].text(), hub.topbar.slots["engagement"].text())
        return a == "ARMED" and b == "UNLOCKED" and c.startswith("ACTIVE") and d == ("OFF", "NONE"), "%s %s %s %s" % (a, b, c, d)
    finally:
        hub.close(); pump(100)


@probe("G12 PoC: FORGE replay banner never says armed+unlocked while the engine says DENIED; cards follow END")
def g12_forge():
    qapp()
    from palisade_qt.forge import ForgeApp, EngagementCard
    E.start("j", "ROE", ["can0:0x700-0x7FF"], OP)
    f = ForgeApp(demo=False, mode="dark")
    try:
        card = f.replay_card
        card._saved = lambda: {"tx_enabled": True, "tx_region": "US"}
        mism = []
        for armed in (False, True):
            for unl in (False, True):
                for mhz in (915.0, 1090.0, 433.92):
                    G.arm(armed); G.unlock_session(unl); card.freq.setValue(mhz); pump(20); card.refresh()
                    eng = G.authorize("replay", int(mhz * 1e6), settings=card._saved())[0]
                    if ("armed + unlocked" in card.state.text()) != eng:
                        mism.append((armed, unl, mhz, card.state.text()))
        cards = [c for c in f._cards if isinstance(c, EngagementCard)]
        before = all(c._btn.isEnabled() for c in cards)
        E.end(); pump()
        after = any(c._btn.isEnabled() or "engagement active" in c.state.text() for c in cards)
        return not mism and before and not after, "mismatches=%s cards_before=%s cards_stale_after_end=%s" % (mism, before, after)
    finally:
        f.stop()


# ============================================================ G13
@probe("G13 PoC: second start refused + trail kept; expiry enforced; operator from profile; auth not prefilled")
def g13():
    assert E.start("first", "ROE-1", ["10.0.0.1"], OP)[0]
    E.authorize_action("net:x", "10.0.0.1")
    second = E.start("second", "ROE-2", ["10.0.0.2"], OP)[0]
    kept = E.info()["name"] == "first" and len(E.actions()) == 1
    E.reset()
    t0 = time.time(); E._now = lambda: t0
    E.start("j", "ROE", ["10.0.0.1"], OP)
    E._now = lambda: t0 + 8 * 3600 + 1
    exp = E.authorize_action("net:x", "10.0.0.1")[0]
    E._now = time.time
    E.reset()
    free_text = E.start("j", "ROE", ["10.0.0.1"], "SOMEONE-ELSE")[0]
    E._profile_operator = lambda: None
    no_prof = E.start("j", "ROE", ["10.0.0.1"])[0]
    E._profile_operator = lambda: OP
    qapp()
    import opprofile
    opprofile.load = lambda fn, name="operator": {"callsign": OP, "authorization": "ROE-SAVED"}
    from palisade_qt import panels
    p = panels.EngagePanel("dark")
    ui = p.eng_operator.isReadOnly() and p.eng_operator.text() == OP and p.eng_auth.text() == ""
    return not second and kept and not exp and not free_text and not no_prof and ui, \
        "second=%s kept=%s expired_denied=%s free_text=%s no_profile=%s ui=%s" % (second, kept, not exp, free_text, no_prof, ui)


# ============================================================ L1
CHILD = r"""
import json, sys, os
sys.path.insert(0, %r)
import txguard, engagement
print(json.dumps({"armed": txguard.is_armed(), "unlocked": txguard.session_unlocked(),
                  "eng": engagement.is_active(), "auth": engagement.check("net:x", "10.0.0.1", kind="ip")[0],
                  "tx": txguard.authorize("replay", 915000000, settings={"tx_enabled": True})[0],
                  "arm_self": (txguard.arm(True), txguard.is_armed())[1],
                  "unlock_self": (txguard.unlock_session(True), txguard.session_unlocked())[1],
                  "start_self": engagement.start("x", "y", ["10.0.0.1"], None)[0]}))
"""


def child(env):
    r = subprocess.run([sys.executable, "-c", CHILD % REPO], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@probe("L1 PoC: a real child follows the hub (arm/unlock/engagement), loses it on disarm, cannot arm itself")
def l1_child(tmp="/tmp/ra_cl2_gate.json"):
    import gatestate
    if os.path.exists(tmp):
        os.remove(tmp)
    pub = gatestate.Publisher(tmp)
    try:
        E.start("j", "ROE", ["10.0.0.0/24"], OP); arm(); pub.publish_from_engines()
        env = gatestate.child_env(tmp, base=dict(os.environ))
        a = child(env)
        G.arm(False); E.end(); pub.publish_from_engines()
        env2 = gatestate.child_env(tmp, base=dict(os.environ))
        locked_env = env2.get("SUITE_TX_LOCK") == "1"
        env2.pop("SUITE_TX_LOCK", None)
        b = child(env2)
        ok = a["armed"] and a["unlocked"] and a["eng"] and a["auth"] and a["tx"] and not a["start_self"] \
            and not b["armed"] and not b["eng"] and not b["auth"] and not b["tx"] and not b["arm_self"] \
            and not b["unlock_self"] and not b["start_self"] and locked_env
        return ok, "armed=%s disarmed=%s lock_exported=%s" % (a, b, locked_env)
    finally:
        pub.close()


@probe("L1: stale (dead hub pid), missing, foreign-writable, and malformed state files fail closed")
def l1_stale(tmp="/tmp/ra_cl2_stale.json"):
    dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
    eng = {"name": "j", "authorization": "a", "scope": ["10.0.0.0/24"], "operator": OP, "started": time.time(),
           "expires": time.time() + 3600, "entries": [{"kind": "ip", "text": "10.0.0.0/24", "data": {"lo": "10.0.0.0", "hi": "10.0.0.255"}}]}
    out = {}
    env = dict(os.environ); env.pop("SUITE_TX_LOCK", None); env["PALISADE_GATE_STATE"] = tmp
    json.dump({"pid": dead.pid, "t": time.time(), "armed": True, "unlocked": True, "engagement": eng}, open(tmp, "w")); os.chmod(tmp, 0o600)
    out["dead_pid"] = child(env)
    json.dump({"pid": os.getpid(), "t": time.time(), "armed": True, "unlocked": True, "engagement": eng}, open(tmp, "w")); os.chmod(tmp, 0o666)
    out["world_writable"] = child(env)
    json.dump({"pid": os.getpid(), "t": time.time(), "armed": "yes", "unlocked": 1, "engagement": eng}, open(tmp, "w")); os.chmod(tmp, 0o600)
    out["non_bool"] = child(env)
    open(tmp, "w").write("{not json"); out["malformed"] = child(env)
    os.remove(tmp); out["missing"] = child(env)
    ok = all(not v["armed"] and not v["eng"] and not v["tx"] and not v["arm_self"] for v in out.values())
    return ok, str({k: (v["armed"], v["eng"], v["tx"]) for k, v in out.items()})


@probe("[NEW] L1: a forged state file naming any LIVE same-user pid is trusted (no nonce / hub identity check)")
def l1_forged(tmp="/tmp/ra_cl2_forged.json"):
    eng = {"name": "j", "authorization": "a", "scope": ["10.0.0.0/24"], "operator": OP, "started": time.time(),
           "expires": time.time() + 3600, "entries": [{"kind": "ip", "text": "10.0.0.0/24", "data": {"lo": "10.0.0.0", "hi": "10.0.0.255"}}]}
    json.dump({"pid": os.getppid(), "t": time.time(), "armed": True, "unlocked": True, "engagement": eng}, open(tmp, "w")); os.chmod(tmp, 0o600)
    env = dict(os.environ); env.pop("SUITE_TX_LOCK", None); env["PALISADE_GATE_STATE"] = tmp
    r = child(env)
    os.remove(tmp)
    return not r["tx"], "child armed=%s eng=%s tx_authorized=%s with a file written by this script naming the parent shell's pid" % (r["armed"], r["eng"], r["tx"])


@probe("L1: child started while armed; hub disarms afterwards -> child's authorize() now denies (file re-read)")
def l1_live_disarm(tmp="/tmp/ra_cl2_live.json"):
    import gatestate
    if os.path.exists(tmp):
        os.remove(tmp)
    pub = gatestate.Publisher(tmp)
    try:
        arm(); pub.publish_from_engines()
        env = gatestate.child_env(tmp, base=dict(os.environ))
        code = ("import sys, time, json; sys.path.insert(0, %r); import txguard\n"
                "a = txguard.authorize('replay', 915000000, settings={'tx_enabled': True})[0]\n"
                "print('READY', flush=True); sys.stdin.readline()\n"
                "b = txguard.authorize('replay', 915000000, settings={'tx_enabled': True})[0]\n"
                "print(json.dumps([a, b]))") % REPO
        p = subprocess.Popen([sys.executable, "-c", code], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert p.stdout.readline().strip() == "READY"
        G.arm(False); pub.publish_from_engines()
        p.stdin.write("\n"); p.stdin.flush()
        a, b = json.loads(p.stdout.read().strip().splitlines()[-1])
        return a is True and b is False, "before_disarm=%s after_disarm=%s" % (a, b)
    finally:
        pub.close()


@probe("L1: Tk hub wires Publisher + child_env on every child launch (static)")
def l1_hub_static():
    src = open(os.path.join(REPO, "hub.py")).read().splitlines()
    popens = [i + 1 for i, l in enumerate(src) if "subprocess.Popen(" in l]
    with_env = [n for n in popens if "env=_child_env()" in "".join(src[n - 1:n + 3])]
    spawns = [i + 1 for i, l in enumerate(src) if "S.spawn(" in l or "S.fire_and_forget(" in l]
    return "_GS.Publisher()" in "".join(src) and popens and set(popens) == set(with_env), \
        "Popen lines=%s with child_env=%s; S.spawn/fire_and_forget lines (no env)=%s" % (popens, with_env, spawns)


# ============================================================ S2
@probe("S2 PoC: Scout scans nothing (no nmap spawn, no TCP connect) without an engagement; real netmask used")
def s2_scout():
    import scout
    calls, conns = [], []
    scout.tcp_open = lambda ip, port, timeout=0.4: (conns.append((ip, port)), False)[1]
    scout.has_nmap = lambda: False
    r1 = scout.scan_network(lambda h: None, lambda t, f: None, None, local_net=lambda: "192.168.4.0/22", wait=True)
    r2 = scout.scan_network(lambda h: None, lambda t, f: None, None, spawner=sleeper(calls), local_net=lambda: "192.168.4.0/22")
    net = scout.network_from_ip_addr("2: wlan0    inet 192.168.5.23/22 brd 192.168.7.255 scope global wlan0")
    E.start("j", "ROE", ["192.168.5.0/24"], OP)              # a /24 does not cover the real /22
    r3 = scout.scan_network(lambda h: None, lambda t, f: None, None, spawner=sleeper(calls), local_net=lambda: "192.168.4.0/22")
    r4 = scout.scan_network(lambda h: None, lambda t, f: None, None, local_net=lambda: "192.168.4.0/22", wait=True)
    none = scout.scan_network(lambda h: None, lambda t, f: None, None, spawner=sleeper(calls), local_net=lambda: None)
    ok = not r1[0] and not r2[0] and not r3[0] and not r4[0] and not none[0] and calls == [] and conns == [] and net == "192.168.4.0/22"
    return ok, "refusals=%s nmap_calls=%d tcp_connects=%d netmask=%s" % ([r1[1][:40], r2[1][:40], r3[1][:40], r4[1][:40]], len(calls), len(conns), net)


@probe("[NEW] S2: Scout's fallback connect-scanner (no nmap) runs OUTSIDE the executor; END does not stop it")
def s2_fallback():
    import scout
    conns = []
    scout.tcp_open = lambda ip, port, timeout=0.4: (conns.append(ip), time.sleep(0.01), False)[2]
    scout.has_nmap = lambda: False
    scout.arp_hosts = lambda: []
    scout.own_ipv4 = lambda: "10.9.0.1"
    E.start("j", "ROE", ["10.9.0.0/24"], OP)
    procs = []
    ok, why = scout.scan_network(lambda h: None, lambda t, f: None, None, local_net=lambda: "10.9.0.0/24", procs=procs)
    time.sleep(0.3)
    E.end()
    n_at_end = len(conns)
    time.sleep(1.0)
    kept_going = len(conns) - n_at_end
    for p in procs:
        p.stop("poc")
    return ok and kept_going == 0 and X.running() == [], "started=%s connects_after_END=%d (in-process threads, no ticket, not in executor.running())" % (ok, kept_going)


@probe("S2: dev terminal BLE connect / MQTT publish / SSH gated; terminal-ssh spawn is outside the executor")
def s2_devterm():
    import devterm
    a = (devterm.authorize_ble_connect("AA:BB:CC:DD:EE:FF")[0], devterm.authorize_mqtt_publish("10.0.0.7")[0],
         devterm.prepare_ssh("10.0.0.7", "id")[0], devterm.prepare_ssh("-oProxyCommand=x", "id")[0])
    E.start("j", "ROE", ["AA:BB:CC:DD:EE:FF", "10.0.0.7"], OP)
    b = (devterm.authorize_ble_connect("AA:BB:CC:DD:EE:FF")[0], devterm.authorize_mqtt_publish("10.0.0.7")[0],
         devterm.prepare_ssh("10.0.0.7", "id")[0], devterm.prepare_ssh("10.0.0.8", "id")[0],
         devterm.authorize_ssh_host("10.0.0.7; rm -rf x")[0], devterm.authorize_ssh_host("10.0.0.7 -oProxyCommand=x")[0])
    src = open(os.path.join(REPO, "devterm.py")).read()
    direct = "subprocess.Popen([term" in src
    return a == (False, False, False, False) and b == (True, True, True, False, False, False), \
        "no_eng=%s with_eng=%s terminal_ssh_direct_popen=%s" % (a, b, direct)


# ============================================================ S3
class FakeHid:
    def __init__(self, fail=False):
        self.writes, self.fail = [], fail

    def __call__(self, path, mode="rb"):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write(self, d):
        if self.fail:
            raise OSError("EPIPE")
        self.writes.append(bytes(d)); return len(d)


@probe("S3 PoC: Tk USB-HID never reports 'sent' unless reports were written; nothing without engagement")
def s3():
    import usbhid
    dev = FakeHid()
    r0 = usbhid.run_payload("STRING hi", "LAPTOP-7", gadget=True, opener=dev)
    E.start("j", "ROE", ["LAPTOP-7"], OP)
    r1 = usbhid.run_payload("STRING hi\nENTER", "LAPTOP-7", gadget=True, opener=FakeHid(fail=True))
    r2 = usbhid.run_payload("STRING hi\nENTER", "LAPTOP-7", gadget=False, opener=dev)
    r3 = usbhid.run_payload("STRING hi\nENTER", "LAPTOP-7", gadget=True, opener=dev)
    def says_sent(t):
        return "sent" in t.lower().replace("not sent", "")
    ok = not r0[0] and r0[2] == 0 and dev.writes == [] or True
    ok = (not r0[0] and r0[2] == 0) and (not r1[0] and r1[2] == 0 and not says_sent(r1[1])) and \
         (not r2[0] and r2[2] == 0 and not says_sent(r2[1])) and (r3[0] and r3[2] == len(dev.writes) > 0)
    return ok, "no_eng=%s epipe=%s no_gadget=%s ok=%s" % (r0[:1] + (r0[2],), (r1[0], r1[2], r1[1][:50]), (r2[0], r2[2]), (r3[0], r3[2]))


@probe("S3: Tk engagement can still never be opened (owner decision pending) — says so honestly")
def s3_tk():
    src = open(os.path.join(REPO, "engagement.py")).read()
    return "not available" in src and "Qt shell" in src, "engagement.main() text mentions the Qt ENGAGEMENT panel: %s" % ("not available" in src)


# ============================================================ owner defaults on every entry point
@probe("Owner defaults: protected denied when conducted; no LoRa bypass; callsign never enables TX")
def owner():
    import opprofile
    arm()
    c = [G.authorize("bench", f, settings=TXS)[0] for f in (1_090_000_000, 121_500_000)]
    l = [G.authorize("lora", 915_000_000, settings={"tx_enabled": False})[0]]
    G.reset_session()
    l.append(G.authorize("lora", 915_000_000, settings={"tx_enabled": True})[0])
    o = opprofile.tx_settings({"callsign": OP})["tx_enabled"], opprofile.tx_settings({"callsign": OP, "tx_enabled": "yes"})["tx_enabled"]
    return not any(c) and not any(l) and o == (False, False) and G.CONDUCTED_PROTECTED_ALLOWED is False and G.EXEMPT_SERVICES == () and opprofile.CALLSIGN_ENABLES_TX is False, \
        "conducted_protected=%s lora=%s callsign_tx=%s" % (c, l, o)


if __name__ == "__main__":
    reset()
    n_fail = sum(1 for _t, ok, _d in RESULTS if not ok)
    print("\n%d probes, %d FAIL" % (len(RESULTS), n_fail))
    json.dump([{"tag": t, "ok": ok, "detail": str(d)} for t, ok, d in RESULTS],
              open(os.environ.get("RA_CL2_OUT", "/tmp/ra_cl2_poc.json"), "w"), indent=1)
    try:
        X.kill_all("exit")
    except Exception:
        pass
    os._exit(0)
