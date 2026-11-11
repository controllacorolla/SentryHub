#!/usr/bin/env python3
"""Dev terminal - the field-admin side of the workbench.

BLE    Scan for Bluetooth Low Energy devices (name, address, signal), connect to one, and
       list its GATT services and characteristics - read the readable ones. The CM5 has
       Bluetooth 5.2, so this is the quick way to bring up a BLE peripheral.
MQTT   Connect to an MQTT broker, subscribe, and watch topics update as live value cards
       (last value, how often, how long ago). Publish a test message to any topic.
SSH    Saved hosts from your ~/.ssh/config and your own list; open a full terminal to one,
       or run a single command and see its output. Key-based only - no passwords are handled
       here; set up an SSH key if a host asks for one.

Everything here talks to your own devices and brokers. --demo runs fake BLE devices and a
fake broker so the screens can be used without hardware.
"""
import json
import os
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S          # noqa: E402

DEFAULTS = {"broker": "127.0.0.1", "port": 1883, "topic": "#", "hosts": [],
            "last_host": "", "scan_secs": 8}


# ---- pure helpers (tested) ------------------------------------------------------------------
def fmt_rssi(rssi):
    """RSSI dBm -> a short strength word + bar glyph. None -> unknown."""
    if rssi is None:
        return "—", ""
    if rssi >= -55:
        return "%d" % rssi, "▂▄▆█"
    if rssi >= -70:
        return "%d" % rssi, "▂▄▆"
    if rssi >= -85:
        return "%d" % rssi, "▂▄"
    return "%d" % rssi, "▂"


def char_props(props):
    """GATT characteristic property list -> short label like 'R W N'."""
    order = [("read", "R"), ("write", "W"), ("write-without-response", "w"),
             ("notify", "N"), ("indicate", "I")]
    return " ".join(sym for name, sym in order if name in (props or []))


def decode_char(data):
    """Best-effort human form of a characteristic's bytes: printable text, else hex."""
    if data is None:
        return "—"
    try:
        text = bytes(data).decode("utf-8")
        if text and all(32 <= ord(c) < 127 or c in "\r\n\t" for c in text):
            return repr(text)[1:-1]
    except (UnicodeDecodeError, TypeError, ValueError):
        pass
    return " ".join("%02x" % b for b in bytes(data))


def mqtt_value(payload):
    """Pretty one-line value for an MQTT payload: JSON stays compact, text as-is, bytes as hex."""
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return " ".join("%02x" % b for b in payload[:16]) + ("…" if len(payload) > 16 else "")
    payload = str(payload)
    s = payload.strip()
    if s and s[0] in "{[":
        try:
            obj = json.loads(s)
            return json.dumps(obj, separators=(",", ":"))[:80]
        except ValueError:
            pass
    return payload[:80]


def topic_leaf(topic):
    """Last segment of an MQTT topic, for a compact card title."""
    return topic.rstrip("/").rsplit("/", 1)[-1] or topic


def parse_ssh_config(text):
    """Host aliases from an ssh_config body (skips wildcards and negations)."""
    hosts = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0].lower() == "host":
            for h in parts[1:]:
                if "*" not in h and "?" not in h and not h.startswith("!"):
                    hosts.append(h)
    seen, out = set(), []
    for h in hosts:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def ssh_hosts(cfg_path=None, extra=()):
    path = cfg_path or os.path.expanduser("~/.ssh/config")
    hosts = []
    try:
        with open(path) as f:
            hosts = parse_ssh_config(f.read())
    except OSError:
        pass
    for h in extra:
        if h and h not in hosts:
            hosts.append(h)
    return hosts


def term_launcher():
    """A terminal emulator present on the system that can run `-e <cmd>`, or None."""
    for term in ("lxterminal", "xterm", "x-terminal-emulator", "kitty", "alacritty",
                 "gnome-terminal", "konsole", "xfce4-terminal"):
        if shutil.which(term):
            return term
    return None


# ---- demo sources ---------------------------------------------------------------------------
DEMO_BLE = [
    {"address": "E4:5F:01:2A:3B:4C", "name": "RF-Reaper", "rssi": -47},
    {"address": "C8:2B:96:11:22:33", "name": "Nordic_HRM", "rssi": -63},
    {"address": "A4:C1:38:AA:BB:CC", "name": "BME280-node", "rssi": -72},
    {"address": "FF:EE:DD:00:11:22", "name": "", "rssi": -88},
]
DEMO_SERVICES = [
    ("180a", "Device Information", [
        ("2a29", "Manufacturer", ["read"], b"RF Reaper Labs"),
        ("2a24", "Model Number", ["read"], b"REAPER- v0.4.1")]),
    ("180f", "Battery Service", [("2a19", "Battery Level", ["read", "notify"], b"\x57")]),
    ("fff0", "Vendor RF", [
        ("fff1", "TX freq (Hz)", ["read", "write"], b"\x00\x6a\xd8\x19"),
        ("fff2", "RX stream", ["notify"], None)]),
]


class DemoMqtt:
    """A fake broker that publishes a handful of ESP32-style topics on a timer."""
    def __init__(self, q):
        self.q, self.open, self.n = q, True, 0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self.q.put(("status", "connected to demo broker"))
        while self.open:
            self.n += 1
            self.q.put(("msg", "reaper/temp", "%.1f" % (21 + self.n % 6 * 0.4)))
            self.q.put(("msg", "reaper/rssi", "-%d" % (60 + self.n % 20)))
            self.q.put(("msg", "reaper/state", json.dumps({"rf": "idle", "heap": 180000})))
            if self.n % 3 == 0:
                self.q.put(("msg", "home/door/front", "closed" if self.n % 6 else "OPEN"))
            time.sleep(1.0)

    def publish(self, topic, payload):
        self.q.put(("msg", topic, payload))
        self.q.put(("status", "published to %s" % topic))

    def close(self):
        self.open = False


# ---- the app --------------------------------------------------------------------------------
def main():
    S.single_instance("Dev terminal")
    demo = "--demo" in sys.argv
    s, spath = S.settings("devterm", DEFAULTS)
    root, F = S.make_root("Dev terminal")
    import tkinter as tk
    import queue
    T = S.T
    slog = S.SessionLog("devterm")
    st = {"tab": "ble", "closed": False, "ble_scan": False, "ble": [], "ble_sel": None,
          "ble_services": None, "mqtt": None, "topics": {}, "mqtt_on": False}
    q = queue.Queue()

    top = S.top_bar(root, F, "Dev terminal", "BLE · MQTT · SSH" if not demo else "demo")
    status_pill = S.pill(top, F, "Ready")
    if demo:
        S.pill(top, F, "DEMO", S.AMBER)

    tabs_row = tk.Frame(root, bg=T.SURFACE)
    tabs_row.pack(side="top", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="top", fill="x")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    panes = {k: tk.Frame(body, bg=S.BG) for k in ("ble", "mqtt", "ssh")}
    tab_btns = {}

    def show_tab(key):
        st["tab"] = key
        for p in panes.values():
            p.pack_forget()
        panes[key].pack(fill="both", expand=True)
        for k, b in tab_btns.items():
            T.set_btn(b, kind="primary" if k == key else "ghost")

    for key, label in (("ble", "BLE"), ("mqtt", "MQTT"), ("ssh", "SSH")):
        b = S.btn(tabs_row, label, lambda k=key: show_tab(k), F, padx=16, pady=6, kind="ghost")
        b.pack(side="left", padx=(T.px(6), 0), pady=T.px(5))
        tab_btns[key] = b

    def save():
        try:
            S.save_json(spath, s)
        except OSError:
            pass

    # ================= BLE =================
    blp = panes["ble"]
    bh = tk.Frame(blp, bg=T.SURFACE)
    bh.pack(side="top", fill="x")
    tk.Frame(blp, bg=S.LINE, height=1).pack(side="top", fill="x")
    bhr = tk.Frame(bh, bg=T.SURFACE)
    bhr.pack(fill="x", padx=T.px(10), pady=T.px(7))
    scan_btn = S.btn(bhr, "Scan", lambda: ble_scan(), F, padx=12, pady=4, kind="primary")
    scan_btn.pack(side="left")
    ble_status = tk.Label(bhr, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
    ble_status.pack(side="left", padx=(T.px(12), 0))
    bcols = tk.Frame(blp, bg=S.BG)
    bcols.pack(fill="both", expand=True)
    blist = tk.Frame(bcols, bg=T.SURFACE, width=T.px(330))
    blist.pack(side="left", fill="y")
    blist.pack_propagate(False)
    tk.Frame(bcols, bg=S.LINE, width=1).pack(side="left", fill="y")
    blist_in = tk.Frame(blist, bg=T.SURFACE)
    blist_in.pack(fill="both", expand=True, padx=T.px(8), pady=T.px(8))
    bdetail = tk.Frame(bcols, bg=S.BG)
    bdetail.pack(side="left", fill="both", expand=True, padx=T.px(12), pady=T.px(10))

    def ble_scan():
        if st["ble_scan"]:
            return
        st["ble_scan"] = True
        st["ble"] = []
        T.set_btn(scan_btn, "Scanning…", "ghost")
        ble_status.config(text="listening %ds…" % s.get("scan_secs", 8), fg=T.TXT_3)

        def work():
            if demo:
                for i, d in enumerate(DEMO_BLE):
                    time.sleep(0.3)
                    q.put(("ble_dev", d))
                q.put(("ble_done", None))
                return
            try:
                import asyncio
                from bleak import BleakScanner

                async def scan():
                    found = {}
                    def cb(dev, adv):
                        found[dev.address] = {"address": dev.address, "name": dev.name or "",
                                              "rssi": getattr(adv, "rssi", None)}
                    scanner = BleakScanner(detection_callback=cb)
                    await scanner.start()
                    await asyncio.sleep(s.get("scan_secs", 8))
                    await scanner.stop()
                    return list(found.values())
                devs = asyncio.run(scan())
                for d in sorted(devs, key=lambda x: -(x["rssi"] or -999)):
                    q.put(("ble_dev", d))
                q.put(("ble_done", None))
            except Exception as e:
                q.put(("ble_err", str(e)[:90]))
        S.in_thread(work)

    def render_ble_list():
        for w in blist_in.winfo_children():
            w.destroy()
        T.section(blist_in, F, "Devices", right="%d" % len(st["ble"])).pack(fill="x")
        if not st["ble"]:
            tk.Label(blist_in, text="Press Scan.", font=F["map"], fg=T.TXT_3,
                     bg=T.SURFACE).pack(anchor="w", pady=T.px(6))
            return
        for d in st["ble"]:
            sel = d["address"] == st["ble_sel"]
            row = tk.Frame(blist_in, bg=T.ACCENT_BG if sel else T.SURFACE, cursor="hand2")
            row.pack(fill="x", pady=1)
            name = d["name"] or "(unnamed)"
            num, bars = fmt_rssi(d["rssi"])
            top_l = tk.Label(row, text=name, font=F["rowb"], fg=T.TXT if d["name"] else T.TXT_3,
                             bg=row["bg"], anchor="w")
            top_l.pack(fill="x", padx=T.px(6), pady=(T.px(4), 0))
            sub = tk.Label(row, text="%s   %s dBm %s" % (d["address"], num, bars), font=F["map"],
                           fg=T.TXT_3, bg=row["bg"], anchor="w")
            sub.pack(fill="x", padx=T.px(6), pady=(0, T.px(4)))
            for wdg in (row, top_l, sub):
                wdg.bind("<Button-1>", lambda e, dd=d: select_ble(dd))

    def select_ble(d):
        st["ble_sel"] = d["address"]
        st["ble_services"] = None
        render_ble_list()
        render_ble_detail()
        connect_ble(d)

    def connect_ble(d):
        ble_status.config(text="connecting to %s…" % (d["name"] or d["address"]), fg=T.TXT_3)

        def work():
            if demo:
                time.sleep(0.6)
                q.put(("ble_svc", (d["address"], DEMO_SERVICES)))
                return
            try:
                import asyncio
                from bleak import BleakClient

                async def go():
                    out = []
                    async with BleakClient(d["address"], timeout=12) as client:
                        for svc in client.services:
                            chars = []
                            for ch in svc.characteristics:
                                val = None
                                if "read" in ch.properties:
                                    try:
                                        val = await client.read_gatt_char(ch.uuid)
                                    except Exception:
                                        val = None
                                chars.append((ch.uuid[4:8], ch.description or ch.uuid,
                                              list(ch.properties), val))
                            out.append((svc.uuid[4:8], svc.description or svc.uuid, chars))
                    return out
                svcs = asyncio.run(go())
                q.put(("ble_svc", (d["address"], svcs)))
            except Exception as e:
                q.put(("ble_err", "connect: " + str(e)[:80]))
        S.in_thread(work)

    def render_ble_detail():
        for w in bdetail.winfo_children():
            w.destroy()
        if st["ble_sel"] is None:
            tk.Label(bdetail, text="Scan, then tap a device to read its services.",
                     font=F["map"], fg=T.TXT_3, bg=S.BG).pack(anchor="w")
            return
        dev = next((d for d in st["ble"] if d["address"] == st["ble_sel"]), None)
        T.section(bdetail, F, (dev["name"] or dev["address"]) if dev else st["ble_sel"]).pack(
            fill="x", pady=(0, T.px(6)))
        if st["ble_services"] is None:
            tk.Label(bdetail, text="reading services…", font=F["map"], fg=T.TXT_3,
                     bg=S.BG).pack(anchor="w")
            return
        cv = tk.Canvas(bdetail, bg=S.BG, highlightthickness=0)
        sb = tk.Scrollbar(bdetail, command=cv.yview, bg=T.SURFACE, troughcolor=S.BG, bd=0,
                          highlightthickness=0, width=T.px(10))
        inner = tk.Frame(cv, bg=S.BG)
        cv.create_window(0, 0, window=inner, anchor="nw")
        cv.config(yscrollcommand=sb.set)
        inner.bind("<Configure>", lambda e: (cv.config(scrollregion=cv.bbox("all")),
                                             S.bind_wheel_tree(inner, cv)))
        S.bind_wheel(cv)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        for suuid, sname, chars in st["ble_services"]:
            tk.Label(inner, text="%s   0x%s" % (sname, suuid), font=F["rowb"], fg=T.NOTE,
                     bg=S.BG, anchor="w").pack(fill="x", pady=(T.px(8), T.px(2)))
            for cuuid, cname, props, val in chars:
                rowf = tk.Frame(inner, bg=S.BG)
                rowf.pack(fill="x", anchor="w")
                tk.Label(rowf, text="0x%s" % cuuid, font=F["mono"], fg=T.TXT_3, bg=S.BG,
                         width=7, anchor="w").pack(side="left")
                tk.Label(rowf, text=char_props(props), font=F["mono"], fg=T.ACCENT, bg=S.BG,
                         width=8, anchor="w").pack(side="left")
                tk.Label(rowf, text=cname[:22], font=F["map"], fg=T.TXT_2, bg=S.BG, width=22,
                         anchor="w").pack(side="left")
                tk.Label(rowf, text=decode_char(val) if val is not None else "", font=F["mono"],
                         fg=T.TXT, bg=S.BG, anchor="w").pack(side="left", fill="x", expand=True)

    # ================= MQTT =================
    mp = panes["mqtt"]
    mh = tk.Frame(mp, bg=T.SURFACE)
    mh.pack(side="top", fill="x")
    tk.Frame(mp, bg=S.LINE, height=1).pack(side="top", fill="x")
    mhr = tk.Frame(mh, bg=T.SURFACE)
    mhr.pack(fill="x", padx=T.px(10), pady=T.px(7))
    tk.Label(mhr, text="Broker", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left")
    broker_e = tk.Entry(mhr, bg=T.SURFACE_2, fg=T.TXT, font=F["map"], bd=0, width=16,
                        insertbackground=T.TXT, highlightthickness=1, highlightbackground=T.LINE,
                        highlightcolor=T.ACCENT)
    broker_e.insert(0, s.get("broker", "127.0.0.1"))
    broker_e.pack(side="left", padx=(T.px(6), T.px(4)), ipady=T.px(3))
    tk.Label(mhr, text="Topic", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left")
    topic_e = tk.Entry(mhr, bg=T.SURFACE_2, fg=T.TXT, font=F["map"], bd=0, width=14,
                       insertbackground=T.TXT, highlightthickness=1, highlightbackground=T.LINE,
                       highlightcolor=T.ACCENT)
    topic_e.insert(0, s.get("topic", "#"))
    topic_e.pack(side="left", padx=(T.px(6), T.px(8)), ipady=T.px(3))
    mqtt_btn = S.btn(mhr, "Connect", lambda: mqtt_toggle(), F, padx=12, pady=4, kind="primary")
    mqtt_btn.pack(side="left")
    mqtt_status = tk.Label(mhr, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
    mqtt_status.pack(side="left", padx=(T.px(10), 0))
    # publish row first (side=bottom) so it always keeps its space, then the grid fills the rest
    mpub = tk.Frame(mp, bg=T.SURFACE)
    mpub.pack(side="bottom", fill="x")
    tk.Frame(mp, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    mgrid = tk.Frame(mp, bg=S.BG)
    mgrid.pack(fill="both", expand=True, padx=T.px(10), pady=T.px(10))
    mpr = tk.Frame(mpub, bg=T.SURFACE)
    mpr.pack(fill="x", padx=T.px(10), pady=T.px(7))
    tk.Label(mpr, text="Publish", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left")
    pub_topic = tk.Entry(mpr, bg=T.SURFACE_2, fg=T.TXT, font=F["map"], bd=0, width=18,
                         insertbackground=T.TXT, highlightthickness=1, highlightbackground=T.LINE,
                         highlightcolor=T.ACCENT)
    pub_topic.pack(side="left", padx=(T.px(6), T.px(4)), ipady=T.px(3))
    pub_topic.insert(0, "reaper/cmd")
    pub_val = tk.Entry(mpr, bg=T.SURFACE_2, fg=T.TXT, font=F["map"], bd=0,
                       insertbackground=T.TXT, highlightthickness=1, highlightbackground=T.LINE,
                       highlightcolor=T.ACCENT)
    pub_val.pack(side="left", fill="x", expand=True, padx=(0, T.px(4)), ipady=T.px(3))
    S.btn(mpr, "Send", lambda: mqtt_publish(), F, padx=12, pady=4, kind="ghost").pack(side="left")

    def mqtt_toggle():
        if st["mqtt"] is not None:
            mqtt_disconnect()
            return
        s["broker"], s["topic"] = broker_e.get().strip(), topic_e.get().strip() or "#"
        save()
        st["topics"] = {}
        render_mqtt()
        mqtt_status.config(text="connecting…", fg=T.TXT_3)
        if demo:
            st["mqtt"] = DemoMqtt(q)
            after_connect()
            return

        def work():
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                q.put(("mqtt_err", "paho-mqtt not installed (sudo pip3 install paho-mqtt)"))
                return
            try:
                cl = mqtt.Client()

                def on_connect(c, u, flags, rc):
                    c.subscribe(s["topic"])
                    q.put(("status", "subscribed to %s" % s["topic"]))

                def on_message(c, u, msg):
                    q.put(("msg", msg.topic, msg.payload))
                cl.on_connect = on_connect
                cl.on_message = on_message
                cl.connect(s["broker"], int(s.get("port", 1883)), 30)
                cl.loop_start()
                st["mqtt"] = cl
                q.put(("mqtt_ready", None))
            except Exception as e:
                q.put(("mqtt_err", str(e)[:90]))
        S.in_thread(work)

    def after_connect():
        mqtt_status.config(text="connected to %s" % s["broker"], fg=T.TXT)
        T.set_btn(mqtt_btn, "Disconnect", "danger")
        status_pill.config(text="MQTT", bg=S.GREEN)
        slog.event("devterm", "mqtt %s %s" % (s["broker"], s["topic"]), id="mqtt")

    def mqtt_disconnect():
        m = st["mqtt"]
        st["mqtt"] = None
        if m:
            try:
                m.loop_stop() if hasattr(m, "loop_stop") else None
                m.disconnect() if hasattr(m, "disconnect") else m.close()
            except Exception:
                pass
        mqtt_status.config(text="disconnected", fg=T.TXT_3)
        T.set_btn(mqtt_btn, "Connect", "primary")
        status_pill.config(text="Ready", bg=S.DIM)

    def mqtt_publish():
        m = st["mqtt"]
        if m is None:
            mqtt_status.config(text="connect first", fg=S.AMBER)
            return
        topic, val = pub_topic.get().strip(), pub_val.get()
        if not topic:
            return
        try:
            m.publish(topic, val)
        except Exception as e:
            mqtt_status.config(text="publish failed: %s" % str(e)[:40], fg=S.AMBER)

    def render_mqtt():
        for w in mgrid.winfo_children():
            w.destroy()
        topics = st["topics"]
        if not topics:
            tk.Label(mgrid, text="Subscribed topics appear here as live cards once messages "
                                 "arrive.", font=F["map"], fg=T.TXT_3, bg=S.BG).pack(anchor="w")
            return
        cols = 3
        for i, (topic, info) in enumerate(sorted(topics.items())):
            r, c = divmod(i, cols)
            mgrid.columnconfigure(c, weight=1, uniform="m")
            card = tk.Frame(mgrid, bg=T.SURFACE, highlightthickness=1, highlightbackground=S.LINE)
            card.grid(row=r, column=c, sticky="nsew", padx=T.px(4), pady=T.px(4))
            tk.Label(card, text=topic_leaf(topic), font=F["rowb"], fg=T.TXT, bg=T.SURFACE,
                     anchor="w").pack(fill="x", padx=T.px(8), pady=(T.px(6), 0))
            tk.Label(card, text=topic, font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE,
                     anchor="w").pack(fill="x", padx=T.px(8))
            tk.Label(card, text=mqtt_value(info["val"]), font=F["data"], fg=T.ACCENT,
                     bg=T.SURFACE, anchor="w").pack(fill="x", padx=T.px(8), pady=(T.px(2), 0))
            age = int(time.time() - info["t"])
            tk.Label(card, text="%d msgs · %s" % (info["n"], "now" if age < 2 else "%ds" % age),
                     font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE, anchor="w").pack(
                fill="x", padx=T.px(8), pady=(0, T.px(6)))

    # ================= SSH =================
    shp = panes["ssh"]
    shh = tk.Frame(shp, bg=T.SURFACE)
    shh.pack(side="top", fill="x")
    tk.Frame(shp, bg=S.LINE, height=1).pack(side="top", fill="x")
    shr = tk.Frame(shh, bg=T.SURFACE)
    shr.pack(fill="x", padx=T.px(10), pady=T.px(7))
    tk.Label(shr, text="Host", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left")
    host_e = tk.Entry(shr, bg=T.SURFACE_2, fg=T.TXT, font=F["map"], bd=0, width=22,
                      insertbackground=T.TXT, highlightthickness=1, highlightbackground=T.LINE,
                      highlightcolor=T.ACCENT)
    host_e.insert(0, s.get("last_host", ""))
    host_e.pack(side="left", padx=(T.px(6), T.px(8)), ipady=T.px(3))
    open_btn = S.btn(shr, "Open terminal", lambda: ssh_open(), F, padx=12, pady=4,
                     kind="primary")
    open_btn.pack(side="left")
    ssh_status = tk.Label(shr, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
    ssh_status.pack(side="left", padx=(T.px(10), 0))
    sbody = tk.Frame(shp, bg=S.BG)
    sbody.pack(fill="both", expand=True)
    shlist = tk.Frame(sbody, bg=T.SURFACE, width=T.px(240))
    shlist.pack(side="left", fill="y")
    shlist.pack_propagate(False)
    tk.Frame(sbody, bg=S.LINE, width=1).pack(side="left", fill="y")
    shlist_in = tk.Frame(shlist, bg=T.SURFACE)
    shlist_in.pack(fill="both", expand=True, padx=T.px(8), pady=T.px(8))
    # quick command runner
    sright = tk.Frame(sbody, bg=S.BG)
    sright.pack(side="left", fill="both", expand=True, padx=T.px(10), pady=T.px(10))
    T.section(sright, F, "Run one command").pack(fill="x")
    crow = tk.Frame(sright, bg=S.BG)
    crow.pack(fill="x", pady=(T.px(6), 0))
    cmd_e = tk.Entry(crow, bg=T.SURFACE_2, fg=T.TXT, font=F["mono"], bd=0,
                     insertbackground=T.TXT, highlightthickness=1, highlightbackground=T.LINE,
                     highlightcolor=T.ACCENT)
    cmd_e.insert(0, "uptime")
    cmd_e.pack(side="left", fill="x", expand=True, ipady=T.px(4))
    S.btn(crow, "Run", lambda: ssh_run(), F, padx=12, pady=4, kind="ghost").pack(
        side="left", padx=(T.px(6), 0))
    cmd_out = tk.Text(sright, bg="#07080a", fg=T.TXT_2, font=F["mono"], bd=0,
                      highlightthickness=0, wrap="word", state="disabled", padx=T.px(8),
                      pady=T.px(6), height=1)
    cmd_out.pack(fill="both", expand=True, pady=(T.px(8), 0))
    S.bind_wheel(cmd_out)

    def render_hosts():
        for w in shlist_in.winfo_children():
            w.destroy()
        hosts = ssh_hosts(extra=s.get("hosts", []))
        T.section(shlist_in, F, "Saved hosts", right="%d" % len(hosts)).pack(fill="x")
        if not hosts:
            tk.Label(shlist_in, text="Hosts from ~/.ssh/config appear here.", font=F["map"],
                     fg=T.TXT_3, bg=T.SURFACE, wraplength=T.px(210), justify="left").pack(
                anchor="w", pady=T.px(6))
            return
        for h in hosts:
            b = tk.Label(shlist_in, text=h, font=F["row"], fg=T.TXT_2, bg=T.SURFACE,
                         anchor="w", cursor="hand2", padx=T.px(6), pady=T.px(3))
            b.pack(fill="x")
            b.bind("<Button-1>", lambda e, hh=h: (host_e.delete(0, "end"), host_e.insert(0, hh)))
            b.bind("<Enter>", lambda e, bb=b: bb.config(bg=T.HOVER))
            b.bind("<Leave>", lambda e, bb=b: bb.config(bg=T.SURFACE))

    def ssh_open():
        host = host_e.get().strip()
        if not host:
            ssh_status.config(text="enter a host", fg=S.AMBER)
            return
        s["last_host"] = host
        if host not in s.get("hosts", []) and host not in ssh_hosts():
            s.setdefault("hosts", []).append(host)
        save()
        render_hosts()
        term = term_launcher()
        if not term:
            ssh_status.config(text="no terminal emulator found (install lxterminal)", fg=S.AMBER)
            return
        try:
            S.spawn([term, "-e", "ssh %s" % host] if term in ("lxterminal", "xterm")
                    else [term, "-e", "ssh", host])
            ssh_status.config(text="opened terminal to %s" % host, fg=T.TXT)
            slog.event("devterm", "ssh %s" % host, id="ssh:" + host)
        except Exception as e:
            ssh_status.config(text="couldn't launch: %s" % str(e)[:50], fg=S.AMBER)

    def ssh_run():
        host, cmd = host_e.get().strip(), cmd_e.get().strip()
        if not host or not cmd:
            ssh_status.config(text="host and command needed", fg=S.AMBER)
            return
        cmd_out.config(state="normal")
        cmd_out.delete("1.0", "end")
        cmd_out.insert("end", "$ ssh %s %s\n" % (host, cmd))
        cmd_out.config(state="disabled")
        ssh_status.config(text="running…", fg=T.TXT_3)

        def work():
            # BatchMode: key-based only, never prompt for a password
            rc, out = S.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, cmd],
                            timeout=30)
            q.put(("ssh_out", (rc, out)))
        S.in_thread(work)

    # ---- pump
    def pump():
        drained = False
        while True:
            try:
                kind, *rest = q.get_nowait()
            except Exception:
                break
            drained = True
            if kind == "ble_dev":
                st["ble"].append(rest[0])
                if st["tab"] == "ble":
                    render_ble_list()
            elif kind == "ble_done":
                st["ble_scan"] = False
                T.set_btn(scan_btn, "Scan", "primary")
                ble_status.config(text="%d found" % len(st["ble"]), fg=T.TXT_3)
            elif kind == "ble_err":
                st["ble_scan"] = False
                T.set_btn(scan_btn, "Scan", "primary")
                ble_status.config(text=rest[0], fg=S.AMBER)
            elif kind == "ble_svc":
                addr, svcs = rest[0]
                if addr == st["ble_sel"]:
                    st["ble_services"] = svcs
                    ble_status.config(text="connected", fg=T.TXT)
                    render_ble_detail()
            elif kind == "mqtt_ready":
                after_connect()
            elif kind == "mqtt_err":
                mqtt_status.config(text=rest[0], fg=S.AMBER)
                mqtt_disconnect()
            elif kind == "msg":
                topic, payload = rest
                info = st["topics"].setdefault(topic, {"n": 0, "t": 0, "val": ""})
                info["val"], info["t"] = payload, time.time()
                info["n"] += 1
            elif kind == "status":
                (mqtt_status if st["tab"] == "mqtt" else ssh_status).config(
                    text=rest[0], fg=T.TXT_3)
            elif kind == "ssh_out":
                rc, out = rest[0]
                cmd_out.config(state="normal")
                cmd_out.insert("end", out or "(no output)")
                if rc != 0:
                    cmd_out.insert("end", "\n[exit %s]" % rc)
                cmd_out.config(state="disabled")
                ssh_status.config(text="done" if rc == 0 else "exit %s" % rc,
                                  fg=T.TXT if rc == 0 else S.AMBER)
        if drained and st["tab"] == "mqtt":
            render_mqtt()
        if not st["closed"]:
            root.after(300, pump)

    def on_close():
        st["closed"] = True
        if st["mqtt"]:
            try:
                m = st["mqtt"]
                m.loop_stop() if hasattr(m, "loop_stop") else None
                m.disconnect() if hasattr(m, "disconnect") else m.close()
            except Exception:
                pass
        root.destroy()

    S.bind_quit(root, on_close)
    S.header_quit(top, root, F, on_close)

    render_ble_list()
    render_ble_detail()
    render_hosts()
    render_mqtt()
    show_tab("ble")
    if demo:
        root.after(400, ble_scan)
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
