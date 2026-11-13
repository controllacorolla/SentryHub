#!/usr/bin/env python3
"""classify.py — automatic modulation classifier (Phase 6 #2).

Takes a complex IQ capture and estimates the modulation (AM/OOK, FM, FSK, PSK, or wideband/OFDM)
from simple, explainable features: envelope variation (amplitude modulation), instantaneous-
frequency spread and bimodality (FM vs FSK), phase clustering (PSK), and spectral flatness
(OFDM/noise). It returns a label, a confidence, and the features, plus a suggested decoder family.

Heuristic, not a trained model — meant as a triage hint. Pure numpy; unit-testable with
synthetic signals. No Tk dependency in the helpers.
"""
import os
import sys


def features(iq, fs):
    """Compute classification features from complex IQ sampled at fs."""
    import numpy as np
    x = np.asarray(iq, dtype=np.complex128)
    n = len(x)
    if n < 8:
        return {"n": n, "env_cv": 0.0, "freq_mad": 0.0, "freq_sustained": 0.0,
                "freq_bimodal": 0.0, "phase_clusters": 0, "flatness": 0.0, "occ_bw": 0.0}
    env = np.abs(x)
    env_mean = float(env.mean()) or 1e-12
    env_cv = float(env.std() / env_mean)                      # amplitude variation

    inst_f = np.diff(np.unwrap(np.angle(x))) * fs / (2 * np.pi)
    f_norm = inst_f / (fs / 2)                                 # normalized to +-1
    med = np.median(f_norm)
    # ROBUST spread (median abs deviation): insensitive to the sparse large frequency spikes a
    # PSK phase jump produces, so PSK (near-zero MAD) separates cleanly from FM/FSK.
    freq_mad = float(np.median(np.abs(f_norm - med)))
    freq_sustained = float(np.median(np.abs(f_norm)))          # steady carrier offset / deviation
    # bimodality of instantaneous frequency (FSK has two clusters): split at median, compare means
    lo, hi = f_norm[f_norm < med], f_norm[f_norm >= med]
    freq_bimodal = 0.0
    if len(lo) > 2 and len(hi) > 2:
        sep = abs(hi.mean() - lo.mean())
        spread = (lo.std() + hi.std()) / 2 + 1e-9
        freq_bimodal = float(sep / spread)

    # phase-constellation clustering (PSK): count dominant bins in the wrapped-phase histogram
    ph = np.angle(x)
    hist, _ = np.histogram(ph, bins=16, range=(-np.pi, np.pi))
    peak = hist.max() or 1
    phase_clusters = int(np.sum(hist > 0.5 * peak))

    win = np.hanning(n)
    spec = np.abs(np.fft.fft(x * win)) ** 2
    tot = spec.sum() or 1e-12
    specn = spec / tot
    nz = specn[specn > 0]
    flatness = float(np.exp(np.mean(np.log(nz))) / np.mean(nz)) if len(nz) else 0.0
    occ_bw = float((np.cumsum(np.sort(specn)[::-1]) < 0.9).sum() + 1) / n
    return {"n": n, "env_cv": env_cv, "freq_mad": freq_mad, "freq_sustained": freq_sustained,
            "freq_bimodal": freq_bimodal, "phase_clusters": phase_clusters,
            "flatness": flatness, "occ_bw": occ_bw}


DECODER_HINT = {"AM/OOK": "AM demod / OOK (rtl_433)", "FM": "FM demod (rtl_fm)",
                "FSK": "2-FSK (rtl_433 / multimon-ng)", "PSK": "PSK (fldigi / gnuradio)",
                "OFDM/wideband": "wideband — DAB/DVB/Wi-Fi or noise"}


def classify(iq, fs):
    """Return (label, confidence 0-1, features). Heuristic triage of the modulation type."""
    f = features(iq, fs)
    if f["n"] < 8:
        return "unknown", 0.0, f
    # Wide and spectrally flat -> OFDM / noise / spread spectrum.
    if f["flatness"] > 0.35 and f["occ_bw"] > 0.25:
        return "OFDM/wideband", min(1.0, f["flatness"]), f
    # Strong amplitude variation -> AM / OOK / CW.
    if f["env_cv"] > 0.35:
        return "AM/OOK", min(1.0, f["env_cv"]), f
    # Constant envelope with a SUSTAINED instantaneous-frequency offset/deviation -> FM or FSK.
    # (PSK sits near zero here because its phase jumps are sparse spikes, not sustained.) FSK's
    # instantaneous frequency is two tight discrete levels (high bimodality); FM's varies smoothly.
    if f["freq_sustained"] > 0.03:
        if f["freq_bimodal"] > 4.5:
            return "FSK", min(1.0, f["freq_bimodal"] / 6), f
        return "FM", min(1.0, f["freq_sustained"] * 5), f
    # Constant envelope, no sustained frequency offset, a few phase clusters -> PSK.
    if 2 <= f["phase_clusters"] <= 8:
        return "PSK", 0.6, f
    return "unknown", 0.2, f


def suggest_decoder(label):
    return DECODER_HINT.get(label, "unknown")


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Classify")
    S.settings("classify", {})
    root, F = S.make_root("Signal Classifier", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Signal Classifier", "Modulation triage from IQ")
    msg = tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
                   wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
                   text="Load an IQ capture (from the IQ Recorder) to classify its modulation. "
                        "Heuristic AM/FM/FSK/PSK/OFDM triage with a suggested decoder.")
    msg.pack(fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
