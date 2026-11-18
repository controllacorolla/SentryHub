import os, sys, json, tempfile, traceback
WT = sys.argv[1]; sys.path[:0] = [WT]
home = tempfile.mkdtemp(); os.environ["HOME"] = home
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
import suite
CASES = {
 "prism.json": [
   "{not json",
   {"bookmarks": [1, "x", None, {"hz": "abc"}, {"hz": 1e30, "mode": "ZZ"}]},
   {"vfo_hz": -5, "mode": "XYZ", "bw": -1, "step": 0, "nfft": 3, "rate": 1, "deemph_us": "a"},
   {"vfo_hz": 1e400 if False else 9.9e18, "smooth": 7, "wf_lo": 10, "wf_hi": -200},
   {"squelch_db": None, "gain_db": "x", "ppm": 1e9},
 ],
 "prowl_scan.json": [
   "{not json",
   {"lockouts": ["abc", None, [1]]},
   {"bank_squelch": {"Airband (full)": "loud"}},
   {"bank": "nope", "priority_mhz": -1, "range_lo": 5000, "range_hi": 1, "range_step": 0},
   {"dwell": -1, "resume": -5, "max_hold": -1, "priority_every": 0, "range_mode": "ZZ", "priority_mode": 7},
   {"engine": "fast", "bank": "Custom range", "range_lo": 24, "range_hi": 1766, "range_step": 5000},
 ],
}
from palisade_qt.prism import PrismApp
from palisade_qt.prowl import ProwlApp
for fn, cases in CASES.items():
    for c in cases:
        p = os.path.join(suite.CFG, fn)
        for f in os.listdir(suite.CFG): os.remove(os.path.join(suite.CFG, f))
        with open(p, "w") as f:
            f.write(c if isinstance(c, str) else json.dumps(c))
        for cls in ((PrismApp,) if fn == "prism.json" else (ProwlApp,)):
            try:
                w = cls(demo=False, mode="dark"); w.resize(1152, 680); w.show()
                for _ in range(20): app.processEvents()
                if hasattr(w, "close"): w.close()
                print("OK   ", fn, str(c)[:90])
            except Exception as e:
                print("CRASH", fn, str(c)[:90], "->", type(e).__name__, e)
                traceback.print_exc(limit=3)
