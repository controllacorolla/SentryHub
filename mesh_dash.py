#!/usr/bin/env python3
"""
Meshtastic dashboard for the uConsole.

Connects to meshtasticd on this machine (TCP 127.0.0.1:4403 - the AIO board's LoRa
radio), or to a USB-serial Meshtastic node if no daemon is running.
Messages, node list with SNR / hops / battery / distance, and a node map.
"""

import json
import math
import os
import queue
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402

DEFAULTS = {"connect": "auto", "tcp_host": "127.0.0.1", "tcp_port": 4403, "serial_port": ""}
MSG_LOG = os.path.join(S.DATA, "mesh_messages.jsonl")


def dist_km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, h)))


def ago(t):
    if not t:
        return ""
    d = int(time.time() - t)
    return "%ds" % d if d < 60 else ("%dm" % (d // 60) if d < 3600 else
                                     ("%dh" % (d // 3600) if d < 86400 else "%dd" % (d // 86400)))


class FakeIface:
    """Simulated mesh for testing without a radio (SUITE_MESH_FAKE=1)."""

    def __init__(self, on_rx):
        self.on_rx = on_rx
        now = time.time()
        self.myInfo = type("I", (), {"my_node_num": 1})()
        mk = lambda num, sid, short, long_, lat, lon, snr, hops, batt, heard: {
            "num": num, "user": {"id": sid, "shortName": short, "longName": long_},
            "position": {"latitude": lat, "longitude": lon}, "snr": snr, "hopsAway": hops,
            "deviceMetrics": {"batteryLevel": batt, "voltage": 3.9}, "lastHeard": now - heard}
        self.nodes = {
            "!00000001": mk(1, "!00000001", "DLTN", "Dalton uConsole", 39.6205, -104.8701, None, 0, 82, 0),
            "!a1b2c3d4": mk(2, "!a1b2c3d4", "KAPA", "Centennial Roof", 39.5702, -104.8490, 6.25, 1, 100, 40),
            "!b2c3d4e5": mk(3, "!b2c3d4e5", "GLDN", "Golden Ridge Rptr", 39.7555, -105.2211, -4.5, 2, 64, 300),
            "!c3d4e5f6": mk(4, "!c3d4e5f6", "BIKE", "Trail bike node", 39.65, -104.95, 2.0, 1, 31, 1500),
            "!d4e5f6a7": mk(5, "!d4e5f6a7", "HMB", "Home base", 39.7392, -104.9903, -11.0, 3, 101, 7200),
        }
        self.localNode = type("L", (), {"channels": []})()

        def chatter():
            msgs = ["Anyone on the south mesh tonight?", "Copy, solid signal from Centennial",
                    "Testing new antenna on the bike node"]
            senders = ["!a1b2c3d4", "!b2c3d4e5", "!c3d4e5f6"]
            i = 0
            while True:
                time.sleep(4)
                self.on_rx({"fromId": senders[i % 3], "toId": "^all", "channel": 0,
                            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": msgs[i % 3]},
                            "rxSnr": 5.5 - i, "rxRssi": -95, "hopStart": 3, "hopLimit": 2})
                i += 1
        threading.Thread(target=chatter, daemon=True).start()

    def getMyNodeInfo(self):
        return self.nodes["!00000001"]

    def sendText(self, text, destinationId="^all", channelIndex=0, wantAck=False):
        return None

    def close(self):
        pass


def main():
    S.single_instance("Mesh")
    s, spath = S.settings("mesh", DEFAULTS)
    root, F = S.make_root("Mesh")
    import tkinter as tk

    events = queue.Queue()
    st = {"iface": None, "me": None, "sel": None, "status": "connecting", "detail": ""}

    # ---------------------------------------------------------- connection
    def on_receive(packet, interface=None):
        events.put(("rx", packet))

    def on_lost(interface=None):
        events.put(("lost", interface))

    def connect():
        events.put(("status", "connecting", ""))
        if os.environ.get("SUITE_MESH_FAKE"):
            st["iface"] = FakeIface(on_receive)
            events.put(("status", "connected", "simulated mesh"))
            return
        try:
            from pubsub import pub
            import meshtastic.tcp_interface
            import meshtastic.serial_interface
            import meshtastic.util
        except ImportError:
            events.put(("status", "error", "meshtastic Python package missing - re-run the installer"))
            return
        pub.subscribe(on_receive, "meshtastic.receive")
        pub.subscribe(on_lost, "meshtastic.connection.lost")
        mode = s.get("connect", "auto")
        tcp_ok = False
        if mode in ("auto", "tcp"):
            try:
                socket.create_connection((s["tcp_host"], int(s["tcp_port"])), timeout=2).close()
                tcp_ok = True
            except OSError:
                tcp_ok = False
        try:
            if tcp_ok:
                st["iface"] = meshtastic.tcp_interface.TCPInterface(
                    hostname=s["tcp_host"], portNumber=int(s["tcp_port"]), timeout=60)
                events.put(("status", "connected", "meshtasticd @ %s" % s["tcp_host"]))
                return
            if mode in ("auto", "serial"):
                port = s.get("serial_port") or None
                if not port:
                    ports = meshtastic.util.findPorts(True)
                    port = ports[0] if ports else None
                if port:
                    st["iface"] = meshtastic.serial_interface.SerialInterface(devPath=port, timeout=60)
                    events.put(("status", "connected", "USB " + port))
                    return
            events.put(("status", "error", "No Meshtastic radio found. Is meshtasticd running? "
                        "(sudo systemctl start meshtasticd)"))
        except Exception as e:
            events.put(("status", "error", "Connect failed: %s. Another app (web UI?) may hold "
                        "the connection." % str(e)[:120]))

    # ---------------------------------------------------------- UI
    top = S.top_bar(root, F, "Mesh", "Meshtastic")
    conn_pill = S.pill(top, F, "connecting")
    T = S.T
    me_lbl = tk.Label(top, text="", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE)
    me_lbl.pack(side="right", padx=20)

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)

    leftw = tk.Frame(body, bg=T.SURFACE, width=S.T.px(300))
    leftw.pack(side="left", fill="y")
    leftw.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y")
    left = tk.Frame(leftw, bg=T.SURFACE)
    left.pack(fill="both", expand=True, padx=14, pady=14)
    MESH_SCHEMA = [
        ("Radio connection", [
            {"key": "connect", "label": "Connect via", "type": "choice",
             "choices": [("auto", "Auto (TCP, then USB serial)"), ("tcp", "meshtasticd over TCP"),
                         ("serial", "USB serial radio")]},
            {"key": "tcp_host", "label": "meshtasticd host", "type": "str"},
            {"key": "tcp_port", "label": "meshtasticd port", "type": "int", "min": 1, "max": 65535},
            {"key": "serial_port", "label": "Serial port", "type": "str", "help": "blank = first found"},
        ]),
    ]

    def open_settings():
        import settings_ui

        def on_save(new):
            s.clear()
            s.update(new)
            S.save_json(spath, s)
            try:
                if st.get("iface"):
                    st["iface"].close()
            except Exception:
                pass
            st["iface"] = None
            S.in_thread(connect)
        settings_ui.open_settings(root, F, "Mesh settings", MESH_SCHEMA, s, on_save, path=spath)

    sec_nodes = T.section(left, F, "Nodes")
    T.btn(sec_nodes, "Settings", open_settings, F, padx=6, pady=0, kind="quiet").pack(side="right")
    sec_nodes.pack(fill="x", pady=(0, 8))
    nodes_txt = tk.Text(left, bg=T.SURFACE, fg=S.TXT, font=F["map"], bd=0, highlightthickness=0,
                        cursor="hand2", wrap="none", spacing1=6, spacing3=6)
    nodes_txt.pack(fill="both", expand=True)
    nodes_txt.tag_config("pick", background=T.ACCENT_BG, foreground=T.ACCENT)
    nodes_txt.tag_config("me", foreground=T.TXT_2)
    nodes_txt.tag_config("old", foreground=T.TXT_3)
    nodes_txt.tag_config("good", foreground=S.TXT)
    nodes_txt.tag_config("mid", foreground=S.TXT)
    nodes_txt.tag_config("bad", foreground=T.TXT_2)

    rightw = tk.Frame(body, bg=T.SURFACE, width=S.T.px(330))
    rightw.pack(side="right", fill="y")
    rightw.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="right", fill="y")

    mid = tk.Frame(body, bg=S.BG)
    mid.pack(side="left", fill="both", expand=True)
    cv = tk.Canvas(mid, bg=S.MAPBG, highlightthickness=0)
    cv.pack(fill="both", expand=True)
    tk.Frame(mid, bg=S.LINE, height=1).pack(fill="x")
    node_info = tk.Label(mid, text="Select a node for details", font=F["sm"], fg=T.TXT_3,
                         bg=T.SURFACE, anchor="w", padx=16, pady=7)
    node_info.pack(fill="x")

    right = tk.Frame(rightw, bg=T.SURFACE)
    right.pack(fill="both", expand=True, padx=14, pady=14)
    sec_msg = T.section(right, F, "Messages", right="channel 0")
    sec_msg.pack(fill="x", pady=(0, 8))
    to_lbl = tk.Label(right, text="To everyone", font=F["sm"], fg=T.TXT_3, bg=T.SURFACE,
                      anchor="w")
    msgs = tk.Text(right, bg=T.SURFACE, fg=S.TXT, font=F["sm"], bd=0, highlightthickness=0,
                   wrap="word", padx=0, pady=0, spacing1=1)
    msgs.tag_config("from", foreground=S.TXT, font=F["smb"])
    msgs.tag_config("mine", foreground=T.TXT_2, font=F["smb"])
    msgs.tag_config("meta", foreground=T.TXT_3, font=F["map"])
    msgs.tag_config("dm", foreground=T.ACCENT, font=F["smb"])
    entry_row = tk.Frame(right, bg=T.SURFACE)
    entry_row.pack(side="bottom", fill="x", pady=(8, 0))
    to_lbl.pack(side="bottom", fill="x")
    msgs.pack(fill="both", expand=True)
    entry = T.entry(entry_row, F, font="sm")
    entry.pack(side="left", fill="x", expand=True, ipady=6)
    count = tk.Label(entry_row, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE, width=4)
    count.pack(side="left")

    # ---------------------------------------------------------- data helpers
    def nodes():
        it = st["iface"]
        return dict(it.nodes) if it and getattr(it, "nodes", None) else {}

    def my_id():
        it = st["iface"]
        try:
            return it.getMyNodeInfo()["user"]["id"]
        except Exception:
            return None

    def my_pos():
        tpv = getattr(main, "_gps", None)
        if tpv:
            return tpv
        me = nodes().get(my_id() or "", {})
        p = me.get("position", {})
        if "latitude" in p:
            return (p["latitude"], p["longitude"])
        return None

    def name_of(nid):
        n = nodes().get(nid, {})
        u = n.get("user", {})
        return u.get("longName") or u.get("shortName") or nid

    def short_of(nid):
        n = nodes().get(nid, {})
        return n.get("user", {}).get("shortName") or (nid or "")[-4:]

    def log_msg(rec):
        try:
            with open(MSG_LOG, "a") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass    # full / read-only card: a lost log line must not freeze the message pump

    def show_msg(rec):
        msgs.config(state="normal")
        if rec.get("mine"):
            msgs.insert("end", "You", "mine")
            if rec.get("to") not in (None, "^all"):
                msgs.insert("end", " → %s" % rec.get("to_name", rec["to"]), "dm")
        else:
            msgs.insert("end", rec.get("from_name", rec.get("from", "?")),
                        "dm" if rec.get("to") not in (None, "^all") else "from")
        bits = [time.strftime("%H:%M", time.localtime(rec["t"]))]
        if rec.get("snr") is not None:
            bits.append("%.0fdB" % rec["snr"])
        if rec.get("hops") is not None:
            bits.append("%dh" % rec["hops"])
        msgs.insert("end", "  " + "  ".join(bits) + "\n", "meta")
        msgs.insert("end", rec["text"] + "\n\n")
        msgs.config(state="disabled")
        msgs.see("end")

    # history
    try:
        for ln in open(MSG_LOG).readlines()[-80:]:
            try:
                show_msg(json.loads(ln))
            except (ValueError, KeyError):
                pass
    except OSError:
        pass

    def handle_rx(p):
        d = p.get("decoded", {})
        if d.get("portnum") != "TEXT_MESSAGE_APP" or "text" not in d:
            return
        hops = None
        if p.get("hopStart") is not None and p.get("hopLimit") is not None:
            hops = p["hopStart"] - p["hopLimit"]
        rec = {"t": time.time(), "from": p.get("fromId"), "from_name": name_of(p.get("fromId")),
               "to": p.get("toId"), "ch": p.get("channel", 0), "text": d["text"],
               "snr": p.get("rxSnr"), "hops": hops}
        log_msg(rec)
        show_msg(rec)
        if rec["to"] not in (None, "^all"):
            S.notify("Mesh DM from %s" % rec["from_name"], rec["text"])

    def send(_=None):
        text = entry.get().strip()
        if not text or not st["iface"]:
            return
        if len(text.encode()) > 200:
            node_info.config(text="Message too long (200 bytes max).", fg=S.RED)
            return
        dest = st["sel"] if st["sel"] and st["sel"] != my_id() else "^all"
        try:
            st["iface"].sendText(text, destinationId=dest, channelIndex=0,
                                 wantAck=dest != "^all")
        except Exception as e:
            node_info.config(text="Send failed: %s" % e, fg=S.RED)
            return
        rec = {"t": time.time(), "mine": True, "to": dest,
               "to_name": name_of(dest) if dest != "^all" else "", "text": text, "ch": 0}
        log_msg(rec)
        show_msg(rec)
        entry.delete(0, "end")

    entry.bind("<Return>", send)
    entry.bind("<Escape>", lambda e: (root.focus_set(), "break")[1])
    entry.bind("<KeyRelease>", lambda e: count.config(text=str(200 - len(entry.get().encode()))))

    # ---------------------------------------------------------- node list + map
    order = []

    cache_t = [0.0]

    def cache_nodes(ns):
        """Positions for the Ops picture: id, names, position, SNR, last heard."""
        if time.time() - cache_t[0] < 30:
            return
        cache_t[0] = time.time()
        out = []
        for nid, n in ns.items():
            p = n.get("position") or {}
            u = n.get("user") or {}
            if "latitude" not in p or "longitude" not in p:
                continue
            out.append({"id": str(nid), "short": str(u.get("shortName") or "")[:4],
                        "long": str(u.get("longName") or "")[:24], "lat": p["latitude"],
                        "lon": p["longitude"], "snr": n.get("snr"),
                        "last": n.get("lastHeard"), "me": nid == my_id()})
        try:
            S.save_json(os.path.join(S.CACHE, "mesh_nodes.json"),
                        {"t": time.time(), "demo": isinstance(st.get("iface"), FakeIface),
                         "nodes": out})
        except Exception:
            pass

    def draw_nodes():
        ns = nodes()
        me = my_id()
        mp = my_pos()
        cache_nodes(ns)
        rows = sorted(ns.items(), key=lambda kv: (kv[0] != me, -(kv[1].get("lastHeard") or 0)))
        nodes_txt.config(state="normal")
        nodes_txt.delete("1.0", "end")
        order.clear()
        for nid, n in rows:
            order.append(nid)
            u = n.get("user", {})
            short = (u.get("shortName") or nid[-4:])[:4]
            longn = (u.get("longName") or "")[:11]
            snr = n.get("snr")
            batt = (n.get("deviceMetrics") or {}).get("batteryLevel")
            p = n.get("position", {})
            dist = ""
            if mp and "latitude" in p and nid != me:
                dist = "%.1fkm" % dist_km(mp, (p["latitude"], p["longitude"]))
            line = "%-4s %-11s %4s %4s %6s %3s\n" % (
                short, longn, "" if snr is None else "%.0fdB" % snr,
                "" if batt is None else ("PWR" if batt > 100 else "%d%%" % batt), dist,
                "me" if nid == me else ago(n.get("lastHeard")))
            tags = []
            if nid == me:
                tags.append("me")
            elif n.get("lastHeard") and time.time() - n["lastHeard"] > 7200:
                tags.append("old")
            elif snr is not None:
                tags.append("good" if snr > 0 else ("mid" if snr > -10 else "bad"))
            if nid == st["sel"]:
                tags.append("pick")
            nodes_txt.insert("end", line, tuple(tags))
        nodes_txt.config(state="disabled")

    def pick_node(e):
        idx = int(nodes_txt.index("@%d,%d" % (e.x, e.y)).split(".")[0]) - 1
        if 0 <= idx < len(order):
            nid = order[idx]
            st["sel"] = None if st["sel"] == nid or nid == my_id() else nid
            update_sel()

    nodes_txt.bind("<Button-1>", pick_node)

    def update_sel():
        nid = st["sel"]
        if nid:
            to_lbl.config(text="Direct to %s  ·  tap the node again to clear" % name_of(nid),
                          fg=T.ACCENT)
            n = nodes().get(nid, {})
            dm = n.get("deviceMetrics") or {}
            p = n.get("position", {})
            bits = [name_of(nid), nid, (n.get("user") or {}).get("hwModel", "")]
            if n.get("snr") is not None:
                bits.append("SNR %.1f dB" % n["snr"])
            if n.get("hopsAway") is not None:
                bits.append("%d hops" % n["hopsAway"])
            if dm.get("voltage"):
                bits.append("%.2f V" % dm["voltage"])
            if "latitude" in p:
                bits.append("%.4f, %.4f" % (p["latitude"], p["longitude"]))
            node_info.config(text="  ·  ".join(str(b) for b in bits if b), fg=S.TXT)
        else:
            to_lbl.config(text="To everyone", fg=T.TXT_3)
            node_info.config(text="Select a node for details", fg=T.TXT_3)
        draw_nodes()
        draw_map()

    import tiles
    mcfg = S.load_json(os.path.join(S.CFG, "mesh.json"), {}) or {}
    view = {"z": int(mcfg.get("map_zoom", 11)), "lat": None, "lon": None, "drag": None, "moved": False,
            "auto": True}
    basemap = tiles.TileLayer(on_ready=lambda ok: root.after(0, lambda: tile_tick()),
                              workers=1 if S.low_power() else 3)
    basemap.layer = mcfg.get("map_layer", "dark") if mcfg.get("map_layer") in tiles.LAYER_ORDER else "dark"
    tile_job = [None]

    def tile_tick():
        if tile_job[0] is None:
            tile_job[0] = root.after(120, lambda: (tile_job.__setitem__(0, None), draw_map()))

    def save_view():
        d = S.load_json(os.path.join(S.CFG, "mesh.json"), {}) or {}
        d["map_zoom"], d["map_layer"] = view["z"], basemap.layer
        try:
            S.save_json(os.path.join(S.CFG, "mesh.json"), d)
        except OSError:
            pass

    def proj(la, lo):
        w, h = cv.winfo_width(), cv.winfo_height()
        cx, cy = tiles.world_px(view["lat"], view["lon"], view["z"])
        x, y = tiles.world_px(la, lo, view["z"])
        return w / 2 + (x - cx), h / 2 + (y - cy)

    def node_points():
        pts = []
        for nid, n in nodes().items():
            p = n.get("position", {})
            if "latitude" in p and p["latitude"]:
                pts.append((nid, p["latitude"], p["longitude"]))
        mp = my_pos()
        if mp:
            pts = [x for x in pts if x[0] != my_id()] + [(my_id() or "me", mp[0], mp[1])]
        return pts, mp

    def fit_view(pts, mp):
        """Centre on me (or the node cloud) and pick a zoom that shows every node."""
        lats = [p[1] for p in pts]
        lons = [p[2] for p in pts]
        view["lat"], view["lon"] = mp if mp else ((max(lats) + min(lats)) / 2, (max(lons) + min(lons)) / 2)
        w, h = cv.winfo_width(), cv.winfo_height()
        for z in range(15, 5, -1):
            cx, cy = tiles.world_px(view["lat"], view["lon"], z)
            ok = True
            for _, la, lo in pts:
                x, y = tiles.world_px(la, lo, z)
                if abs(x - cx) > w / 2 - 60 or abs(y - cy) > h / 2 - 50:
                    ok = False
                    break
            if ok:
                view["z"] = z
                return

    def draw_map():
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 20:
            return
        pts, mp = node_points()
        if view["lat"] is None or (view["auto"] and pts):
            if pts:
                fit_view(pts, mp)
            else:
                view["lat"], view["lon"] = 39.715, -104.76
        k = tiles.px_per_nm(view["lat"], view["z"]) / 1.852   # px per km
        missing = basemap.draw(cv, view["lat"], view["lon"], view["z"], w, h)
        if not pts:
            cv.create_text(w / 2, h / 2, text="No node positions yet", fill=T.TXT_3, font=F["sm"])
        if mp:
            bx, by = proj(*mp)
            ring = min(w, h) / 2 - 26
            T.compass_ring(cv, bx, by, ring, F)
            for km in (1, 2, 5, 10, 20, 50, 100):
                r = km * k
                if 30 < r < max(w, h):
                    T.range_ring(cv, bx, by, r, "%d km" % km, F)
        me = my_id()
        mpx = proj(*mp) if mp else None
        for nid, la, lo in pts:
            x, y = proj(la, lo)
            n = nodes().get(nid, {})
            snr = n.get("snr")
            is_me = nid == me or (mp and (la, lo) == mp)
            sel = nid == st["sel"]
            old = n.get("lastHeard") and time.time() - n["lastHeard"] > 7200
            col = T.ACCENT if sel else (T.TXT_3 if old else (S.TXT if is_me else T.TRACK))
            if mpx and not is_me and n.get("hopsAway") == 0:
                cv.create_line(mpx[0], mpx[1], x, y, fill=T.LINE_HI, dash=(2, 4))
            if is_me:
                cv.create_oval(x - 6, y - 6, x + 6, y + 6, outline=col, width=1.5)
                cv.create_oval(x - 2, y - 2, x + 2, y + 2, fill=col, outline="")
            else:
                cv.create_rectangle(x - 4, y - 4, x + 4, y + 4, outline=col, width=1.2,
                                    fill=col if sel else "")
            if sel:
                cv.create_rectangle(x - 11, y - 11, x + 11, y + 11, outline=T.ACCENT)
            label = short_of(nid) if not is_me else "You"
            if basemap.layer != "dark":
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    cv.create_text(x + 12 + dx, y - 1 + dy, text=label, fill=S.MAPBG, anchor="sw",
                                   font=F["mapb"])
            cv.create_text(x + 12, y - 1, text=label, fill=col, anchor="sw", font=F["mapb"])
            if snr is not None and not is_me:
                cv.create_text(x + 12, y, text="%.0f dB" % snr, fill=T.TXT_3, anchor="nw",
                               font=F["map"])
        T.scale_bar(cv, 18, h - 34, k, F, unit="km")
        if missing and not basemap.online:
            cv.create_text(18, h - 50, anchor="sw", fill=T.TXT_3, font=F["map"],
                           text="offline · %d tiles not cached" % missing)
        cv.create_text(w - 16, h - 12, anchor="se", fill=T._mix(T.TXT_3, S.MAPBG, 0.6), font=F["map"],
                       text=basemap.spec["credit"])

    # pan / zoom / layer controls
    def on_press(e):
        view["drag"] = (e.x, e.y, view["lat"], view["lon"])
        view["moved"] = False

    def on_motion(e):
        if not view["drag"]:
            return
        x0, y0, la0, lo0 = view["drag"]
        if abs(e.x - x0) + abs(e.y - y0) > 6:
            view["moved"] = True
            view["auto"] = False
        cx, cy = tiles.world_px(la0, lo0, view["z"])
        view["lat"], view["lon"] = tiles.from_world_px(cx - (e.x - x0), cy - (e.y - y0), view["z"])
        draw_map()

    def on_release(e):
        view["drag"] = None

    def zoom(d):
        z = max(5, min(16, view["z"] + d))
        if z != view["z"]:
            view["z"], view["auto"] = z, False
            save_view()
            draw_map()

    def refit():
        view["auto"] = True
        draw_map()

    def cycle_layer():
        basemap.cycle()
        layer_btn.config(text=basemap.spec["label"])
        save_view()
        draw_map()

    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_motion)
    cv.bind("<ButtonRelease-1>", on_release)
    cv.bind("<Button-4>", lambda e: zoom(+1))
    cv.bind("<Button-5>", lambda e: zoom(-1))
    mapbtns = tk.Frame(cv, bg=T.SURFACE, highlightthickness=1, highlightbackground=S.LINE)
    mapbtns.place(relx=1.0, rely=0.0, x=-14, y=14, anchor="ne")
    for t, c in (("+", lambda: zoom(+1)), ("−", lambda: zoom(-1)), ("⌖", refit)):
        b = T.btn(mapbtns, t, c, F, font="h", padx=11, pady=2, kind="quiet")
        b.config(fg=S.TXT)
        b.pack(fill="x")
        tk.Frame(mapbtns, bg=S.LINE, height=1).pack(fill="x")
    layer_btn = T.btn(mapbtns, basemap.spec["label"], cycle_layer, F, font="sm", padx=8, pady=3, kind="quiet")
    layer_btn.pack(fill="x")

    cv.bind("<Configure>", lambda e: draw_map())

    # ---------------------------------------------------------- loops
    def pump():
        while not events.empty():
            ev = events.get()
            if ev[0] == "status":
                st["status"], st["detail"] = ev[1], ev[2]
                conn_pill.config(text={"connecting": "connecting…", "connected": "connected",
                                       "error": "not connected", "lost": "lost"}[ev[1]],
                                 bg={"connecting": S.BLUE, "connected": S.GREEN,
                                     "error": S.RED, "lost": S.AMBER}[ev[1]])
                me_lbl.config(text=ev[2])
                if ev[1] == "connected":
                    me_lbl.config(text="%s · %s" % (name_of(my_id()), ev[2]))
                    update_sel()
                if ev[1] == "error":
                    node_info.config(text=ev[2], fg=S.AMBER)
                    root.after(15000, lambda: S.in_thread(connect))
            elif ev[0] == "rx":
                handle_rx(ev[1])
                draw_nodes()
            elif ev[0] == "lost":
                if ev[1] is not None and ev[1] is not st["iface"]:
                    # the interface Settings just closed reporting its own shutdown: dropping
                    # the NEW connection here would leak it and start yet another connect
                    continue
                conn_pill.config(text="lost - reconnecting", bg=S.AMBER)
                st["iface"] = None
                root.after(5000, lambda: S.in_thread(connect))
        root.after(150, pump)

    def refresh():
        def gps():
            tpv = S.gps_fix(timeout=1.0)
            main._gps = (tpv["lat"], tpv["lon"]) if tpv and "lat" in tpv else None
        S.in_thread(gps)
        if st["iface"]:
            draw_nodes()
            draw_map()
        root.after(10000, refresh)

    def on_close():
        try:
            if st["iface"]:
                st["iface"].close()
        except Exception:
            pass
        root.destroy()

    S.bind_quit(root, on_close)
    S.in_thread(connect)
    pump()
    refresh()
    entry.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
