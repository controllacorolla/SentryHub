import os, sys
WT = sys.argv[1]; sys.path[:0] = [WT, os.path.join(WT, "tests")]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import test_radio_sdrpp as T
# same thing on the multi-window airband bank: strong A, weaker B in the SAME window
fa, fb = 124.35, 124.6
w, run, rows, hits, audio = T._scanner(T.AIR, [(fa, "AM", lambda t: True), (fa, "AM", lambda t: True), (fb, "AM", lambda t: True)],
                                       max_hold_s=2.0, resume_s=2.0, squelch_db=10)
run(25)
print("airband hits:", [round(h["mhz"], 4) for h in hits])
