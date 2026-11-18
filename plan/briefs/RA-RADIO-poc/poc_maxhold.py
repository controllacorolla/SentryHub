import os, sys
WT = sys.argv[1]; sys.path[:0] = [WT, os.path.join(WT, "tests")]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import test_radio_sdrpp as T, banks
from palisade_qt.iqworker import plan_windows
for name in ("NOAA Wx", "MURS", "FRS/GMRS", "Marine VHF"):
    if name not in banks.BANKS: continue
    b = banks.BANKS[name]
    chans = [(f, lb, b["mode"], b["bw"]) for f, lb in banks.expand(b)]
    print(name, len(chans), "channels,", len(plan_windows([int(c[0]*1e6) for c in chans], 2048000)), "windows")
print([k for k in banks.BANKS])
b = [k for k in banks.BANKS if "NOAA" in k or "Wx" in k or "Weather" in k][0]
B = banks.BANKS[b]
chans = [(f, lb, B["mode"], B["bw"]) for f, lb in banks.expand(B)]
# station A transmits continuously (NOAA-style), station B also continuously, weaker
fa, fb = chans[0][0], chans[3][0]
w, run, rows, hits, audio = T._scanner(chans, [(fa, "NFM", lambda t: True), (fa, "NFM", lambda t: True), (fb, "NFM", lambda t: True)],
                                       max_hold_s=2.0, resume_s=2.0, squelch_db=10)
run(20)
print("bank", b, "windows", len(w._windows))
print("hits (mhz) over 20 s with max_hold=2 s:", [round(h["mhz"], 4) for h in hits])
print("channel B (%.4f) ever heard: %s" % (fb, any(abs(h["mhz"] - fb) < 1e-6 for h in hits)))
