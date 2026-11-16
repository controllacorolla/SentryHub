"""The Tk sstv.py app also uses sstv.Recorder: on stop it decodes r.path (decode_async(r.path)).
CL5-fix 12 made the file append-and-ROTATE at window_s (240 s). A PD120 frame recorded across a
rotation boundary is split between <path>.prev.wav and <path>; neither decodes. At the RA-CL5 tip
(ed4694a: rolling 240 s window rewritten whole) the same capture decodes. Same audio, both
Recorders, fed through the Recorder's own proc= test seam (a fake rtl_fm stdout)."""
import os
import subprocess
import sys
import tempfile
import time
import types
import numpy as np
import _harness as H

sys.path.insert(0, os.path.join(H.REPO, "tests"))
import test_sstvdec as T  # noqa: E402  (the repo's PD encoder)
import sstvdec as D  # noqa: E402

FS = 24000
img = T.make_pattern(640, 496)
frame = T.encode_pd(img, "PD120", FS, lead_s=1.0)                 # ~127 s of audio
rng = np.random.default_rng(1)
pre = (rng.standard_normal(200 * FS) * 300).astype(np.int16)      # 200 s of band noise first
post = (rng.standard_normal(10 * FS) * 300).astype(np.int16)
audio = np.concatenate([pre, np.asarray(frame, dtype=np.int16), post]).tobytes()
H.log("capture: %.0f s (frame at 200-%.0f s); rotation/window at 240 s" % (
    len(audio) / 2 / FS, 200 + len(frame) / FS))


def load(src_text, name):
    m = types.ModuleType(name)
    m.__file__ = os.path.join(H.REPO, "sstv.py")
    exec(compile(src_text, m.__file__, "exec"), m.__dict__)
    return m


tip = open(os.path.join(H.REPO, "sstv.py")).read()
old = subprocess.run(["git", "-C", H.REPO, "show", "ed4694a:sstv.py"], capture_output=True,
                     text=True).stdout
for label, src in (("RA-CL5 tip ed4694a (rolling window)", old), ("CL5-fix tip (append+rotate)", tip)):
    mod = load(src, "sstv_" + label.split()[0])
    mod.Recorder.FLUSH_S = 0.05
    mod.S.stop_group = lambda p, grace=1.0: None

    class Stdout:
        def __init__(self, b):
            self.b, self.i = b, 0

        def read(self, n):
            n = min(n, 9600)
            c = self.b[self.i:self.i + n]
            self.i += len(c)
            return c

    class Proc:
        stdout = Stdout(audio)
    d = tempfile.mkdtemp(prefix="rasstv")
    path = os.path.join(d, "iss_pass.wav")
    rec = mod.Recorder(path, 145.8, 40, monitor=False, proc=Proc())
    rec.thread.join(120)
    files = sorted(os.listdir(d))
    res = []
    for f in files:
        p = os.path.join(d, f)
        try:
            r = D.decode_wav(p)
            res.append("%s: DECODED %s %d lines" % (f, r["mode"], r["lines"]))
        except ValueError as e:
            res.append("%s: %s" % (f, str(e)[:60]))
        except Exception as e:
            res.append("%s: %s" % (f, type(e).__name__))
    H.log("%s -> files %s" % (label, files))
    for x in res:
        H.log("    decode_wav(%s" % x)
    try:
        r = D.decode_wav(path)
        H.log("    what the Tk app decodes on stop (r.path): DECODED %s" % r["mode"])
    except ValueError as e:
        H.log("    what the Tk app decodes on stop (r.path): FAILS - %s" % str(e)[:70])
