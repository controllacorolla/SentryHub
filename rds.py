#!/usr/bin/env python3
"""RDS — FM broadcast Radio Data System decoder (Phase 4 #22). Receive-only.

The sub-audible data on FM broadcast carries the station name (PS), scrolling RadioText (RT),
programme type, and traffic flags. rtl_fm feeds redsea, which emits one JSON object per decoded
group; this module folds those into a per-station table. Nothing is transmitted.

Pure helpers (parse_rds / Stations) are unit-testable; the Tk workspace + demo follow the module
pattern. --demo synthesizes redsea JSON lines.
"""
import json
import os
import sys
import time

FREQ_DEFAULT = "100.3M"


def parse_rds(line):
    """One redsea JSON line -> a normalized dict, or None. Tolerant of redsea's field variants."""
    try:
        d = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict) or "pi" not in d:
        return None
    return {"pi": str(d.get("pi")),
            "ps": (d.get("ps") or "").strip(),
            "rt": (d.get("radiotext") or d.get("rt") or "").strip(),
            "pty": d.get("prog_type") or d.get("pty"),
            "tp": bool(d.get("tp")), "ta": bool(d.get("ta")),
            "callsign": d.get("callsign"), "group": d.get("group")}


class Stations:
    """Latest PS/RT per station (keyed by PI code)."""

    def __init__(self):
        self.by_pi = {}
        self.count = 0

    def add(self, r, now=None):
        if not r:
            return None
        now = time.time() if now is None else now
        st = self.by_pi.get(r["pi"])
        if st is None:
            st = {"pi": r["pi"], "ps": "", "rt": "", "pty": None, "callsign": None,
                  "first": now, "n": 0}
            self.by_pi[r["pi"]] = st
        if r.get("ps"):
            st["ps"] = r["ps"]
        if r.get("rt"):
            st["rt"] = r["rt"]
        if r.get("pty"):
            st["pty"] = r["pty"]
        if r.get("callsign"):
            st["callsign"] = r["callsign"]
        st["tp"], st["ta"] = r.get("tp"), r.get("ta")
        st["n"] += 1
        st["last"] = now
        self.count += 1
        return st

    def recent(self):
        return sorted(self.by_pi.values(), key=lambda s: -s["last"])


class Demo:
    LINES = [
        '{"pi":"0x403A","group":"0A","ps":"CLASSIC","tp":true,"ta":false,"prog_type":"Classics"}',
        '{"pi":"0x403A","group":"2A","radiotext":"Now playing: Beethoven Symphony No. 7"}',
        '{"pi":"0x1234","group":"0A","ps":"NEWS 24","tp":true,"ta":true,"prog_type":"News"}',
        '{"pi":"0x1234","group":"2A","radiotext":"Traffic on I-25 southbound near downtown"}',
        '{"pi":"0x56CE","group":"0A","ps":"ROCK FM","prog_type":"Rock","callsign":"KROQ"}',
    ]

    def __init__(self):
        self.i = 0

    def lines(self):
        self.i += 1
        return [self.LINES[self.i % len(self.LINES)]]


def pipeline(freq, gain=0):
    g = " -g %d" % int(gain) if gain else ""
    return ("rtl_fm -M fm -l 0 -A std -p 0 -s 171k%s -F 9 -f %s 2>/dev/null | redsea -r 171000 "
            "2>/dev/null" % (g, freq))


DEFAULTS = {"freq": FREQ_DEFAULT, "gain": 0}


def main(parent=None):
    import queue
    import threading
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("RDS")
    s, spath = S.settings("rds", DEFAULTS)
    root, F = S.make_root("RDS", parent=parent)
    import tkinter as tk
    T = S.T
    demo = ("--demo" in sys.argv) or not (shutil.which("rtl_fm") and shutil.which("redsea"))
    q = queue.Queue()
    stations = Stations()
    st = {"on": False, "gen": 0}

    top = S.top_bar(root, F, "RDS", "FM station ID + RadioText · receive-only")
    state_pill = S.pill(top, F, "Off")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    txt = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="word", state="disabled", padx=T.px(12), pady=T.px(8))
    txt.tag_config("ps", foreground=S.AMBER)
    txt.tag_config("meta", foreground=T.TXT_3)
    txt.pack(fill="both", expand=True)

    def render():
        txt.config(state="normal")
        txt.delete("1.0", "end")
        for st_ in stations.recent():
            txt.insert("end", "%-10s " % (st_["ps"] or "?"), "ps")
            txt.insert("end", "%s  %s%s\n" % (
                st_["pi"], st_.get("pty") or "",
                "  [TA]" if st_.get("ta") else ""), "meta")
            if st_["rt"]:
                txt.insert("end", "   %s\n" % st_["rt"])
        if not stations.by_pi:
            txt.insert("end", "Tuning…\n" if st["on"] else "Press Listen.\n", "meta")
        txt.config(state="disabled")

    def worker(gen):
        if demo:
            dm = Demo()
            while st["on"] and st["gen"] == gen:
                for ln in dm.lines():
                    q.put(ln)
                time.sleep(1.0)
            return
        with S.errfile(os.path.join(S.CACHE, "rds.err")) as err:
            p = S.spawn(pipeline(s.get("freq", FREQ_DEFAULT), s.get("gain", 0)), shell=True,
                        stdout=__import__("subprocess").PIPE, stderr=err, text=True, errors="replace")
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
                if stations.add(parse_rds(q.get_nowait())):
                    changed = True
        except queue.Empty:
            pass
        if changed:
            render()
        root.after(500, pump)

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
