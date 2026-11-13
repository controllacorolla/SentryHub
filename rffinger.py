#!/usr/bin/env python3
"""rffinger.py — RF device fingerprinting (Phase 6 #5).

Transmitters have physical quirks — carrier frequency offset, reference-clock drift, the shape of
their power-on ramp, occupied bandwidth — that stay fairly constant across transmissions and
differ between units. This builds a fingerprint vector from those measured features and matches a
new capture against a per-engagement database, so the same physical device can be recognised again
even if its payload/ID changes. Pure + unit-testable.
"""
import math
import os
import sys

# Fingerprint features and the per-feature scale used to normalize distance (so one feature does
# not dominate just because its raw units are larger).
FEATURES = {
    "freq_offset_hz": 500.0,      # carrier offset from nominal
    "clock_ppm": 1.0,             # reference oscillator drift
    "ramp_us": 5.0,               # power-on ramp duration
    "power_dbm": 3.0,             # received power profile
    "bandwidth_hz": 5000.0,       # occupied bandwidth
}


def distance(a, b):
    """Normalized Euclidean distance over the features both fingerprints share (0 = identical)."""
    s, n = 0.0, 0
    for k, scale in FEATURES.items():
        if k in a and k in b and a[k] is not None and b[k] is not None:
            s += ((a[k] - b[k]) / scale) ** 2
            n += 1
    return math.sqrt(s / n) if n else float("inf")


class FingerprintDB:
    def __init__(self):
        self.db = {}

    def add(self, device_id, fingerprint):
        self.db[device_id] = {k: fingerprint[k] for k in FEATURES if k in fingerprint}
        return self.db[device_id]

    def match(self, fingerprint, threshold=1.5):
        """Best matching device id within threshold, or (None, distance). Lower is closer."""
        best, best_d = None, threshold
        for did, known in self.db.items():
            d = distance(fingerprint, known)
            if d <= best_d:
                best, best_d = did, d
        return best, (best_d if best else None)

    def identify_or_enroll(self, fingerprint, threshold=1.5, new_prefix="DEV"):
        """Match an existing device, or enroll a new one and return its generated id."""
        did, d = self.match(fingerprint, threshold)
        if did is not None:
            return did, False
        new_id = "%s-%03d" % (new_prefix, len(self.db) + 1)
        self.add(new_id, fingerprint)
        return new_id, True


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("RFFinger")
    S.settings("rffinger", {})
    root, F = S.make_root("RF Fingerprint", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "RF Fingerprint", "Per-engagement device signatures")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Builds a fingerprint from a transmitter's physical quirks (frequency offset, "
                  "clock drift, power ramp, bandwidth) and recognises the same device again across "
                  "an engagement, even if its ID changes.").pack(fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
