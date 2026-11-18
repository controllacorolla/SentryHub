import os, sys, traceback
WT = sys.argv[1]; sys.path[:0] = [WT, os.path.join(WT, "tests")]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import test_radio_sdrpp as T, banks, dsp
w, run, rows, hits, audio = T._scanner(T.AIR, [(131.55, "AM", lambda t: True)],
        priority=(121.5, "AM", 8330), priority_every_s=1.0, max_hold_s=0, resume_s=3)
# step until the worker is away on a priority check
for i in range(400):
    run(0.05)
    if getattr(w, "_detour", None) is not None: break
print("detour pending:", w._detour, "state:", w._state)
B = banks.BANKS["NOAA Wx"]
noaa = [(f, lb, B["mode"], B["bw"]) for f, lb in banks.expand(B)]
w.queue(channels=noaa, priority=None)        # operator picks another bank from the page
try:
    run(1.0)
    print("no crash; listen=", w._listen)
except Exception as e:
    print("process_block raised:", type(e).__name__, e)
    traceback.print_exc(limit=4)
