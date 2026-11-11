#!/usr/bin/env python3
"""Scanner - preset frequency banks (CB, GMRS, ham, airband, marine, NOAA, railroad...) scanned
with a software squelch, stopping on activity like a classic handheld scanner.

Backend: one rtl_fm per channel (built-in RTL-SDR), raw audio read back and measured; when the
RMS crosses the squelch it holds, plays audio, and logs the hit. Receive-only.
"""
import os
import select
import shutil
import subprocess
import sys
import threading
import time
import queue

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import suite as S  # noqa: E402

try:
    import numpy as _np
except Exception:
    _np = None


def _cb():
    f = [26.965, 26.975, 26.985, 27.005, 27.015, 27.025, 27.035, 27.055, 27.065, 27.075,
         27.085, 27.105, 27.115, 27.125, 27.135, 27.155, 27.165, 27.175, 27.185, 27.205,
         27.215, 27.225, 27.255, 27.235, 27.245, 27.265, 27.275, 27.285, 27.295, 27.305,
         27.315, 27.325, 27.335, 27.345, 27.355, 27.365, 27.375, 27.385, 27.395, 27.405]
    return [(v, str(i + 1)) for i, v in enumerate(f)]


def _gmrs():
    main = [462.5625, 462.5875, 462.6125, 462.6375, 462.6625, 462.6875, 462.7125,
            467.5625, 467.5875, 467.6125, 467.6375, 467.6625, 467.6875, 467.7125,
            462.5500, 462.5750, 462.6000, 462.6250, 462.6500, 462.6750, 462.7000, 462.7250]
    return [(v, str(i + 1)) for i, v in enumerate(main)]


# name -> {"mode": am|nfm, "channels": [(MHz, label)]}
BANKS = {
    "CB": {"mode": "am", "channels": _cb()},
    "GMRS/FRS": {"mode": "nfm", "channels": _gmrs()},
    "MURS": {"mode": "nfm", "channels": [(151.820, "1"), (151.880, "2"), (151.940, "3"),
                                         (154.570, "4"), (154.600, "5")]},
    "Ham 2m": {"mode": "nfm", "channels": [(146.400, "simplex"), (146.520, "calling"),
                                           (146.550, "simplex"), (146.580, "simplex"),
                                           (147.420, "simplex"), (147.450, "simplex"),
                                           (147.480, "simplex"), (147.510, "simplex"),
                                           (147.540, "simplex"), (147.570, "simplex")]},
    "Ham 70cm": {"mode": "nfm", "channels": [(446.000, "calling"), (446.025, "simplex"),
                                             (446.050, "simplex"), (446.075, "simplex"),
                                             (446.100, "simplex"), (446.125, "simplex"),
                                             (446.150, "simplex"), (446.175, "simplex"),
                                             (446.200, "simplex")]},
    "Airband": {"mode": "am", "channels": [(121.500, "guard"), (122.700, "unicom"),
                                           (122.725, "unicom"), (122.750, "air-air"),
                                           (122.800, "unicom"), (122.900, "multicom"),
                                           (123.000, "unicom"), (123.050, "unicom"),
                                           (123.075, "unicom")]},
    "Marine VHF": {"mode": "nfm", "channels": [(156.300, "06"), (156.450, "09"), (156.650, "13"),
                                               (156.800, "16 distress"), (156.425, "68"),
                                               (156.475, "69"), (156.625, "72"), (157.100, "22A")]},
    "NOAA Wx": {"mode": "nfm", "channels": [(162.400, "WX2"), (162.425, "WX4"), (162.450, "WX5"),
                                            (162.475, "WX3"), (162.500, "WX6"), (162.525, "WX7"),
                                            (162.550, "WX1")]},
    "Railroad": {"mode": "nfm", "channels": [(160.230, "AAR 2"), (160.410, "AAR 15"),
                                             (160.590, "AAR 21"), (160.785, "AAR 36"),
                                             (161.100, "AAR 57"), (161.370, "AAR 78"),
                                             (161.520, "AAR 90"), (161.565, "AAR 96")]},
}
BANK_ORDER = list(BANKS.keys())

DEFAULTS = {
    "bank": "NOAA Wx",     # a bank that always has a carrier, so first-run shows the scanner working
    "gain": 40,
    "squelch": 1500,       # AM: software-squelch RMS threshold - TUNE ON DEVICE with a known signal
    # NFM: rtl_fm's own power squelch (-l). An FM discriminator turns an EMPTY channel into
    # full-scale noise, so an RMS gate can't work for NFM; rtl_fm gates on carrier power
    # instead. Raise it if the scanner stops on empty channels, lower it if it misses traffic.
    "nfm_squelch": 50,
    "dwell": 0.4,          # seconds to sample an empty channel before moving on
    "hold": 2.5,           # seconds of quiet before resuming after a signal ends
    "custom": [],          # extra channels: ["462.5500 MyRepeater nfm", ...]
}


def rms_of(chunk):
    if not chunk:
        return 0.0
    if _np is not None:
        a = _np.frombuffer(chunk, dtype=_np.int16)
        return 0.0 if a.size == 0 else float(_np.sqrt(_np.mean(a.astype(_np.float32) ** 2)))
    import array
    a = array.array("h")
    a.frombytes(chunk[: len(chunk) // 2 * 2])
    return 0.0 if not a else (sum(x * x for x in a) / len(a)) ** 0.5


def rtl_cmd(freq_mhz, mode, gain, sq=0):
    """rtl_fm argv. sq > 0 turns on rtl_fm's power squelch (used for NFM scanning);
    0 leaves it open (AM, and manual listening in RF Explorer)."""
    m = "am" if mode == "am" else "fm"
    return ["rtl_fm", "-f", "%.4fM" % freq_mhz, "-M", m, "-s", "12000", "-g", str(int(gain)),
            "-l", str(int(sq)) if (sq and mode != "am") else "0", "-"]


OPEN_RMS = 200      # hardware squelch: closed = no samples or zeros; real audio clears this easily
TUNE_SETTLE = 0.6   # s for rtl_fm to open and tune the dongle before a channel can be judged


def hw_squelch(mode, s):
    """True when rtl_fm gates this channel itself (NFM with a squelch level set)."""
    try:
        return mode != "am" and int(s.get("nfm_squelch") or 0) > 0
    except (TypeError, ValueError):
        return False


def gate_open(rms, mode, s):
    """Is the channel carrying a signal? NFM: anything rtl_fm lets through (it only sends
    audio above its power squelch). AM: the RMS threshold, since AM noise is quiet."""
    if hw_squelch(mode, s):
        return rms >= OPEN_RMS
    return rms >= s["squelch"]


def listen_channel(freq, mode, s, scan, post, popen=subprocess.Popen, sink_fn=None,
                   clock=time.time):
    """Sample one channel; hold and play it while it's active. Returns True if it was
    active, False if not, or "retune" when the NFM squelch level changed mid-listen (the
    caller re-listens the same channel at the new level)."""
    sink_fn = sink_fn or sink_cmd
    hw = hw_squelch(mode, s)
    cmd = rtl_cmd(freq, mode, s["gain"], s.get("nfm_squelch", 0) if hw else 0)
    try:
        proc = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                     start_new_session=True)
    except FileNotFoundError:
        post(("fatal", "rtl_fm not found - install rtl-sdr"))
        return False
    fd = proc.stdout.fileno()
    sink, active, quiet, carry, got = None, False, None, b"", False
    t0 = clock()
    # hardware squelch: an empty channel sends NOTHING, so the dwell is timed from tuner
    # settle; software gate: from the first audio (tuner-open time isn't channel time)
    deadline = t0 + TUNE_SETTLE + s["dwell"] if hw else None
    early_exit = False
    result = False

    def play(chunk):
        nonlocal sink
        if sink and chunk:
            try:
                sink.stdin.write(chunk)
            except (BrokenPipeError, ValueError, OSError):
                sink = None
    try:
        while scan["on"] and not scan["pause"]:
            if scan.get("retune"):
                scan["retune"] = False
                result = "retune"
                break
            ready, _, _ = select.select([fd], [], [], 0.2)
            now = clock()
            chunk, rms = b"", 0.0
            if ready:
                data = os.read(fd, 4096)
                if not data:
                    early_exit = not got and now - t0 < 1.0
                    break                       # rtl_fm exited
                data = carry + data             # keep int16 samples aligned for the sink
                carry, chunk = (data[-1:], data[:-1]) if len(data) % 2 else (b"", data)
                if not got:
                    got = True
                    if deadline is None:
                        deadline = now + s["dwell"]
                rms = rms_of(chunk)
            scan["rms"] = rms
            if chunk and gate_open(rms, mode, s):
                if not active:
                    active = True
                    sc = sink_fn()
                    if sc:
                        sink = popen(sc, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
                    post(("hit", freq))
                quiet = None
                play(chunk)
            elif active:
                if quiet is None:
                    quiet = now
                elif now - quiet > s["hold"]:
                    break
                play(chunk)
            elif deadline is not None and now > deadline:
                break
            elif deadline is None and now - t0 > TUNE_SETTLE + 3.0:
                break                           # software gate, but rtl_fm never sent audio
        if result != "retune":
            result = active
    finally:
        S.stop_group(proc, grace=0.3)
        if sink:
            S.stop_group(sink, grace=0.3)
        scan["rms"] = 0.0
    if early_exit and scan["on"] and not scan["pause"]:
        # rtl_fm quit at once (dongle busy/unplugged): back off instead of respawning it
        # for every channel in a tight loop
        post(("status", "rtl_fm exited at once - is the SDR free?"))
        time.sleep(1.0)
    return result


def sink_cmd():
    if shutil.which("pacat"):
        return ["pacat", "--raw", "--format=s16le", "--rate=12000", "--channels=1",
                "--stream-name=Scanner"]
    if shutil.which("aplay"):
        return ["aplay", "-q", "-r", "12000", "-f", "S16_LE", "-t", "raw", "-c", "1"]
    return None


def parse_custom(lines):
    out = []
    for ln in lines or []:
        p = str(ln).split()
        if not p:
            continue
        try:
            fr = float(p[0])
        except ValueError:
            continue
        if not 24.0 <= fr <= 1766.0:   # outside the RTL's tuning range: a dead tune
            continue
        rest = p[1:]
        mode = "nfm"
        if rest and rest[-1].lower() in ("am", "nfm"):   # "121.5 am" means mode, not label
            mode = rest[-1].lower()
            rest = rest[:-1]
        label = " ".join(rest) or "custom"
        out.append((fr, label, mode))
    return out


def bank_channels(name, custom):
    if name == "Custom":
        return parse_custom(custom)
    b = BANKS.get(name)
    if not b:
        return []
    return [(f, lb, b["mode"]) for f, lb in b["channels"]]


def main():
    S.single_instance("Scanner")
    s, spath = S.settings("scanner", DEFAULTS)
    root, F = S.make_root("Scanner")
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("scanner")
    lease = S.RtlLease("Scanner", log=lambda m: None)
    lease.on_preempt = lambda: stop()   # another workspace wants the radio

    if s.get("bank") not in BANK_ORDER + ["Custom"]:
        s["bank"] = DEFAULTS["bank"]

    scan = {"on": False, "pause": False, "idx": 0, "skip": set(), "thread": None,
            "active": None, "rms": 0.0}
    q = queue.Queue()

    top = S.top_bar(root, F, "Scanner", "Built-in SDR")
    state_pill = S.pill(top, F, "Stopped")
    bank_pill = S.pill(top, F, s["bank"])

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)

    # ---- left: the big active readout + signal meter
    left = tk.Frame(body, bg=S.BG)
    left.pack(side="left", fill="both", expand=True, padx=T.px(30), pady=T.px(22))
    T.section(left, F, "Receiving").pack(fill="x")
    freq_lbl = tk.Label(left, text="—", font=F["xl"], fg=S.TXT, bg=S.BG, anchor="w")
    freq_lbl.pack(fill="x", pady=(T.px(14), 0))
    chan_lbl = tk.Label(left, text="press Scan to start", font=F["sm"], fg=T.TXT_2, bg=S.BG, anchor="w")
    chan_lbl.pack(fill="x")

    meter = tk.Canvas(left, bg=S.BG, highlightthickness=0, height=T.px(26))
    meter.pack(fill="x", pady=(T.px(18), 0))

    def cur_mode():
        """Mode of the channel being sampled, else the bank's (for the Sq buttons/meter)."""
        if scan["on"] and scan.get("mode"):
            return scan["mode"]
        chs = bank_channels(s["bank"], s["custom"])
        return chs[0][2] if chs else "nfm"

    def draw_meter():
        meter.delete("all")
        w = meter.winfo_width() or 400
        h = int(meter.winfo_height() or 20)
        meter.create_rectangle(0, h // 2 - 4, w, h // 2 + 4, fill=T.night("#1b2228"), outline="")
        md = cur_mode()
        lvl = min(1.0, scan["rms"] / 8000.0)
        over = gate_open(scan["rms"], md, s)
        meter.create_rectangle(0, h // 2 - 4, int(w * lvl), h // 2 + 4,
                               fill=T.OK if over else T.ACCENT, outline="")
        if hw_squelch(md, s):
            # NFM: rtl_fm squelches by carrier power, so there's no RMS line to draw;
            # the bar only moves when the squelch is open
            meter.create_text(w - 2, h - 2, text="NFM sq -l %d" % s["nfm_squelch"],
                              anchor="se", fill=T.TXT_3, font=F["map"])
        else:
            sx = int(w * min(1.0, s["squelch"] / 8000.0))
            meter.create_line(sx, 0, sx, h, fill=T.ALERT, width=2)
            meter.create_text(sx + 4, h - 2, text="sq", anchor="sw", fill=T.ALERT, font=F["map"])

    status_lbl = tk.Label(left, text="", font=F["map"], fg=T.TXT_3, bg=S.BG, anchor="w", justify="left")
    status_lbl.pack(fill="x", pady=(T.px(14), 0))

    # what has broken squelch this session: most recent first, with how often
    heard_sec = T.section(left, F, "Heard this session")
    heard_sec.pack(fill="x", pady=(T.px(18), T.px(4)))
    heard_cv = tk.Canvas(left, bg=S.BG, highlightthickness=0, height=T.px(40))
    heard_cv.pack(fill="both", expand=True)
    heard = {}                    # freq -> {"n", "t", "label"}

    def draw_heard():
        heard_cv.delete("all")
        w, h = max(heard_cv.winfo_width(), 100), heard_cv.winfo_height()
        if not heard:
            heard_cv.create_text(0, 2, anchor="nw", font=F["map"], fill=T.TXT_3, width=w,
                                 text="Nothing yet. When a channel breaks squelch the scanner "
                                      "holds on it and it is listed here, newest first.")
            heard_sec.right.config(text="")
            return
        rows = sorted(heard.items(), key=lambda kv: -kv[1]["t"])
        top = max(v["n"] for _, v in rows)
        lh = T.px(19)
        now = time.time()
        x_bar, x_end = T.px(250), w - T.px(70)
        for i, (fr, v) in enumerate(rows[:max(1, h // lh)]):
            y = i * lh
            fresh = now - v["t"] < 20
            heard_cv.create_text(0, y, anchor="nw", font=F["mono"],
                                 fill=T.TXT if fresh else T.TXT_2, text="%9.4f" % fr)
            heard_cv.create_text(T.px(96), y, anchor="nw", font=F["map"], fill=T.TXT_3,
                                 text=str(v["label"])[:18])
            if x_end > x_bar + 20:
                bw = (x_end - x_bar) * v["n"] / top
                heard_cv.create_rectangle(x_bar, y + lh * 0.3, x_bar + max(2, bw), y + lh * 0.7,
                                          fill=T.FILL if fresh else T.LINE_HI, outline="")
                heard_cv.create_text(x_bar + max(2, bw) + 6, y, anchor="nw", font=F["map"],
                                     fill=T.TXT_2, text="%d" % v["n"])
            age = int(now - v["t"])
            heard_cv.create_text(w, y, anchor="ne", font=F["map"], fill=T.TXT_3,
                                 text="now" if age < 5 else ("%ds" % age if age < 60 else
                                                             "%dm" % (age // 60)))
        heard_sec.right.config(text="%d channels · %d hits" % (
            len(heard), sum(v["n"] for v in heard.values())))
    heard_cv.bind("<Configure>", lambda e: draw_heard())

    def heard_tick():
        if heard:
            draw_heard()
        root.after(5000, heard_tick)

    # ---- right: bank + channel list
    right = tk.Frame(body, bg=T.SURFACE, width=T.px(300))
    right.pack(side="right", fill="y")
    right.pack_propagate(False)
    rp = tk.Frame(right, bg=T.SURFACE)
    rp.pack(fill="both", expand=True, padx=T.px(16), pady=T.px(16))
    tk.Label(rp, text="BANK", font=F["map"], fg=T.ACCENT, bg=T.SURFACE, anchor="w").pack(fill="x")
    bank_name = tk.Label(rp, text=s["bank"], font=F["h"], fg=S.TXT, bg=T.SURFACE, anchor="w")
    bank_name.pack(fill="x")
    chans = tk.Text(rp, bg=S.BG, fg=T.TXT_2, font=F["mono"], bd=0, highlightthickness=0,
                    wrap="none", state="disabled", height=16)
    chans.tag_config("active", foreground=T.BG, background=T.OK)
    chans.tag_config("scan", foreground=T.ACCENT)
    chans.tag_config("skip", foreground=T.TXT_3, overstrike=1)
    chans.pack(fill="both", expand=True, pady=(T.px(10), 0))

    def render_channels():
        chans.config(state="normal")
        chans.delete("1.0", "end")
        for i, (fr, lb, md) in enumerate(bank_channels(s["bank"], s["custom"])):
            tag = ("active" if scan.get("active") == i else
                   ("scan" if (scan["on"] and scan["idx"] == i) else
                    ("skip" if fr in scan["skip"] else None)))
            chans.insert("end", "%9.4f  %s\n" % (fr, lb), tag or ())
        chans.config(state="disabled")

    # ---------- scan engine ----------
    def listen(freq, mode):
        scan["mode"] = mode
        return listen_channel(freq, mode, s, scan, q.put)

    def scan_loop():
        while scan["on"]:
            chans_now = bank_channels(s["bank"], s["custom"])
            if not chans_now:
                q.put(("status", "This bank has no channels."))
                time.sleep(1.0)
                continue
            for i, (fr, lb, md) in enumerate(chans_now):
                if not scan["on"]:
                    break
                while scan["pause"] and scan["on"]:
                    time.sleep(0.1)
                if fr in scan["skip"]:
                    continue
                scan["idx"] = i
                scan["active"] = None
                q.put(("scanning", (i, fr, lb)))
                res = "retune"
                while res == "retune" and scan["on"]:
                    res = listen(fr, md)        # squelch changed: same channel, new level
                if res is True:
                    scan["active"] = i
                    q.put(("held_done", i))

    def scan_main():
        # the lease is taken and given back on this thread: acquire() can block for many
        # seconds (stopping readsb), and release() must wait until the last rtl_fm is gone,
        # or readsb restarts onto a dongle the scanner still holds
        try:
            try:
                lease.acquire()
            except Exception as e:
                q.put(("fatal", "SDR busy: %s" % str(e)[:60]))
                return
            q.put(("status", "Scanning."))
            scan_loop()
        finally:
            try:
                lease.release()
            except Exception:
                pass

    def start():
        if scan["on"]:
            return
        if scan["thread"] and scan["thread"].is_alive():
            # the previous scan is still shutting its rtl_fm down: two loops would fight
            status_lbl.config(text="Still stopping the last scan - try again in a moment.",
                              fg=T.TXT_3)
            return
        scan["on"] = True
        scan["pause"] = False
        state_pill.config(text="Scanning", bg=S.GREEN)
        scan["thread"] = threading.Thread(target=scan_main, daemon=True)
        scan["thread"].start()

    def stop():
        scan["on"] = False
        scan["pause"] = False
        scan["active"] = None
        state_pill.config(text="Stopped", bg=S.DIM)
        freq_lbl.config(text="—")
        chan_lbl.config(text="press Scan to start")
        render_channels()

    def toggle():
        stop() if scan["on"] else start()

    def pause():
        if not scan["on"]:
            return
        scan["pause"] = not scan["pause"]
        state_pill.config(text="Paused" if scan["pause"] else "Scanning",
                          bg=S.AMBER if scan["pause"] else S.GREEN)

    def skip_current():
        chans_now = bank_channels(s["bank"], s["custom"])
        if 0 <= scan["idx"] < len(chans_now):
            scan["skip"].add(chans_now[scan["idx"]][0])
            render_channels()

    def clear_skips():
        scan["skip"].clear()
        render_channels()

    def set_bank(delta):
        order = BANK_ORDER + (["Custom"] if parse_custom(s["custom"]) else [])
        cur = order.index(s["bank"]) if s["bank"] in order else 0
        s["bank"] = order[(cur + delta) % len(order)]
        S.save_json(spath, s)
        bank_pill.config(text=s["bank"])
        bank_name.config(text=s["bank"])
        scan["idx"] = 0
        scan["active"] = None
        render_channels()

    def set_sq(direction):
        """Sq −/+ adjusts the squelch that applies to the current channel's mode."""
        md = cur_mode()
        if md != "am":
            v = int(s.get("nfm_squelch") or DEFAULTS["nfm_squelch"])
            step = 5 if (v < 100 or (v == 100 and direction < 0)) else 10
            s["nfm_squelch"] = max(1, min(500, v + direction * step))
            scan["retune"] = scan["on"]       # re-open the current channel at the new level
            msg = ("NFM squelch -l %d  ·  raise it if the scan stops on empty channels, "
                   "lower it if it misses traffic" % s["nfm_squelch"])
        else:
            s["squelch"] = max(100, min(8000, s["squelch"] + direction * 100))
            msg = "AM squelch %d  (lower = more sensitive)" % s["squelch"]
        try:
            S.save_json(spath, s)
        except OSError:
            pass
        status_lbl.config(text=msg, fg=T.TXT_3)

    def set_gain(delta):
        s["gain"] = max(0, min(49, s["gain"] + delta))
        S.save_json(spath, s)
        status_lbl.config(text="Gain %d dB" % s["gain"], fg=T.TXT_3)

    def edit_settings():
        import settings_ui
        schema = [("Scanner", [
            {"key": "gain", "label": "Gain (dB)", "type": "int", "min": 0, "max": 49},
            {"key": "nfm_squelch", "label": "NFM squelch (rtl_fm -l)", "type": "int", "min": 1,
             "max": 500, "help": "raise if the scan stops on empty channels; lower if it misses traffic"},
            {"key": "squelch", "label": "AM squelch (RMS)", "type": "int", "min": 100, "max": 8000,
             "help": "CB / airband; tune with a known-live channel"},
            {"key": "dwell", "label": "Dwell per channel (s)", "type": "float", "min": 0.1, "max": 2.0,
             "step": 0.1},
            {"key": "hold", "label": "Hold after signal (s)", "type": "float", "min": 0.5, "max": 10.0,
             "step": 0.5},
            {"key": "custom", "label": "Custom channels (freq label mode)", "type": "list"},
        ])]

        def saved(ns):
            s.update(ns)
            S.save_json(spath, s)
            render_channels()
        settings_ui.open_settings(root, F, "Scanner settings", schema, s, saved, path=spath)

    # ---------- UI pump ----------
    def pump():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "scanning":
                    i, fr, lb = val
                    if not scan.get("active"):
                        freq_lbl.config(text="%.4f" % fr, fg=T.TXT_2)
                        chan_lbl.config(text="scanning %s  ·  %s" % (s["bank"], lb))
                    render_channels()
                elif kind == "hit":
                    freq_lbl.config(text="%.4f" % val, fg=T.OK)
                    chan_lbl.config(text="RECEIVING")
                    state_pill.config(text="Holding", bg=S.GREEN)
                    slog.event("scanner", "%.4f %s" % (val, s["bank"]), id="%.4f" % val)
                    lb_ = next((lb for fr, lb, _ in bank_channels(s["bank"], s["custom"])
                                if abs(fr - val) < 1e-4), s["bank"])
                    h_ = heard.setdefault(round(val, 4), {"n": 0, "t": 0, "label": lb_})
                    h_["n"] += 1
                    h_["t"] = time.time()
                    draw_heard()
                elif kind == "held_done":
                    state_pill.config(text="Scanning" if scan["on"] else "Stopped",
                                      bg=S.GREEN if scan["on"] else S.DIM)
                    render_channels()
                elif kind == "status":
                    status_lbl.config(text=val, fg=T.TXT_3)
                elif kind == "fatal":
                    status_lbl.config(text=val, fg=T.ALERT)
                    stop()
        except queue.Empty:
            pass
        draw_meter()
        root.after(120, pump)

    # ---------- action row ----------
    tools = tk.Frame(root, bg=T.SURFACE)
    tools.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    trow = tk.Frame(tools, bg=T.SURFACE)
    trow.pack(fill="x", padx=T.px(10), pady=T.px(8))
    S.btn(trow, "Scan / Stop", toggle, F, padx=10, pady=4, kind="primary").pack(side="left")
    for lbl, cmd in (("Pause", pause), ("Skip", skip_current), ("Clear skips", clear_skips)):
        S.btn(trow, lbl, cmd, F, padx=8, pady=4, kind="quiet").pack(side="left", padx=(6, 0))
    S.btn(trow, "Bank ‹", lambda: set_bank(-1), F, padx=8, pady=4, kind="quiet").pack(side="left", padx=(12, 0))
    S.btn(trow, "Bank ›", lambda: set_bank(1), F, padx=8, pady=4, kind="quiet").pack(side="left", padx=(4, 0))
    S.btn(trow, "Sq −", lambda: set_sq(-1), F, padx=8, pady=4, kind="quiet").pack(side="left", padx=(12, 0))
    S.btn(trow, "Sq +", lambda: set_sq(1), F, padx=8, pady=4, kind="quiet").pack(side="left", padx=(4, 0))
    S.btn(trow, "Quit", lambda: on_close(), F, padx=8, pady=4, kind="quiet").pack(side="right")
    S.btn(trow, "Settings", edit_settings, F, padx=8, pady=4, kind="quiet").pack(side="right", padx=(0, 6))

    root.bind("<space>", lambda e: toggle())
    root.bind("s", lambda e: skip_current())
    root.bind("p", lambda e: pause())
    root.bind("<Left>", lambda e: set_bank(-1))
    root.bind("<Right>", lambda e: set_bank(1))
    root.bind("<Up>", lambda e: set_sq(1))
    root.bind("<Down>", lambda e: set_sq(-1))

    def on_close():
        stop()
        end = time.time() + 8.0

        def wait_scan():
            # rtl_fm runs in its own session: exiting before the scan thread has stopped it
            # (and released the lease) would orphan it on the dongle with readsb paused
            th = scan["thread"]
            if th and th.is_alive() and time.time() < end:
                root.after(100, wait_scan)
            else:
                root.destroy()
        root.after(150, wait_scan)

    S.bind_quit(root, on_close)
    root.bind("q", lambda e: on_close())
    render_channels()
    status_lbl.config(text="NFM sq -l %d · AM sq %d · Gain %d dB · dwell %.1fs"
                      % (s["nfm_squelch"], s["squelch"], s["gain"], s["dwell"]), fg=T.TXT_3)
    if "--demo" in sys.argv:              # show the Heard list without a radio
        for fr_, lb_, n_, ago_ in ((162.55, "WX1", 14, 3), (162.4, "WX2", 6, 95),
                                   (162.475, "WX4", 2, 400)):
            heard[fr_] = {"n": n_, "t": time.time() - ago_, "label": lb_}
    heard_tick()
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
