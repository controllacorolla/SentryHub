#!/usr/bin/env python3
"""imsicatch.py — IMSI-catcher / fake base station detector (Phase 6 #15).

Compares observed cellular base stations against a baseline of known-good cells (learned, or from
OpenCelliD) and flags the signatures of a fake BTS: a cell that isn't in the baseline, a known
ARFCN suddenly advertising a different LAC, an encryption downgrade (A5/0), an implausibly strong
signal, or the LAC flapping. Needs a modem/QMI or scanner feed for real data; the analysis is pure
and unit-testable. Heuristic — flags are leads to investigate, not proof.
"""
import os
import sys


def _key(obs):
    return (obs.get("mcc"), obs.get("mnc"), obs.get("lac"), obs.get("cid"))


def analyze_cell(obs, baseline, max_rxlevel_jump=20):
    """Return a list of (code, detail, severity) anomaly flags for one cell observation."""
    flags = []
    key = _key(obs)
    arfcn = obs.get("arfcn")
    known = baseline.get(key)
    if known is None:
        flags.append(("unknown_cell", "cell %s not in baseline" % (key,), "medium"))
    # A known ARFCN now advertising a different LAC is a classic fake-BTS tell.
    for k, v in baseline.items():
        if v.get("arfcn") == arfcn and k != key and k[2] != obs.get("lac"):
            flags.append(("lac_mismatch", "ARFCN %s advertises LAC %s (baseline had %s)" % (
                arfcn, obs.get("lac"), k[2]), "high"))
            break
    if obs.get("encryption") == "A5/0":
        flags.append(("no_encryption", "ciphering disabled (A5/0) — downgrade attack", "high"))
    if (known and obs.get("rxlevel") is not None and known.get("rxlevel") is not None
            and obs["rxlevel"] - known["rxlevel"] > max_rxlevel_jump):
        flags.append(("power_anomaly", "signal %d dB over baseline for this cell" % (
            obs["rxlevel"] - known["rxlevel"]), "medium"))
    return flags


class IMSICatcherDetector:
    def __init__(self, baseline=None):
        self.baseline = dict(baseline or {})
        self.lac_history = []
        self.on_alert = None

    def learn(self, obs):
        """Add an observed cell to the trusted baseline."""
        self.baseline[_key(obs)] = dict(obs)

    def observe(self, obs):
        """Analyze one observation; returns flags and fires on_alert for each."""
        flags = analyze_cell(obs, self.baseline)
        lac = obs.get("lac")
        self.lac_history.append(lac)
        del self.lac_history[:-10]
        if len(set(self.lac_history[-4:])) >= 3:
            flags.append(("lac_flapping", "LAC changing rapidly (%s)" % self.lac_history[-4:],
                          "medium"))
        if self.on_alert:
            for f in flags:
                self.on_alert(f)
        return flags


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("IMSICatch")
    S.settings("imsicatch", {})
    root, F = S.make_root("IMSI-Catcher Watch", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "IMSI-Catcher Watch", "Fake base station detection")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Compares cell towers against a baseline and flags fake-BTS signatures: unknown "
                  "cell, ARFCN/LAC mismatch, encryption downgrade (A5/0), excessive power, LAC "
                  "flapping. Needs a modem/QMI or GSM scanner feed. Heuristic — leads, not proof.").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
