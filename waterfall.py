#!/usr/bin/env python3
"""waterfall.py — wideband spectrum waterfall (Phase 6 #1). Receive-only.

A scrolling waterfall with peak-hold and noise-floor tracking so you can *see* the unknown signal,
not just decode a known one. Feeds from rtl_power sweeps (reuses the noise-floor parser). Pure
buffer/peak logic is unit-testable; the Tk workspace renders the heatmap.
"""
import os
import statistics
import sys

import noisefloor


def rtl_power_sweep_argv(lo_hz, hi_hz, bin_hz, out_csv, gain=0, interval="1"):
    return ["rtl_power", "-f", "%d:%d:%d" % (int(lo_hz), int(hi_hz), int(bin_hz)),
            "-g", str(int(gain)), "-i", interval, out_csv]


def parse_sweep(line):
    """One rtl_power CSV row -> list of (freq_hz, dbm)."""
    r = noisefloor.parse_rtl_power_row(line)
    return r["bins"] if r else []


class Waterfall:
    """Holds the last N sweep rows plus a per-bin peak-hold and the current noise floor."""

    def __init__(self, max_rows=256):
        self.max_rows = max_rows
        self.rows = []              # each row: list of dbm values aligned to self.freqs
        self.freqs = []
        self.peak_hold = {}         # freq_hz -> max dbm ever seen

    def add_sweep(self, bins):
        self.freqs = [f for f, _ in bins]
        row = [db for _, db in bins]
        self.rows.append(row)
        del self.rows[:-self.max_rows]
        for f, db in bins:
            if db > self.peak_hold.get(f, -1e9):
                self.peak_hold[f] = db
        return row

    def reset_peak_hold(self):
        self.peak_hold = {}

    def noise_floor(self):
        """Median power of the latest row (the current floor)."""
        return statistics.median(self.rows[-1]) if self.rows else None

    def peaks(self, above_floor_db=8.0, n=10, min_gap_bins=3):
        """Strongest local maxima in the latest row that stand above the floor."""
        if not self.rows:
            return []
        row = self.rows[-1]
        floor = statistics.median(row)
        cands = []
        for i in range(1, len(row) - 1):
            if row[i] >= row[i - 1] and row[i] >= row[i + 1] and row[i] - floor >= above_floor_db:
                cands.append((i, row[i]))
        cands.sort(key=lambda t: -t[1])
        picked = []
        for i, db in cands:
            if all(abs(i - j) >= min_gap_bins for j, _ in picked):
                picked.append((i, db))
            if len(picked) >= n:
                break
        return [{"freq_hz": self.freqs[i], "dbm": db, "over_db": db - floor}
                for i, db in sorted(picked)]


def heat_color(db, floor=-110.0, ceil=-20.0):
    """Map a dBm value to a blue->green->yellow->red heat colour (hex)."""
    t = 0.0 if ceil == floor else max(0.0, min(1.0, (db - floor) / (ceil - floor)))
    r = int(255 * min(1.0, max(0.0, 1.6 * t - 0.6)))
    g = int(255 * min(1.0, max(0.0, 1.6 * t)) if t < 0.75 else 255 * max(0.0, 1.0 - (t - 0.75) * 2))
    b = int(255 * max(0.0, 1.0 - 2.2 * t))
    return "#%02x%02x%02x" % (r, g, b)


class Demo:
    """Synthetic sweeps: a noise floor with a couple of signals, one of them drifting."""

    def __init__(self, bins=120, lo=400_000_000, step=250_000):
        self.n, self.lo, self.step, self.i = bins, lo, step, 0

    def sweep(self):
        import math
        import random
        self.i += 1
        row = []
        drift = int(self.n / 2 + 20 * math.sin(self.i / 15))
        for k in range(self.n):
            db = -108 + random.uniform(-2, 2)
            if abs(k - 30) < 2:
                db = -45 + random.uniform(-3, 3)          # steady carrier
            if abs(k - drift) < 2:
                db = -55 + random.uniform(-4, 4)          # drifting signal
            row.append((self.lo + k * self.step, db))
        return row


def main(parent=None):
    import queue
    import threading
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Waterfall")
    s, spath = S.settings("waterfall", {"lo_mhz": 400, "hi_mhz": 430, "bin_khz": 250, "gain": 0})
    root, F = S.make_root("Waterfall", parent=parent)
    import tkinter as tk
    T = S.T
    demo = ("--demo" in sys.argv) or not shutil.which("rtl_power")
    wf = Waterfall(max_rows=220)
    q = queue.Queue()
    st = {"on": False, "gen": 0, "img": None, "w": 0, "h": 0}

    top = S.top_bar(root, F, "Waterfall", "Wideband spectrum · peak-hold")
    pill = S.pill(top, F, "Off")
    body = tk.Frame(root, bg=S.MAPBG)
    body.pack(fill="both", expand=True)
    cv = tk.Canvas(body, bg="#05080b", highlightthickness=0)
    cv.pack(fill="both", expand=True)
    info = tk.Label(root, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w")
    info.pack(side="bottom", fill="x")

    def render():
        if not wf.rows:
            return
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 40 or h < 40:
            return
        nb = len(wf.freqs)
        if st["img"] is None or st["w"] != w or st["h"] != h:
            st["img"] = tk.PhotoImage(width=w, height=h)
            st["w"], st["h"] = w, h
            cv.delete("all")
            cv.create_image(0, 0, anchor="nw", image=st["img"])
        img = st["img"]
        rows = wf.rows[-h:]
        # build the image bottom-up from the most recent rows
        for yy, row in enumerate(reversed(rows)):
            y = h - 1 - yy
            line = " ".join(heat_color(row[int(x * nb / w)]) for x in range(w))
            img.put("{" + line + "}", to=(0, y))
        floor = wf.noise_floor()
        pk = wf.peaks(above_floor_db=10, n=5)
        info.config(text="floor %.0f dBm · %d peaks%s" % (
            floor or 0, len(pk),
            ("  top: %.3f MHz" % (pk[0]["freq_hz"] / 1e6)) if pk else ""))

    def worker(gen):
        if demo:
            dm = Demo()
            while st["on"] and st["gen"] == gen:
                q.put(dm.sweep())
                __import__("time").sleep(0.3)
            return
        lo = int(float(s.get("lo_mhz", 400)) * 1e6)
        hi = int(float(s.get("hi_mhz", 430)) * 1e6)
        binhz = int(float(s.get("bin_khz", 250)) * 1e3)
        with S.errfile(os.path.join(S.CACHE, "waterfall.err")) as err:
            p = S.spawn(" ".join(rtl_power_sweep_argv(lo, hi, binhz, "-", s.get("gain", 0), "1")),
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
                wf.add_sweep(q.get_nowait())
                got = True
        except queue.Empty:
            pass
        if got:
            render()
        root.after(300, pump)

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
    S.btn(bar, "Reset peak", lambda: wf.reset_peak_hold(), F, padx=10, pady=5, kind="ghost").pack(
        side="left", padx=2)
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))
    root.bind("<space>", toggle)
    cv.bind("<Configure>", lambda e: render())

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
