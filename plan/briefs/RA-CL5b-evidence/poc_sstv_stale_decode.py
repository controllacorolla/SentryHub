"""SSTV (CL5-fix 12): the decode runs on a disposable thread and writes _decoded_upto /
_scan_from when it finishes. _stop_rec() (hide, STOP, revoke, PANIC, rtl_fm error) resets both to
0 for the NEXT recorder's sample clock. A decode that finishes after that reset writes the OLD
recorder's absolute sample count back. The next recorder starts at sample 0, so
`total - _decoded_upto >= DECODE_EVERY_S * RATE` stays false until it has recorded as long as the
old one had, plus 12 s: live SSTV silently stops decoding (an ISS pass is ~10 min)."""
import threading
import time
import numpy as np
import _harness as H
import sstv
from palisade_qt.babel import SstvWorker

RATE = sstv.RATE


class OldRec:                       # the recorder of the previous RUN, 40 min into a session
    def samples_since(self, s):
        time.sleep(0.5)             # the decode is CPU-bound; it is still running when we stop
        n = 12 * RATE
        return (np.zeros(n, dtype="<i2").tobytes(), 40 * 60 * RATE - n)


w = SstvWorker(demo=False)
w._decode = lambda x, fs: (_ for _ in ()).throw(ValueError("no SSTV header found - nothing"))
w._decoding = True
t = threading.Thread(target=w._decode_job, args=(OldRec(), RATE))
t.start()
time.sleep(0.1)
w._stop_rec()                       # operator hides BABEL / STOP / revoke: recorder torn down
H.log("right after _stop_rec: _decoded_upto=%d _scan_from=%d" % (w._decoded_upto, w._scan_from))
t.join()
H.log("after the old decode finished: _decoded_upto=%d (%.0f s) _scan_from=%d"
      % (w._decoded_upto, w._decoded_upto / RATE, w._scan_from))
# the next RUN: a fresh recorder, its sample clock restarts at 0
for secs in (12, 60, 600):
    total = secs * RATE
    will = (not w._decoding) and total - w._decoded_upto >= w.DECODE_EVERY_S * RATE
    H.log("new recorder at %4d s of audio -> step() starts a decode: %s" % (secs, will))
H.log("RESULT next decode only after %.0f s of new audio (should be 12 s)"
      % ((w._decoded_upto + w.DECODE_EVERY_S * RATE) / RATE))
