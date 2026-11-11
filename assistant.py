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
        model = h.get("model") or ""
        if model and model not in models and model + ":latest" not in models:
            model = ""
        return h["name"], h["url"].rstrip("/"), model or models[0]
    return None


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
                    "or install a local model: ollama pull llama3.2:3b"))
            st["busy"] = False
            ev.put(("talk", None))
            return
        name, url, model = h
        msgs = [{"role": "system", "content": s["system"] + " Current local time: %s." %
                 time.strftime("%A %B %d %Y, %H:%M")}] + st["history"][-16:]
        req = urllib.request.Request(url + "/api/chat", data=json.dumps(
            {"model": model, "messages": msgs, "stream": True}).encode(),
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

    S.bind_quit(root, on_close)
    meta("Hold Space and talk, or type below and press Enter.")
    S.in_thread(load_whisper)
    pump()
    periodic()
    root.mainloop()


if __name__ == "__main__":
    main()
