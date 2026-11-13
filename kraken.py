#!/usr/bin/env python3
"""kraken.py — KrakenSDR direction finding + emitter geolocation (Phase 7 #5).

A KrakenSDR (5 coherent RX channels) gives a bearing to an emitter. This module takes bearings
from several positions (you moving, or several fixes over time) and triangulates the emitter's
location by least-squares intersection of the bearing lines, with a confidence from the residual.
The raw bearing estimate comes from the hardware (heatmap/MUSIC) and degrades gracefully when no
KrakenSDR is attached; the triangulation geometry is pure and unit-testable.
"""
import math
import os
import sys


def _ll_to_xy(lat, lon, lat0, lon0):
    """Local flat-earth ENU metres (good over a DF-sized area)."""
    x = (lon - lon0) * 111320.0 * math.cos(math.radians(lat0))      # east
    y = (lat - lat0) * 110540.0                                     # north
    return x, y


def _xy_to_ll(x, y, lat0, lon0):
    lat = lat0 + y / 110540.0
    lon = lon0 + x / (111320.0 * math.cos(math.radians(lat0)))
    return lat, lon


def triangulate(fixes):
    """Least-squares emitter location from bearings. fixes: [(lat, lon, bearing_deg)] where bearing
    is the direction TO the emitter, degrees from north. Returns (lat, lon), or None if <2 fixes or
    the bearings are parallel."""
    if len(fixes) < 2:
        return None
    lat0 = sum(f[0] for f in fixes) / len(fixes)
    lon0 = sum(f[1] for f in fixes) / len(fixes)
    a00 = a01 = a11 = b0 = b1 = 0.0
    for lat, lon, brg in fixes:
        px, py = _ll_to_xy(lat, lon, lat0, lon0)
        th = math.radians(brg)
        dx, dy = math.sin(th), math.cos(th)       # east, north unit vector along the bearing
        m00, m01, m11 = 1 - dx * dx, -dx * dy, 1 - dy * dy      # I - d d^T (project perpendicular)
        a00 += m00
        a01 += m01
        a11 += m11
        b0 += m00 * px + m01 * py
        b1 += m01 * px + m11 * py
    det = a00 * a11 - a01 * a01
    if abs(det) < 1e-9:
        return None                               # parallel/degenerate bearings
    x = (a11 * b0 - a01 * b1) / det
    y = (-a01 * b0 + a00 * b1) / det
    return _xy_to_ll(x, y, lat0, lon0)


def residual_nm(fixes, emitter):
    """Mean angular miss: how far each observed bearing is from pointing at the estimate (degrees).
    A small value means the bearings agree on the location."""
    import_geo = __import__("geo")
    errs = []
    for lat, lon, brg in fixes:
        true_brg = import_geo.bearing_deg(lat, lon, emitter[0], emitter[1])
        d = abs((true_brg - brg + 180) % 360 - 180)
        errs.append(d)
    return sum(errs) / len(errs) if errs else None


def confidence(fixes, emitter, good_deg=5.0):
    """0..1 confidence from the bearing residual (and more fixes = better)."""
    r = residual_nm(fixes, emitter)
    if r is None:
        return 0.0
    ang = max(0.0, 1.0 - r / (good_deg * 3))
    return round(ang * min(1.0, len(fixes) / 3.0), 3)


def kraken_available(host="127.0.0.1", port=8080, opener=None):
    """Is a KrakenSDR DAQ/DOA server reachable? (The Kraken DOA server exposes an HTTP API.)"""
    import urllib.request
    opener = opener or (lambda url, t: urllib.request.urlopen(url, timeout=t))
    try:
        opener("http://%s:%d/" % (host, int(port)), 2)
        return True
    except Exception:
        return False


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Kraken")
    S.settings("kraken", {"host": "127.0.0.1", "port": 8080})
    root, F = S.make_root("Direction Finding", parent=parent)
    import tkinter as tk
    T = S.T
    avail = kraken_available()
    S.top_bar(root, F, "Direction Finding", "KrakenSDR bearings → emitter fix")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text=("Takes bearings from a KrakenSDR at several positions (drive around, or fixes "
                   "over time) and triangulates the emitter onto the map with a confidence. "
                   + ("KrakenSDR DOA server detected." if avail
                      else "No KrakenSDR DOA server found — attach one and start its DAQ."))).pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
