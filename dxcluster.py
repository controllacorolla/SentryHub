#!/usr/bin/env python3
"""dxcluster.py — DX cluster / PSKReporter propagation feed (Phase 7 #4). Receive-only.

Parses DX-cluster spot lines (telnet feed) into who-is-working-whom-where, so active bands and
openings show at a glance and spotted stations can be overlaid on the map. Pure parser is
unit-testable; the Tk workspace is a spot list filterable by band/mode.
"""
import os
import re
import sys
import time

# Ham band edges (kHz) -> name, for tagging a spot's band.
_BANDS = [(1800, 2000, "160m"), (3500, 4000, "80m"), (5330, 5407, "60m"), (7000, 7300, "40m"),
          (10100, 10150, "30m"), (14000, 14350, "20m"), (18068, 18168, "17m"),
          (21000, 21450, "15m"), (24890, 24990, "12m"), (28000, 29700, "10m"),
          (50000, 54000, "6m"), (144000, 148000, "2m"), (430000, 450000, "70cm")]

_DX = re.compile(r"DX de\s+([A-Z0-9/\-]+?):?\s+([\d.]+)\s+([A-Z0-9/\-]+)\s+(.*?)\s+(\d{3,4}Z)")
_MODES = ["FT8", "FT4", "CW", "RTTY", "PSK", "SSB", "USB", "LSB", "JS8", "WSPR", "FM"]


def band_from_khz(khz):
    for lo, hi, name in _BANDS:
        if lo <= khz <= hi:
            return name
    return None


def mode_from_comment(comment):
    up = str(comment).upper()
    for m in _MODES:
        if m in up:
            return "SSB" if m in ("USB", "LSB") else m
    return None


def parse_dx_spot(line):
    """One DX-cluster spot line -> dict, or None."""
    m = _DX.search(line)
    if not m:
        return None
    spotter, freq, dx, comment, t = m.groups()
    try:
        khz = float(freq)
    except ValueError:
        return None
    return {"spotter": spotter, "freq_khz": khz, "dx_call": dx, "comment": comment.strip(),
            "band": band_from_khz(khz), "mode": mode_from_comment(comment), "time": t}


class Spots:
    def __init__(self, cap=500):
        self.items = []
        self.cap = cap

    def add(self, spot, now=None):
        if not spot:
            return None
        spot = dict(spot, t=time.time() if now is None else now)
        self.items.append(spot)
        del self.items[:-self.cap]
        return spot

    def recent(self, band=None, mode=None, limit=100):
        rows = self.items
        if band:
            rows = [s for s in rows if s.get("band") == band]
        if mode:
            rows = [s for s in rows if s.get("mode") == mode]
        return list(reversed(rows))[:limit]

    def active_bands(self):
        from collections import Counter
        c = Counter(s["band"] for s in self.items if s.get("band"))
        return dict(c.most_common())


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("DXCluster")
    S.settings("dxcluster", {"host": "", "port": 7300})
    root, F = S.make_root("DX Cluster", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "DX Cluster", "Propagation spots · receive-only")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Connect to a DX cluster (telnet) or PSKReporter to see which bands are open and "
                  "who is being worked where; spotted stations overlay on the map. Configure a "
                  "cluster host in settings.").pack(fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
