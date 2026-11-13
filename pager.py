#!/usr/bin/env python3
"""Pagers — POCSAG + FLEX paging decoder (Phase 4 #11). Receive-only.

Hospitals, utilities and some public-safety still page over POCSAG (512/1200/2400 baud) and FLEX
on VHF/UHF. rtl_fm feeds multimon-ng, which prints a text line per message; this module parses
those lines into a per-address message log with optional address filtering/watchlist. Nothing is
transmitted.

Pure helpers (parse_* / Pagers) are unit-testable with no radio; the Tk workspace (main) and the
demo follow the suite module pattern. --demo synthesizes multimon-ng lines.
"""
import os
import re
import sys
import time

FREQ_DEFAULT = "152.007M"           # a common POCSAG frequency; configurable in settings

# multimon-ng POCSAG line:  "POCSAG1200: Address: 1234567  Function: 0  Alpha:  message"
_POCSAG = re.compile(
    r"POCSAG(\d+):\s*Address:\s*(\d+)\s+Function:\s*(\d+)"
    r"(?:\s+(Alpha|Numeric|Skyper):\s?(.*))?", re.I)
# multimon-ng FLEX line (format varies by version): "...FLEX...[0001234567] ALN message"
_FLEX = re.compile(r"FLEX[:|].*?\[(\d+)\]\s+(ALN|NUM|TON|GPN|SPN)\s+(.*)", re.I)


def parse_pocsag(line):
    m = _POCSAG.search(line)
    if not m:
        return None
    baud, addr, func, kind, text = m.groups()
    return {"proto": "POCSAG", "baud": int(baud), "address": int(addr),
            "function": int(func), "kind": (kind or "").lower(), "text": (text or "").strip()}


def parse_flex(line):
    m = _FLEX.search(line)
    if not m:
        return None
    cap, kind, text = m.groups()
    return {"proto": "FLEX", "baud": None, "address": int(cap),
            "function": None, "kind": kind.lower(), "text": text.strip()}


def parse_line(line):
    """Parse one multimon-ng output line into a page dict, or None."""
    return parse_pocsag(line) or parse_flex(line)


class Pagers:
    """Messages grouped by (proto, address)."""

    def __init__(self, cap_per_addr=50):
        self.by_addr = {}
        self.cap = cap_per_addr
        self.count = 0
        self.on_page = None                 # callback(page) — alert hook

    def add(self, page, now=None):
        if not page:
            return None
        now = time.time() if now is None else now
        key = (page["proto"], page["address"])
        rec = self.by_addr.get(key)
        if rec is None:
            rec = {"proto": page["proto"], "address": page["address"], "first": now,
                   "msgs": [], "n": 0}
            self.by_addr[key] = rec
        rec["msgs"].append({"t": now, "kind": page.get("kind"), "text": page.get("text", "")})
        del rec["msgs"][:-self.cap]
        rec["n"] += 1
        rec["last"] = now
        self.count += 1
        if self.on_page:
            self.on_page(page)
        return rec

    def recent(self, now=None, limit=200):
        rows = sorted(self.by_addr.values(), key=lambda r: -r["last"])
        return rows[:limit]


class Demo:
    """Synthetic multimon-ng lines so the log works without hardware."""
    LINES = [
        "POCSAG1200: Address: 1234567  Function: 3  Alpha:   PT in room 412 needs assistance",
        "POCSAG512: Address:  980312  Function: 0  Numeric: 5551212",
        "POCSAG1200: Address: 2000911  Function: 3  Alpha:   STRUCTURE FIRE 100 Main St E9 E12",
        "FLEX: 2026-11-12 18:30:01 1600/2/K/A 00.000 [0001234567] ALN System test page",
        "POCSAG1200: Address: 1234567  Function: 3  Alpha:   Lab results ready",
    ]

    def __init__(self):
        self.i = 0

    def lines(self):
        self.i += 1
        return [self.LINES[self.i % len(self.LINES)]]


def pipeline(freq, gain=0):
    g = " -g %d" % int(gain) if gain else ""
    mm = "multimon-ng -t raw -a POCSAG512 -a POCSAG1200 -a POCSAG2400 -a FLEX /dev/stdin"
    return "rtl_fm -f %s -M fm -s 22050%s -E dc - 2>/dev/null | %s" % (freq, g, mm)


DEFAULTS = {"freq": FREQ_DEFAULT, "gain": 0, "watch": []}       # watch: addresses to alert on


def main(parent=None):
    import queue
    import threading
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Pagers")
    s, spath = S.settings("pager", DEFAULTS)
    root, F = S.make_root("Pagers", parent=parent)
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("pager")
    demo = ("--demo" in sys.argv) or not (shutil.which("rtl_fm") and shutil.which("multimon-ng"))
    q = queue.Queue()
    pagers = Pagers()
    watch = set(int(a) for a in (s.get("watch") or []) if str(a).isdigit())
    st = {"on": False, "gen": 0}

    def on_page(p):
        slog.event("pager", "%s %d" % (p["proto"], p["address"]), id=str(p["address"]))
        if p["address"] in watch:
            try:
                S.notify("Pager watch", "%d: %s" % (p["address"], p.get("text", "")[:60]))
            except Exception:
                pass
    pagers.on_page = on_page

    top = S.top_bar(root, F, "Pagers", "POCSAG + FLEX · receive-only")
    state_pill = S.pill(top, F, "Off")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    txt = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="word", state="disabled", padx=T.px(12), pady=T.px(8))
    txt.tag_config("addr", foreground=S.AMBER)
    txt.tag_config("meta", foreground=T.TXT_3)
    txt.pack(fill="both", expand=True)

    def render():
        txt.config(state="normal")
        txt.delete("1.0", "end")
        for rec in pagers.recent():
            last = rec["msgs"][-1] if rec["msgs"] else {"text": "", "t": rec["last"]}
            txt.insert("end", "%s %d " % (rec["proto"], rec["address"]), "addr")
            txt.insert("end", "(%d msg · %s)\n" % (
                rec["n"], time.strftime("%H:%M:%S", time.localtime(rec["last"]))), "meta")
            txt.insert("end", "   %s\n" % last.get("text", ""))
        txt.config(state="disabled")

    def worker(gen):
        if demo:
            dm = Demo()
            while st["on"] and st["gen"] == gen:
                for ln in dm.lines():
                    q.put(ln)
                time.sleep(1.2)
            return
        with S.errfile(os.path.join(S.CACHE, "pager.err")) as err:
            p = S.spawn(pipeline(s.get("freq", FREQ_DEFAULT), s.get("gain", 0)), shell=True,
                        stdout=__import__("subprocess").PIPE, stderr=err, text=True, errors="replace")
        st["proc"] = p
        try:
            for line in p.stdout:
                if not st["on"] or st["gen"] != gen:
                    break
                q.put(line)
        finally:
            S.stop_group(p, grace=1.0)

    def start():
        if st["on"]:
            return
        st["gen"] += 1
        st["on"] = True
        state_pill.config(text="Listening" + (" (demo)" if demo else ""), bg=S.GREEN)
        T.set_btn(listen_btn, "Stop", kind="danger")
        threading.Thread(target=worker, args=(st["gen"],), daemon=True).start()

    def stop():
        st["on"] = False
        st["gen"] += 1
        state_pill.config(text="Off", bg=S.DIM)
        T.set_btn(listen_btn, "Listen", kind="primary")

    def toggle(_=None):
        stop() if st["on"] else start()

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    listen_btn = S.btn(bar, "Listen", toggle, F, padx=14, pady=5, kind="primary")
    listen_btn.pack(side="left", padx=(10, 6), pady=6)
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))
    root.bind("<space>", toggle)

    def pump():
        changed = False
        try:
            for _ in range(500):
                ln = q.get_nowait()
                if pagers.add(parse_line(ln)):
                    changed = True
        except queue.Empty:
            pass
        if changed:
            render()
        root.after(400, pump)

    def on_close():
        stop()
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()

    S.bind_quit(root, on_close)
    render()
    pump()
    if "--demo" in sys.argv:
        root.after(300, start)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
