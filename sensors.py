#!/usr/bin/env python3
"""Sensors - everything broadcasting in the clear on the ISM bands, decoded by rtl_433
on the built-in RTL: neighborhood weather stations, tire-pressure sensors, soil probes,
door/temp sensors. Receive-only; these are unencrypted public broadcasts.

--demo synthesizes a few sensors so the display can be exercised without hardware;
it is also the automatic fallback when rtl_433 is not installed.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import queue

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import suite as S   # noqa: E402

BANDS = [("433 MHz", "433.92M"), ("915 MHz", "915M"), ("315 MHz", "315M"), ("Hop all", "hop")]
HOP_FREQS = ("433.92M", "315M", "915M")     # weather/door sensors, US car TPMS, 900 MHz ISM
HOP_SECS = 20
DEFAULTS = {"band": "433 MHz", "gain": 0}   # gain 0 = rtl_433 auto

# fields worth showing, in display order: key -> (label, format fn)
def _temp(v):
    return "%.1f°F  (%.1f°C)" % (v * 9 / 5 + 32, v)


def _psi(kpa):
    return "%.1f psi" % (kpa * 0.145038)


FIELDS = [
    ("temperature_C", "Temp", _temp),
    ("humidity", "Humidity", lambda v: "%d %%" % v),
    ("pressure_kPa", "Pressure", _psi),
    ("wind_avg_km_h", "Wind", lambda v: "%.1f mph" % (v * 0.621371)),
    ("wind_dir_deg", "Wind dir", lambda v: "%03d°" % v),
    ("rain_mm", "Rain total", lambda v: "%.2f in" % (v / 25.4)),
    ("moisture", "Moisture", lambda v: "%s %%" % v),
    ("battery_ok", "Battery", lambda v: "ok" if v else "LOW"),
    ("rssi", "RSSI", lambda v: "%.1f dB" % v),
    ("snr", "SNR", lambda v: "%.1f dB" % v),
    ("channel", "Channel", str),
    ("type", "Type", str),
]


def rtl433_cmd(freq, gain):
    # -C si: rtl_433 otherwise reports each decoder's native units (temperature_F,
    # pressure_PSI, wind_avg_mi_h, rain_in), which FIELDS / primary_reading don't read
    if freq == "hop":       # rtl_433 cycles the bands itself, HOP_SECS on each
        fq = [a for f in HOP_FREQS for a in ("-f", f)] + ["-H", str(HOP_SECS)]
    else:
        fq = ["-f", freq]
    cmd = ["rtl_433"] + fq + ["-F", "json", "-M", "level", "-C", "si"]
    if gain:
        cmd += ["-g", str(int(gain))]
    return cmd


def parse_report(line):
    """One rtl_433 JSON line -> (device_key, title, fields) or None."""
    try:
        r = json.loads(line)
    except ValueError:
        return None
    if not isinstance(r, dict) or "model" not in r:
        return None
    model = str(r.get("model"))
    ident = r.get("id")
    key = "%s/%s" % (model, ident if ident is not None else "?")
    title = model if ident is None else "%s  #%s" % (model, ident)
    return key, title, r


def primary_reading(r):
    """The one number to headline for a device."""
    if isinstance(r.get("temperature_C"), (int, float)):
        return "%.1f°F" % (r["temperature_C"] * 9 / 5 + 32)
    if isinstance(r.get("pressure_kPa"), (int, float)):
        return "%.1f psi" % (r["pressure_kPa"] * 0.145038)
    if isinstance(r.get("humidity"), (int, float)):
        return "%d%%" % r["humidity"]
    if isinstance(r.get("moisture"), (int, float)):
        return "%s%%" % r["moisture"]
    return r.get("event") or r.get("code") or "signal"


DEMO_SENSORS = [
    ("Acurite-5n1", 2847, {"temperature_C": 11.0, "humidity": 38, "wind_avg_km_h": 9.0,
                           "wind_dir_deg": 310, "rain_mm": 231.4, "battery_ok": 1}, 8),
    ("LaCrosse-TX141THBv2", 101, {"temperature_C": 21.3, "humidity": 44,
                                  "battery_ok": 1, "channel": "1"}, 12),
    ("Schrader", "0A7F31", {"type": "TPMS", "pressure_kPa": 232.0,
                            "temperature_C": 18.0}, 20),
    ("Oregon-THGR122N", 59, {"temperature_C": 3.2, "humidity": 71, "battery_ok": 0,
                             "channel": "2"}, 15),
    ("Fineoffset-WH51", 771, {"moisture": 23, "battery_ok": 1}, 25),
]


def demo_report(t0):
    """One synthetic rtl_433 JSON line, from whichever demo sensor is 'due'."""
    now = time.time()
    model, ident, base, period = random.choice(
        [d for d in DEMO_SENSORS if int(now - t0) % d[3] < 2] or DEMO_SENSORS)
    r = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "model": model, "id": ident,
         "rssi": -8 - random.random() * 14, "snr": 12 + random.random() * 10}
    for k, v in base.items():
        if isinstance(v, (int, float)) and k not in ("battery_ok", "wind_dir_deg"):
            drift = {"temperature_C": 0.6, "humidity": 2, "pressure_kPa": 3,
                     "wind_avg_km_h": 3, "moisture": 1, "rain_mm": 0.0}.get(k, 0)
            v = round(v + random.uniform(-drift, drift), 1)
        r[k] = v
    return json.dumps(r)


def prune_devices(devices, sel, cap=400):
    """Noise on the ISM bands decodes into phantom device IDs; without a cap the
    registry grows forever. Evict the oldest entries, never the selected one."""
    if len(devices) <= cap:
        return
    for k in sorted(devices, key=lambda k2: devices[k2]["t"])[:len(devices) - cap + 50]:
        if k != sel:
            devices.pop(k, None)


def main():
    S.single_instance("Sensors")
    s, spath = S.settings("sensors", DEFAULTS)
    if s.get("band") not in [b[0] for b in BANDS]:
        s["band"] = DEFAULTS["band"]
    root, F = S.make_root("Sensors")
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("sensors")
    lease = S.RtlLease("Sensors", log=lambda m: None)
    lease.on_preempt = lambda: stop()   # another workspace wants the radio
    demo = "--demo" in sys.argv or not shutil.which("rtl_433")

    devices = {}   # key -> {"title", "last": report, "t", "n", "hist": [(t, temp_C)]}
    st = {"on": False, "proc": None, "sel": None, "band": s["band"]}
    q = queue.Queue()

    top = S.top_bar(root, F, "Sensors", "demo" if demo else "Built-in SDR · rtl_433")
    state_pill = S.pill(top, F, "Stopped")
    count_pill = S.pill(top, F, "0 devices")

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    listwrap = tk.Frame(body, bg=T.SURFACE, width=T.px(420))
    listwrap.pack(side="left", fill="y")
    listwrap.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    lpad = tk.Frame(listwrap, bg=T.SURFACE)
    lpad.pack(fill="both", expand=True, padx=T.px(12), pady=T.px(10))
    T.section(lpad, F, "Heard").pack(fill="x")
    rows_box = tk.Frame(lpad, bg=T.SURFACE)
    rows_box.pack(fill="both", expand=True, pady=(T.px(4), 0))
    hint = tk.Label(lpad, text="press Listen to start", font=F["sm"], fg=S.MUTED,
                    bg=T.SURFACE, anchor="w", wraplength=T.px(390), justify="left")
    hint.pack(fill="x")

    detail = tk.Frame(body, bg=S.BG)
    detail.pack(side="left", fill="both", expand=True)
    dpad = tk.Frame(detail, bg=S.BG)
    dpad.pack(fill="both", expand=True, padx=T.px(18), pady=T.px(12))
    d_title = tk.Label(dpad, text="—", font=F["now"], fg=S.TXT, bg=S.BG, anchor="w")
    d_title.pack(fill="x")
    d_big = tk.Label(dpad, text="", font=F["now"], fg=S.AMBER, bg=S.BG, anchor="w")
    d_big.pack(fill="x")
    d_sub = tk.Label(dpad, text="", font=F["sm"], fg=S.MUTED, bg=S.BG, anchor="w")
    d_sub.pack(fill="x", pady=(0, T.px(6)))
    spark = tk.Canvas(dpad, bg=T.night("#10151a"), highlightthickness=0, height=T.px(110))
    spark.pack(fill="x", pady=(0, T.px(8)))
    d_grid = tk.Frame(dpad, bg=S.BG)
    d_grid.pack(fill="x")

    def draw_spark(hist):
        spark.delete("all")
        w, h = spark.winfo_width(), T.px(110)
        if w < 40:
            return
        pts = [(t, v) for t, v in hist if isinstance(v, (int, float))]
        if len(pts) < 2:
            spark.create_text(w / 2, h / 2, text="temperature history builds here",
                              fill=S.MUTED, font=F["sm"])
            return
        t0, t1 = pts[0][0], pts[-1][0]
        vs = [v for _, v in pts]
        lo, hi = min(vs), max(vs)
        if hi - lo < 0.5:
            lo, hi = lo - 0.5, hi + 0.5
        line = []
        for t, v in pts:
            x = 6 + (t - t0) / max(1, t1 - t0) * (w - 12)
            y = h - 8 - (v - lo) / (hi - lo) * (h - 20)
            line += [x, y]
        spark.create_line(*line, fill=T.ACCENT, width=1.5)
        spark.create_text(6, 4, anchor="nw", text="%.1f°F" % (hi * 9 / 5 + 32),
                          fill=T.TXT_3, font=F["map"])
        spark.create_text(6, h - 4, anchor="sw", text="%.1f°F" % (lo * 9 / 5 + 32),
                          fill=T.TXT_3, font=F["map"])

    def show_detail():
        for wdg in d_grid.winfo_children():
            wdg.destroy()
        d = devices.get(st["sel"])
        if not d:
            d_title.config(text="—")
            d_big.config(text="")
            d_sub.config(text="select a device on the left")
            spark.delete("all")
            return
        r = d["last"]
        d_title.config(text=d["title"])
        d_big.config(text=primary_reading(r))
        d_sub.config(text="%d reports  ·  last %ds ago" % (d["n"], int(time.time() - d["t"])))
        rr = 0
        for k, label, fmt in FIELDS:
            v = r.get(k)
            if v is None:
                continue
            try:
                txt = fmt(v)
            except (TypeError, ValueError):
                txt = str(v)
            cell = tk.Frame(d_grid, bg=S.BG)
            cell.grid(row=rr // 2, column=rr % 2, sticky="w", padx=(0, T.px(24)), pady=1)
            tk.Label(cell, text=label, font=F["map"], fg=T.TXT_3, bg=S.BG, width=11,
                     anchor="w").pack(side="left")
            tk.Label(cell, text=txt, font=F["mono"],
                     fg=S.RED if (k == "battery_ok" and not v) else S.TXT,
                     bg=S.BG, anchor="w").pack(side="left")
            rr += 1
        draw_spark(d["hist"])

    def rebuild_list():
        for wdg in rows_box.winfo_children():
            wdg.destroy()
        now = time.time()
        order = sorted(devices.items(), key=lambda kv: -kv[1]["t"])
        for key, d in order[:14]:
            fg = S.AMBER if key == st["sel"] else T.TXT_2
            age = int(now - d["t"])
            r = tk.Label(rows_box, text="%-26s %8s %4ds" % (d["title"][:26],
                         primary_reading(d["last"])[:8], age),
                         font=F["mono"], fg=fg, bg=T.SURFACE, anchor="w", cursor="hand2")
            r.pack(fill="x", pady=1)
            r.bind("<Button-1>", lambda e, kk=key: (st.update(sel=kk), rebuild_list(),
                                                    show_detail()))
        count_pill.config(text="%d devices" % len(devices),
                          bg=S.GREEN if devices else S.DIM)

    # ---- radio worker ---------------------------------------------------------
    def worker(band_freq, gen):
        # gen: set_band() does stop()+start() at once, so st["on"] alone can't tell this
        # (old) worker that it has been replaced
        if demo:
            t0 = time.time()
            while st["on"] and st.get("gen") == gen:
                q.put(("line", demo_report(t0)))
                time.sleep(1.2)
            return
        err_path = os.path.join(S.CACHE, "sensors.err")
        with S.errfile(err_path) as err:
            p = S.spawn(rtl433_cmd(band_freq, s["gain"]), stdout=subprocess.PIPE,
                        stderr=err, text=True, errors="replace")
        if st.get("gen") == gen:
            st["proc"] = p
        try:
            for line in p.stdout:
                if not st["on"] or st.get("gen") != gen:
                    break
                q.put(("line", line))
        finally:
            S.stop_group(p, grace=1.5)
            if st["on"] and st.get("gen") == gen:
                q.put(("died", None))

    def start():
        if st["on"] or st.get("starting"):
            return
        if demo or st.get("held"):
            begin()
            return
        # take the dongle from the plane map off the UI thread (stopping readsb can be slow)
        st["starting"] = True
        state_pill.config(text="Starting", bg=S.AMBER)
        hint.config(text="Taking the SDR from the plane map…", fg=S.MUTED)

        def done(ok, err):
            if not st.get("starting"):
                return          # Stop was pressed meanwhile; its release is queued after us
            st["starting"] = False
            if not ok:
                state_pill.config(text="Stopped", bg=S.DIM)
                hint.config(text="SDR busy: %s" % str(err)[:70], fg=S.RED)
                return
            st["held"] = True
            begin()
        S.acquire_bg(root, lease, done)

    def begin():
        st["gen"] = st.get("gen", 0) + 1
        st["on"] = True
        freq = dict(BANDS)[st["band"]]
        state_pill.config(text="Listening", bg=S.GREEN)
        hint.config(text="listening on %s - unencrypted broadcasts only, receive-only"
                    % (st["band"] if freq != "hop" else
                       "433 / 315 / 915 MHz in turn, %d s each" % HOP_SECS), fg=S.MUTED)
        threading.Thread(target=worker, args=(freq, st["gen"]), daemon=True).start()

    def stop(release=True, sync=False):
        was_starting, st["starting"] = st.get("starting"), False
        st["on"] = False
        st["gen"] = st.get("gen", 0) + 1
        p = st["proc"]
        st["proc"] = None
        if p:
            # wait for rtl_433 to let go of the dongle before readsb (release) or the next
            # band's rtl_433 tries to claim it
            S.stop_group(p, grace=1.5)
        if not demo and release and (st.get("held") or was_starting):
            st["held"] = False
            if sync:
                S.release_now(lease)     # quitting: a background release could die with us
            else:
                S.release_bg(root, lease)
        state_pill.config(text="Stopped", bg=S.DIM)
        hint.config(text="stopped", fg=S.MUTED)

    def toggle(_=None):
        stop() if (st["on"] or st.get("starting")) else start()

    def set_band(name):
        st["band"] = s["band"] = name
        S.save_json(spath, s)
        for nm, b in band_btns.items():
            T.set_btn(b, kind="primary" if nm == name else "ghost")
        if st["on"]:
            stop(release=False)      # keep the radio: only rtl_433 restarts, readsb stays paused
            start()

    # ---- bottom bar
    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Listen", toggle, F, padx=14, pady=5, kind="primary").pack(side="left",
                                                                          padx=(10, 8), pady=6)
    band_btns = {}
    for name, _f in BANDS:
        b = S.btn(bar, name, lambda n=name: set_band(n), F, font="map", padx=6, pady=3,
                  kind="primary" if name == st["band"] else "ghost")
        b.pack(side="left", padx=1)
        band_btns[name] = b
    S.btn(bar, "Clear", lambda: (devices.clear(), st.update(sel=None), rebuild_list(),
                                 show_detail()), F, padx=8, pady=5,
          kind="ghost").pack(side="left", padx=8)
    S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5,
          kind="quiet").pack(side="right", padx=(2, 10))
    root.bind("<space>", toggle)

    def pump():
        changed = False
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "line":
                    rep = parse_report(payload)
                    if not rep:
                        continue
                    key, title, r = rep
                    d = devices.setdefault(key, {"title": title, "last": r,
                                                 "t": time.time(), "n": 0, "hist": []})
                    d["last"], d["t"] = r, time.time()
                    d["n"] += 1
                    if d["n"] == 1:
                        slog.event("sensors", "new device: %s" % title, id=key)
                    if isinstance(r.get("temperature_C"), (int, float)):
                        d["hist"].append((time.time(), r["temperature_C"]))
                        del d["hist"][:-240]
                    if st["sel"] is None:
                        st["sel"] = key
                    prune_devices(devices, st["sel"])
                    changed = True
                elif kind == "died":
                    hint.config(text="rtl_433 exited - see sensors.err "
                                     "(SDR unplugged or busy?)", fg=S.RED)
                    stop()
        except queue.Empty:
            pass
        if changed:
            rebuild_list()
            show_detail()
            if not demo and time.time() - st.get("cache_t", 0) > 15:
                # a small summary other workspaces (Overwatch, Home) can read
                st["cache_t"] = time.time()
                try:
                    S.save_json(os.path.join(S.CACHE, "sensors.json"),
                                {"t": time.time(), "n": len(devices),
                                 "devices": [{"title": d["title"], "t": d["t"]}
                                             for d in list(devices.values())[-40:]]})
                except OSError:
                    pass
        root.after(400, pump)

    def on_close():
        stop(sync=True)
        root.destroy()

    S.bind_quit(root, on_close)
    rebuild_list()
    show_detail()
    if "--listen" in sys.argv or demo:
        root.after(400, start)
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
