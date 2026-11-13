#!/usr/bin/env python3
"""bugsweep.py — bug / hidden-camera sweep (Phase 6 #14). DEFENSIVE, receive-only.

A technical surveillance counter-measures (TSCM) aid: wideband-sweep a space you control, learn the
quiet baseline, and flag anomalous narrowband emitters in the bands hidden wireless cameras, audio
bugs and trackers commonly use — then rank by RSSI to help you walk toward the source. Passive (it
only listens), so no engagement gate. Pure analysis is unit-testable.
"""
import os
import sys

import noisefloor

# Bands commonly used by covert wireless cameras / bugs / trackers (Hz).
SUSPECT_BANDS = [
    (40_000_000, 50_000_000, "analog baby-cam / bug"),
    (300_000_000, 350_000_000, "analog camera"),
    (390_000_000, 470_000_000, "UHF bug / tracker"),
    (900_000_000, 930_000_000, "900 MHz analog video"),
    (1_100_000_000, 1_300_000_000, "1.2 GHz video"),
    (2_400_000_000, 2_500_000_000, "2.4 GHz camera / Wi-Fi cam"),
    (5_700_000_000, 5_900_000_000, "5.8 GHz video"),
]


def in_suspect_band(freq_hz):
    for lo, hi, label in SUSPECT_BANDS:
        if lo <= freq_hz <= hi:
            return label
    return None


def find_suspects(new_signals):
    """From noise-floor new_signals (bins above baseline), keep those in a suspect band, annotate,
    and rank by how far above the floor they are."""
    out = []
    for s in new_signals:
        label = in_suspect_band(s["freq_hz"])
        if label:
            out.append(dict(s, band=label))
    return sorted(out, key=lambda s: -s["over_db"])


def proximity(rssi_or_over_db):
    """Coarse closeness hint from signal strength over the floor (dB)."""
    v = rssi_or_over_db
    if v >= 30:
        return "very close"
    if v >= 20:
        return "close"
    if v >= 12:
        return "nearby"
    return "faint"


class Sweeper:
    """Learns a quiet baseline, then reports suspect emitters on each sweep."""

    def __init__(self, threshold_db=12.0):
        self.nf = noisefloor.NoiseFloor()
        self.threshold = threshold_db

    def learn(self, bins):
        self.nf.update(bins)

    def sweep(self, bins):
        return find_suspects(self.nf.new_signals(bins, threshold_db=self.threshold))


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("BugSweep")
    S.settings("bugsweep", {})
    root, F = S.make_root("Bug Sweep", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Bug Sweep", "TSCM · hidden-transmitter detection")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Sweep a room you control, learn the quiet baseline, then flag new narrowband "
                  "emitters in the bands hidden cameras/bugs use and rank them by strength to walk "
                  "toward the source. Receive-only — a defensive counter-surveillance aid.").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
