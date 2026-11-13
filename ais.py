#!/usr/bin/env python3
"""AIS — maritime vessel tracker (Phase 4 #7). Receive-only.

Ships broadcast position (AIS types 1/2/3) and identity/voyage (type 5) on 161.975 / 162.025 MHz.
rtl_ais demodulates both channels and emits NMEA AIVDM sentences; this module decodes them into a
vessel table + map markers, keyed by MMSI (a clean handle for the fusion engine). Nothing is TX'd.

The AIVDM bit-field offsets and the 6-bit de-armoring/charset are taken from the gpsd AIVDM guide
(verified, incl. the worked example MMSI 477553000) — not guessed. Pure helpers are unit-testable.
"""
import os
import sys
import time

# Navigation status (types 1-3), abbreviated.
NAV_STATUS = {0: "under way", 1: "anchored", 2: "not under command", 3: "restricted mnv",
              4: "constrained", 5: "moored", 6: "aground", 7: "fishing", 8: "sailing",
              15: "undefined"}
# Ship type (type 5), coarse buckets by tens digit.
SHIP_TYPE = {2: "WIG", 3: "special", 4: "high-speed", 5: "special", 6: "passenger",
             7: "cargo", 8: "tanker", 9: "other"}


def unarmor(payload):
    """AIVDM 6-bit ASCII payload -> bit string (MSB first per char)."""
    bits = []
    for c in payload:
        v = ord(c) - 48
        if v > 40:
            v -= 8
        if 0 <= v <= 63:
            bits.append(format(v, "06b"))
    return "".join(bits)


def _u(bits, start, length):
    seg = bits[start:start + length]
    return int(seg, 2) if seg else 0


def _i(bits, start, length):
    v = _u(bits, start, length)
    if len(bits[start:start + length]) == length and v >= (1 << (length - 1)):
        v -= (1 << length)
    return v


def _text6(bits, start, nchars):
    out = []
    for i in range(nchars):
        seg = bits[start + i * 6:start + i * 6 + 6]
        if len(seg) < 6:
            break
        v = int(seg, 2)
        out.append(chr(v + 64) if v < 32 else chr(v))     # 0-31 -> @.._ ; 32-63 -> space..?
    return "".join(out).split("@", 1)[0].rstrip().strip()


def decode_bits(bits):
    """Decode an AIVDM bit string into a message dict (types 1/2/3 and 5; others -> {type,mmsi})."""
    if len(bits) < 38:
        return None
    mtype = _u(bits, 0, 6)
    out = {"type": mtype, "mmsi": _u(bits, 8, 30)}
    if mtype in (1, 2, 3):
        sog = _u(bits, 50, 10)
        lon = _i(bits, 61, 28)
        lat = _i(bits, 89, 27)
        cog = _u(bits, 116, 12)
        hdg = _u(bits, 128, 9)
        status = _u(bits, 38, 4)
        out.update({"status": status, "status_name": NAV_STATUS.get(status, "?"),
                    "sog_kt": None if sog == 1023 else sog / 10.0,
                    "lon": None if lon == 181 * 600000 else lon / 600000.0,
                    "lat": None if lat == 91 * 600000 else lat / 600000.0,
                    "cog_deg": None if cog == 3600 else cog / 10.0,
                    "heading_deg": None if hdg == 511 else hdg})
    elif mtype == 5:
        out.update({"imo": _u(bits, 40, 30), "callsign": _text6(bits, 70, 7),
                    "name": _text6(bits, 112, 20),
                    "ship_type": _u(bits, 232, 8),
                    "ship_type_name": SHIP_TYPE.get(_u(bits, 232, 8) // 10, "?"),
                    "destination": _text6(bits, 302, 20)})
    return out


def decode_sentence(line):
    """Decode a single-fragment !AIVDM/!AIVDO sentence. Returns a message dict, or None (for a
    multi-fragment sentence, assemble the payloads first with AivdmAssembler)."""
    if "AIVD" not in line:
        return None
    body = line.split("!", 1)[-1].split("*", 1)[0]
    f = body.split(",")
    if len(f) < 6:
        return None
    try:
        count = int(f[1])
    except ValueError:
        return None
    if count != 1:
        return None
    return decode_bits(unarmor(f[5]))


class AivdmAssembler:
    """Reassembles multi-fragment AIVDM sentences (e.g. type 5) keyed by sequence id."""

    def __init__(self):
        self.parts = {}

    def feed(self, line):
        if "AIVD" not in line:
            return None
        body = line.split("!", 1)[-1].split("*", 1)[0]
        f = body.split(",")
        if len(f) < 6:
            return None
        try:
            count, idx = int(f[1]), int(f[2])
        except ValueError:
            return None
        payload, seq = f[5], f[3]
        if count == 1:
            return decode_bits(unarmor(payload))
        key = seq or "_"
        slot = self.parts.setdefault(key, {})
        slot[idx] = payload
        if len(slot) == count:
            full = "".join(slot[i] for i in sorted(slot))
            del self.parts[key]
            return decode_bits(unarmor(full))
        return None


class Vessels:
    """Per-MMSI vessel state, merging position (1/2/3) and identity (5)."""

    def __init__(self, stale_s=600, trail_max=100):
        self.by_mmsi = {}
        self.stale_s = stale_s
        self.trail_max = trail_max
        self.on_new = None

    def ingest(self, msg, now=None):
        if not msg or not msg.get("mmsi"):
            return False
        now = time.time() if now is None else now
        is_new = msg["mmsi"] not in self.by_mmsi
        v = self.by_mmsi.get(msg["mmsi"])
        if v is None:
            v = {"mmsi": msg["mmsi"], "first": now, "trail": [], "name": None,
                 "callsign": None, "lat": None, "lon": None}
            self.by_mmsi[msg["mmsi"]] = v
        if msg["type"] in (1, 2, 3):
            for k in ("lat", "lon", "sog_kt", "cog_deg", "heading_deg", "status_name"):
                if msg.get(k) is not None:
                    v[k] = msg[k]
            if msg.get("lat") is not None and msg.get("lon") is not None:
                v["trail"].append((msg["lat"], msg["lon"], now))
                del v["trail"][:-self.trail_max]
        elif msg["type"] == 5:
            for k in ("name", "callsign", "destination", "ship_type_name", "imo"):
                if msg.get(k):
                    v[k] = msg[k]
        v["last"] = now
        if is_new and self.on_new:
            self.on_new(v)
        return is_new

    def active(self, now=None):
        now = time.time() if now is None else now
        return [v for v in self.by_mmsi.values() if now - v["last"] <= self.stale_s]

    def prune(self, now=None):
        now = time.time() if now is None else now
        for m in [m for m, v in self.by_mmsi.items() if now - v["last"] > self.stale_s]:
            del self.by_mmsi[m]

    def label(self, v):
        return v.get("name") or str(v["mmsi"])

    def fusion_contact(self, v):
        return {"source": "ais", "id": self.label(v), "mmsi": v["mmsi"], "type": "vessel",
                "lat": v.get("lat"), "lon": v.get("lon"), "speed_mps": (v.get("sog_kt") or 0) * 0.514,
                "heading_deg": v.get("cog_deg"), "callsign": v.get("callsign"),
                "timestamp": v.get("last")}


class Demo:
    """Synthetic AIVDM: a couple of vessels moving, plus a static (type 5) name sentence."""
    SENTENCES = [
        "!AIVDM,1,1,,B,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C",      # real type-1, MMSI 477553000
        "!AIVDM,1,1,,A,15MwkT1P1lG?S:0Hm2Q6W0000@;5,0*0A",
        "!AIVDM,1,1,,B,B6CdCm0t3`tba35f@V9faHi7kP06,0*58",
    ]

    def __init__(self):
        self.i = 0

    def lines(self):
        self.i += 1
        return [self.SENTENCES[self.i % len(self.SENTENCES)]]


def pipeline(gain=0):
    g = " -g %d" % int(gain) if gain else ""
    return "rtl_ais -n%s 2>/dev/null" % g        # prints AIVDM sentences to stdout


DEFAULTS = {"home": {"lat": 47.6, "lon": -122.33}, "range_nm": 20.0, "gain": 0}


def main(parent=None):
    import queue
    import threading
    import shutil
    import math
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    import skyintel as SI
    if parent is None:
        S.single_instance("AIS")
    s, spath = S.settings("ais", DEFAULTS)
    root, F = S.make_root("AIS", parent=parent)
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("ais")
    demo = ("--demo" in sys.argv) or not shutil.which("rtl_ais")
    q = queue.Queue()
    vessels = Vessels()
    asm = AivdmAssembler()
    home = dict(s.get("home") or DEFAULTS["home"])
    st = {"on": False, "gen": 0, "sel": None}
    vessels.on_new = lambda v: slog.event("ais", "Vessel %s" % vessels.label(v), id=str(v["mmsi"]))

    top = S.top_bar(root, F, "AIS", "Ships · 161.975/162.025 MHz · receive-only")
    state_pill = S.pill(top, F, "Off")
    bodyf = tk.Frame(root, bg=S.BG)
    bodyf.pack(fill="both", expand=True)
    left = tk.Frame(bodyf, bg=T.SURFACE, width=T.px(430))
    left.pack(side="left", fill="y")
    left.pack_propagate(False)
    lst = tk.Text(left, bg=T.SURFACE, fg=T.TXT_2, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="none", state="disabled", padx=T.px(10), pady=T.px(8))
    lst.tag_config("hdr", foreground=T.TXT_3)
    lst.pack(fill="both", expand=True)
    tk.Frame(bodyf, bg=S.LINE, width=1).pack(side="left", fill="y")
    right = tk.Frame(bodyf, bg=S.MAPBG)
    right.pack(side="left", fill="both", expand=True)
    mapcv = tk.Canvas(right, bg=S.MAPBG, highlightthickness=0)
    mapcv.pack(fill="both", expand=True)

    def draw_map():
        cv = mapcv
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50:
            return
        nm_r = float(s.get("range_nm") or 20)
        k = (min(w, h) / 2 - 20) / nm_r
        cx, cy = w / 2, h / 2

        def xy(lat, lon):
            d = SI.dist_nm(home["lat"], home["lon"], lat, lon)
            b = math.radians(SI.bearing_deg(home["lat"], home["lon"], lat, lon))
            return cx + d * k * math.sin(b), cy - d * k * math.cos(b)
        for ring in (nm_r / 2, nm_r):
            r = ring * k
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=T.night("#1f2a31"))
        cv.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3, fill=S.GREEN, outline="")
        now = time.time()
        for v in vessels.active(now):
            if v.get("lat") is None:
                continue
            x, y = xy(v["lat"], v["lon"])
            col = T.night("#5ec4d4")
            cv.create_text(x, y, text="▸", fill=col, font=F["now"])
            cv.create_text(x + 8, y, text=vessels.label(v), anchor="w", fill=col, font=F["map"])

    def render():
        now = time.time()
        lst.config(state="normal")
        lst.delete("1.0", "end")
        lst.insert("end", "%-16s %6s %5s\n" % ("VESSEL", "nm", "kt"), "hdr")
        for v in sorted(vessels.active(now), key=lambda v: -v["last"]):
            d = "—"
            if v.get("lat") is not None:
                d = "%.1f" % SI.dist_nm(home["lat"], home["lon"], v["lat"], v["lon"])
            lst.insert("end", "%-16s %6s %5s\n" % (vessels.label(v)[:16], d,
                       "—" if v.get("sog_kt") is None else "%.0f" % v["sog_kt"]))
        lst.config(state="disabled")
        draw_map()
    mapcv.bind("<Configure>", lambda e: draw_map())

    def worker(gen):
        if demo:
            dm = Demo()
            while st["on"] and st["gen"] == gen:
                for ln in dm.lines():
                    q.put(ln)
                time.sleep(1.0)
            return
        with S.errfile(os.path.join(S.CACHE, "ais.err")) as err:
            p = S.spawn(pipeline(s.get("gain", 0)), shell=True,
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
                msg = asm.feed(q.get_nowait())
                if msg and vessels.ingest(msg):
                    changed = True
                elif msg:
                    changed = True
        except queue.Empty:
            pass
        if changed:
            render()
        root.after(500, pump)

    def tick():
        vessels.prune()
        render()
        root.after(5000, tick)

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
    root.after(5000, tick)
    if "--demo" in sys.argv:
        root.after(300, start)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
