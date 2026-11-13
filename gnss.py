#!/usr/bin/env python3
"""gnss.py — GPS/GNSS health, jamming & spoofing monitor (Phase 6 #16).

Watches the receiver's satellite view (C/N0 per PRN, fix quality, position) and flags trouble:
  Jamming  — carrier-to-noise collapses across all satellites and/or the usable count drops.
  Spoofing — the position jumps faster than physics allows, time steps backward, or every
             satellite reports an implausibly uniform, strong C/N0 (one spoofer feeding them all).

Pure analysis helpers are unit-testable; it consumes satellite snapshots + fixes from gpsd/NMEA.
No transmission. Jamming/spoofing detection is heuristic (an alert to investigate, not proof).
"""
import os
import statistics
import sys

import geo


def cn0_stats(sats):
    """Summary of carrier-to-noise across satellites. sats: [{prn, cn0, elev, used}]."""
    cn0s = [s["cn0"] for s in sats if s.get("cn0") and s["cn0"] > 0]
    if not cn0s:
        return {"n": 0, "median": 0.0, "mean": 0.0, "std": 0.0, "max": 0.0}
    return {"n": len(cn0s), "median": statistics.median(cn0s), "mean": statistics.fmean(cn0s),
            "std": statistics.pstdev(cn0s) if len(cn0s) > 1 else 0.0, "max": max(cn0s)}


def jamming_check(sats, nominal_cn0=38.0, min_sats=4):
    """(jammed: bool, score 0-1, reason). Jamming looks like a broad C/N0 collapse / sat dropout."""
    st = cn0_stats(sats)
    if st["n"] == 0:
        return True, 1.0, "no satellites with signal — total loss"
    low_median = st["median"] < nominal_cn0 - 12       # ~12 dB-Hz below nominal
    few = st["n"] < min_sats
    if low_median and few:
        return True, 0.9, "C/N0 collapsed (median %.0f) and only %d sats" % (st["median"], st["n"])
    if low_median:
        return True, 0.6, "C/N0 depressed across the band (median %.0f dB-Hz)" % st["median"]
    if few:
        return False, 0.3, "only %d sats with signal" % st["n"]
    return False, 0.0, "nominal"


def spoofing_check(prev_fix, cur_fix, dt_s, sats, max_speed_mps=600.0):
    """List of spoofing indicators. prev_fix/cur_fix: {lat, lon, t}. dt_s: seconds between them."""
    flags = []
    if prev_fix and cur_fix and dt_s and dt_s > 0:
        nm = geo.dist_nm(prev_fix["lat"], prev_fix["lon"], cur_fix["lat"], cur_fix["lon"])
        speed = nm * 1852.0 / dt_s
        if speed > max_speed_mps:
            flags.append("position jumped %.1f km in %.1fs (%.0f m/s)" % (nm * 1.852, dt_s, speed))
    if prev_fix and cur_fix and cur_fix.get("t") is not None and prev_fix.get("t") is not None:
        if cur_fix["t"] < prev_fix["t"]:
            flags.append("receiver time stepped backward (spoof clock)")
    st = cn0_stats(sats)
    if st["n"] >= 5 and st["std"] < 1.5 and st["mean"] > 44:
        flags.append("every satellite at a uniform strong C/N0 (mean %.0f, σ%.1f) — spoofer signature"
                     % (st["mean"], st["std"]))
    return flags


class GnssMonitor:
    def __init__(self, nominal_cn0=38.0):
        self.nominal = nominal_cn0
        self.last_fix = None
        self.on_alert = None

    def ingest(self, fix, sats, now=None):
        """Feed one fix + satellite snapshot. Returns a list of alert strings."""
        alerts = []
        jammed, score, reason = jamming_check(sats, self.nominal)
        if jammed:
            alerts.append("GNSS jamming: " + reason)
        dt = None
        if self.last_fix and fix and fix.get("t") is not None and self.last_fix.get("t") is not None:
            dt = fix["t"] - self.last_fix["t"]
        for f in spoofing_check(self.last_fix, fix, dt, sats):
            alerts.append("GNSS spoofing: " + f)
        if fix and fix.get("lat") is not None:
            self.last_fix = fix
        if self.on_alert:
            for a in alerts:
                self.on_alert(a)
        return alerts


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("GNSS")
    S.settings("gnss", {})
    root, F = S.make_root("GNSS Monitor", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "GNSS Monitor", "GPS health · jamming + spoofing watch")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Monitors satellite C/N0, fix quality and position for jamming (C/N0 collapse) "
                  "and spoofing (impossible position jumps, backward time, uniform strong C/N0). "
                  "Feeds from gpsd. Alerts are investigative hints, not proof.").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
