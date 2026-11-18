"""Preset frequency banks for PROWL's scanner and PRISM's bookmark browser — pure data.

A bank is a set of channels (fixed frequencies with labels) and/or ranges (start, stop, step)
that a range scan steps through, plus the mode, channel bandwidth, default scan step and default
squelch (dB above the noise floor) the scanner uses for it. Order is the owner's priority:
aviation first (full 118-137 MHz airband), then amateur, then everything else.

Frequencies are US allocations (FCC / NTIA). Tower / approach / ATIS frequencies are assigned per
airport, so the airband bank carries the nationwide-common channels plus the full 25 kHz range;
local towers are found by range-scanning it and locked in as bookmarks.
"""

# mode, bw (Hz), step (Hz), squelch (dB above floor)
def _bank(mode, bw, step, sq, channels=(), ranges=(), note=""):
    return {"mode": mode, "bw": bw, "step": step, "squelch": sq,
            "channels": [(float(f), str(lb)) for f, lb in channels],
            "ranges": [(float(a), float(b), float(s)) for a, b, s in ranges], "note": note}


def _seq(start, n, step, fmt):
    return [(round(start + i * step, 4), fmt % (i + 1)) for i in range(n)]


AIR_COMMON = [
    (121.500, "Guard (emergency)"), (122.750, "Air-to-air (fixed wing)"),
    (123.025, "Air-to-air (helicopter)"), (122.700, "UNICOM"), (122.725, "UNICOM"),
    (122.800, "UNICOM"), (122.950, "UNICOM (towered)"), (122.975, "UNICOM"),
    (123.000, "UNICOM"), (123.050, "UNICOM"), (123.075, "UNICOM"),
    (122.900, "MULTICOM"), (122.850, "MULTICOM"), (123.100, "SAR"),
    (122.000, "FSS / EFAS (legacy)"), (122.200, "FSS"), (122.100, "FSS (receive)"),
    (123.450, "Air-to-air (unofficial)"), (126.200, "Military tower (common)"),
    (135.275, "ATIS (common)"), (128.825, "ATIS (common)"),
]

MARINE = [
    (156.050, "01A"), (156.300, "06 safety"), (156.350, "07A"), (156.400, "08"),
    (156.450, "09 calling"), (156.500, "10"), (156.550, "11 VTS"), (156.600, "12 VTS"),
    (156.650, "13 bridge"), (156.700, "14 VTS"), (156.800, "16 distress"),
    (156.850, "17 state"), (156.900, "18A"), (156.950, "19A"), (157.000, "20"),
    (157.050, "21A USCG"), (157.100, "22A USCG"), (157.150, "23A USCG"), (156.250, "05A VTS"),
    (156.425, "68"), (156.475, "69"), (156.525, "70 DSC"), (156.575, "71"), (156.625, "72"),
    (156.675, "73"), (156.725, "74"), (156.875, "77"), (156.925, "78A"), (156.975, "79A"),
    (157.025, "80A"), (157.075, "81A"), (157.125, "82A"), (157.175, "83A"),
    (161.975, "AIS 1"), (162.025, "AIS 2"),
]

BANKS = {
    # ---- aviation (priority 1)
    "Airband (full)": _bank("AM", 8330, 25000, 8, channels=AIR_COMMON,
                            ranges=[(118.000, 136.975, 25000)],
                            note="Full civil VHF airband, 25 kHz. Tower/approach/ATIS are local: "
                                 "range-scan, then bookmark what you hear."),
    "Airband common": _bank("AM", 8330, 25000, 8, channels=AIR_COMMON),
    "Airband 8.33": _bank("AM", 6000, 8333.33, 8, ranges=[(118.000, 136.990, 8333.33)],
                          note="8.33 kHz channel spacing (Europe; some US upper airspace)."),
    "Mil air UHF": _bank("AM", 8330, 25000, 8,
                         channels=[(243.000, "Military guard"), (282.800, "SAR"),
                                   (311.000, "Air refuel"), (255.400, "FSS")],
                         ranges=[(225.000, 380.000, 25000)]),
    # ---- amateur (priority 2)
    "Ham 2m": _bank("NFM", 12500, 5000, 10,
                    channels=[(146.520, "National simplex calling"), (146.400, "simplex"),
                              (146.550, "simplex"), (146.580, "simplex"), (147.420, "simplex"),
                              (147.450, "simplex"), (147.480, "simplex"), (147.510, "simplex"),
                              (147.540, "simplex"), (147.570, "simplex"), (144.390, "APRS"),
                              (145.825, "ISS APRS / voice")],
                    ranges=[(144.000, 148.000, 5000)]),
    "Ham 70cm": _bank("NFM", 12500, 12500, 10,
                      channels=[(446.000, "National simplex calling"), (446.025, "simplex"),
                                (446.050, "simplex"), (446.075, "simplex"), (446.100, "simplex"),
                                (446.125, "simplex"), (446.150, "simplex"), (446.175, "simplex"),
                                (446.200, "simplex"), (437.800, "ISS downlink")],
                      ranges=[(420.000, 450.000, 12500)]),
    "Ham 1.25m": _bank("NFM", 12500, 20000, 10, channels=[(223.500, "Simplex calling")],
                       ranges=[(222.000, 225.000, 20000)]),
    "Ham 6m": _bank("NFM", 12500, 20000, 10,
                    channels=[(52.525, "FM simplex calling"), (50.125, "SSB calling (USB)")],
                    ranges=[(50.000, 54.000, 20000)]),
    "Ham 10m FM": _bank("NFM", 12500, 20000, 10, channels=[(29.600, "FM simplex calling")],
                        ranges=[(29.520, 29.700, 20000)]),
    # ---- everything else
    "NOAA Wx": _bank("NFM", 12500, 25000, 10,
                     channels=[(162.400, "WX2"), (162.425, "WX4"), (162.450, "WX5"),
                               (162.475, "WX3"), (162.500, "WX6"), (162.525, "WX7"),
                               (162.550, "WX1")]),
    "FRS/GMRS": _bank("NFM", 12500, 12500, 10,
                      channels=_seq(462.5625, 7, 0.025, "FRS/GMRS %d")
                      + [(round(467.5625 + i * 0.025, 4), "FRS %d" % (i + 8)) for i in range(7)]
                      + [(round(462.550 + i * 0.025, 4), "FRS/GMRS %d" % (i + 15))
                         for i in range(8)]
                      + [(round(467.550 + i * 0.025, 4), "GMRS repeater in %d" % (i + 15))
                         for i in range(8)]),
    "MURS": _bank("NFM", 12500, 12500, 10,
                  channels=[(151.820, "MURS 1"), (151.880, "MURS 2"), (151.940, "MURS 3"),
                            (154.570, "MURS 4 (Blue Dot)"), (154.600, "MURS 5 (Green Dot)")]),
    "Marine VHF": _bank("NFM", 12500, 25000, 10, channels=MARINE),
    "Public safety VHF": _bank("NFM", 12500, 7500, 10,
                               channels=[(155.475, "NLEEC (law national)"),
                                         (155.160, "SAR"), (155.340, "EMS / hospital (HEAR)"),
                                         (154.280, "Fire mutual aid"), (154.265, "Fire tac"),
                                         (154.295, "Fire tac"), (156.045, "VCALL10"),
                                         (155.7525, "VCALL10 (interop)"), (151.1375, "VTAC11"),
                                         (154.4525, "VTAC12"), (158.7375, "VTAC13"),
                                         (159.4725, "VTAC14")],
                               ranges=[(150.800, 162.000, 7500)],
                               note="Analog only; P25/DMR digital voice is not decoded."),
    "Public safety UHF": _bank("NFM", 12500, 12500, 10,
                               channels=[(453.2125, "UCALL40"), (453.4625, "UTAC41"),
                                         (453.7125, "UTAC42"), (453.8625, "UTAC43")],
                               ranges=[(450.000, 470.000, 12500)],
                               note="Analog only; P25/DMR digital voice is not decoded."),
    "Railroad": _bank("NFM", 12500, 15000, 10,
                      channels=[(160.230, "AAR 2"), (160.410, "AAR 15"), (160.590, "AAR 21"),
                                (160.785, "AAR 36"), (161.100, "AAR 57"), (161.370, "AAR 78"),
                                (161.520, "AAR 90"), (161.565, "AAR 96")],
                      ranges=[(159.810, 161.565, 15000)]),
    "CB": _bank("AM", 8000, 10000, 8,
                channels=[(f, str(i + 1)) for i, f in enumerate(
                    [26.965, 26.975, 26.985, 27.005, 27.015, 27.025, 27.035, 27.055, 27.065,
                     27.075, 27.085, 27.105, 27.115, 27.125, 27.135, 27.155, 27.165, 27.175,
                     27.185, 27.205, 27.215, 27.225, 27.255, 27.235, 27.245, 27.265, 27.275,
                     27.285, 27.295, 27.305, 27.315, 27.325, 27.335, 27.345, 27.355, 27.365,
                     27.375, 27.385, 27.395, 27.405])]),
    "Data: ADS-B / APRS / AIS": _bank("NFM", 12500, 25000, 10,
                                      channels=[(1090.000, "ADS-B / Mode S (AM pulses)"),
                                                (978.000, "UAT (US GA)"),
                                                (144.390, "APRS (US)"), (161.975, "AIS 1"),
                                                (162.025, "AIS 2")],
                                      note="Data channels: you hear the bursts; ATLAS decodes them."),
    "ISM / devices": _bank("AM", 20000, 25000, 10,
                           channels=[(433.920, "ISM 433 (sensors, fobs)"),
                                     (315.000, "315 (US key fobs, TPMS)"),
                                     (915.000, "ISM 915 (LoRa, meters)"),
                                     (868.000, "SRD 868 (EU)"), (345.000, "345 (alarm sensors)"),
                                     (390.000, "390 (garage doors)")]),
}
BANK_ORDER = list(BANKS)
MAX_RANGE_CHANNELS = 20000       # a typed range larger than this is refused, not truncated


def expand(bank, include_ranges=True):
    """Every channel of a bank as (MHz, label), named channels first, then the range steps that
    are not already a named channel (+/- half a step). Sorted by frequency."""
    out = list(bank["channels"])
    if include_ranges:
        named = [f for f, _ in out]
        for a, b, step in bank["ranges"]:
            for f in range_channels(a, b, step):
                if not any(abs(f - n) * 1e6 < step / 2 for n in named):
                    out.append((f, ""))
    return sorted(out, key=lambda c: c[0])


def range_channels(start_mhz, stop_mhz, step_hz):
    """Frequencies (MHz) from start to stop inclusive in step_hz steps. ValueError on nonsense."""
    start_mhz, stop_mhz, step_hz = float(start_mhz), float(stop_mhz), float(step_hz)
    if step_hz <= 0:
        raise ValueError("step must be > 0")
    if not (24.0 <= start_mhz <= 1766.0 and 24.0 <= stop_mhz <= 1766.0):
        raise ValueError("range must be within 24-1766 MHz (RTL-SDR tuning range)")
    if stop_mhz < start_mhz:
        start_mhz, stop_mhz = stop_mhz, start_mhz
    n = int(round((stop_mhz - start_mhz) * 1e6 / step_hz)) + 1
    if n > MAX_RANGE_CHANNELS:
        raise ValueError("%d channels — narrow the range or widen the step" % n)
    return [round(start_mhz + i * step_hz / 1e6, 6) for i in range(n)]


def find(mhz, tol_hz=1500):
    """(bank name, label) of a named channel at this frequency, or None."""
    for name in BANK_ORDER:
        for f, lb in BANKS[name]["channels"]:
            if abs(f - mhz) * 1e6 <= tol_hz:
                return name, lb
    return None
