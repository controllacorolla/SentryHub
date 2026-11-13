"""Tests for the modulation classifier (Phase 6 #2), with synthetic IQ."""
import numpy as np

import classify

FS = 1_000_000
N = 8192
T = np.arange(N) / FS
RNG = np.random.default_rng(1)


def test_am_detected():
    am = (1 + 0.8 * np.sin(2 * np.pi * 3000 * T)).astype(complex)   # amplitude varies, freq ~0
    assert classify.classify(am, FS)[0] == "AM/OOK"


def test_fm_detected():
    msg = np.sin(2 * np.pi * 1500 * T)
    ph = 2 * np.pi * np.cumsum(80000 * msg) / FS
    assert classify.classify(np.exp(1j * ph), FS)[0] == "FM"


def test_fsk_detected():
    bits = np.repeat(RNG.integers(0, 2, N // 128), 128)[:N]
    ph = 2 * np.pi * np.cumsum(np.where(bits > 0, 60000, -60000)) / FS
    assert classify.classify(np.exp(1j * ph), FS)[0] == "FSK"


def test_psk_detected():
    sym = np.repeat(RNG.integers(0, 2, N // 128), 128)[:N]
    assert classify.classify(np.exp(1j * np.pi * sym), FS)[0] == "PSK"


def test_noise_is_wideband():
    noise = RNG.standard_normal(N) + 1j * RNG.standard_normal(N)
    assert classify.classify(noise, FS)[0] == "OFDM/wideband"


def test_short_signal_unknown():
    assert classify.classify([1 + 1j, 2 + 2j], FS)[0] == "unknown"


def test_suggest_decoder():
    assert "rtl_fm" in classify.suggest_decoder("FM")
    assert classify.suggest_decoder("nope") == "unknown"
