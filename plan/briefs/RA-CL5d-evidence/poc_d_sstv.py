"""RA-CL5d (N-m attack): a late SSTV decode from a STOPPED recorder.

Real BabelApp page, real SstvWorker QThread, real decode thread. Seams (as RA-CL5c's
poc_c_sstv_drop): the recorder (fake audio clock, accelerated) and the decoder (fake result).
radio_arbiter._make_lease is patched (instant FakeLease). fake rtl_fm on PATH so _sstv_ready passes.

  dup   : frame partly decoded (200 lines), a slow refinement decode (DECODE_S) is running when the
          operator presses STOP. Expect: the late result is a refinement of frame 1 -> ONE decode
          event total, page count 1.
  leak  : as dup, but the operator presses RUN again 0.3 s after STOP and the new RUN decodes its
          own frame before the late result lands. Expect: the new RUN's count/frames unaffected.
Usage: QT_QPA_PLATFORM=minimal python3 poc_d_sstv.py dup|leak [DECODE_S]
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "RA-CL5c-evidence"))
import _harness as H  # noqa: E402  (PATH fakebin, HOME tmp, QApplication, log/pump)
from palisade_qt import babel, radio_arbiter, eventbus  # noqa: E402
import numpy as np  # noqa: E402

which = sys.argv[1]
DECODE_S = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
radio_arbiter._make_lease = H.slow_make_lease(0.0)
FS = 22050
RATE = 13 * FS            # 13 s of audio per real second: one decode job per worker step


class Rec:
    err = ""
    level = 900.0

    def __init__(self, tag):
        self.tag, self.t0, self.stopped, self.last_base = tag, time.time(), False, 0

    def total_samples(self):
        return int((time.time() - self.t0) * RATE) if not self.stopped else self._n

    def seconds(self):
        return int(self.total_samples() / FS)

    def samples_since(self, a):
        self.last_base = int(a)
        n = max(0, self.total_samples() - int(a))
        return b"\0\0" * min(n, FS), int(a)        # content is irrelevant: the decoder is a seam

    def stop(self):
        self._n = self.total_samples()
        self.stopped = True
        H.log("REC.stop", self.tag)


RECS = []


def make_rec(self, path):
    r = Rec("rec%d" % (len(RECS) + 1))
    RECS.append(r)
    H.log("REC.start", r.tag)
    return r


FRAME_ABS = {}           # rec tag -> absolute start sample of the frame on that recorder
CALLS = []


def decode(self, x, fs):
    rec = self._rec_for_job
    n = len([c for c in CALLS if c[0] == rec.tag])
    CALLS.append((rec.tag, n))
    F = FRAME_ABS.setdefault(rec.tag, rec.last_base + 5000)
    if rec.tag == "rec1" and n == 0:
        lines, slow = 200, 0.0                          # frame 1 begins: 200 of 496 lines
    elif rec.tag == "rec1":
        lines, slow = 400, DECODE_S                     # its refinement — slow decode
    else:
        lines, slow = 150 + 50 * n, 0.0                 # the new RUN's own frame
    H.log("DECODE start", rec.tag, "call", n, "->", lines, "lines in", slow, "s")
    time.sleep(slow)
    H.log("DECODE done", rec.tag, "call", n)
    return {"image": np.zeros((lines, 64, 3), np.uint8), "mode": "PD120", "lines": lines,
            "start": F - rec.last_base, "t0": F - rec.last_base, "period": 0.5 * fs}


_orig_job = babel.SstvWorker._decode_job


def job(self, rec, fs):
    self._rec_for_job = rec
    return _orig_job(self, rec, fs)


babel.SstvWorker._make_recorder = make_rec
babel.SstvWorker._decode = decode
babel.SstvWorker._decode_job = job

page = babel.BabelApp(demo=False)
page.resize(1280, 720)
page.show()
page.set_active(True)
H.pump(0.3)
page.mode_combo.setCurrentText("SSTV")
H.pump(0.5)
ROWS = []


def hook_rows():
    w = page._worker
    w.row.connect(lambda r: ROWS.append((H.t(), r.get("frame"), r.get("lines"))))


hook_rows()


def events():
    return [e for e in eventbus.bus.recent(100, etype="decode") if e["source"] == "BABEL-SSTV"]


page.run_btn.setChecked(True)
H.log("RUN")
# wait until the slow refinement decode has started
end = time.monotonic() + 15
while time.monotonic() < end and not any(c == ("rec1", 1) for c in CALLS):
    H.pump(0.05)
H.pump(0.5)
page.run_btn.setChecked(False)
H.log("STOP pressed (refinement decode running)")
STOP_T = [H.t()]
if which == "leak":
    H.pump(0.3)
    page.run_btn.setChecked(True)
    H.log("RUN again")
H.pump(DECODE_S + 3.0)
page.run_btn.setChecked(False)
H.pump(1.5)
ev = events()
H.log("decode events:", len(ev), [e["payload"].get("summary") for e in ev])
H.log("rows (t, frame id, lines):", ROWS)
H.log("page count label:", page.count.text())
T_STOP = STOP_T[0]
rec1_frames = sorted({f for (_t, f, l) in ROWS if l in (200, 400) and (_t <= T_STOP or l == 400)})
H.log("frame ids used for rec1's ONE frame:", rec1_frames)
bad = []
if len([e for e in ev if "200 lines" in e["payload"].get("summary", "")
        or "400 lines" in e["payload"].get("summary", "")]) != 1:
    bad.append("rec1's single frame produced %d decode events (expect 1)" % len(
        [e for e in ev if "200 lines" in e["payload"].get("summary", "")
         or "400 lines" in e["payload"].get("summary", "")]))
if len(rec1_frames) != 1:
    bad.append("rec1's single frame shown under %d frame ids" % len(rec1_frames))
if not any(l == 400 for (_t, _f, l) in ROWS):
    bad.append("late refinement NOT shown")
if which == "leak" and page.count.text() != "2 frames":
    bad.append("page count after the new RUN reads %r (truth: 2 frames)" % page.count.text())
H.log("RESULT", which, "FAIL: " + "; ".join(bad) if bad else "clean")
page.stop()
H.pump(1.0)
H.log("arbiter", radio_arbiter.arbiter.state())
