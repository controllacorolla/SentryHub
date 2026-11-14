#!/usr/bin/env python3
"""
Airband transcriber.

  transcriber.py --worker   watch Sky's per-transmission MP3s, transcribe with Whisper
  transcriber.py --view     scrolling transcript viewer
  transcriber.py --test F   transcribe one audio file and print it

Sky writes one MP3 per transmission into ~/.cache/sky-app/recordings/
(<tx>_<YYYYMMDD_HHMMSS>_<freq Hz>.mp3). The worker turns each one into a line in
~/.local/share/sky-app/transcripts/<date>.jsonl and deletes old audio.
"""

import glob
import json
import os
import re
import sys
import time

HOME = os.path.expanduser("~")
REC_DIR = os.path.join(HOME, ".cache", "sky-app", "recordings")
OUT_DIR = os.path.join(HOME, ".local", "share", "sky-app", "transcripts")
STATUS = os.path.join(HOME, ".cache", "sky-app", "transcriber.json")
SKY_SETTINGS = os.path.join(HOME, ".config", "sky-app", "settings.json")

PROMPT = ("Air traffic control radio. Denver approach, Centennial tower, ground. "
          "United, Southwest, SkyWest, Frontier, American, Delta, Cessna, November. "
          "Runway three five right, one seven left, cleared to land, cleared for takeoff, "
          "line up and wait, contact departure, squawk, altimeter, traffic, roger, wilco.")

# Spoken airline callsigns -> ICAO prefixes (common at DEN/APA)
TELEPHONY = {
    "united": "UAL", "southwest": "SWA", "skywest": "SKW", "sky west": "SKW",
    "frontier": "FFT", "frontier flight": "FFT", "american": "AAL", "delta": "DAL",
    "alaska": "ASA", "jetblue": "JBU", "jet blue": "JBU", "fedex": "FDX", "ups": "UPS",
    "envoy": "ENY", "brickyard": "RPA", "lindbergh": "GJS", "air shuttle": "ASH",
    "execjet": "EJA", "exec jet": "EJA", "flexjet": "LXJ", "lexus": "LXJ", "key lime": "LYM",
    "spirit": "NKS", "sun country": "SCX", "allegiant": "AAY", "air canada": "ACA",
    "cactus": "AWE", "kitty hawk": "KHA", "ameriflight": "AMF", "denver air": "DNA",
}
NATO = {"alpha": "A", "alfa": "A", "bravo": "B", "charlie": "C", "delta": "D", "echo": "E",
        "foxtrot": "F", "golf": "G", "hotel": "H", "india": "I", "juliet": "J", "juliett": "J",
        "kilo": "K", "lima": "L", "mike": "M", "november": "N", "oscar": "O", "papa": "P",
        "quebec": "Q", "romeo": "R", "sierra": "S", "tango": "T", "uniform": "U", "victor": "V",
        "whiskey": "W", "x-ray": "X", "xray": "X", "yankee": "Y", "zulu": "Z"}
NUM = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
       "seven": "7", "eight": "8", "nine": "9", "niner": "9", "tree": "3", "fife": "5"}


TEENS = {"ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
         "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19"}
TENS = {"twenty": "2", "thirty": "3", "forty": "4", "fifty": "5", "sixty": "6", "seventy": "7",
        "eighty": "8", "ninety": "9"}


def normalize(text):
    """Lower-case transcript -> token string with spoken numbers turned into digits
    ("fifty five thirty" -> "5530", "two two oh one" -> "2201")."""
    t = text.lower().replace("-", " ")
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    words = t.split()
    out = []
    i = 0
    while i < len(words):
        w = words[i]
        if w in TENS:
            nxt = words[i + 1] if i + 1 < len(words) else ""
            if nxt in NUM and NUM[nxt] != "0":
                out.append(TENS[w] + NUM[nxt])
                i += 2
                continue
            out.append(TENS[w] + "0")
        elif w in TEENS:
            out.append(TEENS[w])
        elif w == "oh":
            out.append("0")
        elif w == "hundred":
            out.append("00")
        elif w in NUM:
            out.append(NUM[w])
        elif w in NATO and w != "delta":  # "delta" is usually the airline
            out.append(NATO[w])
        else:
            out.append(w)
        i += 1
    # join runs of digit tokens: "55 30" -> "5530"
    joined = re.sub(r"(?<=\d) (?=\d)", "", " ".join(out))
    return joined


def mentioned_callsigns(text, flights):
    """Which ADS-B flight idents (e.g. 'SKW5530', 'N734SP') the transcript mentions."""
    n = normalize(text)
    compact = n.replace(" ", "").upper()
    hits = set()
    for fl in flights:
        f = fl.strip().upper()
        if not f:
            continue
        m = re.match(r"^([A-Z]{3})(\d+[A-Z]?)$", f)
        if m:  # airline flight: spoken prefix + digits
            pre, num = m.groups()
            for spoken, icao in TELEPHONY.items():
                if icao == pre and re.search(r"\b%s\b" % re.escape(spoken), n):
                    digits = num.lower()
                    if re.search(r"%s\s*%s" % (re.escape(spoken), " ?".join(digits)), n) or \
                       num in compact:
                        hits.add(f)
            if f in compact:
                hits.add(f)
        elif f.startswith("N") and len(f) >= 3:  # US registration: full or last 3
            tail = f[1:]
            if f in compact or ("N" + tail) in compact or (len(tail) >= 3 and tail[-3:] in compact
                                                            and re.search(r"cessna|piper|cirrus|bonanza|"
                                                                          r"skyhawk|mooney|diamond|"
                                                                          r"november|beech|citation",
                                                                          n)):
                hits.add(f)
    return hits


def parse_name(path):
    m = re.search(r"_(\d{8})_(\d{6})(?:_\d{8}_\d{6})?_(\d+)\.mp3$", os.path.basename(path))
    if not m:
        return None, None
    freq = int(m.group(3)) / 1e6
    return "%.3f" % freq, m.group(1) + m.group(2)


def labels():
    try:
        s = json.load(open(SKY_SETTINGS))
        return {"%.3f" % float(c["freq"]): c["label"] for c in s.get("channels", [])}
    except (OSError, ValueError):
        return {}


def cpu_temp():
    try:
        return int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except (OSError, ValueError):
        return None


_HOT = [False]


def too_hot(temp=None, hot_c=80.0, cool_c=72.0):
    """Own check (the worker can outlive the app that started it): trip at hot_c, and stay
    tripped until back under cool_c."""
    t = cpu_temp() if temp is None else temp
    if t is None:
        _HOT[0] = False
    elif t >= hot_c:
        _HOT[0] = True
    elif t <= cool_c:
        _HOT[0] = False
    return _HOT[0]


def low_power():
    marker = os.path.join(HOME, ".cache", "uconsole-suite", "low_power")
    return os.environ.get("UCS_LOW_POWER", "0") not in ("0", "", "off", "no") or os.path.exists(marker)


def worker():
    os.makedirs(REC_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    # one worker at a time (an orphan from a killed Sky would otherwise double-transcribe)
    import fcntl
    lock = open(os.path.join(os.path.dirname(STATUS), "transcriber.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    globals()["_LOCK"] = lock
    try:
        s = json.load(open(SKY_SETTINGS))
    except (OSError, ValueError):
        s = {}
    model_name = s.get("whisper_model", "base.en")
    keep_hours = float(s.get("keep_audio_hours", 24))

    last_status = {"key": None, "t": 0}

    def status(**kw):
        # write only on change, plus a heartbeat every 10 s (SD-card friendly)
        key = json.dumps(kw, sort_keys=True)
        if key == last_status["key"] and time.time() - last_status["t"] < 10:
            return
        last_status["key"], last_status["t"] = key, time.time()
        kw["t"] = time.time()
        tmp = STATUS + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(kw, f)
            os.replace(tmp, STATUS)
        except OSError:
            pass       # full/read-only card: a status file must not kill the worker

    status(state="loading", model=model_name)
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        status(state="error", error="faster-whisper not installed (re-run the suite installer)")
        return 1
    try:
        # leave a core for the radio and the UI; on battery saver use half the cores
        cores = os.cpu_count() or 4
        model = WhisperModel(model_name, device="cpu", compute_type="int8",
                             cpu_threads=max(1, cores // 2 if low_power() else cores - 1))
    except Exception as e:
        status(state="error", error="model load failed: %s" % e)
        return 1
    status(state="ready", model=model_name)
    done = set()
    fails = {}     # clip -> failed transcript writes (retried a couple of times)
    names = labels()
    last_clean = 0
    while True:
        clips = list_clips()
        pending = [(f, m) for f, m in clips if f not in done and not os.path.exists(f + ".json")]
        for f, mtime in pending:
            # Whisper is the hottest thing this device does: stand down while the CPU is over
            # its limit. Clips stay on disk and are transcribed once it has cooled.
            waited = False
            while too_hot():
                waited = True
                status(state="cooling", queue=len(pending), temp=cpu_temp())
                time.sleep(5)
            if waited:
                status(state="ready", model=model_name)
            if time.time() - mtime < 1.0:
                continue  # just finished; let rtl_airband close it
            freq, stamp = parse_name(f)
            if freq is None:
                done.add(f)  # not one of ours (odd name); leave it alone
                continue
            t0 = time.time()
            status(state="working", file=os.path.basename(f), queue=len(pending))
            try:
                segs, info = model.transcribe(f, language="en", beam_size=1, vad_filter=True,
                                              initial_prompt=PROMPT,
                                              condition_on_previous_text=False)
                text = " ".join(x.text.strip() for x in segs).strip()
                dur = getattr(info, "duration", 0.0)
            except Exception as e:
                text, dur = "", 0.0
                status(state="warn", error=str(e)[:200])
            if freq not in names:
                names = labels()
            rec = {"t": mtime - dur, "freq": freq, "label": names.get(freq, freq),
                   "text": text, "dur": round(dur, 1), "file": os.path.basename(f),
                   "secs": round(time.time() - t0, 1)}
            day = time.strftime("%Y-%m-%d", time.localtime(rec["t"]))
            logged = False
            try:
                with open(os.path.join(OUT_DIR, day + ".jsonl"), "a") as out:
                    out.write(json.dumps(rec) + "\n")
                logged = True
                with open(f + ".json", "w") as jf:
                    json.dump(rec, jf)
            except OSError as e:   # full/read-only card, or the clip was cleaned up meanwhile
                status(state="warn", error=str(e)[:200])
                if not logged and os.path.exists(f) and fails.get(f, 0) < 2:
                    # nothing was saved: try again next sweep, but only a couple of times so a
                    # full card can't keep the CPU re-transcribing the same clip
                    fails[f] = fails.get(f, 0) + 1
                    time.sleep(2)
                    continue
            fails.pop(f, None)
            done.add(f)
        if time.time() - last_clean > 600:
            last_clean = time.time()
            for f in glob.glob(os.path.join(REC_DIR, "*.mp3*")):
                try:
                    if time.time() - os.path.getmtime(f) > keep_hours * 3600:
                        os.remove(f)
                except OSError:
                    pass
            # forget clips that no longer exist so `done` doesn't grow for the life of the daemon
            done = {f for f in done if os.path.exists(f)}
        status(state="ready", model=model_name)
        time.sleep(0.7)


def list_clips():
    """[(path, mtime)] of recorded clips, oldest first. A clip deleted between the glob and
    the stat (Sky's or our own cleanup) is skipped instead of killing the worker."""
    out = []
    for f in glob.glob(os.path.join(REC_DIR, "*.mp3")):
        try:
            out.append((f, os.path.getmtime(f)))
        except OSError:
            continue
    out.sort(key=lambda fm: fm[1])
    return out


def recent(n=200, since_days=1):
    lines = []
    for day in sorted(glob.glob(os.path.join(OUT_DIR, "*.jsonl")))[-(since_days + 1):]:
        try:
            for ln in open(day):
                try:
                    lines.append(json.loads(ln))
                except ValueError:
                    pass
        except OSError:
            pass
    return lines[-n:]


def viewer():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    import tkinter as tk
    S.single_instance("Transcripts")
    root, F = S.make_root("Transcripts")
    top = S.top_bar(root, F, "Transcripts", "Airband")
    T = S.T
    st_pill = S.pill(top, F, "Worker")
    search = T.entry(top, F, width=22, font="sm")
    search.pack(side="right", padx=(0, 20), ipady=3)
    search.bind("<Escape>", lambda e: (root.focus_set(), "break")[1])
    tk.Label(top, text="Filter", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE).pack(side="right", padx=8)
    strip = tk.Canvas(root, bg=T.SURFACE, highlightthickness=0, height=S.T.px(150))
    strip.pack(fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(fill="x")

    def draw_strip(rows):
        strip.delete("all")
        w = strip.winfo_width()
        if w < 100:
            return
        chans = []
        for r in rows:
            lab = r.get("label") or r.get("freq")
            if lab not in chans:
                chans.append(lab)
        chans = chans[:6]
        x0, x1, y0 = 170, w - 24, 26
        h = strip.winfo_height()            # the canvas is px()-scaled, so don't assume 150
        if h < 60:
            h = S.T.px(150)
        lane = (h - y0 - 24) / max(len(chans), 1)
        now = time.time()
        span = 6 * 3600
        strip.create_text(28, 10, text=S.T.spaced("Last 6 hours"), anchor="nw", fill=T.TXT_3,
                          font=F["lbl"])
        for hh in range(0, 7):
            xx = x1 - (x1 - x0) * hh / 6
            strip.create_line(xx, y0, xx, h - 22, fill=T.RING)
            strip.create_text(xx, h - 18, text="now" if hh == 0 else "−%dh" % hh, anchor="n",
                              fill=T.TXT_3, font=F["map"])
        for i, ch in enumerate(chans):
            yy = y0 + lane * i + lane / 2
            strip.create_text(28, yy, text=ch, anchor="w", fill=T.TXT_2, font=F["sm"])
            strip.create_line(x0, yy, x1, yy, fill=T.LINE)
            for r in rows:
                if (r.get("label") or r.get("freq")) != ch:
                    continue
                age = now - r["t"]
                if age > span:
                    continue
                xx = x1 - (x1 - x0) * age / span
                ww = max(2, (x1 - x0) * r.get("dur", 2) / span)
                strip.create_rectangle(xx, yy - lane * 0.3, xx + ww, yy + lane * 0.3,
                                       fill=T.ACCENT if age < 300 else T.TXT_2, outline="")

    txt = tk.Text(root, bg=S.BG, fg=S.TXT, font=F["row"], bd=0, highlightthickness=0,
                  wrap="word", padx=28, pady=16, spacing1=5, spacing3=5)
    txt.pack(fill="both", expand=True)
    txt.config(tabs=(110, 290))
    txt.tag_config("time", foreground=T.TXT_3, font=F["mono"])
    txt.tag_config("chan", foreground=T.TXT_2, font=F["smb"])
    txt.tag_config("empty", foreground=T.TXT_3)
    txt.tag_config("hit", background=T.ACCENT_BG, foreground=T.ACCENT)
    seen = {"n": -1, "q": None}

    def refresh():
        try:
            _refresh()
        finally:
            root.after(1500, refresh)   # one bad row must not freeze the viewer for good

    def _refresh():
        rows = recent(400)
        draw_strip(rows)
        q = search.get().strip().lower()
        # recent() caps at 400 rows, so the count alone stops changing once it's full:
        # include the newest row so new transcripts still show up
        sig = (len(rows), rows[-1].get("file"), rows[-1].get("t")) if rows else (0,)
        if sig != seen["n"] or q != seen["q"]:
            at_end = txt.yview()[1] > 0.98
            seen["n"], seen["q"] = sig, q
            txt.config(state="normal")
            txt.delete("1.0", "end")
            for r in rows:
                if q and q not in (r.get("text", "") + r.get("label", "")).lower():
                    continue
                try:
                    stamp = time.strftime("%H:%M:%S\t", time.localtime(r.get("t", 0)))
                except (TypeError, ValueError, OverflowError):
                    stamp = "--:--:--\t"
                txt.insert("end", stamp, "time")
                txt.insert("end", "%s\t" % r.get("label", r.get("freq")), "chan")
                t = r.get("text") or "(no speech detected)"
                txt.insert("end", t + "\n", "empty" if not r.get("text") else ("hit" if q else ()))
            txt.config(state="disabled")
            if at_end or q:
                txt.see("end")
        try:
            s = json.load(open(STATUS))
            age = time.time() - s.get("t", 0)
            label = {"ready": "Whisper ready", "working": "Transcribing…", "loading": "Loading model…",
                     "cooling": "Paused for heat · %d waiting" % s.get("queue", 0),
                     "error": "Error: " + s.get("error", "")}.get(s.get("state"), s.get("state"))
            if age > 30 and s.get("state") != "error":
                label = "Worker stopped · open Sky"
            st_pill.config(text=label[:60], bg=S.GREEN if s.get("state") in ("ready", "working")
                           and age < 30 else (S.RED if s.get("state") == "error" else
                                              S.AMBER if s.get("state") == "cooling" else S.DIM))
        except (OSError, ValueError):
            st_pill.config(text="Worker not started", bg=S.DIM)

    S.bind_quit(root, root.destroy)
    refresh()
    root.mainloop()


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("transcriber: airband transcript worker/viewer\n"
              "  (no args)      open the transcript viewer\n"
              "  --worker       run the Whisper worker loop\n"
              "  --test FILE    transcribe one audio file and print the text")
        return
    if "--worker" in sys.argv:
        sys.exit(worker() or 0)
    if "--test" in sys.argv:
        i = sys.argv.index("--test") + 1
        if i >= len(sys.argv):
            print("transcriber --test needs an audio file path")
            sys.exit(2)
        f = sys.argv[i]
        from faster_whisper import WhisperModel
        m = WhisperModel("base.en", device="cpu", compute_type="int8")
        segs, info = m.transcribe(f, language="en", beam_size=1, vad_filter=True, initial_prompt=PROMPT)
        print(" ".join(s.text.strip() for s in segs))
        return
    viewer()


if __name__ == "__main__":
    main()
