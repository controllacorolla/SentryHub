#!/usr/bin/env python3
"""FM broadcast + NOAA Weather Radio on the built-in SDR (rtl_fm -> PulseAudio)."""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402

DEFAULTS = {
    "freq": 97.3,
    "mode": "wbfm",
    "gain": 40,
    "squelch": 0,
    "rds": True,     # decode RDS (station name / text) with redsea when it is installed
    "presets": [
        {"name": "NWS Denver", "freq": 162.550, "mode": "nbfm"},
        {"name": "NWS Franktown", "freq": 162.450, "mode": "nbfm"},
    ],
}


def pipeline(freq, mode, gain, squelch, rds=False):
    """argv lists (no shell): rtl_fm producer, optional redsea RDS decoder, audio sink."""
    freq, gain, squelch = float(freq), float(gain), int(squelch)
    mid = None
    if mode == "nbfm":
        rate = 24000
        rtl = ["rtl_fm", "-d", "0", "-M", "fm", "-f", "%.4fM" % freq, "-s", str(rate), "-r", str(rate),
               "-g", "%g" % gain, "-l", str(squelch), "-E", "dc", "-"]
    elif rds and shutil.which("redsea"):
        # full MPX at 171 kHz so redsea can see the 57 kHz RDS subcarrier; redsea echoes the
        # audio through to the sink (-e) and prints decoded groups as JSON on stderr
        rate = 171000
        rtl = ["rtl_fm", "-d", "0", "-M", "fm", "-f", "%.4fM" % freq, "-s", str(rate), "-A", "std",
               "-F", "9", "-g", "%g" % gain, "-"]
        mid = ["redsea", "-r", str(rate), "-u", "-e"]
    else:
        rate = 48000
        rtl = ["rtl_fm", "-d", "0", "-M", "wbfm", "-f", "%.4fM" % freq, "-s", "200000", "-r", str(rate),
               "-g", "%g" % gain, "-E", "deemp", "-"]
    if shutil.which("pacat"):
        sink = ["pacat", "--raw", "--format=s16le", "--rate=%d" % rate, "--channels=1",
                "--stream-name=FM %.3f" % freq]
    else:
        sink = ["aplay", "-q", "-r", str(rate), "-f", "S16_LE", "-t", "raw", "-c", "1"]
    return rtl, mid, sink


class Pipe:
    """rtl_fm | sink as two processes, each in its own session, stopped together.
    Exposes pid/poll/wait like a Popen so S.stop_group() can handle it; its killpg on
    rtl_fm's group is followed by stopping the sink here."""

    def __init__(self, rtl, sink, mid=None, on_rds=None):
        self.rtl = subprocess.Popen(rtl, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
        src = self.rtl.stdout
        self.mid = None
        self.sink = None
        try:
            if mid:
                self.mid = subprocess.Popen(mid, stdin=src, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, start_new_session=True)
                src.close()
                src = self.mid.stdout
                threading.Thread(target=self._read_rds, args=(self.mid.stderr, on_rds),
                                 daemon=True).start()
            self.sink = subprocess.Popen(sink, stdin=src, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception:
            # a later stage failed to exec: don't leave rtl_fm holding the dongle
            src.close()
            self.stop()
            raise
        src.close()
        self.pid = self.rtl.pid

    def stop(self):
        """Stop every stage. S.stop_group() alone is not enough once one stage has died:
        poll() then reports the pipe finished and the survivors (often rtl_fm) are skipped."""
        for p in self.procs():
            S.stop_group(p, grace=1.0)

    @staticmethod
    def _read_rds(stream, on_rds):
        for line in iter(stream.readline, b""):
            try:
                d = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue
            if on_rds and isinstance(d, dict):
                on_rds(d)
        stream.close()

    def procs(self):
        return [p for p in (self.rtl, self.mid, self.sink) if p is not None]

    def poll(self):
        codes = [p.poll() for p in self.procs()]
        live = [c for c in codes if c is not None]
        return None if not live else live[0]

    def wait(self, timeout=None):
        self.rtl.wait(timeout=timeout)
        # once rtl_fm is gone the others see EOF and exit on their own; nudge them if not
        for p in self.procs()[1:]:
            try:
                p.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                S.stop_group(p, grace=0.5)


def main():
    S.single_instance("FM Radio")
    s, spath = S.settings("fm", DEFAULTS)
    root, F = S.make_root("FM Radio")
    import tkinter as tk
    log_q = queue.Queue()
    lease = S.RtlLease("FM", log=lambda m: log_q.put(m))
    lease.on_preempt = lambda: stop()   # another workspace wants the radio
    st = {"proc": None, "busy": False}

    T = S.T
    top = S.top_bar(root, F, "FM Radio", "Built-in SDR")
    state_pill = S.pill(top, F, "Off")
    out_lbl = tk.Label(top, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE)
    out_lbl.pack(side="right", padx=20)

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)

    left = tk.Frame(body, bg=S.BG)
    left.pack(side="left", fill="both", expand=True, padx=36, pady=28)
    T.section(left, F, "Tuner").pack(fill="x")
    freq_lbl = tk.Label(left, text="", font=F["xl"], fg=S.TXT, bg=S.BG, anchor="w")
    freq_lbl.pack(fill="x", pady=(18, 0))
    mode_lbl = tk.Label(left, text="", font=F["sm"], fg=T.TXT_2, bg=S.BG, anchor="w")
    mode_lbl.pack(fill="x")
    rds_name = tk.Label(left, text="", font=F["h"], fg=S.TXT, bg=S.BG, anchor="w")
    rds_name.pack(fill="x", pady=(14, 0))
    rds_text = tk.Label(left, text="", font=F["sm"], fg=T.TXT_2, bg=S.BG, anchor="w", justify="left")
    rds_text.pack(fill="x")
    rds = {"ps": "", "rt": "", "pty": "", "call": "", "pi": "", "t": 0}

    def on_rds(d):
        now = time.time()
        if d.get("ps"):
            rds["ps"] = d["ps"].strip()
        if d.get("radiotext"):
            rds["rt"] = d["radiotext"].strip()
        if d.get("prog_type"):
            rds["pty"] = d["prog_type"]
        if d.get("callsign"):
            rds["call"] = d["callsign"]
        if d.get("pi"):
            rds["pi"] = d["pi"]
        rds["t"] = now

    def draw_rds():
        if s["mode"] != "wbfm" or not st.get("proc") or time.time() - rds["t"] > 30:
            rds_name.config(text="")
            rds_text.config(text=("RDS: no data yet" if st.get("proc") and s["mode"] == "wbfm"
                                  and s.get("rds") and shutil.which("redsea") else ""))
            return
        head = rds["ps"] or rds["call"] or rds["pi"]
        if rds["call"] and rds["ps"] and rds["call"] not in rds["ps"]:
            head += "   " + rds["call"]
        rds_name.config(text=head)
        rds_text.config(text="  ·  ".join(x for x in (rds["pty"], rds["rt"]) if x),
                        wraplength=max(200, left.winfo_width() - 20))

    def clear_rds():
        for k in ("ps", "rt", "pty", "call", "pi"):
            rds[k] = ""
        rds["t"] = 0
    dial = tk.Canvas(left, bg=S.BG, highlightthickness=0, height=S.T.px(96))
    dial.pack(fill="x", pady=(22, 0))

    def band():
        if s["mode"] == "wbfm" and 87.5 <= s["freq"] <= 108.1:
            return 87.5, 108.0, 0.1, 2.0
        span = 2.0 if s["mode"] == "wbfm" else 0.4
        lo = s["freq"] - span / 2
        return lo, lo + span, span / 100, span / 5

    def draw_dial(_=None):
        dial.delete("all")
        w = dial.winfo_width()
        if w < 50:
            return
        lo, hi, minor, major = band()
        y = 56
        dial.create_line(0, y, w, y, fill=T.LINE)
        n = int(round((hi - lo) / minor))
        pad = 18
        W = w - 2 * pad
        for i in range(n + 1):
            v = lo + i * minor
            x = pad + W * i / n
            is_major = abs((v / major) - round(v / major)) < 1e-6
            is_mid = abs((v / (major / 2)) - round(v / (major / 2))) < 1e-6
            hgt = 16 if is_major else (10 if is_mid else 5)
            dial.create_line(x, y, x, y - hgt, fill=T.night("#4a535c") if is_major else T.LINE)
            if is_major:
                dial.create_text(x, y + 14, text=("%g" % round(v, 3)), fill=T.TXT_3, font=F["map"])
        for p_ in s["presets"]:
            if lo <= p_["freq"] <= hi:
                x = pad + W * (p_["freq"] - lo) / (hi - lo)
                dial.create_polygon(x - 4, y + 26, x + 4, y + 26, x, y + 20, fill=T.TXT_3, outline="")
                dial.create_text(x, y + 38, text=p_["name"], fill=T.TXT_3, font=F["map"])
        x = pad + W * (min(max(s["freq"], lo), hi) - lo) / (hi - lo)
        dial.create_rectangle(x - 22, 4, x + 22, y - 20, fill=T.ACCENT_BG, outline="")
        dial.create_line(x, 2, x, y + 4, fill=T.ACCENT, width=2)

    def dial_click(e):
        lo, hi, minor, _ = band()
        w = dial.winfo_width()
        f = lo + (hi - lo) * (e.x - 18) / max(w - 36, 1)
        f = round(round(f / minor) * minor, 3)
        if s["mode"] == "wbfm":
            f = round(f, 1)
        if f == s["freq"]:
            return
        s["freq"] = f
        draw()
        retune(delay=True)
        if save_job[0]:
            root.after_cancel(save_job[0])
        save_job[0] = root.after(800, save)

    save_job = [None]
    dial.bind("<Configure>", draw_dial)
    dial.bind("<Button-1>", dial_click)
    dial.bind("<B1-Motion>", dial_click)

    tune = tk.Frame(left, bg=S.BG)
    tune.pack(fill="x", pady=(22, 0))
    act = tk.Frame(left, bg=S.BG)
    act.pack(fill="x", pady=(16, 0))
    play = S.btn(act, "Play", lambda: toggle(), F, font="smb", padx=22, pady=6, kind="primary")
    play.pack(side="left")
    tk.Label(act, text="Go to", font=F["sm"], fg=T.TXT_2, bg=S.BG).pack(side="left", padx=(24, 8))
    ent = T.entry(act, F, width=9)
    ent.pack(side="left", ipady=4)
    tk.Label(act, text="MHz", font=F["sm"], fg=T.TXT_3, bg=S.BG).pack(side="left", padx=6)
    detail = tk.Label(left, text="← → tune  ·  ↑ ↓ big steps  ·  Space play/stop.  " +
                      ("Playing pauses the plane map (one SDR)." if S.adsb_device() != "hackrf"
                       else "Plane map stays live (ADS-B is on the H4M)."), font=F["sm"], fg=T.TXT_3,
                      bg=S.BG, anchor="w", justify="left", wraplength=S.T.px(640))
    detail.pack(fill="x", pady=(18, 0))
    logbox = tk.Text(left, height=4, bg=S.BG, fg=T.TXT_3, font=F["map"], bd=0,
                     highlightthickness=0)
    logbox.pack(side="bottom", fill="x")

    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    rightw = tk.Frame(body, bg=T.SURFACE, width=S.T.px(330))
    rightw.pack(side="left", fill="y")
    rightw.pack_propagate(False)
    right = tk.Frame(rightw, bg=T.SURFACE)
    right.pack(fill="both", expand=True, padx=20, pady=18)
    T.section(right, F, "Presets", right="hold to delete").pack(fill="x", pady=(0, 6))
    plist = tk.Frame(right, bg=T.SURFACE)
    plist.pack(fill="both", expand=True)
    tools = tk.Frame(right, bg=T.SURFACE)
    tools.pack(fill="x")

    def draw():
        draw_dial()
        for m, b in mode_btns.items():
            S.set_btn(b, kind="primary" if s["mode"] == m else "ghost")
        freq_lbl.config(text="%.3f MHz" % s["freq"] if s["mode"] == "nbfm" else "%.1f MHz" % s["freq"])
        mode_lbl.config(text={"wbfm": "Wideband FM  ·  broadcast", "nbfm": "Narrowband FM  ·  weather / two-way"}[s["mode"]])


    def save():
        S.save_json(spath, s)

    def build_presets():
        for w in plist.winfo_children():
            w.destroy()
        for i, p in enumerate(s["presets"]):
            cur = abs(p["freq"] - s["freq"]) < 1e-6
            r = tk.Frame(plist, bg=T.ACCENT_BG if cur else T.SURFACE, cursor="hand2")
            r.pack(fill="x")
            n = tk.Label(r, text=p["name"], font=F["sm"], fg=T.ACCENT if cur else S.TXT,
                         bg=r.cget("bg"), anchor="w", pady=8)
            n.pack(side="left", padx=(8, 0))
            fq = tk.Label(r, text="%.3f" % p["freq"], font=F["mono"], fg=T.TXT_2, bg=r.cget("bg"))
            fq.pack(side="right", padx=8)
            tk.Frame(plist, bg=S.LINE, height=1).pack(fill="x")
            press = {"t": 0}
            for wdg in (r, n, fq):
                wdg.bind("<ButtonPress-1>", lambda e, press=press: press.update(t=time.time()))
                wdg.bind("<ButtonRelease-1>",
                         lambda e, i=i, press=press: preset_tap(i, time.time() - press["t"]))

    def preset_tap(i, held):
        if held > 0.8:
            del s["presets"][i]
            save()
            build_presets()
            return
        p = s["presets"][i]
        s["freq"], s["mode"] = p["freq"], p.get("mode", "wbfm")
        save()
        draw()
        build_presets()
        retune()

    def add_preset():
        name = "%.3f" % s["freq"]
        s["presets"].append({"name": name, "freq": s["freq"], "mode": s["mode"]})
        save()
        build_presets()

    def step(d):
        inc = 0.2 if s["mode"] == "wbfm" else 0.025
        s["freq"] = round(s["freq"] + d * inc, 3)
        save()
        draw()
        retune(delay=True)

    def set_mode(m):
        s["mode"] = m
        save()
        draw()
        retune()

    for t, cmd in (("−1.0", lambda: step(-5)), ("−0.2", lambda: step(-1)), ("+0.2", lambda: step(1)),
                   ("+1.0", lambda: step(5))):
        S.btn(tune, t, cmd, F, font="mono", padx=14, pady=4).pack(side="left", padx=(0, 6))
    mode_btns = {}
    for m, t in (("wbfm", "Wide"), ("nbfm", "Narrow")):
        mode_btns[m] = S.btn(tune, t, lambda m=m: set_mode(m), F, padx=14, pady=4)
        mode_btns[m].pack(side="left", padx=(18 if m == "wbfm" else 0, 6))
    S.btn(tools, "Save current as preset", add_preset, F, padx=10, pady=4).pack(fill="x", pady=(10, 0))

    FM_SCHEMA = [
        ("Tuner", [
            {"key": "gain", "label": "Tuner gain", "type": "float", "min": 0, "max": 49.6, "step": 2, "unit": "dB"},
            {"key": "squelch", "label": "Squelch (narrowband)", "type": "int", "min": 0, "max": 500, "step": 10,
             "help": "0 = open; raise until background hiss mutes"},
            {"key": "rds", "label": "RDS station names", "type": "bool", "help": "needs redsea installed"},
        ]),
        ("Presets", [
            {"key": "presets", "label": "Stations", "type": "table",
             "columns": [("name", "Name", "str"), ("freq", "MHz", "float"), ("mode", "Mode", "str")],
             "help": "mode: wbfm (broadcast) or nbfm (weather, two-way)",
             "template": {"name": "New", "freq": 100.0, "mode": "wbfm"}},
        ]),
    ]

    def open_settings():
        import settings_ui

        def on_save(new):
            s.clear()
            s.update(new)
            save()
            build_presets()
            draw()
            if st.get("proc"):
                retune()
        settings_ui.open_settings(root, F, "FM Radio settings", FM_SCHEMA, s, on_save, path=spath)

    S.btn(tools, "Settings", open_settings, F, padx=10, pady=4, kind="quiet").pack(fill="x", pady=(6, 0))

    def toggle_rds():
        s["rds"] = not s.get("rds", True)
        save()
        S.set_btn(rds_btn, "RDS on" if s["rds"] else "RDS off", "primary" if s["rds"] else "ghost")
        if st.get("proc"):
            retune()

    if shutil.which("redsea"):
        rds_btn = S.btn(tools, "RDS on" if s.get("rds", True) else "RDS off", toggle_rds, F, padx=10, pady=4,
                        kind="primary" if s.get("rds", True) else "ghost")
        rds_btn.pack(fill="x", pady=(6, 0))
    else:
        tk.Label(tools, text="RDS station names: sudo apt install redsea", font=F["map"], fg=T.TXT_3,
                 bg=tools.cget("bg"), anchor="w").pack(fill="x", pady=(6, 0))

    def go_entry(_=None):
        try:
            f = float(ent.get())
        except ValueError:
            detail.config(text="Type a frequency in MHz, e.g. 97.3 or 162.55")
            return
        if not 24 <= f <= 1766:
            detail.config(text="The built-in SDR tunes about 24-1766 MHz")
            return
        s["freq"] = f
        if 162.3 < f < 162.6:
            s["mode"] = "nbfm"
        save()
        draw()
        retune()

    ent.bind("<Return>", go_entry)

    retune_job = [None]
    cmds = queue.Queue()

    def retune(delay=False):
        if not st["proc"]:
            return
        if retune_job[0]:
            root.after_cancel(retune_job[0])
        retune_job[0] = root.after(600 if delay else 50, lambda: cmds.put("restart"))

    def ui(fn):
        log_q.put(("ui", fn))

    def start():
        ui(lambda: state_pill.config(text="Starting", bg=S.AMBER))
        try:
            lease.acquire()
            clear_rds()
            rtl, mid, sink = pipeline(s["freq"], s["mode"], s["gain"], s["squelch"], s.get("rds", True))
            log_q.put("$ %s | %s%s" % (" ".join(rtl), (" ".join(mid) + " | ") if mid else "", " ".join(sink)))
            st["proc"] = Pipe(rtl, sink, mid, on_rds)
            time.sleep(1.5)
            if st["proc"].poll() is not None:
                st["proc"].stop()            # one stage died: don't orphan the others (rtl_fm)
                st["proc"] = None
                log_q.put("rtl_fm exited - is the SDR free? Try again.")
                lease.release()
                ui(lambda: state_pill.config(text="Fault", bg=S.RED))
            else:
                ui(lambda: (state_pill.config(text="Playing", bg=S.GREEN),
                            S.set_btn(play, "Stop", "danger")))
        except Exception as e:
            log_q.put(str(e))
            st["proc"] = None
            # give the built-in SDR back - otherwise a failed start (rtl_fm missing, bad
            # gain, sink not installed) leaves FM holding the lease and blocks every other app
            try:
                lease.release()
            except Exception:
                pass
            ui(lambda: state_pill.config(text="Fault", bg=S.RED))

    def stop(release=True):
        if st["proc"]:
            st["proc"].stop()
        st["proc"] = None
        if release:
            lease.release()
        ui(lambda: (state_pill.config(text="Off", bg=S.DIM), S.set_btn(play, "Play", "primary")))

    def worker():
        while True:
            cmd = cmds.get()
            try:
                if cmd == "start" and not st["proc"]:
                    start()
                elif cmd == "stop":
                    stop()
                elif cmd == "restart" and st["proc"]:
                    st["proc"].stop()
                    st["proc"] = None
                    start()
                elif isinstance(cmd, tuple) and cmd[0] == "died":
                    # only for the pipe that actually died: a restart may already have
                    # replaced it, and releasing then would orphan the new rtl_fm
                    if st["proc"] is cmd[1]:
                        cmd[1].stop()        # the surviving stages (e.g. rtl_fm after pacat quit)
                        st["proc"] = None
                        lease.release()
                        ui(lambda: (state_pill.config(text="Off", bg=S.DIM),
                                    S.set_btn(play, "Play", "primary")))
                elif cmd == "quit":
                    stop()
                    ui(root.destroy)
                    return
            except Exception as e:
                log_q.put("Error: %s" % e)

    S.in_thread(worker)

    def toggle():
        cmds.put("stop" if st["proc"] else "start")

    def typing():
        return root.focus_get() is ent

    root.bind("<space>", lambda e: None if typing() else toggle())
    root.bind("<Left>", lambda e: None if typing() else step(-1))
    root.bind("<Right>", lambda e: None if typing() else step(1))
    root.bind("<Up>", lambda e: None if typing() else step(5))
    root.bind("<Down>", lambda e: None if typing() else step(-5))
    ent.bind("<Escape>", lambda e: (root.focus_set(), "break")[1])

    def pump():
        while not log_q.empty():
            item = log_q.get()
            if isinstance(item, tuple) and item[0] == "ui":
                try:
                    item[1]()
                except Exception:
                    pass
                continue
            logbox.insert("end", str(item) + "\n")
            logbox.see("end")
        try:
            draw_rds()
        except Exception:
            return          # window is going away
        p = st["proc"]
        if p and p.poll() is not None and st.get("dying") is not p:
            st["dying"] = p          # report each dead pipe once, not every 200 ms
            log_q.put("Radio pipeline exited (code %s) - another app may have taken the SDR." % p.poll())
            cmds.put(("died", p))
        root.after(200, pump)

    audio_busy = [False]

    def poll_audio():
        # the lookup runs in a thread; the label update goes through the ui queue (Tk calls,
        # root.after included, must stay on the main thread), and at most one lookup at a time
        def work():
            try:
                n = S.core.audio_output_name()
                ui(lambda: out_lbl.config(text="Audio · " + n))
            finally:
                audio_busy[0] = False
        if not audio_busy[0]:
            audio_busy[0] = True
            S.in_thread(work)
        root.after(5000, poll_audio)

    closing = [False]

    def on_close():
        if closing[0]:
            return
        closing[0] = True
        cmds.put("quit")

    S.bind_quit(root, on_close)
    draw()
    build_presets()
    pump()
    poll_audio()
    root.mainloop()


if __name__ == "__main__":
    main()
