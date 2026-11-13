#!/usr/bin/env python3
"""jammer.py — jamming / interference detector (Phase 6 #17).

Watches the noise floor (via noisefloor's baseline) and alerts when energy rises across the band:
WIDEBAND jamming lifts most bins at once; NARROWBAND interference is a strong persistent spike.
Alerts only on SUSTAINED elevation (several consecutive sweeps), so a transient burst doesn't cry
wolf. Pure analysis; unit-testable.
"""
import os
import sys

import noisefloor


def classify_interference(new_signals, total_bins, wideband_frac=0.3, narrow_db=20.0):
    """(kind, severity 0-1). kind: 'wideband' | 'narrowband' | None.
    new_signals: the bins above baseline (from NoiseFloor.new_signals)."""
    if total_bins <= 0:
        return None, 0.0
    frac = len(new_signals) / total_bins
    if frac >= wideband_frac:
        return "wideband", min(1.0, frac)
    if new_signals:
        strongest = max(s["over_db"] for s in new_signals)
        if strongest >= narrow_db:
            return "narrowband", min(1.0, strongest / 40.0)
    return None, 0.0


class JammingDetector:
    def __init__(self, sustained_sweeps=3, wideband_frac=0.3, threshold_db=10.0):
        self.nf = noisefloor.NoiseFloor()
        self.sustained = sustained_sweeps
        self.wideband_frac = wideband_frac
        self.threshold_db = threshold_db
        self.streak = 0
        self.last_kind = None
        self.on_alert = None

    def learn(self, bins):
        """Fold a quiet sweep into the baseline (call during a known-clean period)."""
        self.nf.update(bins)

    def feed(self, bins):
        """Analyze one sweep. Returns an alert string when interference is SUSTAINED, else None."""
        new = self.nf.new_signals(bins, threshold_db=self.threshold_db)
        kind, sev = classify_interference(new, len(bins), self.wideband_frac)
        if kind:
            self.streak = self.streak + 1 if kind == self.last_kind else 1
            self.last_kind = kind
            if self.streak >= self.sustained:
                alert = "%s interference — severity %.2f, %d sweeps, %d bins up" % (
                    kind, sev, self.streak, len(new))
                if self.on_alert:
                    self.on_alert(alert)
                return alert
        else:
            self.streak, self.last_kind = 0, None
        return None


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Jammer")
    S.settings("jammer", {})
    root, F = S.make_root("Jamming Detector", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Jamming Detector", "Sustained interference watch")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Learns the clean noise floor, then alerts on sustained energy: wideband "
                  "(most of the band lifts) or narrowband (a strong persistent spike). Only "
                  "fires after several consecutive sweeps, so transients are ignored.").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
