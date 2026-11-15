#!/usr/bin/env python3
"""RA-CL2 — second probe set: do the TX kill switch / env hard lock / DISARM reach the RF emitters
that are gated by the ENGAGEMENT gate (aireplay-ng deauth, zbreplay / zbstumbler, gatttool write,
Flipper subghz tx)? Run from the fix/cl2-gates worktree with the venv python."""
import os
import subprocess
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
import engagement as E  # noqa: E402
import txguard as G  # noqa: E402
import executor as X  # noqa: E402

OP = "KD0ABC"
E._profile_operator = lambda: OP


def sleeper(calls):
    def spawn(argv, **kw):
        calls.append(list(argv))
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    return spawn


def wait_dead(p, t=3.0):
    t0 = time.time()
    while p.poll() is None and time.time() - t0 < t:
        time.sleep(0.02)
    return p.poll() is not None


def reset():
    os.environ.pop("SUITE_TX_LOCK", None)
    X.kill_all("reset"); X.reset(); G.reset_session(); E.reset()


def run(tag, fn):
    reset()
    try:
        ok, d = fn()
    except Exception:
        ok, d = False, traceback.format_exc()
    print("%s  %s\n      %s" % ("PASS" if ok else "FAIL", tag, d))


def tickets():
    import wifipent, zigbee, blepent, flipper
    E.start("j", "ROE", ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66", "pan:0x1A2B@15", "usb:0483:5740"], OP)
    out = {}
    out["wifi deauth"] = wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF", client="11:22:33:44:55:66")
    out["zigbee inject"] = zigbee.prepare("inject", pan=0x1A2B, channel=15)
    out["zigbee discover"] = zigbee.prepare("discover", channel=15)
    out["ble write"] = blepent.prepare("write", "AA:BB:CC:DD:EE:FF", handle="0x1", value="ff")
    out["flipper subghz tx"] = flipper.prepare_command("subghz tx 0 433920000", device="usb:0483:5740", kind="flipper")
    return out


def p1():
    """SUITE_TX_LOCK=1 (the hard lock) + txguard disarmed: are RF-emitting engagement tickets still issued?"""
    os.environ["SUITE_TX_LOCK"] = "1"
    out = tickets()
    issued = {k: v[0] for k, v in out.items()}
    return not any(issued.values()), "issued under SUITE_TX_LOCK=1 and disarmed: %s" % issued


def p2():
    """Does the executor run an RF-emitting engagement ticket while txguard is disarmed + env-locked?"""
    os.environ["SUITE_TX_LOCK"] = "1"
    out = tickets()
    calls = []
    ran = {}
    for k in ("wifi deauth", "zigbee inject"):
        ok, why, t = out[k]
        try:
            h = X.start(t, spawner=sleeper(calls)); ran[k] = "SPAWNED"; h.stop()
        except X.TicketRefused as e:
            ran[k] = "refused: %s" % e
    return all(v.startswith("refused") for v in ran.values()), "%s argv=%s" % (ran, calls)


def p3():
    """Does DISARM (the kill switch) kill a RUNNING deauth / zigbee inject?"""
    G.arm(True); G.unlock_session(True)
    out = tickets()
    ok, why, t = out["wifi deauth"]
    h = X.start(t, spawner=sleeper([]))
    G.arm(False)
    dead = wait_dead(h.proc, 1.5)
    if not dead:
        h.stop("poc")
    return dead, "deauth process killed by DISARM: %s (END does kill it; DISARM is the TX kill switch)" % dead


def p4():
    """Qt PANIC (Shift+Esc) path: executor.kill_all + engagement.end + arm(False) — does it reach them?"""
    out = tickets()
    ok, why, t = out["zigbee inject"]
    h = X.start(t, spawner=sleeper([]))
    n = X.kill_all("PANIC")
    return wait_dead(h.proc) and n == 1, "kill_all stopped %d; dead=%s" % (n, h.proc.poll() is not None)


def p5():
    """engagement.issue() is public: any module can mint a ticket for an UNRELATED argv under a label scope
    (e.g. an RF TX command through the engagement gate, skipping txguard entirely)."""
    E.start("j", "ROE", ["LAB-1"], OP)
    ok, why, t = E.issue("anything", "LAB-1", argv=["hackrf_transfer", "-t", "x.iq", "-f", "1090000000", "-x", "47"])
    calls = []
    try:
        h = X.start(t, spawner=sleeper(calls)); h.stop(); spawned = True
    except X.TicketRefused:
        spawned = False
    return not spawned, "issued=%s spawned=%s argv=%s (ISSUERS guards executor.issue, not engagement.issue)" % (ok, spawned, calls)


def p6():
    """flipper.prepare_command(kind='demo') is caller-controlled: an ungated write ticket usable on any port."""
    import flipper
    ok, why, t = flipper.prepare_command("subghz tx 0 433920000", device="usb:0483:5740", kind="demo")

    class P:
        w = []

        def write(self, d):
            P.w.append(d); return len(d)
    n = X.write(t, P(), port_name="/dev/ttyACM0")
    return n == 0, "ungated 'demo' ticket wrote %d bytes to a port object (caller passes kind='demo')" % n


for tag, fn in (("[NEW] env hard lock + disarmed: RF engagement tickets still issued?", p1),
                ("[NEW] env hard lock + disarmed: executor still spawns them?", p2),
                ("[NEW] DISARM kills a running deauth?", p3),
                ("PANIC kill_all reaches engagement-gated processes", p4),
                ("[NEW] engagement.issue() mints a ticket for an unrelated argv (txguard skipped)", p5),
                ("[NEW] flipper kind='demo' ungated write ticket", p6)):
    run(tag, fn)
reset()
os._exit(0)
