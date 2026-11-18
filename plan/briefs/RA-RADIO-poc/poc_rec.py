import os, sys, tempfile, wave, numpy as np
sys.path.insert(0, sys.argv[1]); import iqsource
d = tempfile.mkdtemp()
iqsource.MIN_FREE_BYTES = 1 << 60
a = iqsource.AudioRecorder(121500000, "AM", 48000, directory=d); a.write(np.ones(4800, np.int16))
print("audio guard stopped:", a.stopped_reason, "| wav valid:", wave.open(a.path).getnframes())
r = iqsource.IqRecorder(121500000, 2048000, directory=d); r.write(b"\x80" * 1000)
print("iq guard stopped:", r.stopped_reason, "bytes", r.bytes)
iqsource.MIN_FREE_BYTES = 0
r1 = iqsource.IqRecorder(121500000, 2048000, directory=d); r1.write(b"\x10" * 4000); r1.close()
r2 = iqsource.IqRecorder(121500000, 2048000, directory=d); r2.write(b"\x20" * 10); r2.close()
print("two IQ recordings in the same second share a path:", r1.path == r2.path, "size now", os.path.getsize(r1.path))
