#!/usr/bin/env python3
"""SSTV - pictures from the International Space Station on 145.800 MHz. Receive-only.

The ISS only sends SSTV during announced ARISS events (a few times a year; the schedule
is posted at ariss.org). This app predicts ISS passes over you, records a pass's audio
(armed in advance, or by hand any time), and decodes PD-mode pictures (PD120/PD180/...)
with the built-in decoder - no qsstv, no audio routing.

--demo shows the app without hardware (recording disabled; decoding still works).
"""
import glob
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import suite as S          # noqa: E402
import sstvdec as D        # noqa: E402

DIR = os.path.join(S.DATA, "sstv")
TLE = os.path.join(S.CACHE, "sstv.tle")
SATS = {"satellites": [{"name": "ISS", "norad": 25544, "freq": 145.8}],
        "tle_urls": ["https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle"]}
DEFAULTS = {"gain": 40, "freq": 145.800, "auto": False, "min_elev": 20,
            "home": {"lat": 39.62, "lon": -104.87, "alt_m": 1750}}
RATE = 24000          # Hz: twice what SSTV needs, so each pixel averages more samples


def rec_cmd(freq, gain):
    """NFM audio for SSTV: no de-emphasis (it would tilt the tones), DC removed so ISS
    Doppler (+-3.5 kHz) doesn't offset the audio."""
    return ["rtl_fm", "-f", "%.4fM" % freq, "-M", "fm", "-s", str(RATE),
            "-g", str(int(gain)), "-E", "dc", "-"]


def good_pass(p, min_elev):
    return p.get("max", 0) >= min_elev


def pass_line(p, now=None):
    now = now or time.time()
    aos, los = p["aos"], p["los"]
    when = time.strftime("%a %H:%M", time.localtime(aos))
    dur = int((los - aos) / 60)
    if aos <= now <= los:
        state = "NOW"
    elif aos > now:
        m = int((aos - now) / 60)
        state = "in %dh%02d" % (m // 60, m % 60) if m >= 60 else "in %d min" % m
    else:
        state = "done"
    return "%-9s %3d°  %2d min  %-10s %s" % (when, round(p["max"]), dur,
                                             p.get("dir", ""), state)


class Recorder:
    """rtl_fm -> WAV file, optionally also to the speaker. One per recording."""

    def __init__(self, path, freq, gain, monitor):
        self.path, self.level, self.err = path, 0.0, ""
        self.proc = self.sink = None
        self.t0 = time.time()
        self.stop_flag = threading.Event()
        errf = S.errfile(os.path.join(S.CACHE, "sstv_rtl.err"))
        self.proc = subprocess.Popen(rec_cmd(freq, gain), stdout=subprocess.PIPE, stderr=errf,
                                     start_new_session=True)
        errf.close()
        if monitor:
            sc = shutil.which("pacat") and ["pacat", "--raw", "--format=s16le",
                                             "--rate=%d" % RATE, "--channels=1"]
            if sc:
                self.sink = subprocess.Popen(sc, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, start_new_session=True)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        import array
        w = wave.open(self.path, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        try:
            while not self.stop_flag.is_set():
                chunk = self.proc.stdout.read(4800)
                if not chunk:
                    self.err = "rtl_fm stopped - is the SDR free?"
                    break
                chunk = chunk[: len(chunk) // 2 * 2]
                w.writeframes(chunk)
                a = array.array("h")
                a.frombytes(chunk)
                self.level = (sum(x * x for x in a[::8]) / max(1, len(a[::8]))) ** 0.5
                if self.sink:
                    try:
                        self.sink.stdin.write(chunk)
                    except (BrokenPipeError, ValueError, OSError):
                        self.sink = None
        finally:
            w.close()

    def stop(self):
        self.stop_flag.set()
        for p in (self.proc, self.sink):
            if p:
                S.stop_group(p, grace=1.0)
        self.thread.join(timeout=3)

    def seconds(self):
        return time.time() - self.t0


def main():
    S.single_instance("SSTV")
    s, spath = S.settings("sstv", DEFAULTS)
    root, F = S.make_root("SSTV")
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("sstv")
    lease = S.RtlLease("SSTV", log=lambda m: None)
    lease.on_preempt = lambda: stop_rec()   # another workspace wants the radio
    demo = "--demo" in sys.argv or not shutil.which("rtl_fm")
    os.makedirs(DIR, exist_ok=True)
    q = queue.Queue()
    st = {"passes": [], "rec": None, "starting": False, "auto_pass": None,
          "img": None, "photo": None, "decoding": False, "pred_err": ""}

    top = S.top_bar(root, F, "SSTV", "ISS · %.3f MHz · receive-only" % s["freq"])
    state_pill = S.pill(top, F, "Idle")
    next_pill = S.pill(top, F, "")

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    left = tk.Frame(body, bg=T.SURFACE, width=T.px(470))
    left.pack(side="left", fill="y")
    left.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    lp = tk.Frame(left, bg=T.SURFACE)
    lp.pack(fill="both", expand=True, padx=T.px(14), pady=T.px(12))
    T.section(lp, F, "ISS passes over you").pack(fill="x")
    passes_box = tk.Text(lp, bg=T.SURFACE, fg=T.TXT_2, font=F["mono"], bd=0,
                         highlightthickness=0, height=9, wrap="none", state="disabled")
    passes_box.tag_config("good", foreground=S.TXT)
    passes_box.tag_config("now", foreground=S.AMBER)
    passes_box.tag_config("hdr", foreground=T.TXT_3)
    passes_box.pack(fill="x", pady=(T.px(4), T.px(6)))
    note = tk.Label(lp, text="The ISS sends pictures only during ARISS events (schedule: "
                             "ariss.org). Arm a pass, or record by hand.", font=F["sm"],
                    fg=T.TXT_3, bg=T.SURFACE, anchor="w", justify="left",
                    wraplength=T.px(440))
    note.pack(fill="x", pady=(0, T.px(8)))
    T.section(lp, F, "Receiver").pack(fill="x")
    rec_lbl = tk.Label(lp, text="—", font=F["now"], fg=S.TXT, bg=T.SURFACE, anchor="w")
    rec_lbl.pack(fill="x", pady=(T.px(4), 0))
    meter = tk.Canvas(lp, bg=T.SURFACE, highlightthickness=0, height=T.px(14))
    meter.pack(fill="x", pady=(T.px(4), T.px(4)))
    status = tk.Label(lp, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE, anchor="w",
                      justify="left", wraplength=T.px(440))
    status.pack(fill="x")
    T.section(lp, F, "Recordings").pack(fill="x", pady=(T.px(8), 0))
    recs_box = tk.Text(lp, bg=T.SURFACE, fg=T.TXT_2, font=F["mono"], bd=0,
                       highlightthickness=0, wrap="none", state="disabled", cursor="arrow")
    recs_box.pack(fill="both", expand=True, pady=(T.px(4), 0))

    right = tk.Frame(body, bg=S.BG)
    right.pack(side="left", fill="both", expand=True)
    img_title = tk.Label(right, text="", font=F["smb"], fg=S.TXT, bg=S.BG, anchor="w")
    img_title.pack(fill="x", padx=T.px(14), pady=(T.px(10), T.px(4)))
    img_lbl = tk.Label(right, bg=S.MAPBG, text="Decoded pictures appear here",
                       font=F["sm"], fg=T.TXT_3)
    img_lbl.pack(fill="both", expand=True, padx=T.px(14), pady=(0, T.px(10)))

    # ---- pictures ------------------------------------------------------------------------
    def show_image(path):
        try:
            from PIL import Image, ImageTk
            im = Image.open(path)
            w = max(100, img_lbl.winfo_width() - 8)
            h = max(100, img_lbl.winfo_height() - 8)
            im.thumbnail((w, h))
            st["photo"] = ImageTk.PhotoImage(im)
            img_lbl.config(image=st["photo"], text="")
            img_title.config(text=os.path.basename(path))
        except Exception as e:
            img_lbl.config(image="", text="can't show %s: %s" % (os.path.basename(path), e))

    def decode_async(wav):
        if st["decoding"]:
            return
        st["decoding"] = True
        status.config(text="decoding %s…" % os.path.basename(wav), fg=T.TXT_3)

        def work():
            try:
                r = D.decode_wav(wav)
                png = D.save_image(r["image"], wav[:-4] + ".png")
                q.put(("decoded", wav, png, r["mode"], r["lines"], r["slant_ppm"]))
            except Exception as e:
                q.put(("decode_err", wav, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def list_recordings():
        recs_box.config(state="normal")
        recs_box.delete("1.0", "end")
        wavs = sorted(glob.glob(os.path.join(DIR, "*.wav")), reverse=True)[:30]
        if not wavs:
            recs_box.insert("end", "none yet", ())
        for i, w in enumerate(wavs):
            png = w[:-4] + ".png"
            mins = os.path.getsize(w) / 2.0 / RATE / 60.0
            tag = "r%d" % i
            recs_box.insert("end", "%-23s %4.1f min  %s\n" % (
                os.path.basename(w)[:-4], mins, "picture" if os.path.exists(png) else "decode ▸"),
                (tag,))
            recs_box.tag_bind(tag, "<Button-1>", lambda e, w=w, png=png: (
                show_image(png) if os.path.exists(png) else decode_async(w)))
        recs_box.config(state="disabled")

    # ---- recording ------------------------------------------------------------------------
    def start_rec(reason="manual"):
        if st["rec"] or st["starting"]:
            return
        if demo:
            status.config(text="demo: recording needs rtl_fm and the SDR", fg=S.AMBER)
            return
        st["starting"] = True
        state_pill.config(text="Starting", bg=S.AMBER)
        status.config(text="Taking the SDR from the plane map…", fg=T.TXT_3)

        def done(ok, err):
            if not st["starting"]:
                return          # stopped meanwhile; its release is queued after this
            st["starting"] = False
            if not ok:
                state_pill.config(text="Idle", bg=S.DIM)
                status.config(text="SDR busy: %s" % str(err)[:80], fg=S.RED)
                return
            path = os.path.join(DIR, time.strftime("iss_%Y%m%d_%H%M%S.wav"))
            try:
                st["rec"] = Recorder(path, s["freq"], s["gain"], monitor=True)
            except OSError as e:
                S.release_bg(root, lease)
                state_pill.config(text="Idle", bg=S.DIM)
                status.config(text="couldn't start rtl_fm: %s" % e, fg=S.RED)
                return
            state_pill.config(text="Recording", bg=S.RED)
            status.config(text="recording %s (%s)" % (os.path.basename(path), reason),
                          fg=T.TXT_3)
            slog.event("sstv", "recording %s (%s)" % (os.path.basename(path), reason))
        S.acquire_bg(root, lease, done)

    def stop_rec(sync=False, decode=True):
        was_starting, st["starting"] = st["starting"], False
        r, st["rec"] = st["rec"], None
        if r:
            r.stop()
        if (r or was_starting) and not demo:
            S.release_now(lease) if sync else S.release_bg(root, lease)
        state_pill.config(text="Idle", bg=S.DIM)
        if r:
            list_recordings()
            if decode and r.seconds() > 20:
                decode_async(r.path)

    def toggle_rec(_=None):
        stop_rec() if (st["rec"] or st["starting"]) else start_rec()

    def toggle_auto(_=None):
        s["auto"] = not s["auto"]
        try:
            S.save_json(spath, s)
        except OSError:
            pass
        T.set_btn(auto_btn, "Auto: ON" if s["auto"] else "Auto: off",
                  kind="primary" if s["auto"] else "ghost")
        status.config(text=("Armed: every ISS pass above %d° is recorded and decoded" %
                             s["min_elev"]) if s["auto"] else "Auto-record off", fg=T.TXT_3)

    # ---- passes ---------------------------------------------------------------------------
    def predict_async():
        def work():
            try:
                import wxsat
                home = s.get("home") or DEFAULTS["home"]
                fx = S.gps_fix(timeout=2) if hasattr(S, "gps_fix") else None
                if fx and fx.get("lat") is not None:
                    home = {"lat": fx["lat"], "lon": fx["lon"], "alt_m": fx.get("alt") or 0}
                state = wxsat.fetch_tles(SATS, path=TLE)
                ps = wxsat.predict(SATS, home, 48, path=TLE)
                q.put(("passes", ps, state))
            except ImportError:
                q.put(("pred_err", "skyfield not installed - re-run the suite installer"))
            except Exception as e:
                q.put(("pred_err", str(e)[:80]))
        threading.Thread(target=work, daemon=True).start()

    def render_passes():
        passes_box.config(state="normal")
        passes_box.delete("1.0", "end")
        passes_box.insert("end", "%-9s %4s  %6s  %-10s %s\n" % ("WHEN", "MAX", "LENGTH",
                                                              "DIRECTION", ""), "hdr")
        now = time.time()
        shown = [p for p in st["passes"] if p["los"] > now][:8]
        if not shown:
            passes_box.insert("end", st["pred_err"] or "predicting…", "hdr")
        for p in shown:
            tag = "now" if p["aos"] <= now <= p["los"] else (
                "good" if good_pass(p, s["min_elev"]) else "")
            passes_box.insert("end", pass_line(p, now) + "\n", tag)
        passes_box.config(state="disabled")
        nxt = next((p for p in shown if good_pass(p, s["min_elev"])), None)
        if nxt:
            next_pill.config(text="next good pass " + pass_line(nxt, now).split()[-1]
                             if nxt["aos"] > now else "ISS overhead now", bg=S.GREEN)
        else:
            next_pill.config(text="", bg=S.DIM)

    def auto_tick():
        """Armed: start at AOS-30 s for passes above min_elev, stop at LOS+30 s."""
        now = time.time()
        if s["auto"] and not demo:
            ap = st["auto_pass"]
            if ap is None and not st["rec"] and not st["starting"]:
                for p in st["passes"]:
                    if good_pass(p, s["min_elev"]) and p["aos"] - 30 <= now < p["los"]:
                        st["auto_pass"] = p
                        start_rec("ISS pass, max %d°" % round(p["max"]))
                        break
            elif ap is not None and now > ap["los"] + 30:
                st["auto_pass"] = None
                stop_rec()

    # ---- bottom bar -----------------------------------------------------------------------
    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Record", toggle_rec, F, padx=14, pady=5, kind="primary").pack(
        side="left", padx=(10, 6), pady=6)
    auto_btn = S.btn(bar, "Auto: ON" if s["auto"] else "Auto: off", toggle_auto, F, padx=10,
                     pady=5, kind="primary" if s["auto"] else "ghost")
    auto_btn.pack(side="left", padx=2)
    S.btn(bar, "Decode newest", lambda: (lambda w: decode_async(w[0]) if w else
                                         status.config(text="no recordings yet"))(
        sorted(glob.glob(os.path.join(DIR, "*.wav")), reverse=True)), F, padx=10, pady=5,
        kind="ghost").pack(side="left", padx=2)
    S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
        side="right", padx=(2, 10))
    root.bind("<space>", toggle_rec)
    root.bind("a", toggle_auto)

    def pump():
        try:
            while True:
                item = q.get_nowait()
                k = item[0]
                if k == "passes":
                    st["passes"], st["pred_err"] = item[1], ""
                    if not item[1]:
                        st["pred_err"] = ("no ISS elements (offline?)" if item[2] in
                                          ("none", "offline") else "no passes in 48 h")
                elif k == "pred_err":
                    st["pred_err"] = item[1]
                elif k == "decoded":
                    _, wav, png, mode, lines, ppm = item
                    st["decoding"] = False
                    status.config(text="%s: %s, %d lines (clock %+d ppm, corrected)" % (
                        os.path.basename(wav), mode, lines, ppm), fg=S.GREEN)
                    slog.event("sstv", "decoded %s %s" % (mode, os.path.basename(png)))
                    show_image(png)
                    list_recordings()
                elif k == "decode_err":
                    st["decoding"] = False
                    status.config(text="%s: %s" % (os.path.basename(item[1]), item[2]),
                                  fg=S.AMBER)
        except queue.Empty:
            pass
        try:
            render_passes()
            auto_tick()
            r = st["rec"]
            meter.delete("all")
            w = meter.winfo_width() or 300
            if r:
                if r.err:
                    status.config(text=r.err, fg=S.RED)
                    stop_rec(decode=True)
                else:
                    m = int(r.seconds())
                    rec_lbl.config(text="● REC %d:%02d   %.4f MHz" % (m // 60, m % 60, s["freq"]),
                                   fg=S.RED)
                    T.level_bar(meter, 0, 2, w, T.px(10), min(1.0, r.level / 8000.0),
                                segments=24, color=S.GREEN)
            else:
                rec_lbl.config(text="Idle  ·  %.4f MHz  ·  gain %d" % (s["freq"], s["gain"]),
                               fg=T.TXT_2)
        except Exception as e:      # keep the UI pump alive whatever happens
            print("sstv pump: %r" % e, file=sys.stderr)
        root.after(500, pump)

    def hourly():
        predict_async()
        root.after(3600 * 1000, hourly)

    def on_close():
        stop_rec(sync=True, decode=False)
        root.destroy()

    S.bind_quit(root, on_close)
    list_recordings()
    newest = sorted(glob.glob(os.path.join(DIR, "*.png")), reverse=True)
    if newest:
        root.after(300, lambda: show_image(newest[0]))
    if demo:
        status.config(text="demo: no rtl_fm/SDR here - passes and decoding still work",
                      fg=S.AMBER)
    hourly()
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
