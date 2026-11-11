#!/usr/bin/env python3
"""RF Explorer - band spectrum + waterfall swept with rtl_power on the built-in RTL.

Pick a band, watch the spectrum and waterfall, click a peak (or press Enter) to tune
and listen with rtl_fm; sweeping pauses while listening because the one dongle can't
do both. Receive-only: this app only ever reads the spectrum.

--demo sweeps a synthetic band so the display can be exercised without hardware;
it is also the automatic fallback when rtl_power is not installed.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
import queue
import math
import random

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import suite as S           # noqa: E402
from scanner import sink_cmd, rtl_cmd   # noqa: E402

# label, MHz lo, MHz hi, step kHz, listen mode
BANDS = [
    ("FM radio", 88.0, 108.0, 50.0, "wbfm"),
    ("Airband", 118.0, 137.0, 25.0, "am"),
    ("2m ham", 144.0, 148.0, 12.5, "nfm"),
    ("VHF public", 150.0, 163.0, 12.5, "nfm"),
    ("ISM 433", 432.5, 435.0, 10.0, "nfm"),
    ("70cm ham", 440.0, 450.0, 25.0, "nfm"),
    ("GMRS", 462.0, 468.0, 12.5, "nfm"),
    ("VHF wide", 118.0, 174.0, 50.0, "nfm"),
]
BAND_BY_NAME = {b[0]: b for b in BANDS}
DEFAULTS = {"band": "FM radio", "gain": 32}


def tune_cmd(freq_mhz, mode, gain):
    if mode == "wbfm":
        return ["rtl_fm", "-f", "%.4fM" % freq_mhz, "-M", "wbfm", "-s", "170k",
                "-r", "12k", "-g", str(int(gain)), "-"]
    return rtl_cmd(freq_mhz, mode, gain)


def power_cmd(lo, hi, step_khz, gain):
    return ["rtl_power", "-f", "%gM:%gM:%gk" % (lo, hi, step_khz),
            "-g", str(int(gain)), "-i", "1", "-"]


def parse_row(line):
    """One rtl_power CSV row -> (hz_lo, hz_step, [dB]) or None."""
    p = [c.strip() for c in str(line).split(",")]
    if len(p) < 8:
        return None
    try:
        hz_lo, step = float(p[2]), float(p[4])
        dbs = [float(v) for v in p[6:] if v]
    except ValueError:
        return None
    if not (math.isfinite(hz_lo) and math.isfinite(step)):
        return None
    # rtl_power can print nan / -inf bins (e.g. a dead first hop); they break the median,
    # the scale and Tk coordinates. Replace them with the row's floor so bin->frequency
    # positions stay aligned.
    good = [v for v in dbs if math.isfinite(v)]
    if not good:
        return None
    floor = min(good)
    dbs = [v if math.isfinite(v) else floor for v in dbs]
    return (hz_lo, step, dbs)


class SweepAssembler:
    """rtl_power prints one row per retune hop; a full sweep is several rows.
    Rows are collected until the band's lowest hop repeats, then the previous
    sweep is emitted as (freqs_mhz, dbs)."""

    def __init__(self):
        self.rows = {}

    def feed(self, line):
        r = parse_row(line)
        if not r:
            return None
        hz_lo, step, dbs = r
        out = None
        if hz_lo in self.rows and hz_lo <= min(self.rows):
            out = self.emit()
        self.rows[hz_lo] = (step, dbs)
        return out

    def emit(self):
        if not self.rows:
            return None
        freqs, dbs = [], []
        for hz_lo in sorted(self.rows):
            step, row = self.rows[hz_lo]
            for i, db in enumerate(row):
                freqs.append((hz_lo + i * step) / 1e6)
                dbs.append(db)
        self.rows = {}
        return (freqs, dbs) if freqs else None


def find_peaks(freqs, dbs, above_floor=8.0, n=8, min_gap_bins=4):
    """Local maxima at least above_floor dB over the median floor, strongest first."""
    if len(dbs) < 3:
        return []
    med = sorted(dbs)[len(dbs) // 2]
    thr = med + above_floor
    cand = [i for i in range(1, len(dbs) - 1)
            if dbs[i] >= thr and dbs[i] >= dbs[i - 1] and dbs[i] >= dbs[i + 1]]
    cand.sort(key=lambda i: -dbs[i])
    out = []
    for i in cand:
        if all(abs(i - j) >= min_gap_bins for j, _, _ in out):
            out.append((i, freqs[i], dbs[i]))
        if len(out) >= n:
            break
    return out


def demo_carriers(lo, hi):
    """Stable pseudo-random carriers for a band, plus one bursty one."""
    rnd = random.Random(int(lo * 1000) ^ int(hi * 7))
    span = hi - lo
    cs = []
    for k in range(4):
        cs.append((lo + span * (0.12 + 0.76 * rnd.random()),
                   -4 - 14 * rnd.random(), None))          # steady
    cs.append((lo + span * (0.3 + 0.4 * rnd.random()), -6, 7.0))   # bursts every ~7 s
    if 88.0 <= lo <= 89.0:   # FM band: put them on real-looking channels
        cs = [(88.5, -9, None), (94.1, -5, None), (98.5, -11, None),
              (103.5, -7, None), (105.9, -10, 6.0)]
    if abs(lo - 150.0) < 1 or abs(hi - 163.0) < 1:
        cs.append((162.55, -10, None))                      # NOAA is always on
    return cs


def demo_sweep(lo, hi, step_khz, t):
    n = max(40, int((hi - lo) * 1000 / step_khz))
    carriers = demo_carriers(lo, hi)
    freqs, dbs = [], []
    rnd = random.Random()
    for i in range(n):
        f = lo + (hi - lo) * i / (n - 1)
        db = -36.0 + rnd.gauss(0, 1.1)
        for cf, amp, burst in carriers:
            if burst and (t % burst) > burst * 0.35:
                continue
            w = 3.5 * step_khz / 1000.0
            db = max(db, amp - ((f - cf) / w) ** 2 * 18 + rnd.gauss(0, 0.6))
        freqs.append(f)
        dbs.append(db)
    return freqs, dbs


def main():
    S.single_instance("RF Explorer")
    s, _spath = S.settings("rf_explorer", DEFAULTS)
    if s.get("band") not in BAND_BY_NAME:
        s["band"] = DEFAULTS["band"]
    root, F = S.make_root("RF Explorer")
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("rf_explorer")
    lease = S.RtlLease("RF Explorer", log=lambda m: None)
    lease.on_preempt = lambda: stop_all()   # another workspace wants the radio
    demo = "--demo" in sys.argv or not shutil.which("rtl_power")

    st = {"mode": "stopped", "band": s["band"], "gain": int(s["gain"]),
          "sel": None, "sweep": None, "peaks": [], "proc": None, "sink": None,
          "thread": None, "run": False, "lo": None, "hi": None, "gen": 0}
    q = queue.Queue()

    # ---- top bar
    top = S.top_bar(root, F, "RF Explorer", "demo sweep" if demo else "Built-in SDR")
    state_pill = S.pill(top, F, "Stopped")
    peak_pill = S.pill(top, F, "")
    freq_lbl = tk.Label(top, text="", font=F["smb"], fg=S.AMBER, bg=T.SURFACE)
    freq_lbl.pack(side="right", padx=10)

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    spec = tk.Canvas(body, bg=S.MAPBG, highlightthickness=0)
    spec.pack(fill="both", expand=True, padx=10, pady=(8, 2))
    wf_cv = tk.Canvas(body, bg=S.MAPBG, highlightthickness=0, height=T.px(210))
    wf_cv.pack(fill="x", padx=10, pady=(2, 4))
    status = tk.Label(root, text="", font=F["sm"], fg=S.MUTED, bg=S.BG, anchor="w")
    status.pack(fill="x", padx=12)

    # waterfall double buffer (copying an image onto itself is undefined in Tk)
    wf = {"a": None, "b": None, "w": 0, "h": 0, "item": None}

    def heat(tf):
        tf = max(0.0, min(1.0, tf))
        stops = ([(0.0, (8, 9, 11)), (0.45, (18, 42, 82)), (0.75, (76, 144, 240)),
                  (1.0, (232, 240, 255))] if T.STYLE == "maven" and not T.NIGHT else
                 [(0.0, (10, 14, 18)), (0.45, (74, 46, 8)), (0.75, (240, 165, 42)),
                  (1.0, (255, 243, 200))])
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if tf <= t1:
                k = (tf - t0) / (t1 - t0)
                return "#%02x%02x%02x" % tuple(int(a + (b - a) * k) for a, b in zip(c0, c1))
        return "#%02x%02x%02x" % stops[-1][1]

    def db_range(dbs):
        med = sorted(dbs)[len(dbs) // 2]
        return med - 5.0, max(max(dbs) + 3.0, med + 25.0)

    def x_of(f, w):
        lo, hi = st["lo"], st["hi"]
        return (f - lo) / (hi - lo) * (w - 1) if hi > lo else 0

    def f_of(x, w):
        lo, hi = st["lo"], st["hi"]
        return lo + (hi - lo) * max(0, min(w - 1, x)) / (w - 1)

    def draw_spectrum():
        spec.delete("all")
        w, h = spec.winfo_width(), spec.winfo_height()
        if w < 40 or not st["sweep"]:
            if w > 40:
                spec.create_text(w / 2, h / 2, fill=S.MUTED, font=F["sm"],
                                 text="press Sweep to start" if st["mode"] == "stopped"
                                 else "sweeping...")
            return
        freqs, dbs = st["sweep"]
        lo_db, hi_db = db_range(dbs)

        def y_of(db):
            return h - 4 - (max(lo_db, min(hi_db, db)) - lo_db) / (hi_db - lo_db) * (h - 20)
        # grid + frequency labels
        for gx in range(6):
            x = 6 + gx * (w - 12) / 5
            f = f_of(x, w)
            spec.create_line(x, 4, x, h - 14, fill=T.night("#1a2228"))
            spec.create_text(max(24, min(w - 24, x)), h - 7, text="%.2f" % f,
                             fill=S.MUTED, font=F["map"])
        for gdb in range(4):
            db = lo_db + (hi_db - lo_db) * gdb / 3
            spec.create_line(0, y_of(db), w, y_of(db), fill=T.night("#141b20"))
            spec.create_text(w - 4, y_of(db) - 7, text="%d" % db, anchor="e",
                             fill=T.night("#3c4850"), font=F["map"])
        pts = []
        for f, db in zip(freqs, dbs):
            pts += [x_of(f, w), y_of(db)]
        if len(pts) >= 4:
            spec.create_line(*pts, fill=T.ACCENT, width=1)
        for i, f, db in st["peaks"][:6]:
            x = x_of(f, w)
            spec.create_polygon(x, y_of(db) - 10, x - 4, y_of(db) - 17, x + 4, y_of(db) - 17,
                                fill=S.AMBER, outline="")
            spec.create_text(x, y_of(db) - 26, text="%.3f" % f, fill=S.AMBER, font=F["map"])
        if st["sel"] is not None:
            x = x_of(st["sel"], w)
            spec.create_line(x, 0, x, h, fill=S.AMBER, dash=(3, 3))
            spec.create_text(min(w - 40, max(40, x)), 10, text="%.4f MHz" % st["sel"],
                             fill=S.AMBER, font=F["smb"])

    def push_waterfall(freqs, dbs):
        w, h = wf_cv.winfo_width(), int(wf_cv.winfo_height())
        if w < 40 or h < 20:
            return
        if wf["w"] != w or wf["h"] != h:
            wf["a"] = tk.PhotoImage(width=w, height=h)
            wf["b"] = tk.PhotoImage(width=w, height=h)
            wf["w"], wf["h"] = w, h
            wf["item"] = None
        lo_db, hi_db = db_range(dbs)
        n = len(dbs)
        row = []
        for x in range(w):
            i = min(n - 1, int(x * n / w))
            j = min(n, max(i + 1, int((x + 1) * n / w)))
            db = max(dbs[i:j])
            row.append(heat((db - lo_db) / (hi_db - lo_db)))
        src, dst = wf["a"], wf["b"]
        rpx = 2   # draw each sweep 2 px tall so the fall fills at a readable rate
        dst.tk.call(dst, "copy", src, "-from", 0, 0, w, h - rpx, "-to", 0, rpx)
        line = "{" + " ".join(row) + "} "
        dst.put(line * rpx, to=(0, 0))
        wf["a"], wf["b"] = dst, src
        if wf["item"] is None:
            wf["item"] = wf_cv.create_image(0, 0, anchor="nw", image=dst)
        else:
            wf_cv.itemconfig(wf["item"], image=dst)

    # ---- sweep engine ---------------------------------------------------------
    def sweep_loop(band, gen):
        # gen: a stop+start (band/gain change) bumps st["gen"]; this thread then knows it is
        # stale and must neither keep sweeping nor report "died" for the new sweep
        label, lo, hi, step, _mode = band
        asm = SweepAssembler()
        t0 = time.time()
        if demo:
            while st["run"] and st["gen"] == gen:
                q.put(("sweep", demo_sweep(lo, hi, step, time.time() - t0)))
                time.sleep(0.7)
            return
        err_path = os.path.join(S.CACHE, "rf_explorer.err")
        with S.errfile(err_path) as err:
            # own session, so S.stop_group() can actually signal and wait for it
            p = subprocess.Popen(power_cmd(lo, hi, step, st["gain"]),
                                 stdout=subprocess.PIPE, stderr=err, text=True,
                                 errors="replace", start_new_session=True)
        if st["gen"] == gen:
            st["proc"] = p
        try:
            for line in p.stdout:
                if not st["run"] or st["gen"] != gen:
                    break
                out = asm.feed(line)
                if out:
                    q.put(("sweep", out))
        finally:
            S.stop_group(p)
            if st["run"] and st["gen"] == gen:
                q.put(("sweeper_died", None))

    def take_radio(then):
        """Get the dongle from the plane map without freezing the window, then run then()."""
        st["mode"] = "starting"
        state_pill.config(text="Starting", bg=S.AMBER)
        status.config(text="Taking the SDR from the plane map…", fg=S.MUTED)

        def done(ok, err):
            if st["mode"] != "starting":
                return          # Stop was pressed meanwhile; its release is queued after us
            if not ok:
                st["mode"] = "stopped"
                state_pill.config(text="Stopped", bg=S.DIM)
                status.config(text="SDR busy: %s" % str(err)[:70], fg=S.RED)
                return
            st["mode"] = "paused"
            then()
        S.acquire_bg(root, lease, done)

    def start_sweep():
        if st["mode"] in ("sweep", "starting"):
            return
        stop_listen(keep_lease=True)
        if st["mode"] == "stopped" and not demo:
            take_radio(start_sweep)
            return
        band = BAND_BY_NAME[st["band"]]
        st["lo"], st["hi"] = band[1], band[2]
        st["gen"] += 1
        st["run"], st["mode"] = True, "sweep"
        state_pill.config(text="Sweeping", bg=S.GREEN)
        status.config(text="%s  ·  %.3f-%.3f MHz  ·  gain %d  ·  click a peak to listen"
                      % (band[0], band[1], band[2], st["gain"]), fg=S.MUTED)
        st["thread"] = threading.Thread(target=sweep_loop, args=(band, st["gen"]), daemon=True)
        st["thread"].start()

    def stop_sweep():
        st["run"] = False
        st["gen"] += 1
        p = st["proc"]
        st["proc"] = None
        if p:
            # wait for it: the next rtl_power/rtl_fm can't claim the dongle until it's gone
            S.stop_group(p, grace=1.5)

    def stop_all(sync=False):
        stop_sweep()
        stop_listen(keep_lease=False, sync=sync)
        st["mode"] = "stopped"
        state_pill.config(text="Stopped", bg=S.DIM)
        status.config(text="stopped", fg=S.MUTED)

    # ---- listen ---------------------------------------------------------------
    def listen(freq):
        if st["mode"] == "starting":
            return
        if st["mode"] == "stopped" and not demo:
            # after Stop the lease is back with readsb: take it again before tuning
            st["sel"] = freq
            take_radio(lambda: listen(freq))
            return
        band = BAND_BY_NAME[st["band"]]
        mode = band[4]
        stop_listen(keep_lease=True)   # retuning: the old rtl_fm AND its sink must go
        stop_sweep()
        sink = sink_cmd()
        st["mode"] = "listen"
        st["sel"] = freq
        state_pill.config(text="Listening", bg=S.AMBER)
        freq_lbl.config(text="%.4f MHz %s" % (freq, mode.upper()))
        slog.event("rf_explorer", "tuned %.4f MHz %s (%s)" % (freq, mode.upper(), band[0]),
                   id="%.4f" % freq)
        if demo:
            status.config(text="demo: would listen on %.4f MHz %s" % (freq, mode.upper()),
                          fg=S.AMBER)
            return
        if not sink:
            status.config(text="no audio sink (pacat/aplay missing)", fg=S.RED)
            return
        with S.errfile(os.path.join(S.CACHE, "rf_explorer_fm.err")) as err:
            p1 = subprocess.Popen(tune_cmd(freq, mode, st["gain"]),
                                  stdout=subprocess.PIPE, stderr=err, start_new_session=True)
        try:
            p2 = subprocess.Popen(sink, stdin=p1.stdout, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            S.stop_group(p1)
            raise
        finally:
            p1.stdout.close()   # parent's copy: lets rtl_fm see SIGPIPE if the sink dies
        st["proc"], st["sink"] = p1, p2
        status.config(text="listening %.4f MHz %s  ·  Space resumes the sweep"
                      % (freq, mode.upper()), fg=S.AMBER)

    def stop_listen(keep_lease, sync=False):
        for k in ("proc", "sink"):
            p = st.get(k)
            st[k] = None
            if p:
                S.stop_group(p, grace=1.0)   # waits, so the dongle is free for what's next
        if not keep_lease and not demo and st["mode"] != "stopped":
            if sync:
                S.release_now(lease)         # quitting: a background release could die with us
            else:
                S.release_bg(root, lease)
        freq_lbl.config(text="")

    # ---- interactions ---------------------------------------------------------
    def on_click(e, from_wf=False):
        w = (wf_cv if from_wf else spec).winfo_width()
        if st["lo"] is None or w < 40:
            return
        f = f_of(e.x, w)
        # snap to the nearest found peak within ~1% of the span
        near = [p for p in st["peaks"] if abs(p[1] - f) < (st["hi"] - st["lo"]) * 0.01]
        if near:
            f = min(near, key=lambda p: abs(p[1] - f))[1]
        st["sel"] = f
        freq_lbl.config(text="%.4f MHz" % f)
        draw_spectrum()

    def tune_sel(_=None):
        if st["sel"] is not None:
            listen(st["sel"])

    def tune_strongest(_=None):
        if st["peaks"]:
            st["sel"] = st["peaks"][0][1]
            listen(st["sel"])

    def toggle_sweep(_=None):
        stop_all() if st["mode"] in ("sweep", "starting") else start_sweep()

    def set_band(name):
        st["band"] = s["band"] = name
        S.save_json(_spath, s)
        for nm, b in band_btns.items():
            T.set_btn(b, kind="primary" if nm == name else "ghost")
        st["sel"], st["peaks"], st["sweep"] = None, [], None
        if st["mode"] in ("sweep", "listen"):
            stop_listen(keep_lease=True)
            stop_sweep()
            st["mode"] = "paused"
            start_sweep()
        else:
            band = BAND_BY_NAME[name]
            st["lo"], st["hi"] = band[1], band[2]
            draw_spectrum()

    def set_gain(d):
        st["gain"] = s["gain"] = max(0, min(49, st["gain"] + d))
        S.save_json(_spath, s)
        gain_lbl.config(text="%d dB" % st["gain"])
        if st["mode"] == "sweep":   # restart the sweep at the new gain
            stop_sweep()
            st["mode"] = "paused"
            start_sweep()

    # ---- bottom controls
    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    sweep_btn = S.btn(bar, "Sweep", toggle_sweep, F, padx=14, pady=5, kind="primary")
    sweep_btn.pack(side="left", padx=(10, 6), pady=6)
    S.btn(bar, "Tune", tune_sel, F, padx=10, pady=5, kind="ghost").pack(side="left", padx=2)
    S.btn(bar, "Strongest", tune_strongest, F, padx=10, pady=5,
          kind="ghost").pack(side="left", padx=2)
    band_box = tk.Frame(bar, bg=T.SURFACE)
    band_box.pack(side="left", padx=8)
    band_btns = {}
    SHORT = {"FM radio": "FM", "Airband": "Air", "2m ham": "2m", "VHF public": "VHF-P",
             "ISM 433": "433", "70cm ham": "70cm", "GMRS": "GMRS", "VHF wide": "VHF-W"}
    for name, *_rest in BANDS:
        b = S.btn(band_box, SHORT.get(name, name), lambda n=name: set_band(n), F,
                  font="map", padx=4, pady=3,
                  kind="primary" if name == st["band"] else "ghost")
        b.pack(side="left", padx=1)
        band_btns[name] = b
    S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5,
          kind="quiet").pack(side="right", padx=(2, 10))
    gain_lbl = tk.Label(bar, text="%d dB" % st["gain"], font=F["mono"], fg=S.TXT,
                        bg=T.SURFACE)
    S.btn(bar, "+", lambda: set_gain(+4), F, padx=8, pady=5,
          kind="ghost").pack(side="right", padx=1)
    gain_lbl.pack(side="right", padx=4)
    S.btn(bar, "−", lambda: set_gain(-4), F, padx=8, pady=5,
          kind="ghost").pack(side="right", padx=1)

    spec.bind("<Button-1>", on_click)
    wf_cv.bind("<Button-1>", lambda e: on_click(e, True))
    spec.bind("<Double-Button-1>", lambda e: (on_click(e), tune_sel()))
    root.bind("<Return>", tune_sel)
    root.bind("<space>", toggle_sweep)
    root.bind("b", lambda e: set_band(BANDS[([b[0] for b in BANDS].index(st["band"]) + 1)
                                            % len(BANDS)][0]))
    spec.bind("<Configure>", lambda e: draw_spectrum())

    def pump():
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "sweep":
                    freqs, dbs = payload
                    st["sweep"] = (freqs, dbs)
                    st["peaks"] = find_peaks(freqs, dbs)
                    if st["peaks"]:
                        i, f, db = st["peaks"][0]
                        peak_pill.config(text="peak %.3f  %d dB" % (f, int(db)), bg=S.AMBER)
                    draw_spectrum()
                    push_waterfall(freqs, dbs)
                elif kind == "sweeper_died":
                    if st["mode"] == "sweep":
                        status.config(text="rtl_power exited - see rf_explorer.err "
                                           "(SDR unplugged or busy?)", fg=S.RED)
                        stop_all()
        except queue.Empty:
            pass
        except Exception as e:      # one bad frame must not stop the pump for good
            status.config(text="display error: %s" % str(e)[:70], fg=S.RED)
        root.after(120, pump)

    def on_close():
        st["run"] = False
        stop_all(sync=True)
        root.destroy()

    S.bind_quit(root, on_close)
    band = BAND_BY_NAME[st["band"]]
    st["lo"], st["hi"] = band[1], band[2]
    if "--sweep" in sys.argv or demo:
        root.after(400, start_sweep)
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
