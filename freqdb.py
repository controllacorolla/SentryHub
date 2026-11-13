#!/usr/bin/env python3
"""freqdb.py — offline frequency allocation database (Phase 6 #3).

A built-in table of who is allocated where (US-centric: broadcast, amateur, ISM, aviation,
marine, land-mobile, GMRS/FRS/MURS, cellular, public safety, GNSS, weather/satellite). Lets any
module cross-reference a live signal against the known allocation at that frequency — "what is
this?" and "am I even allowed here?". Pure + unit-testable; the Tk workspace is a lookup/search.
"""
import os
import sys

# (low_hz, high_hz, service, band/notes). Conservative, not exhaustive to the kHz.
ALLOCATIONS = [
    (148_500, 283_500, "LF/MF broadcast", "longwave (ROW)"),
    (530_000, 1_700_000, "AM broadcast", "MW band"),
    (1_800_000, 2_000_000, "Amateur", "160 m"),
    (2_300_000, 2_495_000, "SW broadcast", "120 m SW"),
    (3_500_000, 4_000_000, "Amateur", "80 m"),
    (4_750_000, 5_060_000, "SW broadcast", "60 m SW"),
    (5_330_500, 5_406_500, "Amateur", "60 m (channels)"),
    (5_900_000, 6_200_000, "SW broadcast", "49 m"),
    (7_000_000, 7_300_000, "Amateur", "40 m"),
    (9_400_000, 9_900_000, "SW broadcast", "31 m"),
    (10_100_000, 10_150_000, "Amateur", "30 m"),
    (11_600_000, 12_100_000, "SW broadcast", "25 m"),
    (13_570_000, 13_870_000, "SW broadcast", "22 m"),
    (14_000_000, 14_350_000, "Amateur", "20 m"),
    (15_100_000, 15_830_000, "SW broadcast", "19 m"),
    (18_068_000, 18_168_000, "Amateur", "17 m"),
    (21_000_000, 21_450_000, "Amateur", "15 m"),
    (24_890_000, 24_990_000, "Amateur", "12 m"),
    (26_965_000, 27_405_000, "CB radio", "Citizens Band (27 MHz)"),
    (28_000_000, 29_700_000, "Amateur", "10 m"),
    (50_000_000, 54_000_000, "Amateur", "6 m"),
    (88_000_000, 108_000_000, "FM broadcast", "FM band"),
    (108_000_000, 118_000_000, "Aviation nav", "VOR/ILS"),
    (118_000_000, 137_000_000, "Aviation voice", "airband AM"),
    (137_000_000, 138_000_000, "Weather satellite", "NOAA APT / Meteor"),
    (144_000_000, 148_000_000, "Amateur", "2 m"),
    (151_820_000, 154_600_000, "MURS / business", "VHF LMR"),
    (156_000_000, 162_050_000, "Marine VHF", "incl. AIS 161.975/162.025"),
    (162_400_000, 162_550_000, "NOAA Weather Radio", "NWR SAME"),
    (222_000_000, 225_000_000, "Amateur", "1.25 m"),
    (225_000_000, 400_000_000, "Military air / UHF", "mil UHF"),
    (406_000_000, 406_100_000, "Emergency beacons", "COSPAS-SARSAT"),
    (420_000_000, 450_000_000, "Amateur", "70 cm"),
    (450_000_000, 470_000_000, "Land mobile (UHF)", "business/public safety"),
    (462_000_000, 467_740_000, "GMRS / FRS", "family/general mobile"),
    (470_000_000, 608_000_000, "TV broadcast (UHF)", "DTV"),
    (698_000_000, 806_000_000, "Cellular / public safety", "700 MHz"),
    (824_000_000, 894_000_000, "Cellular", "850 MHz band"),
    (902_000_000, 928_000_000, "ISM / Amateur", "33 cm, LoRa, rtl_433"),
    (960_000_000, 1_215_000_000, "Aeronautical radionav", "DME/TACAN, ADS-B 1090"),
    (1_227_600_000, 1_227_600_000, "GNSS L2", "GPS L2"),
    (1_240_000_000, 1_300_000_000, "Amateur", "23 cm"),
    (1_525_000_000, 1_559_000_000, "Mobile satellite", "Inmarsat / Iridium downlink region"),
    (1_559_000_000, 1_610_000_000, "GNSS", "GPS L1 / Galileo / GLONASS"),
    (1_616_000_000, 1_626_500_000, "Iridium", "L-band satellite"),
    (1_710_000_000, 1_780_000_000, "Cellular uplink", "AWS/PCS"),
    (2_400_000_000, 2_483_500_000, "ISM / Amateur / Wi-Fi", "2.4 GHz, BLE"),
    (5_725_000_000, 5_875_000_000, "ISM / Wi-Fi / Amateur", "5.8 GHz"),
]


def lookup(freq_hz):
    """All allocations covering freq_hz, most specific (narrowest) first."""
    f = float(freq_hz)
    hits = [a for a in ALLOCATIONS if a[0] <= f <= a[1]]
    return sorted(hits, key=lambda a: a[1] - a[0])


def describe(freq_hz):
    hits = lookup(freq_hz)
    if not hits:
        return "unallocated / unknown"
    lo, hi, svc, note = hits[0]
    return "%s (%s)" % (svc, note) if note else svc


def search(term):
    """Allocations whose service or notes match `term` (case-insensitive)."""
    t = str(term).lower()
    return [a for a in ALLOCATIONS if t in a[2].lower() or t in a[3].lower()]


def cross_reference(signals):
    """Annotate detected signals [{freq_hz, ...}] with their allocation. Returns new dicts."""
    out = []
    for s in signals:
        f = s.get("freq_hz")
        out.append(dict(s, allocation=describe(f) if f is not None else "?"))
    return out


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("FreqDB")
    S.settings("freqdb", {})
    root, F = S.make_root("Frequency DB", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Frequency DB", "Offline allocations · lookup / search")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    ent = tk.Entry(body, font=F["mono"])
    ent.pack(fill="x", padx=T.px(12), pady=T.px(8))
    res = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="word", state="disabled", padx=T.px(12), pady=T.px(4))
    res.tag_config("svc", foreground=S.AMBER)
    res.pack(fill="both", expand=True)

    def show(_=None):
        q = ent.get().strip()
        res.config(state="normal")
        res.delete("1.0", "end")
        rows = []
        # a bare number is a frequency in MHz; otherwise a service search
        try:
            rows = lookup(float(q) * 1e6)
            res.insert("end", "At %s MHz:\n" % q, "svc")
        except ValueError:
            rows = search(q)
        for lo, hi, svc, note in rows:
            res.insert("end", "%-28s " % svc, "svc")
            res.insert("end", "%.3f–%.3f MHz  %s\n" % (lo / 1e6, hi / 1e6, note))
        if not rows:
            res.insert("end", "no match\n")
        res.config(state="disabled")
    ent.bind("<KeyRelease>", show)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
