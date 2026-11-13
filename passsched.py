#!/usr/bin/env python3
"""passsched.py — satellite pass scheduler (Phase 7 #3).

Predicts upcoming passes (NOAA APT, Meteor LRPT, ISS SSTV, GOES, amateur sats) via wxsat's
skyfield propagator, picks which to capture given one radio (classic interval scheduling to
maximise unattended captures), and routes each to the right decoder. The prediction is wxsat's;
the scheduling/decoder-routing logic here is pure and unit-testable.
"""
import os
import sys


def assign_decoder(sat_name):
    """Which decoder captures this satellite."""
    n = str(sat_name).upper()
    if "NOAA" in n:
        return "noaa-apt"
    if "METEOR" in n:
        return "satdump"
    if "GOES" in n:
        return "satdump"
    if "ISS" in n:
        return "sstv"
    return None


def schedule(passes, min_elev=20.0, radio_free_at=0.0):
    """Choose a non-overlapping set of passes for one radio, maximising the number captured.

    passes: [{sat, aos, los, max_elev, freq_mhz}] (aos/los are unix seconds). Filters by
    max_elev >= min_elev, then greedily picks by earliest LOS (optimal interval scheduling).
    Returns the chosen passes in time order, each annotated with its decoder."""
    good = sorted((p for p in passes if p.get("max_elev", 0) >= min_elev),
                  key=lambda p: p["los"])
    chosen, busy = [], radio_free_at
    for p in good:
        if p["aos"] >= busy:
            q = dict(p, decoder=assign_decoder(p["sat"]))
            chosen.append(q)
            busy = p["los"]
    return sorted(chosen, key=lambda p: p["aos"])


def conflicts(passes, min_elev=20.0):
    """Passes that pass the elevation filter but were dropped by scheduling (radio busy)."""
    kept = {(p["sat"], p["aos"]) for p in schedule(passes, min_elev)}
    return [p for p in passes if p.get("max_elev", 0) >= min_elev
            and (p["sat"], p["aos"]) not in kept]


def next_pass(passes, now):
    future = [p for p in passes if p["los"] > now]
    return min(future, key=lambda p: p["aos"]) if future else None


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    import time
    if parent is None:
        S.single_instance("PassSched")
    s, spath = S.settings("passsched", {"min_elev": 20})
    root, F = S.make_root("Pass Scheduler", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Pass Scheduler", "Upcoming satellite passes · auto-capture")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    txt = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="word", state="disabled", padx=T.px(12), pady=T.px(8))
    txt.tag_config("sat", foreground=S.AMBER)
    txt.pack(fill="both", expand=True)

    def load():
        passes = []
        try:
            import wxsat
            home = (S.settings("wxsat", getattr(wxsat, "DEFAULTS", {}))[0].get("home")
                    or {"lat": 39.6, "lon": -104.9})
            # wxsat.predict returns pass dicts; shape may vary, so adapt defensively
            raw = wxsat.predict(getattr(wxsat, "SATS", []), (home["lat"], home["lon"]), 24)
            for p in raw or []:
                passes.append({"sat": p.get("sat", "?"), "aos": p.get("aos", 0),
                               "los": p.get("los", 0), "max_elev": p.get("max", 0),
                               "freq_mhz": p.get("freq", 0)})
        except Exception:
            passes = []
        chosen = schedule(passes, s.get("min_elev", 20))
        txt.config(state="normal")
        txt.delete("1.0", "end")
        if not chosen:
            txt.insert("end", "No scheduled passes (needs wxsat TLEs / network).\n")
        for p in chosen:
            txt.insert("end", "%s  " % p["sat"], "sat")
            txt.insert("end", "%s  max %.0f°  %s  → %s\n" % (
                time.strftime("%a %H:%M", time.localtime(p["aos"])), p["max_elev"],
                "%.3f MHz" % p["freq_mhz"] if p["freq_mhz"] else "", p.get("decoder") or "?"))
        txt.config(state="disabled")

    load()
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
