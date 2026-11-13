#!/usr/bin/env python3
"""tpms.py — TPMS (tire pressure sensor) decoder/analyzer (Phase 6 #12). Receive-only.

Vehicles continuously broadcast per-tire sensor IDs, pressure and temperature on 315/433 MHz.
rtl_433 decodes them; this module groups sensors into vehicles (4 sensor IDs seen together),
tracks pressure/temp, and estimates range from RSSI — useful for correlating a vehicle to a
physical-security assessment (a given car reappearing). Pure parser is unit-testable. No TX.
"""
import json
import os
import sys
import time


def parse_tpms(line):
    """One rtl_433 JSON line -> normalized TPMS dict, or None (non-TPMS rows ignored)."""
    try:
        d = json.loads(line)
    except (ValueError, TypeError):
        return None
    if "TPMS" not in str(d.get("type", "")) and "tpms" not in str(d.get("model", "")).lower():
        return None
    press = d.get("pressure_kPa")
    if press is None and d.get("pressure_PSI") is not None:
        press = d["pressure_PSI"] * 6.89476
    return {"model": d.get("model"), "id": str(d.get("id")), "pressure_kpa": press,
            "temp_c": d.get("temperature_C"), "battery_ok": d.get("battery_ok"),
            "rssi": d.get("rssi")}


def rssi_to_distance_m(rssi, ref_rssi=-40.0, ref_dist_m=1.0, path_loss=2.5):
    """Rough log-distance range estimate from RSSI (very approximate)."""
    if rssi is None:
        return None
    return ref_dist_m * 10 ** ((ref_rssi - rssi) / (10 * path_loss))


class Vehicles:
    """Groups TPMS sensors heard close together in time into a vehicle (by sensor-id set)."""

    def __init__(self, group_window_s=5.0):
        self.sensors = {}        # sensor id -> latest reading
        self.window = group_window_s

    def add(self, reading, now=None):
        if not reading or not reading.get("id"):
            return None
        now = time.time() if now is None else now
        r = dict(reading, last=now)
        self.sensors[reading["id"]] = r
        return r

    def recent_sensors(self, now=None):
        now = time.time() if now is None else now
        return [s for s in self.sensors.values() if now - s["last"] <= 60]

    def vehicle_candidates(self, now=None):
        """Sensor ids heard within the grouping window of each other — a likely single vehicle."""
        now = time.time() if now is None else now
        recent = sorted(self.recent_sensors(now), key=lambda s: s["last"])
        groups, cur = [], []
        for s in recent:
            if cur and s["last"] - cur[-1]["last"] > self.window:
                groups.append([x["id"] for x in cur])
                cur = []
            cur.append(s)
        if cur:
            groups.append([x["id"] for x in cur])
        return groups


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("TPMS")
    S.settings("tpms", {})
    root, F = S.make_root("TPMS", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "TPMS", "Tire sensors · 315/433 MHz · receive-only")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Decodes tire-pressure sensors (via rtl_433), groups the four sensors of a "
                  "vehicle, tracks pressure/temperature and estimates range from RSSI — for "
                  "correlating a vehicle during a physical-security assessment.").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
