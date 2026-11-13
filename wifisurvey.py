#!/usr/bin/env python3
"""wifisurvey.py — passive 802.11 survey (Phase 6 #9). PASSIVE ONLY.

Parses `iw dev <iface> scan` into an access-point table (BSSID, SSID, channel, signal, security)
and summarises channel utilization. Passive: it lists what the Wi-Fi adapter already hears. No
deauth, no injection, no transmission beyond the normal scan the OS performs. Pure parser is
unit-testable; the Tk workspace shows the AP table + channel load.
"""
import os
import re
import sys
from collections import Counter

_BSS = re.compile(r"BSS ([0-9a-fA-F:]{17})")


def channel_from_freq(mhz):
    mhz = float(mhz)
    if 2412 <= mhz <= 2472:
        return int(round((mhz - 2407) / 5))
    if mhz == 2484:
        return 14
    if 5000 <= mhz <= 5900:
        return int(round((mhz - 5000) / 5))
    if 5955 <= mhz <= 7115:                       # 6 GHz (Wi-Fi 6E)
        return int(round((mhz - 5950) / 5))
    return None


def parse_iw_scan(text):
    """`iw ... scan` output -> list of AP dicts."""
    aps = []
    cur = None
    for line in (text or "").splitlines():
        m = _BSS.search(line)
        if m:
            if cur:
                aps.append(cur)
            cur = {"bssid": m.group(1).lower(), "ssid": "", "freq": None, "channel": None,
                   "signal": None, "security": "open"}
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("freq:"):
            try:
                cur["freq"] = float(s.split(":", 1)[1].strip())
                cur["channel"] = channel_from_freq(cur["freq"])
            except ValueError:
                pass
        elif s.startswith("signal:"):
            try:
                cur["signal"] = float(s.split(":", 1)[1].split()[0])
            except (ValueError, IndexError):
                pass
        elif s.startswith("SSID:"):
            cur["ssid"] = s[5:].strip()
        elif "RSN:" in s:
            cur["security"] = "WPA2/3"
        elif "WPA:" in s and cur["security"] == "open":
            cur["security"] = "WPA"
    if cur:
        aps.append(cur)
    return aps


def channel_utilization(aps):
    """AP count per channel (busiest first)."""
    c = Counter(a["channel"] for a in aps if a.get("channel") is not None)
    return dict(c.most_common())


def open_networks(aps):
    return [a for a in aps if a.get("security") == "open"]


def scan_argv(iface="wlan0"):
    return ["iw", "dev", iface, "scan"]


def main(parent=None):
    import shutil
    import subprocess
    import threading
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("WiFiSurvey")
    s, spath = S.settings("wifisurvey", {"iface": "wlan0"})
    root, F = S.make_root("Wi-Fi Survey", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Wi-Fi Survey", "Passive 802.11 scan · no deauth/inject")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    txt = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="none", state="disabled", padx=T.px(12), pady=T.px(8))
    txt.tag_config("ssid", foreground=S.AMBER)
    txt.tag_config("open", foreground=S.RED)
    txt.pack(fill="both", expand=True)

    scanning = {"on": False}

    def render(aps):
        txt.config(state="normal")
        txt.delete("1.0", "end")
        util = channel_utilization(aps)
        chans = ", ".join("ch%s×%d" % (k, v) for k, v in util.items())
        txt.insert("end", "Channels (busiest): %s\n\n" % (chans or "(none)"))  # fmt string is
        for a in sorted(aps, key=lambda a: -(a.get("signal") or -999)):        # always truthy, so
            txt.insert("end", "%-24s " % (a["ssid"] or "<hidden>"),            # the (none) default
                       "open" if a["security"] == "open" else "ssid")          # must be on `chans`
            txt.insert("end", "%s  ch%s  %s dBm  %s\n" % (
                a["bssid"], a.get("channel"), a.get("signal"), a["security"]))
        if not aps:
            txt.insert("end", "No scan (needs iw + a Wi-Fi adapter).\n")
        txt.config(state="disabled")

    def scan():
        # `iw scan` blocks for up to 15 s; run it off the shared Tk thread or the whole suite
        # freezes. Results are rendered back on the main thread via root.after.
        if scanning["on"]:
            return
        scanning["on"] = True

        def work():
            aps = []
            if shutil.which("iw"):
                try:
                    out = subprocess.run(scan_argv(s.get("iface", "wlan0")), capture_output=True,
                                         text=True, timeout=15).stdout
                    aps = parse_iw_scan(out)
                except (OSError, subprocess.TimeoutExpired):
                    aps = []

            def done():
                scanning["on"] = False
                try:
                    render(aps)
                except tk.TclError:
                    pass                 # workspace closed while the scan was running
            root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Scan", scan, F, padx=14, pady=5, kind="primary").pack(side="left", padx=(10, 6),
                                                                      pady=6)
    scan()
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
