"""Deterministic: a retune lands while a sample is half-arrived (TCP may split anywhere).
drop_buffered() throws away an odd byte count and clears _carry -> every later read has I and Q
swapped (complex conjugate = spectrum mirrored about the centre) until the next retune."""
import sys, os, time, socket, struct
sys.path.insert(0, sys.argv[1])
import numpy as np, iqsource, dsp
a, b = socket.socketpair()
b.sendall(b"RTL0" + struct.pack(">II", 5, 29))
class P:
    stdout = None
    def poll(self): return None
    def terminate(self): pass
s = iqsource.RtlTcpSource(121_500_000, 2048000, spawn=lambda av: P(), port=1, connect=lambda p: a).open()
rate, f0 = 2048000, 200_000.0                       # a tone 200 kHz ABOVE the centre
n = np.arange(400_000)
z = np.exp(2j * np.pi * f0 * n / rate) * 0.5
cu8 = np.empty(2 * len(z), np.uint8); cu8[0::2] = np.clip(127.5 + 127 * z.real, 0, 255); cu8[1::2] = np.clip(127.5 + 127 * z.imag, 0, 255)
data = cu8.tobytes()
b.sendall(data[:100001]); time.sleep(0.1)          # old-frequency IQ, last sample half-arrived
s.set_freq(122_000_000)                             # retune -> drop_buffered
b.sendall(data[100001:300001]); time.sleep(0.1)
raw, iq = s.read(0.05)
sp = np.fft.fftshift(np.abs(np.fft.fft(iq[:65536])))
fr = np.fft.fftshift(np.fft.fftfreq(65536, 1 / rate))
print("tone sent at %+.0f kHz, receiver sees it at %+.0f kHz" % (f0 / 1e3, fr[np.argmax(sp)] / 1e3))
