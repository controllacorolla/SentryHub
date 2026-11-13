#!/usr/bin/env python3
"""NOAA Weather Radio — SAME / EAS alert decoder (Phase 4 #10). Receive-only.

NWR transmitters (162.400–162.550 MHz) send SAME digital headers ahead of warnings; EAS on
broadcast uses the same protocol. rtl_fm feeds multimon-ng -a EAS, which prints the ZCZC header;
this module decodes it into originator / event / affected areas / valid time, logs it, and speaks
the warning. Nothing is transmitted.

Pure helpers (parse_same, the code tables) are unit-testable; the Tk workspace + demo follow the
module pattern. SAME header format (NWSI 10-1712):
  ZCZC-ORG-EEE-PSSCCC-PSSCCC...+TTTT-JJJHHMM-LLLLLLLL-
"""
import os
import re
import sys
import time

FREQ_DEFAULT = "162.400M"

ORG = {"WXR": "National Weather Service", "EAS": "Broadcast station/cable",
       "PEP": "Presidential (national)", "CIV": "Civil authorities", "EAN": "Emergency Action"}

# Common SAME event codes -> plain name (not exhaustive; unknown codes pass through).
EVENT = {
    "TOR": "Tornado Warning", "SVR": "Severe Thunderstorm Warning", "FFW": "Flash Flood Warning",
    "FFA": "Flash Flood Watch", "FLW": "Flood Warning", "FLA": "Flood Watch",
    "TOA": "Tornado Watch", "SVA": "Severe Thunderstorm Watch", "WSW": "Winter Storm Warning",
    "BZW": "Blizzard Warning", "HWW": "High Wind Warning", "HUW": "Hurricane Warning",
    "TRW": "Tropical Storm Warning", "EWW": "Extreme Wind Warning", "FRW": "Fire Warning",
    "SMW": "Special Marine Warning", "EQW": "Earthquake Warning", "CDW": "Civil Danger Warning",
    "EVI": "Evacuation Immediate", "SPW": "Shelter in Place Warning", "LEW": "Law Enforcement",
    "CAE": "Child Abduction Emergency", "RWT": "Required Weekly Test", "RMT": "Required Monthly Test",
    "DMO": "Practice/Demo", "NPT": "National Periodic Test", "ADR": "Administrative Message",
    "EAN": "Emergency Action Notification", "NIC": "National Information Center",
}
# Events that are an actual emergency (spoken aloud), vs tests/admin.
URGENT = {"TOR", "SVR", "FFW", "FLW", "HUW", "EWW", "FRW", "EQW", "CDW", "EVI", "SPW",
          "LEW", "CAE", "EAN", "BZW", "SMW", "TRW"}

_SAME = re.compile(r"ZCZC-([A-Z]{3})-([A-Z]{3})-(.+?)\+(\d{4})-(\d{7})-([\w/ ]+?)-")


def parse_same(line):
    """Decode one SAME header line into a dict, or None."""
    m = _SAME.search(line)
    if not m:
        return None
    org, event, locs, purge, issue, station = m.groups()
    areas = [a for a in locs.split("-") if a.strip()]
    return {"org": org, "org_name": ORG.get(org, org), "event": event,
            "event_name": EVENT.get(event, event + " (unknown code)"),
            "areas": areas, "purge": purge, "issue": issue,
            "station": station.strip(), "urgent": event in URGENT}


def purge_minutes(purge):
    """+TTTT valid duration -> minutes (TT hours, TT minutes)."""
    try:
        return int(purge[:2]) * 60 + int(purge[2:])
    except (ValueError, TypeError):
        return None


class Alerts:
    def __init__(self, cap=100):
        self.items = []
        self.cap = cap
        self.on_alert = None            # callback(alert) — alert/speak hook

    def add(self, alert, now=None):
        if not alert:
            return None
        alert = dict(alert, t=time.time() if now is None else now)
        self.items.append(alert)
        del self.items[:-self.cap]
        if self.on_alert:
            self.on_alert(alert)
        return alert

    def recent(self):
        return list(reversed(self.items))


class Demo:
    LINES = [
        "EAS: ZCZC-WXR-TOR-020121-020127+0045-3181700-KICT/NWS-",
        "EAS: ZCZC-WXR-SVR-048201+0100-3181830-KFWS/NWS-",
        "EAS: ZCZC-WXR-RWT-048000+0015-3181200-KFWS/NWS-",
        "EAS: ZCZC-WXR-FFW-020013-020014+0300-3181900-KBOU/NWS-",
    ]

    def __init__(self):
        self.i = 0

    def lines(self):
        self.i += 1
        return [self.LINES[self.i % len(self.LINES)]]


def pipeline(freq, gain=0):
    g = " -g %d" % int(gain) if gain else ""
    mm = "multimon-ng -t raw -a EAS /dev/stdin"
    return "rtl_fm -f %s -M fm -s 22050%s -E dc - 2>/dev/null | %s" % (freq, g, mm)


DEFAULTS = {"freq": FREQ_DEFAULT, "gain": 0, "speak": True}


def main(parent=None):
    import queue
    import threading
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("NWR")
    s, spath = S.settings("nwr", DEFAULTS)
    root, F = S.make_root("Weather Radio", parent=parent)
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("nwr")
    demo = ("--demo" in sys.argv) or not (shutil.which("rtl_fm") and shutil.which("multimon-ng"))
    q = queue.Queue()
    alerts = Alerts()
    st = {"on": False, "gen": 0}

    def on_alert(a):
        slog.event("nwr", "%s %s" % (a["event"], ",".join(a["areas"])), id=a["event"])
        if a.get("urgent") and s.get("speak", True):
            try:
                S.notify("Weather alert", a["event_name"])
            except Exception:
                pass
    alerts.on_alert = on_alert

    top = S.top_bar(root, F, "Weather Radio", "NWR SAME / EAS · receive-only")
    state_pill = S.pill(top, F, "Off")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    txt = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="word", state="disabled", padx=T.px(12), pady=T.px(8))
    txt.tag_config("urgent", foreground=S.RED)
    txt.tag_config("event", foreground=S.AMBER)
    txt.tag_config("meta", foreground=T.TXT_3)
    txt.pack(fill="both", expand=True)

    def render():
        txt.config(state="normal")
        txt.delete("1.0", "end")
        for a in alerts.recent():
            mins = purge_minutes(a["purge"])
            txt.insert("end", a["event_name"] + "\n", "urgent" if a["urgent"] else "event")
            txt.insert("end", "   %s · areas %s · valid %s · %s\n" % (
                a["org_name"], ", ".join(a["areas"]),
                ("%d min" % mins) if mins is not None else "?", a["station"]), "meta")
            txt.insert("end", "   %s\n\n" % time.strftime("%H:%M:%S", time.localtime(a["t"])), "meta")
        if not alerts.items:
            txt.insert("end", "Listening for SAME alerts…\n" if st["on"] else "Press Listen.\n",
                       "meta")
        txt.config(state="disabled")

    def worker(gen):
        if demo:
            dm = Demo()
            while st["on"] and st["gen"] == gen:
                for ln in dm.lines():
                    q.put(ln)
                time.sleep(2.0)
            return
        with S.errfile(os.path.join(S.CACHE, "nwr.err")) as err:
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
            for _ in range(200):
                if alerts.add(parse_same(q.get_nowait())):
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
