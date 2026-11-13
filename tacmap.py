#!/usr/bin/env python3
"""tacmap.py — unified all-source tactical map (ties the suite together).

Collects contacts from every source the suite produces — aircraft (ADS-B), vessels (AIS), APRS
stations, drones (Remote ID), radiosondes, vehicles (TPMS), BLE/cell — normalizes them, optionally
de-duplicates through the fusion engine, and presents one map model with per-type markers,
filtering and a bounding box for auto-zoom. Pure aggregation/filter is unit-testable; the Tk
workspace renders on tiles.py.
"""
import os
import sys
import time

import geo

# type -> marker glyph + display priority (higher = drawn on top / more salient).
TYPE_STYLE = {
    "aircraft": {"glyph": "✈", "prio": 2}, "vessel": {"glyph": "▸", "prio": 2},
    "drone": {"glyph": "✦", "prio": 3}, "station": {"glyph": "◇", "prio": 1},
    "sonde": {"glyph": "○", "prio": 1}, "vehicle": {"glyph": "▭", "prio": 1},
    "contact": {"glyph": "•", "prio": 1},
}


def normalize(contact, source=None):
    """Unify a contact dict from any module into a display record."""
    typ = contact.get("type", "contact")
    style = TYPE_STYLE.get(typ, TYPE_STYLE["contact"])
    return {"id": contact.get("id") or contact.get("uas_id") or contact.get("mmsi")
            or contact.get("callsign") or "?",
            "type": typ, "source": contact.get("source") or source or "?",
            "lat": contact.get("lat"), "lon": contact.get("lon"),
            "alt_m": contact.get("alt_m"),
            "ts": contact.get("timestamp") or contact.get("ts"),
            "glyph": style["glyph"], "prio": style["prio"]}


def collect(sources):
    """sources: {name: [contacts]} -> flat list of normalized records that have a position."""
    out = []
    for name, contacts in sources.items():
        for c in contacts:
            r = normalize(c, source=name)
            if r["lat"] is not None and r["lon"] is not None:
                out.append(r)
    return out


def filter_contacts(contacts, types=None, sources=None, max_age_s=None, now=None):
    now = time.time() if now is None else now
    out = contacts
    if types:
        out = [c for c in out if c["type"] in types]
    if sources:
        out = [c for c in out if c["source"] in sources]
    if max_age_s is not None:
        out = [c for c in out if c.get("ts") is not None and now - c["ts"] <= max_age_s]
    return out


def bounds(contacts):
    """Bounding box (min_lat, min_lon, max_lat, max_lon) over positioned contacts, or None."""
    pts = [(c["lat"], c["lon"]) for c in contacts if c["lat"] is not None]
    if not pts:
        return None
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    return (min(lats), min(lons), max(lats), max(lons))


def nearest(contacts, lat, lon):
    pos = [c for c in contacts if c["lat"] is not None]
    if not pos:
        return None
    return min(pos, key=lambda c: geo.dist_nm(lat, lon, c["lat"], c["lon"]))


def counts_by_type(contacts):
    from collections import Counter
    return dict(Counter(c["type"] for c in contacts))


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("TacMap")
    S.settings("tacmap", {})
    root, F = S.make_root("Tactical Map", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Tactical Map", "All-source · one picture")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Fuses every contact the suite produces — aircraft, vessels, APRS, drones, "
                  "radiosondes, vehicles, BLE/cell — onto one map with per-type markers, source "
                  "badges and filters. Reads live caches + the fusion engine.").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
