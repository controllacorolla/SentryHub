"""SSTV decoder round-trip. The encoder here exists only to make test audio files - it
generates samples into a WAV, nothing is transmitted."""
import math
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sstvdec as D  # noqa: E402


def _tone_writer(fs):
    st = {"phase": 0.0, "out": [], "t_err": 0.0}

    def tone(freq, ms):
        exact = ms * fs / 1000.0 + st["t_err"]
        n = int(exact)
        st["t_err"] = exact - n
        if n <= 0:
            return
        ph = st["phase"] + 2 * np.pi * np.cumsum(np.full(n, freq if np.isscalar(freq) else 0))
        st["out"].append(np.sin(ph))
        st["phase"] = ph[-1]

    def sweep(freqs, ms):            # one tone per pixel, continuous phase
        exact = ms * fs / 1000.0 + st["t_err"]
        n = int(exact)
        st["t_err"] = exact - n
        idx = np.minimum((np.arange(n) * len(freqs) / n).astype(int), len(freqs) - 1)
        inc = 2 * np.pi * np.asarray(freqs)[idx] / fs
        ph = st["phase"] + np.cumsum(inc)
        st["out"].append(np.sin(ph))
        st["phase"] = ph[-1]

    def fixed_tone(freq, ms):
        exact = ms * fs / 1000.0 + st["t_err"]
        n = int(exact)
        st["t_err"] = exact - n
        ph = st["phase"] + 2 * np.pi * freq / fs * np.arange(1, n + 1)
        st["out"].append(np.sin(ph))
        st["phase"] = ph[-1]
    return fixed_tone, sweep, st


def make_pattern(w, h):
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[..., 0] = (xx * 255 // max(1, w - 1))                       # red ramp left->right
    img[..., 1] = (yy * 255 // max(1, h - 1))                       # green ramp top->bottom
    img[..., 2] = np.where((xx // 40 + yy // 40) % 2 == 0, 220, 30)  # blue checkerboard
    return img


def rgb_to_ycc(img):
    r, g, b = [img[..., i].astype(float) for i in range(3)]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return y, cr, cb


def encode_pd(img, mode, fs, rate_err=0.0, noise=0.0, lead_s=1.0):
    """PD-mode test audio. rate_err stretches time like a mis-clocked sound card."""
    vis, comp_ms, w, h = D.PD_MODES[mode]
    fs_eff = fs * (1 + rate_err)
    tone, sweep, st = _tone_writer(fs_eff)
    lvl = lambda v: D.F_BLACK + np.clip(v, 0, 255) * (D.F_WHITE - D.F_BLACK) / 255.0  # noqa
    tone(1500, lead_s * 1000)                          # dead air before the transmission
    tone(1900, 300); tone(1200, 10); tone(1900, 300); tone(1200, 30)
    bits = [(vis >> k) & 1 for k in range(7)]
    bits.append(sum(bits) % 2)
    for b in bits:
        tone(1100 if b else 1300, 30)
    tone(1200, 30)
    y, cr, cb = rgb_to_ycc(img)
    for g in range(h // 2):
        tone(1200, D.SYNC_MS)
        tone(1500, D.PORCH_MS)
        cr_avg = (cr[2 * g] + cr[2 * g + 1]) / 2
        cb_avg = (cb[2 * g] + cb[2 * g + 1]) / 2
        for comp in (y[2 * g], cr_avg, cb_avg, y[2 * g + 1]):
            sweep(lvl(comp), comp_ms)
    tone(1500, 500)
    x = np.concatenate(st["out"])
    if noise:
        x = x + np.random.default_rng(7).normal(0, noise, len(x))
    return (np.clip(x * 0.6, -1, 1) * 32767).astype("<i2")


def write_wav(path, samples, fs):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(samples.tobytes())


def _err(a, b):
    h = min(len(a), len(b))
    return float(np.mean(np.abs(a[:h].astype(int) - b[:h].astype(int))))


def test_pd120_clean_roundtrip(tmp_path):
    img = make_pattern(640, 496)
    p = tmp_path / "pd120.wav"
    write_wav(p, encode_pd(img, "PD120", 12000), 12000)
    r = D.decode_wav(str(p))
    assert r["mode"] == "PD120" and r["lines"] == 496
    assert _err(r["image"], img) < 12, _err(r["image"], img)


def _block_err(a, b):
    """Noise averages out over 16x16 blocks; slant, shift or colour errors don't."""
    blk = lambda x: x[:480, :640].astype(float).reshape(30, 16, 40, 16, 3).mean(axis=(1, 3))  # noqa
    return float(np.mean(np.abs(blk(a) - blk(b))))


def test_pd120_clock_error_is_corrected(tmp_path):
    # rtl_fm / sound cards are rarely exactly on rate: 300 ppm slants ~5 px uncorrected
    img = make_pattern(640, 496)
    p = tmp_path / "pd120_clock.wav"
    write_wav(p, encode_pd(img, "PD120", 12000, rate_err=300e-6), 12000)
    r = D.decode_wav(str(p))
    assert abs(r["slant_ppm"] - 300) < 60          # it measured the clock error ...
    assert _err(r["image"], img) < 8, _err(r["image"], img)   # ... and corrected it


def test_pd120_noisy_pass_keeps_structure(tmp_path):
    # a weak ISS pass: header still decodes, picture is grainy but aligned and in colour
    img = make_pattern(640, 496)
    p = tmp_path / "pd120_noisy.wav"
    write_wav(p, encode_pd(img, "PD120", 12000, rate_err=300e-6, noise=0.35), 12000)
    r = D.decode_wav(str(p))
    assert r["mode"] == "PD120" and abs(r["slant_ppm"] - 300) < 60
    assert _block_err(r["image"], img) < 15, _block_err(r["image"], img)


def test_pd90_detected_by_vis(tmp_path):
    img = make_pattern(320, 256)
    p = tmp_path / "pd90.wav"
    write_wav(p, encode_pd(img, "PD90", 11025), 11025)
    r = D.decode_wav(str(p))
    assert r["mode"] == "PD90" and r["image"].shape[1] == 320


def test_no_signal_gives_actionable_error(tmp_path):
    p = tmp_path / "hiss.wav"
    noise = (np.random.default_rng(1).normal(0, 0.3, 12000 * 5) * 32767).astype("<i2")
    write_wav(p, noise, 12000)
    try:
        D.decode_wav(str(p))
        raise AssertionError("decoded a picture out of hiss")
    except ValueError as e:
        assert "no SSTV header" in str(e)


def test_truncated_recording_keeps_what_arrived(tmp_path):
    img = make_pattern(640, 496)
    full = encode_pd(img, "PD120", 12000)
    p = tmp_path / "cut.wav"
    write_wav(p, full[: len(full) // 2], 12000)       # pass ended halfway through
    r = D.decode_wav(str(p))
    assert 200 < r["lines"] < 300
    assert _err(r["image"], img[: r["lines"]]) < 12


def test_save_image(tmp_path):
    out = D.save_image(make_pattern(64, 32), str(tmp_path / "x.png"))
    assert os.path.getsize(out) > 0


def test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone(tmp_path, monkeypatch):
    import importlib, time
    sys.path.insert(0, os.path.dirname(__file__))
    from iss_tle_fixture import iss_tle
    import wxsat, sstv
    weather_cache = os.path.join(wxsat.S.CACHE, "wx_passes.json")
    before = os.path.getmtime(weather_cache) if os.path.exists(weather_cache) else None
    tle = tmp_path / "sstv.tle"
    tle.write_text(iss_tle())
    passes = wxsat.predict(sstv.SATS, {"lat": 39.62, "lon": -104.87}, 48, path=str(tle))
    assert passes, "a 51.6-degree orbit always passes over Denver within 48 h"
    p = passes[0]
    assert p["sat"] == "ISS" and p["los"] > p["aos"] and 10 <= p["max"] <= 90
    # ISS passes last from seconds (a pass grazing right at the 10-degree cutoff) up to ~12 minutes
    # (a high overhead pass). The first pass in the window can be either, and los > aos is already
    # asserted above, so the only real invariant is "minutes, not hours" — the <=12 upper bound.
    # (This used to flake by wall clock when the first pass happened to be a short grazing one.)
    assert 0 < (p["los"] - p["aos"]) / 60 <= 12
    after = os.path.getmtime(weather_cache) if os.path.exists(weather_cache) else None
    assert before == after                               # weather sats' cache untouched
    assert "NOW" in sstv.pass_line(dict(p, aos=time.time() - 60, los=time.time() + 60))
