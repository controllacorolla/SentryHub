#!/usr/bin/env python3
"""noisefloor.py — automated noise-floor survey (Phase 7 #1).

Sweeps the spectrum (rtl_power), learns the per-bin noise floor over time (a site baseline), then
flags bins that rise above baseline — new emitters that weren't there before. Useful for site
characterization and for spotting a signal that appears mid-engagement. Pure parsing/analysis is
unit-testable; the Tk workspace shows the floor and new signals.
"""
import os
import statistics
import sys


def parse_rtl_power_row(line):
    """One rtl_power CSV row -> {f_low, f_high, step, bins: [(freq_hz, dbm), ...]}.
    Row layout: date, time, Hz_low, Hz_high, Hz_step, samples, db0, db1, ..."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 7:
        return None
    try:
        f_low, f_high, step = float(parts[2]), float(parts[3]), float(parts[4])
        dbs = [float(x) for x in parts[6:] if x != ""]
    except ValueError:
        return None
    bins = [(f_low + i * step, db) for i, db in enumerate(dbs)]
    return {"f_low": f_low, "f_high": f_high, "step": step, "bins": bins}


def band_floor(bins, lo_hz, hi_hz):
    """Median power (the floor estimate) over bins within [lo_hz, hi_hz]."""
    vals = [db for f, db in bins if lo_hz <= f <= hi_hz]
    return statistics.median(vals) if vals else None


class NoiseFloor:
    """Learns a per-bin floor (running minimum) and finds bins above it."""

    def __init__(self, bin_key_hz=10_000):
        self.key = bin_key_hz
        self.floor = {}            # quantized freq -> lowest dBm seen (the floor)
        self.n = 0

    def _k(self, f):
        return round(f / self.key) * self.key

    def update(self, bins):
        """Fold a sweep into the baseline floor."""
        self.n += 1
        for f, db in bins:
            k = self._k(f)
            cur = self.floor.get(k)
            if cur is None or db < cur:
                self.floor[k] = db

    def new_signals(self, bins, threshold_db=10.0):
        """Bins in the current sweep that rise threshold_db above the learned floor."""
        out = []
        for f, db in bins:
            base = self.floor.get(self._k(f))
            if base is not None and db > base + threshold_db:
                out.append({"freq_hz": f, "dbm": db, "floor": base, "over_db": db - base})
        return sorted(out, key=lambda s: -s["over_db"])

    def summary(self):
        if not self.floor:
            return {"bins": 0}
        vals = list(self.floor.values())
        return {"bins": len(vals), "sweeps": self.n,
                "floor_median": statistics.median(vals), "floor_min": min(vals)}


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("NoiseFloor")
    S.settings("noisefloor", {})
    root, F = S.make_root("Noise Floor", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Noise Floor", "Band survey · baseline + new-emitter watch")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Sweeps with rtl_power, learns the per-bin noise floor as a site baseline, then "
                  "flags bins that rise above it — new emitters. Export a baseline to compare a "
                  "site over time.").pack(fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
