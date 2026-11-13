#!/usr/bin/env python3
"""
Push-to-talk AI assistant.

Hold SPACE (or the big button) and talk -> Whisper (on the uConsole) -> Ollama on your
desktop over Tailscale if it's reachable, otherwise a small model on the uConsole ->
spoken reply in your headset (espeak-ng, or Piper if you configure a voice).
You can also type a question and press Enter.
"""

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402

DEFAULTS = {
    "hosts": [
        {"name": "Desktop", "url": "http://desktop:11434", "model": ""},
        {"name": "uConsole", "url": "http://127.0.0.1:11434", "model": "llama3.2:3b"},
    ],
    "local_threads": 2,     # CPU threads for a model on this device (0 = all cores)
    "live_context": True,   # tell the model what the suite currently sees (aircraft, GPS, ...)
    "whisper_model": "base.en",
    "tts": "auto",          # auto | piper | espeak | off
    "piper_voice": "",      # path to a Piper .onnx voice
    "espeak_voice": "en-us",
    "espeak_rate": 170,
    "system": ("You are a voice assistant running on a handheld Linux computer (ClockworkPi "
               "uConsole). Replies are read aloud through a headset, so answer in plain spoken "
               "sentences: short, direct, no markdown, no lists unless asked, no code blocks "
               "unless asked. If unsure, say so."),
}
REC = os.path.join(S.CACHE, "ptt.wav")


def http_json(url, data=None, timeout=3):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def pick_host(s):
    """First reachable Ollama host -> (name, url, model) or None."""
    for h in s["hosts"]:
        try:
            tags = http_json(h["url"].rstrip("/") + "/api/tags", timeout=1.5)
        except Exception:
            continue
        models = [m["name"] for m in tags.get("models", [])]
        if not models:
            continue
        return h["name"], h["url"].rstrip("/"), best_model(models, h.get("model") or "")
    return None


# General-purpose chat models, best first; used only when the host's Model field is blank or
# names a model the server doesn't have. Substring match on the model name.
PREFERRED = ("qwen-smart", "qwen3", "qwen2.5", "llama3", "gemma", "mistral", "phi")
NOT_CHAT = ("embed", "bge-", "minilm", "whisper", "clip")


def best_model(models, want=""):
    """The model to chat with: the configured one if the server has it, else the best
    general chat model it does have - never an embedding model just because it is listed first."""
    if want and (want in models or want + ":latest" in models):
        return want
    chat = [m for m in models if not any(x in m.lower() for x in NOT_CHAT)] or list(models)
    for pref in PREFERRED:
        for m in chat:
            if pref in m.lower():
                return m
    return chat[0]


def is_local(url):
    """True when the Ollama URL points at this device (so the model runs on the CM5)."""
    host = re.sub(r"^\w+://", "", url or "").split("/")[0].rsplit(":", 1)[0].strip("[]")
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def chat_body(s, url, model, messages, stream=True):
    """The /api/chat request. A model running on this device is capped to a couple of CPU
    threads: all four cores at full load can brown out the uConsole on battery."""
    body = {"model": model, "messages": messages, "stream": stream}
    try:
        n = int(s.get("local_threads", 2))
    except (TypeError, ValueError):
        n = 2
    if is_local(url) and n > 0:
        body["options"] = {"num_thread": n}
    return body


def power_warning(p, local):
    """One line of advice before an on-device model runs on a weak supply, else ""."""
    if not local or not p:
        return ""
    if p.get("undervolt_now"):
        return "Under-voltage right now - an on-device model may crash the uConsole. Plug in first."
    pct = p.get("pct")
    if not p.get("charging") and pct is not None and pct < 50:
        return ("Battery %d%% and not charging - an on-device model draws a lot of power; "
                "plug in if it stutters or the device resets." % pct)
    return ""


def live_context(d, p=None):
    """A few plain sentences describing what the suite sees right now, from sitrep.gather()'s
    dict (and S.power_status()). Only facts that are present; "" when there is nothing."""
    out = []
    if not isinstance(d, dict):
        d = {}
    if "aircraft_airborne" in d:
        line = "ADS-B receiver: %d aircraft airborne" % d["aircraft_airborne"]
        hi = d.get("highest") or {}
        if isinstance(hi.get("alt"), (int, float)):
            line += ", highest %s at %d feet" % (hi.get("cs") or "unknown", hi["alt"])
        out.append(line + ".")
    if d.get("emergencies"):
        out.append("Emergency squawks: %s." % ", ".join(d["emergencies"]))
    m = d.get("metar")
    if m and m.get("cat"):
        line = "Weather at %s: %s" % (m.get("station") or "the home field", m["cat"])
        if isinstance(m.get("temp"), (int, float)):
            line += ", %d C" % m["temp"]
        if isinstance(m.get("wind_dir"), int) and isinstance(m.get("wind_spd"), (int, float)):
            line += ", wind %03d at %d knots" % (m["wind_dir"], m["wind_spd"])
        out.append(line + ".")
    if d.get("tfrs"):
        n = len(d["tfrs"])
        out.append("%d active flight restriction%s in the area." % (n, "" if n == 1 else "s"))
    g = d.get("gps")
    if g:
        out.append("GPS fix: %.4f, %.4f." % (g["lat"], g["lon"]))
    else:
        out.append("GPS: no fix.")
    np_ = d.get("next_pass")
    if np_:
        out.append("Next weather satellite pass: %s in %d minutes." % (np_.get("sat"), np_["in_min"]))
    sd = d.get("sonde")
    if sd and isinstance(sd.get("alt_m"), (int, float)):
        out.append("Weather balloon %s %s at %d metres." % (sd.get("id"), sd.get("phase") or "aloft",
                                                            sd["alt_m"]))
    if d.get("aprs_24h"):
        out.append("%d APRS stations heard in the last day." % d["aprs_24h"])
    if d.get("mesh_nodes_24h"):
        out.append("%d mesh nodes heard in the last day." % d["mesh_nodes_24h"])
    b = p or d.get("battery") or {}
    if b.get("pct") is not None:
        line = "Battery %d%%, %s" % (b["pct"], str(b.get("status") or "unknown").lower())
        if p and p.get("temp") is not None:
            line += ", CPU %d C" % p["temp"]
        if p and p.get("undervolt_now"):
            line += ", under-voltage now"
        out.append(line + ".")
    return " ".join(out)


def system_prompt(s, context="", now=None):
    """System message: the user's prompt, the clock, and (if any) the live status block."""
    txt = s["system"] + " Current local time: %s." % time.strftime("%A %B %d %Y, %H:%M", now or time.localtime())
    if context:
        txt += (" Live status from this device's own receivers and sensors follows. Use it only "
                "when the question is about it, and do not invent readings that are not listed. "
                + context)
    return txt


class LiveContext:
    """Keeps a recent live_context() string without ever making a question wait: get() returns
    the last snapshot at once and refreshes it in the background when it is older than ttl."""

    def __init__(self, ttl=120, gather=None, power=None, spawn=None):
        self.ttl, self.text, self.t, self.busy = ttl, "", 0.0, False
        self._gather, self._power = gather, power
        self._spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())

    def refresh(self):
        try:
            if self._gather is None:
                import sitrep
                self._gather = sitrep.gather
            p = (self._power or S.power_status)()
            self.text = live_context(self._gather(), p)
        except Exception:
            pass        # keep the previous snapshot
        finally:
            self.t, self.busy = time.time(), False

    def get(self):
        if not self.busy and time.time() - self.t > self.ttl:
            self.busy = True
            self._spawn(self.refresh)
        return self.text


def espeak_cmd(exe, voice, rate, text):
    """espeak argv; "--" ends option parsing so model text starting with "-" (a markdown
    list item, or anything option-like) is spoken instead of parsed as flags."""
    return [exe, "-v", voice, "-s", str(rate), "--", text]


def next_sentence(buf, done=False):
    """(sentence, rest) for the first speakable sentence in a streaming buffer, or None.
    Very short sentences ("Sure.") are joined with the next one instead of blocking the
    stream: the old check stopped at the first short sentence and spoke nothing until the end."""
    mm = re.search(r"(.{12,}?[.!?])(\s|$)", buf, re.S)
    if not mm:
        return None
    return mm.group(1), buf[mm.end():]


class Speaker:
    def __init__(self, s, log):
        self.s, self.log = s, log
        self.q = queue.Queue()
        self.proc = None
        self.gen = 0
        threading.Thread(target=self._loop, daemon=True).start()

    def engine(self):
        t = self.s.get("tts", "auto")
        if t == "off":
            return None
        piper = shutil.which("piper")
        voice = self.s.get("piper_voice")
        if t in ("auto", "piper") and piper and voice and os.path.exists(voice):
            return "piper"
        if shutil.which("espeak-ng") or shutil.which("espeak"):
            return "espeak"
        return None

    def say(self, text):
        text = re.sub(r"[*_`#>]+", "", text).strip()
        if text:
            self.q.put((self.gen, text))

    def stop(self):
        self.gen += 1
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        S.stop_group(self.proc, grace=0.3)

    def busy(self):
        return not self.q.empty() or (self.proc is not None and self.proc.poll() is None)

    def _loop(self):
        while True:
            gen, text = self.q.get()
            if gen is None:              # workspace closed
                return
            if gen != self.gen:
                continue
            eng = self.engine()
            if not eng:
                continue
            try:
                if eng == "piper":
                    wav = os.path.join(S.CACHE, "tts.wav")
                    p = subprocess.run(["piper", "--model", self.s["piper_voice"], "--output_file", wav],
                                       input=text, text=True, capture_output=True, timeout=60)
                    if gen != self.gen:
                        continue      # Stop / a new question arrived while piper was rendering
                    if p.returncode == 0 and os.path.exists(wav):
                        player = ["paplay", wav] if shutil.which("paplay") else ["aplay", "-q", wav]
                        self.proc = S.spawn(player)
                    else:
                        eng = "espeak"
                if eng == "espeak":
                    exe = shutil.which("espeak-ng") or shutil.which("espeak")
                    self.proc = S.spawn(espeak_cmd(exe, self.s["espeak_voice"],
                                                   self.s["espeak_rate"], text),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.proc.wait()
            except Exception as e:
                self.log("TTS error: %s" % e)


def main():
    S.single_instance("Assistant")
    s, spath = S.settings("assistant", DEFAULTS)
    root, F = S.make_root("Assistant")
    import tkinter as tk

    ev = queue.Queue()
    st = {"rec": None, "model": None, "history": [], "gen": 0, "host": None, "busy": False,
          "t_rec": 0}
    spk = Speaker(s, lambda m: ev.put(("log", m)))
    live = LiveContext()
    if s.get("live_context"):
        live.get()                       # warm the first snapshot while Whisper loads

    top = S.top_bar(root, F, "Assistant", "Local AI")
    T = S.T
    stt_pill = S.pill(top, F, "Whisper")
    llm_pill = S.pill(top, F, "Model")
    mic_lbl = tk.Label(top, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE)
    mic_lbl.pack(side="right", padx=20)

    bottomw = tk.Frame(root, bg=T.SURFACE)
    bottomw.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    bottom = tk.Frame(bottomw, bg=T.SURFACE)
    bottom.pack(fill="x", padx=20, pady=12)
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    chat = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["row"], bd=0, highlightthickness=0,
                   wrap="word", padx=0, pady=20, spacing1=2, spacing3=4)
    chat.pack(fill="both", expand=True, padx=(S.T.px(90), S.T.px(90)))
    chat.tag_config("you", foreground=T.TXT_3, font=F["lbl"], spacing1=14)
    chat.tag_config("ai", foreground=T.ACCENT, font=F["lbl"], spacing1=14)
    chat.tag_config("meta", foreground=T.TXT_3, font=F["map"])
    chat.config(state="disabled")

    talk = S.btn(bottom, "Hold Space to talk", lambda: None, F, font="smb", padx=18, pady=7,
                 kind="primary")
    talk.pack(side="left")
    entry = T.entry(bottom, F, font="row")
    entry.pack(side="left", fill="x", expand=True, padx=12, ipady=5)
    row = tk.Frame(bottom, bg=T.SURFACE)
    row.pack(side="left")
    S.btn(row, "Stop", lambda: stop_all(), F, kind="quiet").pack(side="left")
    S.btn(row, "New chat", lambda: new_chat(), F, kind="quiet").pack(side="left")
    S.btn(row, "Settings", lambda: edit_settings(), F, kind="quiet").pack(side="left")

    def add(who, text, tag):
        chat.config(state="normal")
        chat.insert("end", S.T.spaced(who) + "\n", tag)
        chat.insert("end", text + "\n\n")
        chat.config(state="disabled")
        chat.see("end")

    def meta(text):
        chat.config(state="normal")
        chat.insert("end", text + "\n", "meta")
        chat.config(state="disabled")
        chat.see("end")

    stream_mark = {"on": False}

    def stream_start():
        chat.config(state="normal")
        chat.insert("end", S.T.spaced("Assistant") + "\n", "ai")
        chat.mark_set("streamend", "end-1c")
        chat.mark_gravity("streamend", "right")
        chat.config(state="disabled")
        stream_mark["on"] = True

    def stream_add(tok):
        chat.config(state="normal")
        chat.insert("streamend", tok)
        chat.config(state="disabled")
        chat.see("end")

    def stream_end():
        chat.config(state="normal")
        chat.insert("streamend", "\n\n")
        chat.config(state="disabled")
        stream_mark["on"] = False

    # ------------------------------------------------------------- models
    def load_whisper():
        try:
            from faster_whisper import WhisperModel
            st["model"] = WhisperModel(s["whisper_model"], device="cpu", compute_type="int8")
            ev.put(("stt", "ready"))
        except Exception as e:
            ev.put(("stt", "error: %s" % str(e)[:60]))

    def check_llm():
        h = pick_host(s)
        st["host"] = h
        ev.put(("llm", h))

    def mic_name():
        rc, out = S.run(["pactl", "get-default-source"], timeout=3)
        if rc != 0 or not out:
            return "no mic found"
        rc2, lst = S.run(["pactl", "list", "sources"], timeout=3)
        cur = None
        for ln in (lst or "").splitlines():
            ln = ln.strip()
            if ln.startswith("Name:"):
                cur = ln.split(":", 1)[1].strip()
            elif ln.startswith("Description:") and cur == out.strip():
                return ln.split(":", 1)[1].strip()
        return out.strip()

    # ------------------------------------------------------------- recording
    def rec_start():
        if st["rec"] or st["busy"]:
            return
        spk.stop()
        try:
            os.remove(REC)
        except OSError:
            pass
        if shutil.which("parecord"):
            cmd = ["parecord", "--channels=1", "--rate=16000", "--format=s16le",
                   "--file-format=wav", REC]
        else:
            cmd = ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", REC]
        st["rec"] = S.spawn(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        st["t_rec"] = time.time()
        S.set_btn(talk, "Listening — release to send", "danger")

    def rec_stop():
        p, st["rec"] = st["rec"], None
        if not p:
            return
        try:
            os.killpg(p.pid, signal.SIGINT)
            p.wait(timeout=3)
        except Exception:
            S.stop_group(p, grace=0.5)
        S.set_btn(talk, "Hold Space to talk", "primary")
        if time.time() - st["t_rec"] < 0.4:
            meta("(too short - hold while you speak)")
            return
        S.in_thread(transcribe_and_ask)

    def transcribe_and_ask():
        if not st["model"]:
            ev.put(("meta", "Speech model still loading…"))
            return
        st["busy"] = True
        ev.put(("talk", "transcribing…"))
        try:
            segs, _ = st["model"].transcribe(REC, language="en", beam_size=1, vad_filter=True)
            text = " ".join(x.text.strip() for x in segs).strip()
        except Exception as e:
            ev.put(("meta", "Transcription failed: %s" % e))
            st["busy"] = False
            ev.put(("talk", None))
            return
        st["busy"] = False
        if not text:
            ev.put(("meta", "(didn't catch that)"))
            ev.put(("talk", None))
            return
        ev.put(("ask", text))

    # ------------------------------------------------------------- LLM
    def ask(text):
        add("You", text, "you")
        st["history"].append({"role": "user", "content": text})
        st["gen"] += 1
        S.in_thread(run_llm, st["gen"])

    def run_llm(gen):
        st["busy"] = True
        ev.put(("talk", "thinking…"))
        h = pick_host(s)
        st["host"] = h
        ev.put(("llm", h))
        if not h:
            ev.put(("meta", "No Ollama server reachable. Start Ollama on your desktop (and Tailscale), "
                    "or start it on this device: systemctl start ollama  "
                    "(no local model yet? ollama pull llama3.2:3b)"))
            st["busy"] = False
            ev.put(("talk", None))
            return
        name, url, model = h
        if is_local(url):
            try:
                warn = power_warning(S.power_status(), True)
            except Exception:
                warn = ""
            if warn:
                ev.put(("meta", warn))
        ctx = live.get() if s.get("live_context") else ""
        msgs = [{"role": "system", "content": system_prompt(s, ctx)}] + st["history"][-16:]
        req = urllib.request.Request(url + "/api/chat", data=json.dumps(
            chat_body(s, url, model, msgs)).encode(),
            headers={"Content-Type": "application/json"})
        full, buf = "", ""
        ev.put(("stream_start", None))
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                for line in r:
                    if gen != st["gen"]:
                        return
                    try:
                        m = json.loads(line)
                    except ValueError:
                        continue
                    tok = m.get("message", {}).get("content", "")
                    if tok:
                        full += tok
                        buf += tok
                        ev.put(("tok", tok))
                        # speak each finished sentence as it arrives
                        while True:
                            nxt = next_sentence(buf)
                            if not nxt:
                                break
                            spk.say(nxt[0])
                            buf = nxt[1]
                    if m.get("done"):
                        break
        except Exception as e:
            ev.put(("tok", "\n[error talking to %s: %s]" % (name, e)))
        if gen != st["gen"]:
            return  # superseded by a newer question; its handler owns the UI now
        if buf.strip():
            spk.say(buf)
        ev.put(("stream_end", "%s · %s" % (name, model)))
        if full:
            st["history"].append({"role": "assistant", "content": full})
        st["busy"] = False
        ev.put(("talk", None))

    def stop_all():
        st["gen"] += 1
        # the superseded run_llm returns early without clearing busy; without this,
        # push-to-talk stays dead after Stop / New chat mid-answer
        st["busy"] = False
        spk.stop()
        if st["rec"]:
            S.stop_group(st["rec"], grace=0.3)
            st["rec"] = None
        S.set_btn(talk, "Hold Space to talk", "primary")

    def new_chat():
        stop_all()
        st["history"] = []
        chat.config(state="normal")
        chat.delete("1.0", "end")
        chat.config(state="disabled")

    AI_SCHEMA = [
        ("Language model", [
            {"key": "hosts", "label": "Ollama hosts", "type": "table",
             "help": "tried in order; first one that answers wins. Model blank = server default",
             "columns": [("name", "Name", "str"), ("url", "URL", "str"), ("model", "Model", "str")],
             "template": {"name": "New", "url": "http://host:11434", "model": ""}},
            {"key": "system", "label": "System prompt", "type": "text", "rows": 5},
            {"key": "live_context", "label": "Live device status", "type": "bool",
             "help": "lets it answer about aircraft, weather, GPS and battery from the suite's own data"},
            {"key": "local_threads", "label": "On-device CPU threads", "type": "int", "min": 0, "max": 4,
             "step": 1, "help": "for a model running on the uConsole; 2 avoids brownouts, 0 = all cores"},
        ]),
        ("Speech", [
            {"key": "whisper_model", "label": "Whisper model", "type": "choice",
             "choices": [("tiny.en", "tiny.en (fastest)"), ("base.en", "base.en"), ("small.en", "small.en")]},
            {"key": "tts", "label": "Voice output", "type": "choice",
             "choices": [("auto", "Auto (Piper if available)"), ("piper", "Piper"), ("espeak", "espeak-ng"),
                         ("off", "Off")]},
            {"key": "piper_voice", "label": "Piper voice (.onnx)", "type": "str"},
            {"key": "espeak_voice", "label": "espeak voice", "type": "str"},
            {"key": "espeak_rate", "label": "espeak rate", "type": "int", "min": 80, "max": 400, "step": 10,
             "unit": "wpm"},
        ]),
    ]

    def edit_settings():
        import settings_ui

        def on_save(new):
            s.clear()
            s.update(new)
            S.save_json(spath, s)
            meta("Settings saved - host/model apply to the next message.")
        settings_ui.open_settings(root, F, "Assistant settings", AI_SCHEMA, s, on_save, path=spath)

    # ------------------------------------------------------------- keys (debounced autorepeat)
    rel_job = [None]

    def key_down(e):
        if root.focus_get() is entry:
            return
        if rel_job[0]:
            root.after_cancel(rel_job[0])
            rel_job[0] = None
            return
        rec_start()

    def key_up(e):
        if root.focus_get() is entry:
            return

        def really():
            rel_job[0] = None
            rec_stop()
        rel_job[0] = root.after(120, really)

    root.bind("<KeyPress-space>", key_down)
    root.bind("<KeyRelease-space>", key_up)
    talk.bind("<ButtonPress-1>", lambda e: rec_start())
    talk.bind("<ButtonRelease-1>", lambda e: rec_stop())

    def send_typed(_=None):
        t = entry.get().strip()
        if t:
            entry.delete(0, "end")
            spk.stop()
            ask(t)
        root.focus_set()

    entry.bind("<Return>", send_typed)
    entry.bind("<Escape>", lambda e: (root.focus_set(), "break")[1])

    def pump():
        while not ev.empty():
            e = ev.get()
            k = e[0]
            if k == "stt":
                stt_pill.config(text="Whisper " + e[1], bg=S.GREEN if e[1] == "ready" else S.RED)
            elif k == "llm":
                h = e[1]
                llm_pill.config(text=("%s · %s" % (h[2], h[0])) if h else "No model reachable",
                                bg=S.GREEN if h else S.RED)
            elif k == "ask":
                ask(e[1])
            elif k == "meta":
                meta(e[1])
            elif k == "log":
                meta(e[1])
            elif k == "talk":
                if not st["rec"]:
                    if e[1]:
                        S.set_btn(talk, e[1][:1].upper() + e[1][1:], "busy")
                    else:
                        S.set_btn(talk, "Hold Space to talk", "primary")
            elif k == "stream_start":
                stream_start()
            elif k == "tok":
                stream_add(e[1])
            elif k == "stream_end":
                stream_end()
                meta(e[1])
            elif k == "mic":
                mic_lbl.config(text="Mic · " + e[1])
        root.after(80, pump)

    def periodic():
        S.reap()
        S.in_thread(check_llm)
        S.in_thread(lambda: ev.put(("mic", mic_name())))
        root.after(30000, periodic)

    def on_close():
        stop_all()
        spk.q.put((None, None))          # ends the speech thread
        root.destroy()

    S.header_quit(top, root, F, on_close)
    S.bind_quit(root, on_close)
    meta("Hold Space and talk, or type below and press Enter.")
    S.in_thread(load_whisper)
    pump()
    periodic()
    root.mainloop()


if __name__ == "__main__":
    main()
