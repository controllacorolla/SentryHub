#!/usr/bin/env python3
"""specan.py — spectrum analyzer (Phase 6/7). Receive-only.

A proper swept spectrum analyzer trace, complementary to the waterfall heatmap: a live trace with
max-hold and an exponential average, movable markers with a delta readout, channel-power integration,
and an RBW derived from the sweep bin width. Feeds from rtl_power sweeps. The trace math, peak
finder, markers and channel power are pure and unit-testable; the Tk workspace draws the trace.
"""
import math
import os
import sys

import noisefloor


def sweep_argv(lo_hz, hi_hz, bin_hz, out, gain=0, interval="1"):
    return ["rtl_power", "-f", "%d:%d:%d" % (int(lo_hz), int(hi_hz), int(bin_hz)),
            "-g", str(int(gain)), "-i", interval, out]


def parse_sweep(line):
    r = noisefloor.parse_rtl_power_row(line)
    return r["bins"] if r else []


def rbw_hz(lo_hz, hi_hz, nbins):
    """Resolution bandwidth ≈ the sweep bin width."""
    return (float(hi_hz) - float(lo_hz)) / nbins if nbins else None


def find_peaks(freqs, dbm, n=8, above_floor_db=8.0, min_sep_bins=3):
    """Strongest local maxima standing above the median floor of this trace."""
    if len(dbm) < 3:
        return []
    import statistics
    floor = statistics.median(dbm)
    cands = []
    for i in range(1, len(dbm) - 1):
        if dbm[i] >= dbm[i - 1] and dbm[i] >= dbm[i + 1] and dbm[i] - floor >= above_floor_db:
            cands.append((i, dbm[i]))
    cands.sort(key=lambda t: -t[1])
    picked = []
    for i, db in cands:
        if all(abs(i - j) >= min_sep_bins for j, _ in picked):
            picked.append((i, db))
        if len(picked) >= n:
            break
    return [{"freq_hz": freqs[i], "dbm": db, "over_db": db - floor} for i, db in sorted(picked)]


def channel_power(freqs, dbm, f_lo, f_hi):
    """Integrated power (dBm) across [f_lo, f_hi] — sum in the linear domain, back to dB."""
    lin = sum(10 ** (db / 10.0) for f, db in zip(freqs, dbm) if f_lo <= f <= f_hi)
    return 10 * math.log10(lin) if lin > 0 else None


def db_to_y(db, ref_dbm, range_db, height):
    """Map a dBm value to a y pixel (ref at top, ref-range at bottom), clamped to the canvas."""
    if range_db <= 0:
        return 0
    t = (ref_dbm - db) / range_db
    return int(max(0.0, min(1.0, t)) * height)


class Spectrum:
    """Holds the live trace plus a per-bin max-hold and an exponential running average."""

    def __init__(self, avg_alpha=0.3):
        self.freqs = []
        self.cur = []
        self.maxhold = []
        self.avg = []
        self.alpha = avg_alpha

    def add(self, bins):
        self.freqs = [f for f, _ in bins]
        row = [d for _, d in bins]
        self.cur = row
        if len(self.maxhold) != len(row):
            self.maxhold = list(row)
            self.avg = list(row)
        else:
            self.maxhold = [max(m, v) for m, v in zip(self.maxhold, row)]
            a = self.alpha
            self.avg = [a * v + (1 - a) * m for v, m in zip(row, self.avg)]
        return row

    def reset_hold(self):
        self.maxhold = list(self.cur)
        self.avg = list(self.cur)

    def nearest(self, freq_hz):
        """Marker readout: the (freq, dbm) of the bin closest to freq_hz on the current trace."""
        if not self.freqs:
            return None
        i = min(range(len(self.freqs)), key=lambda k: abs(self.freqs[k] - freq_hz))
        return {"freq_hz": self.freqs[i], "dbm": self.cur[i], "bin": i}

    def peaks(self, **kw):
        return find_peaks(self.freqs, self.cur, **kw)

    def channel_power(self, f_lo, f_hi):
        return channel_power(self.freqs, self.cur, f_lo, f_hi)


def marker_delta(m1, m2):
    """Delta between two marker readouts: (Δfreq_hz, Δdbm)."""
    if not m1 or not m2:
        return None
    return {"dfreq_hz": m2["freq_hz"] - m1["freq_hz"], "ddbm": m2["dbm"] - m1["dbm"]}


class Demo:
    """Synthetic sweeps: a noise floor with two steady carriers and one drifting signal."""

    def __init__(self, bins=160, lo=430_000_000, step=250_000):
        self.n, self.lo, self.step, self.i = bins, lo, step, 0

    def sweep(self):
        import random
        self.i += 1
        drift = int(self.n * 0.6 + 18 * math.sin(self.i / 12))
        row = []
        for k in range(self.n):
            db = -106 + random.uniform(-2, 2)
            if abs(k - 40) < 2:
                db = -40 + random.uniform(-2, 2)
            if abs(k - 95) < 2:
                db = -58 + random.uniform(-3, 3)
            if abs(k - drift) < 2:
                db = -62 + random.uniform(-3, 3)
            row.append((self.lo + k * self.step, db))
        return row


def main(parent=None):
    import queue
    import threading
    import shutil
    import time
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("SpecAn")
    s, spath = S.settings("specan", {"lo_mhz": 430, "hi_mhz": 470, "bin_khz": 250, "gain": 0,
                                      "ref_dbm": -20, "range_db": 90})
    root, F = S.make_root("Spectrum", parent=parent)
    import tkinter as tk
    T = S.T
    demo = ("--demo" in sys.argv) or not shutil.which("rtl_power")
    sp = Spectrum()
    q = queue.Queue()
    st = {"on": False, "gen": 0, "markers": []}

    top = S.top_bar(root, F, "Spectrum", "Analyzer · max-hold · markers")
    pill = S.pill(top, F, "Off")
    cv = tk.Canvas(root, bg="#05080b", highlightthickness=0)
    cv.pack(fill="both", expand=True)
    info = tk.Label(root, text="click to drop a marker (2 markers → delta)", font=F["map"],
                    fg=T.TXT_3, bg=T.SURFACE, anchor="w")
    info.pack(side="bottom", fill="x")

    def render():
        if not sp.freqs:
            return
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 40 or h < 40:
            return
        ref = float(s.get("ref_dbm", -20))
        rng = float(s.get("range_db", 90))
        nb = len(sp.freqs)
        cv.delete("all")
        for gi in range(1, 6):                                   # horizontal dB gridlines
            y = int(h * gi / 6)
            cv.create_line(0, y, w, y, fill="#13202b")
            cv.create_text(2, y, anchor="w", fill="#35506a", font=F["map"],
                           text="%.0f" % (ref - rng * gi / 6))

        def poly(vals, colour):
            pts = []
            for i, db in enumerate(vals):
                pts.append(int(i * (w - 1) / max(1, nb - 1)))
                pts.append(db_to_y(db, ref, rng, h))
            if len(pts) >= 4:
                cv.create_line(*pts, fill=colour, width=1)
        poly(sp.maxhold, "#7a5a16")                              # max-hold (amber, dim)
        poly(sp.avg, "#2a4a63")                                  # average (blue, dim)
        poly(sp.cur, "#3fd07a")                                  # live trace (green)

        for mf in st["markers"]:
            r = sp.nearest(mf)
            if r:
                x = int(r["bin"] * (w - 1) / max(1, nb - 1))
                cv.create_line(x, 0, x, h, fill="#d05a5a")
                cv.create_text(x + 3, db_to_y(r["dbm"], ref, rng, h), anchor="w", fill="#ffb3b3",
                               font=F["map"], text="%.3f MHz %.0f dBm" % (r["freq_hz"] / 1e6, r["dbm"]))
        pk = sp.peaks(n=3, above_floor_db=10)
        txt = "peaks: " + ("  ".join("%.3fMHz %.0f" % (p["freq_hz"] / 1e6, p["dbm"]) for p in pk)
                           if pk else "—")
        if len(st["markers"]) == 2:
            d = marker_delta(sp.nearest(st["markers"][0]), sp.nearest(st["markers"][1]))
            if d:
                txt += "   Δ %.3f MHz  %.1f dB" % (d["dfreq_hz"] / 1e6, d["ddbm"])
        info.config(text=txt)

    def on_click(e):
        if not sp.freqs:
            return
        w = cv.winfo_width()
        nb = len(sp.freqs)
        i = min(nb - 1, max(0, int(e.x * (nb - 1) / max(1, w - 1))))
        st["markers"].append(sp.freqs[i])
        st["markers"] = st["markers"][-2:]
        render()
    cv.bind("<Button-1>", on_click)
    cv.bind("<Configure>", lambda e: render())

    def worker(gen):
        if demo:
            dm = Demo()
            while st["on"] and st["gen"] == gen:
                q.put(dm.sweep())
                time.sleep(0.3)
            return
        lo = int(float(s.get("lo_mhz", 430)) * 1e6)
        hi = int(float(s.get("hi_mhz", 470)) * 1e6)
        binhz = int(float(s.get("bin_khz", 250)) * 1e3)
        with S.errfile(os.path.join(S.CACHE, "specan.err")) as err:
            p = S.spawn(" ".join(sweep_argv(lo, hi, binhz, "-", s.get("gain", 0), "1")),
                        shell=True, stdout=__import__("subprocess").PIPE, stderr=err, text=True)
        try:
            for line in p.stdout:
                if not st["on"] or st["gen"] != gen:
                    break
                b = parse_sweep(line)
                if b:
                    q.put(b)
        finally:
            S.stop_group(p, grace=1.0)

    def pump():
        got = False
        try:
            for _ in range(50):
                sp.add(q.get_nowait())
                got = True
        except queue.Empty:
            pass
        if got:
            render()
        root.after(250, pump)

    def toggle(_=None):
        if st["on"]:
            st["on"] = False
            st["gen"] += 1
            pill.config(text="Off", bg=S.DIM)
            T.set_btn(btn, "Start", kind="primary")
        else:
            st["on"] = True
            st["gen"] += 1
            pill.config(text="Sweeping" + (" (demo)" if demo else ""), bg=S.GREEN)
            T.set_btn(btn, "Stop", kind="danger")
            threading.Thread(target=worker, args=(st["gen"],), daemon=True).start()

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    btn = S.btn(bar, "Start", toggle, F, padx=14, pady=5, kind="primary")
    btn.pack(side="left", padx=(10, 6), pady=6)
    S.btn(bar, "Reset hold", lambda: (sp.reset_hold(), render()), F, padx=10, pady=5,
          kind="ghost").pack(side="left", padx=2)
    S.btn(bar, "Clear markers", lambda: (st["markers"].clear(), render()), F, padx=10, pady=5,
          kind="ghost").pack(side="left", padx=2)
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))
    root.bind("<space>", toggle)

    def on_close():
        st["on"] = False
        st["gen"] += 1
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()
    S.bind_quit(root, on_close)
    pump()
    if "--demo" in sys.argv:
        root.after(300, toggle)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
