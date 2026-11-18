import sys; sys.path.insert(0, sys.argv[1])
import numpy as np, dsp
fs = 2048000; n = fs  # 1 s
t = np.arange(n) / fs
def tone_db(a, rate, f):
    a = a.astype(np.float64)[len(a)//4:]
    X = np.abs(np.fft.rfft(a * np.hanning(a.size)))
    fr = np.fft.rfftfreq(a.size, 1/rate)
    k = np.argmin(abs(fr - f)); return 20*np.log10(X[max(0,k-3):k+4].max() + 1e-9)
for off in (-612_345, 0.0, 333_333, 850_000):
    x = (0.05*np.exp(2j*np.pi*(off+1000)*t) + 0.05*np.exp(2j*np.pi*(off-1500)*t)
         + 0.002*(np.random.randn(n)+1j*np.random.randn(n))).astype(np.complex64)
    for mode in ("USB", "LSB"):
        d = dsp.Demodulator(fs, mode, offset_hz=off)
        out = np.concatenate([d.process(x[i:i+102400])[0] for i in range(0, n, 102400)])
        a1, a2 = tone_db(out, d.audio_rate, 1000), tone_db(out, d.audio_rate, 1500)
        print("off=%+9.0f %s  1000Hz=%.1f dB  1500Hz=%.1f dB  rejection=%+.1f dB" % (off, mode, a1, a2, (a1-a2) if mode=="USB" else (a2-a1)))
# squelch = channel power? strong out-of-channel signal must not open squelch
x = (0.5*np.exp(2j*np.pi*(25_000)*t) + 0.001*(np.random.randn(n)+1j*np.random.randn(n))).astype(np.complex64)
d = dsp.Demodulator(fs, "NFM", offset_hz=0, squelch_db=-50)
_, lv, op = d.process(x[:204800]); _, lv, op = d.process(x[204800:409600])
print("strong carrier 25 kHz away (0.5 FS): channel level %.1f dBFS, squelch -50 open=%s" % (lv, op))
for m in dsp.MODES:
    print(m, "clamp 1 ->", dsp.clamp_bw(m, 1), " clamp 1e9 ->", dsp.clamp_bw(m, 1e9), " at 250k rate bw:", dsp.Demodulator(250000, m, 1e9).bw)
