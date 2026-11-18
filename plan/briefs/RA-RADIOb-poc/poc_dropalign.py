"""drop_buffered discards a byte count that can be odd -> I/Q swap (spectrum mirrored)."""
import sys, os, time, socket, struct, threading
sys.path.insert(0, sys.argv[1])
import numpy as np, iqsource
lag = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1); port = srv.getsockname()[1]
def serve():
    c, _ = srv.accept()
    c.sendall(b"RTL0" + struct.pack(">II", 5, 29))
    threading.Thread(target=lambda: [c.recv(4096) for _ in iter(int, 1)], daemon=True).start()
    blk = bytes([200, 60]) * (262144 // 2)        # rtl_tcp-sized buffers, I=200 Q=60
    t = time.monotonic()
    while True:
        try: c.sendall(blk)
        except OSError: return
        t += len(blk) / 4.096e6                   # 2.048 Msps real time
        d = t - time.monotonic()
        if d > 0: time.sleep(d)
threading.Thread(target=serve, daemon=True).start()
class P:
    stdout = None
    def poll(self): return None
    def terminate(self): pass
s = iqsource.RtlTcpSource(121_500_000, 2048000, spawn=lambda a: P(), port=port).open()
swapped = odd = 0; N = 300; blocks = bad_blocks = 0
for n in range(N):
    for _ in range(4):
        raw, iq = s.read(0.05)
        a = np.frombuffer(raw, np.uint8); blocks += 1
        if len(a) and a[0::2].mean() < a[1::2].mean(): bad_blocks += 1
        if lag: time.sleep(lag)                    # DSP slower than real time
    s.set_freq(118_000_000 + n * 25000)
    raw, iq = s.read(0.01)
    a = np.frombuffer(raw, np.uint8)
    if a[0::2].mean() < a[1::2].mean():
        swapped += 1
print("lag %.3f s/block: retunes %d, retunes left I/Q swapped: %d; 50 ms blocks read swapped: %d/%d" % (lag, N, swapped, bad_blocks, blocks))
s.close()
