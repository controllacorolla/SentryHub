"""RA-CL5c (N-e lock): a decode job that finishes a COMPLETE frame just after the operator presses
STOP (or hides BABEL / a revoke): _stop_rec swaps the recorder, so the job's result is dropped.
Real SstvWorker + real decode thread; the recorder and the decoder are seams (fake audio, a decode
that takes 0.5 s and returns a full PD120 frame). Run from this dir against any checkout:
  REPO=<checkout> QT_QPA_PLATFORM=minimal python3 poc_c_sstv_drop.py"""
import os
import sys
import threading
import time
sys.path.insert(0, os.environ.get("REPO", os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))))
from PySide6 import QtWidgets
APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
import numpy as np
from palisade_qt import babel


class Rec:
    n = 22050 * 130
    def samples_since(self, a):
        return b"\0\0" * (self.n - int(a)), int(a)
    def stop(self):
        pass


w = babel.SstvWorker(demo=False)
rows = []
w.row.connect(lambda r: rows.append(r))
rec = Rec()
w._rec = rec


def decode(x, fs):
    time.sleep(0.5)
    return {"image": np.zeros((496, 640, 3), np.uint8), "mode": "PD120", "lines": 496,
            "start": 1000, "t0": 1000, "period": 0.5 * fs}


w._decode = decode
t = threading.Thread(target=w._decode_job, args=(rec, 22050)); t.start()
time.sleep(0.2)
w._stop_rec()                      # operator presses STOP / hides the page mid-decode
t.join()
for _ in range(20):
    APP.processEvents()
print("complete PD120 frame decoded from audio captured BEFORE stop; rows shown:", len(rows),
      "->", "DROPPED" if not rows else "shown")
