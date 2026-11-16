"""RA-CL5d NWR safety (copy of RA-CL5c poc_c_nwr.py + new scenarios: bursty15, bursty08, trickle, realistic, healthy60, healthy_load, stopcont, stderr_trickle; io_unreadable now injects _rchar) (owner priority) through the real hub. Every 0.1 s: what the page SAYS
(LIVE label / 'NO ALERTS' hero) vs what is TRUE: arbiter HELD(PROWL-NWR) AND audio flowing INTO
the decoder (multimon-ng's /proc/<pid>/io rchar grew in the last 1.0 s). Truth is measured on the
decoder's input, independently of the fix's own heartbeat (rtl_fm's wchar).
Scenarios (argv[1]): wedged · wedge_mid · chatter · stuck_mm · sigstop · dies1 · dies3 · dies5 ·
io_unreadable (fault injection: NwrWorker._wchar -> None) · revoke · forced · panic · hide ·
retune · to_fm · from_fm · from_scan."""
import os
import signal
import sys
import time
HERE0 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE0, "..", "RA-CL5c-evidence"))
import _harness as H
from palisade_qt import radio_arbiter, shell

which = sys.argv[1]
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0
HERE = os.path.dirname(os.path.abspath(__file__))
PYW = ("#!/usr/bin/env python3\nimport sys,time\no=sys.stdout.buffer\nB=%s\n"
       "while True:\n    o.write(B); o.flush(); time.sleep(%s)\n")
FAKES = {
    "wedged": {"rtl_fm": "#!/bin/sh\nexec sleep 600\n"},
    "wedge_mid": {"rtl_fm": "#!/usr/bin/env python3\nimport sys,time\no=sys.stdout.buffer\n"
                  "t=time.time()\nwhile time.time()-t<6:\n    o.write(b'\\x10\\x20'*2048); o.flush(); time.sleep(0.02)\n"
                  "time.sleep(600)\n"},
    "chatter": {"rtl_fm": "#!/bin/sh\n# stalled: no samples on stdout, but librtlsdr-style errors on stderr\n"
                "while :; do echo 'rtlsdr_demod_write_reg failed with -7' >&2; sleep 0.2; done\n"},
    "stuck_mm": {"multimon-ng": "#!/bin/sh\nexec sleep 600\n"},
    "dies1": {"multimon-ng": "#!/bin/sh\ncat >/dev/null & p=$!\nsleep 1\nkill $p\nexit 3\n"},
    "dies3": {"multimon-ng": "#!/bin/sh\ncat >/dev/null & p=$!\nsleep 3\nkill $p\nexit 3\n"},
    "dies5": {"multimon-ng": "#!/bin/sh\ncat >/dev/null & p=$!\nsleep 5\nkill $p\nexit 3\n"},
    # 66 kB bursts every 1.5 s (gaps > AUDIO_GAP_S) / every 0.8 s
    "bursty15": {"rtl_fm": PYW % ("b'\\x10\\x20'*33075", "1.5")},
    "bursty08": {"rtl_fm": PYW % ("b'\\x10\\x20'*17640", "0.8")},
    # a wedged-but-dribbling rtl_fm: 64 bytes every 0.3 s (0.5 %% of the audio rate)
    "trickle": {"rtl_fm": PYW % ("b'\\x10\\x20'*32", "0.3")},
    # real rtl_fm cadence for -s 22050: ~5.7 kB per 129 ms USB buffer
    "realistic": {"rtl_fm": PYW % ("b'\\x10\\x20'*2844", "0.129")},
    # stderr chatter AND a 2-byte dribble every 0.5 s on stdout
    "stderr_trickle": {"rtl_fm": "#!/usr/bin/env python3\nimport sys,time\no=sys.stdout.buffer\n"
                       "while True:\n    sys.stderr.write('rtlsdr_demod_write_reg failed with -7\\n'); sys.stderr.flush()\n"
                       "    o.write(b'\\x00\\x00'); o.flush(); time.sleep(0.5)\n"},
}
for _n in (1, 3, 5):        # a REAL reader (its own pid reads stdin) that exits after N s
    FAKES["pydies%d" % _n] = {"multimon-ng": "#!/usr/bin/env python3\nimport sys,time\nt=time.time()\n"
                              "f=open('/dev/stdin','rb',buffering=0)\n"
                              "while time.time()-t<%d:\n    f.read(4096)\nsys.exit(3)\n" % _n}
FAKES["realistic60"] = FAKES["realistic"]
FAKES["realistic_load"] = FAKES["realistic"]
if which in FAKES:
    d = os.path.join(HERE, "fakebin_" + which)
    os.makedirs(d, exist_ok=True)
    for n, body in FAKES[which].items():
        p = os.path.join(d, n)
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, 0o755)
    os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
radio_arbiter._make_lease = lambda name: H.FakeLease(name)
A = radio_arbiter.arbiter
from palisade_qt.prowl import ProwlApp, NwrWorker  # noqa: E402
if which == "io_unreadable":
    NwrWorker._rchar = staticmethod(lambda pid: None)       # fault injection: /proc/<pid>/io EACCES
BURN = []
if which == "realistic_load":
    import subprocess as _sp
    BURN = [_sp.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(os.cpu_count() or 4)]
    H.log("LOAD: %d CPU burners" % len(BURN))

hub = shell.PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720); hub.show(); H.pump(0.5)
hub.open_callsign("PROWL"); H.pump(0.5)
page = hub.pages["PROWL"]
prowl = page.child(ProwlApp)
page.switch_subtab("FM" if which == "from_fm" else "SCAN" if which == "from_scan" else "NWR")
H.pump(3.0 if which not in ("wedged", "chatter", "stuck_mm", "io_unreadable", "trickle",
                            "stderr_trickle", "bursty15") else 0.3)

_hist = {}


def rchar(pid):
    try:
        with open("/proc/%d/io" % pid) as f:
            for ln in f:
                if ln.startswith("rchar:"):
                    return int(ln.split()[1])
    except OSError:
        return None


def audio_into_decoder():
    w = prowl._worker
    proc = getattr(w, "_proc", None) if isinstance(w, NwrWorker) else None
    procs = getattr(proc, "procs", None) or []
    if not procs or procs[-1].poll() is not None:
        return False
    pid = procs[-1].pid
    r = rchar(pid)
    now = time.monotonic()
    h = _hist.setdefault(pid, [])
    h.append((now, r))
    old = [x for x in h if now - x[0] >= 1.0]
    if not old or r is None or old[-1][1] is None:
        return False
    return r > old[-1][1]


def sample(tag):
    txt = prowl.nwr_state.text()
    hero = prowl.nwr_detail.sub.text()
    st = A.state()
    flow = audio_into_decoder()
    says = txt.startswith("LIVE") or hero == "NO ALERTS"
    true = st == ("HELD", "PROWL-NWR") and flow
    v = says and not true
    H.log("%s label=%r hero=%r arbiter=%s audio_in=%s%s" % (tag, txt[:60], hero, st, flow,
                                                         "  <<< VIOLATION" if v else ""))
    return v, says


# prime the truth's rchar history during the warm-up (the RA-CL5c PoC started it here, which made
# its first second of every run an artefact "violation")
for _ in range(15):
    audio_into_decoder(); H.pump(0.1)
sample("BEFORE")
if which == "sigstop":
    pid = prowl._worker._proc.procs[-1].pid
    os.kill(pid, signal.SIGSTOP)
    H.log("INJECT SIGSTOP multimon-ng", pid)
elif which == "revoke":
    A.revoke()
elif which == "forced":
    A.revoke(timeout_s=0.05)
elif which == "panic":
    H.log("PANIC banner: " + " · ".join(hub.panic()))
elif which == "hide":
    hub.show_page("OPS")
elif which == "retune":
    i = prowl.nwr_combo.currentIndex()
    prowl.nwr_combo.setCurrentIndex((i + 1) % prowl.nwr_combo.count())
    H.log("RETUNE ->", prowl.nwr_combo.currentText())
elif which == "to_fm":
    page.switch_subtab("FM")
elif which in ("from_fm", "from_scan"):
    page.switch_subtab("NWR")
elif which == "stopcont":
    import threading as _th
    pid = prowl._worker._proc.procs[-1].pid
    def _cyc():
        for _ in range(int(DUR)):
            try:
                os.kill(pid, signal.SIGSTOP); time.sleep(0.6); os.kill(pid, signal.SIGCONT); time.sleep(0.4)
            except OSError:
                return
    _th.Thread(target=_cyc, daemon=True).start()
    H.log("INJECT SIGSTOP 0.6 s / SIGCONT 0.4 s cycles on multimon-ng", pid)
viol = says_n = run = maxrun = 0
notlive = 0
n = int(DUR * 10)
for i in range(n):
    H.pump(0.1)
    v, s = sample("t+%.1f" % ((i + 1) / 10.0))
    viol += v
    says_n += s
    notlive += (not s) and (i >= 40)
    run = run + 1 if v else 0
    maxrun = max(maxrun, run)
H.log("RESULT %s: not-LIVE samples after t+4s: %d of %d" % (which, notlive, max(0, n - 40)))
for p in BURN:
    p.kill()
H.log("RESULT %s: %d violating samples of %d (LIVE-claims %d; longest violation %.1fs)"
      % (which, viol, n, says_n, maxrun / 10.0))
try:
    if which == "sigstop":
        os.kill(pid, signal.SIGCONT)
except Exception:
    pass
hub.close(); H.pump(1.5)
