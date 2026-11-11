"""SSTV decoder for the PD family (what the ISS / ARISS events use: PD120, PD180...).

Pure numpy, offline: WAV in, RGB image out. Pipeline:
  audio -> instantaneous frequency (quadrature mix + FIR low-pass + phase difference)
        -> VIS header (which mode)            -> 20 ms 1200 Hz line-sync pulses
        -> straight-line fit of sync times    (sound-card / rtl_fm sample-rate error
                                               would otherwise slant the picture)
        -> per line pair: Y0, R-Y, B-Y, Y1     -> YCrCb -> RGB
Receive-only: decoding audio you recorded.
"""
import math
import wave

import numpy as np

# name: (VIS code, component ms, width, lines)  - sync 20 ms + porch 2.08 ms for all PD modes
PD_MODES = {
    "PD90": (99, 170.240, 320, 256),
    "PD120": (95, 121.600, 640, 496),
    "PD180": (96, 183.040, 640, 496),
    "PD240": (97, 244.480, 640, 496),
}
VIS_TO_MODE = {v[0]: k for k, v in PD_MODES.items()}
SYNC_MS, PORCH_MS = 20.0, 2.08
F_BLACK, F_WHITE = 1500.0, 2300.0


def group_ms(mode):
    return SYNC_MS + PORCH_MS + 4 * PD_MODES[mode][1]


# ---- audio -> instantaneous frequency ------------------------------------------------------
def read_wav(path):
    with wave.open(path, "rb") as w:
        fs, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("need 16-bit WAV, got %d-bit" % (8 * sw))
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, fs


def inst_freq(x, fs, f0=1900.0, chunk=1 << 18):
    """Frequency (Hz) per sample. Mixing to baseband around f0 and low-passing at ~1.1 kHz
    keeps the whole SSTV range (1100-2300 Hz) while rejecting the 2*f0 image."""
    taps = 63
    fc = 1100.0 / fs
    k = np.arange(taps) - (taps - 1) / 2
    h = (2 * fc * np.sinc(2 * fc * k) * np.hamming(taps)).astype(np.float32)
    out = np.empty(len(x), dtype=np.float32)
    n = np.arange(len(x))
    pos = 0
    while pos < len(x):                       # chunked: a 10-minute pass is ~7M samples
        end = min(len(x), pos + chunk)
        lo = max(0, pos - taps)
        seg = x[lo:end] * np.exp(-2j * np.pi * f0 * n[lo:end] / fs)
        z = np.convolve(seg, h, mode="same")
        ph = np.unwrap(np.angle(z))
        f = np.empty(len(ph), dtype=np.float32)
        f[1:] = np.diff(ph) * fs / (2 * np.pi) + f0
        f[0] = f[1] if len(f) > 1 else f0
        out[pos:end] = f[pos - lo:]
        pos = end
    # a short median-ish smoothing: kill single-sample phase glitches from noise
    m = max(1, int(fs * 0.0003))
    out = _movavg_same(out, m)
    return out


def _movsum_valid(a, w):
    """Sum over every length-w window (== np.convolve(a, ones(w), 'valid')) in O(n):
    a long window via convolve was O(n*w) - ~10 s on one 2-minute recording."""
    cs = np.concatenate(([0], np.cumsum(a, dtype=np.int64 if a.dtype.kind in "biu" else np.float64)))
    return cs[w:] - cs[:-w]


def _movavg_same(a, w):
    """Centred moving average, same length as a (== convolve(a, ones(w)/w, 'same'))."""
    if w <= 1:
        return a
    pad = np.concatenate((np.zeros(w // 2, a.dtype), a, np.zeros(w - 1 - w // 2, a.dtype)))
    return (_movsum_valid(pad, w) / w).astype(a.dtype)


# ---- VIS header ----------------------------------------------------------------------------
def find_vis(f, fs):
    """(mode, sample index where the image starts) or (None, None). VIS = 300 ms 1900 Hz,
    10 ms 1200, 300 ms 1900, 30 ms 1200 start bit, 7 data bits LSB first (1100 Hz = 1,
    1300 Hz = 0), even parity, 30 ms 1200 stop bit."""
    ms = fs / 1000.0
    # noisy passes scatter per-sample estimates by +-100 Hz; ~8 ms of averaging brings the
    # 300 ms leader tones back into a tight band without blurring 30 ms bits
    k = max(1, int(8 * ms))
    f = _movavg_same(f, k)
    lead = np.abs(f - 1900) < 60
    win = int(250 * ms)
    if len(f) < win * 3:
        return None, None
    run = _movsum_valid(lead.astype(np.int32), win)
    cands = np.flatnonzero(run >= int(0.9 * win))
    # where the signal leaves the leader band: a leader's end is a binary search away
    # (a per-sample Python walk took ~10 s on a 2-minute noisy recording)
    off = np.flatnonzero(np.abs(f - 1900) >= 150)
    limit = len(f) - int(30 * ms)
    i = 0
    while i < len(cands):
        st = cands[i]
        # second leader ends where the 1200 Hz start bit begins
        k = np.searchsorted(off, st + win)
        j = min(int(off[k]) if k < len(off) else limit, limit)
        # step into the start bit, then read 8 bits at their centres
        if abs(np.median(f[j:j + int(25 * ms)]) - 1200) < 80:
            bits = []
            for b in range(8):
                c = j + int((30 + 30 * b + 15) * ms)
                seg = f[c - int(8 * ms):c + int(8 * ms)]
                if len(seg) == 0:
                    break
                bits.append(1 if np.median(seg) < 1200 else 0)
            if len(bits) == 8:
                code = sum(bit << k for k, bit in enumerate(bits[:7]))
                parity_ok = (sum(bits[:7]) % 2) == bits[7]
                if parity_ok and code in VIS_TO_MODE:
                    return VIS_TO_MODE[code], j + int(30 * 10 * ms)    # start+8 bits+stop
        # resume where this leader ended: the 1st leader is followed by a 10 ms break, not
        # the start bit, so the real header is found on the 2nd leader right after it
        nxt = np.searchsorted(cands, j)
        i = max(i + 1, nxt)
    return None, None


# ---- line sync -----------------------------------------------------------------------------
def find_syncs(f, fs, start=0):
    """Sample indices of 20 ms 1200 Hz sync pulses (leading edges) from start on."""
    ms = fs / 1000.0
    low = (f[start:] < 1350).astype(np.int32)
    win = int(16 * ms)
    if len(low) < win:
        return np.array([], dtype=np.int64)
    run = _movsum_valid(low, win)
    hit = run >= int(0.85 * win)
    edges = np.flatnonzero(hit[1:] & ~hit[:-1]) + 1
    if hit[0]:
        edges = np.r_[0, edges]
    # a pulse is followed by at least 60 ms of image: drop edges inside the same pulse
    out, last = [], -10 ** 9
    span = int(32 * ms)
    for e in edges:
        if e - last <= 60 * ms:
            continue
        # the window test fires a few ms early; the pulse's true start is its centre of
        # mass minus 10 ms (robust to noise spikes at the edges, unlike a first-sample test)
        idx = np.flatnonzero(low[e:e + span])
        if len(idx) < 0.5 * win:
            continue
        mid = idx[(idx >= np.median(idx) - 12 * ms) & (idx <= np.median(idx) + 12 * ms)]
        out.append(int(e + mid.mean() - SYNC_MS / 2 * ms))
        last = e
    return np.asarray(out, dtype=np.int64) + start


def fit_line_timing(syncs, nominal):
    """Fit sync_k = t0 + k*period robustly. Real recordings drift (sample-rate error) and
    noise adds false/missing pulses, so: pair each pulse with its nearest group index,
    keep consistent ones, least-squares the rest."""
    if len(syncs) < 3:
        return None
    best = None
    for anchor in syncs[: min(len(syncs), 12)]:
        k = np.round((syncs - anchor) / nominal)
        resid = syncs - (anchor + k * nominal)
        ok = np.abs(resid) < 0.02 * nominal
        if best is None or ok.sum() > best[0]:
            best = (ok.sum(), anchor, k, ok)
    n, anchor, k, ok = best
    if n < 3:
        return None
    A = np.vstack([np.ones(n), k[ok]]).T
    (t0, period), *_ = np.linalg.lstsq(A, syncs[ok].astype(np.float64), rcond=None)
    t0 += k[ok].min() * period              # first group we actually saw
    return float(t0), float(period)


# ---- the image -----------------------------------------------------------------------------
def to_level(fr):
    return np.clip((fr - F_BLACK) * 255.0 / (F_WHITE - F_BLACK), 0, 255)


def ycc_to_rgb(y, cr, cb):
    r = y + 1.402 * (cr - 128)
    g = y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    return np.clip(np.stack([r, g, b], axis=-1), 0, 255).astype(np.uint8)


def decode_pd(f, fs, mode, t0, period):
    vis, comp_ms, width, lines = PD_MODES[mode]
    ms = fs / 1000.0
    groups = lines // 2
    img = np.zeros((lines, width, 3), dtype=np.uint8)
    pix = comp_ms * ms / width
    offs = (np.arange(width) + 0.5) * pix
    half = max(1, int(pix / 2))
    for g in range(groups):
        base = t0 + g * period + (SYNC_MS + PORCH_MS) * ms
        if base + 4 * comp_ms * ms >= len(f):
            img = img[: 2 * g]
            break
        comps = []
        for c in range(4):
            idx = (base + c * comp_ms * ms + offs).astype(np.int64)
            lo = np.clip(idx - half, 0, len(f) - 1)
            hi = np.clip(idx + half, 0, len(f) - 1)
            cs = np.cumsum(np.r_[0.0, f.astype(np.float64)[lo.min():hi.max() + 2]])
            a, b = lo - lo.min(), hi - lo.min() + 1
            comps.append(to_level((cs[b] - cs[a]) / np.maximum(1, b - a)))
        y0, cr, cb, y1 = comps
        img[2 * g] = ycc_to_rgb(y0, cr, cb)
        img[2 * g + 1] = ycc_to_rgb(y1, cr, cb)
    return img


def decode_wav(path, mode=None):
    """Decode one SSTV picture. Returns dict(mode, image (H,W,3 uint8), lines, slant_ppm)
    or raises ValueError with a reason a person can act on."""
    x, fs = read_wav(path)
    if fs < 8000:
        raise ValueError("sample rate %d Hz is too low for SSTV (need 8 kHz+)" % fs)
    f = inst_freq(x, fs)
    vmode, start = find_vis(f, fs)
    mode = mode or vmode
    if mode is None:
        raise ValueError("no SSTV header found - nothing was being sent, or the signal "
                         "was too weak (try the pass's highest part)")
    syncs = find_syncs(f, fs, start or 0)
    nominal = group_ms(mode) * fs / 1000.0
    fit = fit_line_timing(syncs, nominal)
    if fit is None:
        raise ValueError("found a %s header but no usable line syncs" % mode)
    t0, period = fit
    if start is not None:
        # the first line pair begins right after the VIS: if its sync was missed in noise,
        # step the fitted timing back so the picture isn't shifted down by a line pair
        t0 -= round((t0 - start) / period) * period
        if t0 < start - 0.05 * period:
            t0 += period
    img = decode_pd(f, fs, mode, t0, period)
    if len(img) < 4:
        raise ValueError("%s picture started but the recording ended" % mode)
    return {"mode": mode, "image": img, "lines": len(img),
            "slant_ppm": round((period / nominal - 1) * 1e6)}


def save_image(img, path):
    """PNG via Pillow when present (it is on the uConsole), else binary PPM."""
    try:
        from PIL import Image
        Image.fromarray(img).save(path)
        return path
    except ImportError:
        p = path.rsplit(".", 1)[0] + ".ppm"
        with open(p, "wb") as fh:
            fh.write(b"P6 %d %d 255\n" % (img.shape[1], img.shape[0]))
            fh.write(img.tobytes())
        return p
