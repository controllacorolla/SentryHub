"""Receive DSP for PRISM / PROWL — pure numpy, no Qt, no radio.

One IQ stream (8-bit unsigned interleaved I/Q as rtl_sdr / rtl_tcp send it, or a recording) feeds
two consumers, the way SDR++ works:

  * Spectrum   — windowed FFT, averaged per frame, in dBFS (a full-scale tone reads ~0 dB).
  * Demodulator — the VFO: shift the channel to DC, decimate, channel-filter, demodulate
                  (NFM / WFM / AM / USB / LSB / CW), squelch on channel power, optional audio
                  AGC, int16 audio out at `audio_rate`.

Everything here is block-in / block-out with carried state, so a stream cut into arbitrary blocks
gives the same audio as one long block (tests check this). FIR filtering is overlap-save FFT
convolution, so the cost is a few FFTs per block, not a Python loop per sample.
"""
import math

import numpy as np

MODES = ("NFM", "WFM", "AM", "USB", "LSB", "CW")

# default / minimum / maximum channel bandwidth per mode, Hz (SDR++-like defaults)
DEFAULT_BW = {"NFM": 12500, "WFM": 200000, "AM": 10000, "USB": 2800, "LSB": 2800, "CW": 500}
BW_LIMITS = {"NFM": (3000, 38000), "WFM": (50000, 250000), "AM": (1000, 38000),
             "USB": (500, 5000), "LSB": (500, 5000), "CW": (50, 3000)}
DEFAULT_STEP = {"NFM": 12500, "WFM": 100000, "AM": 25000, "USB": 100, "LSB": 100, "CW": 10}
CW_PITCH = 700.0            # Hz: a CW carrier at the VFO is heard as this tone
SSB_LOW_CUT = 50.0          # Hz: SSB passband starts this far from the carrier
SAMPLE_RATES = (250000, 1024000, 1400000, 1800000, 2048000, 2400000)
# R820T/R828D tuner gain steps (dB) — what rtl_tcp / rtl_sdr accept on the common dongles
RTL_GAINS = (0.0, 0.9, 1.4, 2.7, 3.7, 7.7, 8.7, 12.5, 14.4, 15.7, 16.6, 19.7, 20.7, 22.9, 25.4,
             28.0, 29.7, 32.8, 33.8, 36.4, 37.2, 38.6, 40.2, 42.1, 43.4, 43.9, 44.5, 48.0, 49.6)


def clamp_bw(mode, bw):
    lo, hi = BW_LIMITS[mode]
    return float(min(hi, max(lo, float(bw))))


def cu8_to_iq(buf):
    """uint8 interleaved I/Q bytes -> complex64 in [-1, 1). An odd trailing byte is ignored."""
    a = np.frombuffer(buf, dtype=np.uint8)
    if a.size % 2:
        a = a[:-1]
    f = a.astype(np.float32)
    f -= 127.5
    f *= 1.0 / 127.5
    return (f[0::2] + 1j * f[1::2]).astype(np.complex64)


def iq_to_cu8(iq):
    """complex -> uint8 interleaved I/Q (for synthesised sources and tests)."""
    iq = np.asarray(iq)
    out = np.empty(iq.size * 2, dtype=np.float32)
    out[0::2] = iq.real
    out[1::2] = iq.imag
    return np.clip(np.round(out * 127.5 + 127.5), 0, 255).astype(np.uint8).tobytes()


# ---------------------------------------------------------------- filters

def lowpass_taps(cutoff, fs, transition):
    """Blackman-windowed sinc low-pass, unity DC gain. Length from the transition width."""
    n = int(math.ceil(5.5 * fs / max(1.0, float(transition))))
    n = max(15, min(n, 4095))
    if n % 2 == 0:
        n += 1
    m = np.arange(n) - (n - 1) / 2.0
    fc = float(cutoff) / fs
    h = 2 * fc * np.sinc(2 * fc * m) * np.blackman(n)
    h /= h.sum()
    return h.astype(np.float64)


def bandpass_taps(f_lo, f_hi, fs, transition):
    """Complex band-pass passing f_lo..f_hi (Hz, may be negative): a low-pass of half the width
    shifted to the band centre. Unity gain at the centre."""
    half = (f_hi - f_lo) / 2.0
    h = lowpass_taps(half, fs, transition)
    m = np.arange(h.size) - (h.size - 1) / 2.0
    return (h * np.exp(2j * np.pi * ((f_lo + f_hi) / 2.0) / fs * m)).astype(np.complex128)


def deemphasis_taps(tau_s, fs):
    """FIR of a first-order de-emphasis (RC = tau), truncated at 6 tau, unity DC gain."""
    if not tau_s:
        return np.ones(1)
    a = math.exp(-1.0 / (tau_s * fs))
    k = max(2, int(6 * tau_s * fs))
    h = (1 - a) * a ** np.arange(k)
    return h / h.sum()


class OSFilter:
    """Overlap-save FIR with integer decimation. State is carried between blocks: the output of
    any split of a stream equals the output of the whole stream."""

    def __init__(self, taps, decim=1):
        self.taps = np.asarray(taps)
        self.decim = max(1, int(decim))
        self._m = self.taps.size
        self._hist = np.zeros(self._m - 1, dtype=np.complex64)
        self._phase = 0
        self._H = {}

    def _resp(self, nfft):
        H = self._H.get(nfft)
        if H is None:
            H = np.fft.fft(self.taps, nfft).astype(np.complex64)
            self._H = {nfft: H}
        return H

    def process(self, x):
        x = np.asarray(x, dtype=np.complex64)
        if x.size == 0:
            return x
        buf = np.concatenate((self._hist, x))
        nfft = 1 << int(math.ceil(math.log2(buf.size)))
        y = np.fft.ifft(np.fft.fft(buf, nfft) * self._resp(nfft))
        y = y[self._m - 1:self._m - 1 + x.size].astype(np.complex64)
        if self._m > 1:
            self._hist = buf[-(self._m - 1):]
        out = y[self._phase::self.decim]
        self._phase = (self._phase - x.size) % self.decim
        return out


class Mixer:
    """Multiply by exp(-j 2 pi f t) with a phase that carries across blocks."""

    def __init__(self):
        self._ph = 0.0

    def process(self, x, f_hz, fs):
        w = -2.0 * math.pi * float(f_hz) / fs
        n = np.arange(x.size, dtype=np.float64)
        out = x * np.exp(1j * (self._ph + w * n)).astype(np.complex64)
        self._ph = (self._ph + w * x.size) % (2 * math.pi)
        return out.astype(np.complex64)


# ---------------------------------------------------------------- spectrum

class Spectrum:
    """Averaged, windowed FFT of the stream. process(iq) -> dBFS per bin, DC in the middle
    (bins ordered low -> high frequency), or None until nfft samples have arrived."""

    def __init__(self, nfft=8192):
        self.nfft = int(nfft)
        self._w = np.blackman(self.nfft).astype(np.float32)
        self._norm = float(self._w.sum())
        self._carry = np.zeros(0, dtype=np.complex64)

    def reset(self):
        """Forget buffered samples (after a retune they belong to another frequency)."""
        self._carry = np.zeros(0, dtype=np.complex64)

    def process(self, iq):
        buf = np.concatenate((self._carry, np.asarray(iq, dtype=np.complex64)))
        k = buf.size // self.nfft
        if k == 0:
            self._carry = buf[-self.nfft:]
            return None
        segs = buf[:k * self.nfft].reshape(k, self.nfft)
        self._carry = buf[k * self.nfft:]
        X = np.fft.fft(segs * self._w, axis=1)
        p = np.mean((X.real ** 2 + X.imag ** 2), axis=0) / (self._norm ** 2)
        return np.fft.fftshift(10.0 * np.log10(p + 1e-20)).astype(np.float32)

    @staticmethod
    def bin_freqs(nfft, fs, centre_hz):
        """Absolute frequency (Hz) of each bin process() returns."""
        return centre_hz + (np.arange(nfft) - nfft // 2) * (fs / nfft)


def noise_floor_db(spec_db):
    """Robust floor estimate: the median bin (signals occupy a minority of the bins)."""
    return float(np.median(spec_db))


def channel_levels(spec_db, fs, centre_hz, freqs_hz, bw_hz):
    """Peak bin level (dBFS) within +/- bw/2 of each channel frequency. Channels outside the
    captured band get None. Used by the scanner to judge many channels from one capture."""
    n = spec_db.size
    bin_hz = fs / n
    out = []
    half = max(bin_hz, bw_hz / 2.0)
    for f in freqs_hz:
        off = f - centre_hz
        lo = int(math.floor((off - half) / bin_hz)) + n // 2
        hi = int(math.ceil((off + half) / bin_hz)) + n // 2
        if lo < 0 or hi >= n:
            out.append(None)
            continue
        out.append(float(np.max(spec_db[lo:hi + 1])))
    return out


# ---------------------------------------------------------------- the VFO

class Demodulator:
    """One VFO. configure() (re)builds the chain; process(iq) -> (int16 audio, level_db, open).

    level_db is the channel power in dBFS after the channel filter — the number the squelch is
    compared with (squelch_db None = squelch off). The squelch has 2 dB of hysteresis."""

    SQ_HYST_DB = 2.0

    def __init__(self, fs, mode="NFM", bw=None, offset_hz=0.0, squelch_db=None, agc=None,
                 deemph_us=75):
        self.fs = int(fs)
        self.offset_hz = float(offset_hz)
        self.squelch_db = squelch_db
        self._open = False
        self.deemph_us = deemph_us
        self.configure(mode, bw, agc)

    # ---- configuration
    def configure(self, mode=None, bw=None, agc=None):
        mode = (mode or getattr(self, "mode", "NFM")).upper()
        if mode not in MODES:
            raise ValueError("unknown mode %r" % mode)
        if bw is None:
            bw = DEFAULT_BW[mode] if mode != getattr(self, "mode", None) else self.bw
        self.mode = mode
        self.bw = clamp_bw(mode, bw)
        self.agc = (mode in ("AM", "USB", "LSB", "CW")) if agc is None else bool(agc)
        fs = self.fs
        if mode == "WFM":
            d1 = max(1, fs // 240000)
        else:
            d1 = max(1, fs // 48000)
        self.mid = fs / d1
        if mode != "WFM":
            self.bw = min(self.bw, 0.8 * self.mid)
        # stage 1: decimating low-pass at the full rate (anti-alias for the mid rate)
        edge = self._edges()
        reach = max(abs(edge[0]), abs(edge[1]))
        stop = self.mid - reach                     # first frequency that aliases into the band
        cutoff = min(reach + 0.1 * self.bw + 200, 0.45 * self.mid)
        trans = max(stop - cutoff, 0.05 * self.mid)
        self._s1 = OSFilter(lowpass_taps(cutoff + trans / 2 if d1 > 1 else 0.49 * fs, fs,
                                         trans if d1 > 1 else 0.02 * fs), d1)
        # stage 2: the channel filter at the mid rate (exact passband, complex for SSB/CW)
        sharp = max(100.0, 0.08 * self.bw) if mode in ("USB", "LSB", "CW") else max(
            500.0, 0.15 * self.bw)
        if mode in ("USB", "LSB", "CW"):
            self._s2 = OSFilter(bandpass_taps(edge[0], edge[1], self.mid, sharp))
        else:
            self._s2 = OSFilter(lowpass_taps(self.bw / 2.0, self.mid, sharp))
        # audio filter + decimation to the audio rate
        if mode == "WFM":
            d2 = max(1, int(self.mid // 48000))
            taps = np.convolve(lowpass_taps(15000, self.mid, 4000),
                               deemphasis_taps((self.deemph_us or 0) * 1e-6, self.mid))
            self._audio = OSFilter(taps, d2)
            self.dev = 75000.0
        else:
            d2 = 1
            cut = {"NFM": min(self.bw / 2.0, 5000.0), "AM": self.bw / 2.0}.get(mode)
            self._audio = OSFilter(lowpass_taps(cut, self.mid, max(300.0, 0.2 * cut)))\
                if cut else None
            self.dev = max(1000.0, self.bw / 2.0 - 1000.0)
        self.audio_rate = int(round(self.mid / d2))
        self._mix = Mixer()
        self._last = np.complex64(0)
        self._dc = None
        self._gain = 1.0
        self._peak = 0.0

    def _edges(self):
        """Channel passband relative to the (shifted) carrier, Hz."""
        if self.mode == "USB":
            return (SSB_LOW_CUT, self.bw)
        if self.mode == "LSB":
            return (-self.bw, -SSB_LOW_CUT)
        if self.mode == "CW":
            return (CW_PITCH - self.bw / 2.0, CW_PITCH + self.bw / 2.0)
        return (-self.bw / 2.0, self.bw / 2.0)

    def set_offset(self, offset_hz):
        self.offset_hz = float(offset_hz)

    # ---- processing
    def process(self, iq):
        iq = np.asarray(iq, dtype=np.complex64)
        shift = self.offset_hz - (CW_PITCH if self.mode == "CW" else 0.0)
        x = self._mix.process(iq, shift, self.fs)
        x = self._s1.process(x)
        x = self._s2.process(x)
        if x.size == 0:
            return np.zeros(0, dtype=np.int16), -200.0, self._open
        level = 10.0 * math.log10(float(np.mean(x.real ** 2 + x.imag ** 2)) + 1e-20)
        a = self._demod(x)
        if self._audio is not None:
            a = self._audio.process(a).real
        a = np.asarray(a, dtype=np.float32)
        if self.agc:
            a = self._apply_agc(a)
        if self.squelch_db is None:
            self._open = True
        else:
            thr = float(self.squelch_db) - (self.SQ_HYST_DB if self._open else 0.0)
            self._open = level >= thr
        if not self._open:
            a = np.zeros_like(a)
        pcm = np.clip(a, -1.0, 1.0)
        return (pcm * 32767).astype(np.int16), level, self._open

    def _demod(self, x):
        m = self.mode
        if m in ("NFM", "WFM"):
            prev = np.concatenate(([self._last], x[:-1]))
            self._last = x[-1]
            d = np.angle(x * np.conj(prev))
            return (d * (self.mid / (2 * math.pi * self.dev))).astype(np.float32)
        if m == "AM":
            env = np.abs(x).astype(np.float32)
            mean = float(np.mean(env))
            self._dc = mean if self._dc is None else 0.9 * self._dc + 0.1 * mean
            return (env - self._dc) / max(self._dc, 1e-6)
        return x.real.astype(np.float32)            # USB / LSB / CW: the filter did the work

    AGC_TARGET = 0.3           # RMS the AGC aims for
    AGC_MAX_GAIN = 2000.0      # +66 dB
    AGC_DECAY = 1.25           # at most x1.25 gain rise per block (slow recovery)

    def _apply_agc(self, a):
        if a.size == 0:
            return a
        rms = float(np.sqrt(np.mean(a.astype(np.float64) ** 2)))
        peak = float(np.max(np.abs(a)))
        want = self.AGC_TARGET / max(rms, 1e-6)
        if peak * want > 0.95:
            want = 0.95 / max(peak, 1e-9)
        want = min(want, self.AGC_MAX_GAIN)
        g0 = self._gain
        g1 = want if want < g0 else min(want, g0 * self.AGC_DECAY)   # fast attack, slow decay
        self._gain = g1
        ramp = np.linspace(g0, g1, a.size, dtype=np.float32)
        out = a * ramp
        # the start of a block may still be over the old (higher) gain: hard limit, no wrap
        return np.clip(out, -1.0, 1.0)
