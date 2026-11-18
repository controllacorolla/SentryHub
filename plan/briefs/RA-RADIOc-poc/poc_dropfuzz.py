"""Fuzz B1: random odd TCP splits, random reads (incl. tiny/odd-carry states), random drops.
Every byte pair returned by read_bytes must be (I=200, Q=60)."""
import sys, os, time, socket, struct, threading, random
sys.path.insert(0, sys.argv[1])
import iqsource
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
rnd = random.Random(seed)
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1); port = srv.getsockname()[1]
def serve():
    c, _ = srv.accept()
    c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    c.sendall(b"RTL0" + struct.pack(">II", 5, 29))
    threading.Thread(target=lambda: [c.recv(4096) for _ in iter(int, 1)], daemon=True).start()
    r = random.Random(seed + 99); pos = 0
    stream = bytes([200, 60]) * 400000
    while True:
        k = r.choice([1, 3, 7, 1001, 4097, 65537, r.randint(1, 300000)])
        chunk = stream[pos % 2: pos % 2 + k] if False else None
        # build exactly k bytes continuing the pattern from pos
        start = pos % 2
        chunk = stream[start:start + k]
        try: c.sendall(chunk)
        except OSError: return
        pos += k
        if r.random() < 0.3: time.sleep(r.random() * 0.004)
threading.Thread(target=serve, daemon=True).start()
class P:
    stdout = None
    def poll(self): return None
    def terminate(self): pass
    def wait(self, timeout=None): return 0
    def kill(self): pass
s = iqsource.RtlTcpSource(121_500_000, 2048000, spawn=lambda a: P(), port=port).open()
bad = reads = drops = oddcarry_drops = 0
t0 = time.monotonic()
while time.monotonic() - t0 < float(sys.argv[3] if len(sys.argv) > 3 else 8):
    op = rnd.random()
    if op < 0.35:
        if s._carry: oddcarry_drops += 1
        s.set_freq(100_000_000 + rnd.randint(0, 1000) * 1000); drops += 1
    elif op < 0.45:
        time.sleep(rnd.random() * 0.003)
    else:
        n = rnd.choice([2, 4, 6, 102, 4096, 100000, 2 * rnd.randint(1, 50000)])
        out = s.read_bytes(n); reads += 1
        if len(out) % 2: bad += 1; continue
        if out[0::2].count(60) or out[1::2].count(200): bad += 1
print("seed %d reads %d drops %d drops-with-carry %d misaligned reads %d" % (seed, reads, drops, oddcarry_drops, bad))
