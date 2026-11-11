#!/usr/bin/env python3
"""Scout: site survey and self-testing for YOUR OWN network and RF environment.

Four tabs, all diagnostic and receive-only:
  - Device   : the read-only self-audit (exposed ports, firewall, SSH, TX-lockout) from doctor.py
  - Network  : discovers hosts on this device's own subnet and flags open ports / exposed services
  - Wi-Fi    : nearby access points - SSID, signal, channel, security (passive scan)
  - Spectrum : an SDR power sweep across a band - noise floor and what's transmitting (receive-only)

Nothing here transmits, cracks, deauths or spoofs, and the network scan is scoped to the local
subnet this device is already on. It's for checking your own setup, not reaching anyone else's.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402

DEFAULTS = {
    "ports": [22, 80, 443, 445, 139, 21, 23, 3389, 5900, 8080, 8081, 3306, 5432, 6379,
              11434, 4403, 2947, 1234, 4532, 8073, 62078, 32400, 8123, 1883],
    "ping_sweep": True,
    "spectrum_band": "70cm (420-450)",
    "spectrum_gain": 30,
    "wifi_cmd": "nmcli -t -f SSID,SIGNAL,CHAN,SECURITY,BSSID dev wifi list",
}

# notable services worth calling out when found open on the LAN
NOTABLE = {
    22: "SSH", 23: "Telnet (cleartext!)", 21: "FTP", 445: "SMB", 139: "NetBIOS",
    3389: "RDP", 5900: "VNC", 3306: "MySQL", 5432: "Postgres", 6379: "Redis (often no auth)",
    11434: "Ollama (LLM, no auth!)", 4403: "Meshtastic", 2947: "gpsd", 1234: "rtl_tcp",
    4532: "rigctl", 8073: "OpenWebRX", 62078: "iOS sync", 32400: "Plex", 1883: "MQTT",
    80: "HTTP", 443: "HTTPS", 8080: "HTTP-alt", 8081: "HTTP-alt", 8123: "Home Assistant",
}
RISKY = {23, 445, 139, 3389, 5900, 6379, 11434, 3306, 5432, 1883}

EXPOSURE = {
    11434: "Ollama has no authentication — bind to 127.0.0.1 or your tailnet IP",
    6379: "Redis often ships with no auth — set requirepass or bind to localhost",
    1883: "MQTT broker — require auth/TLS if it carries anything real",
    23: "Telnet is cleartext — use SSH instead",
    21: "FTP is cleartext — prefer SFTP",
    445: "SMB exposed — restrict to trusted hosts / VPN",
    139: "NetBIOS exposed — restrict or disable",
    3389: "RDP exposed — put behind a VPN and enable NLA",
    5900: "VNC exposed — tunnel over SSH and set a password",
    3306: "MySQL reachable — bind to localhost or firewall it",
    5432: "Postgres reachable — bind to localhost or firewall it",
    30003: "ADS-B feed (SBS) — receive-only data, but open to the LAN; firewall in the field",
    30005: "ADS-B feed (beast) — receive-only data, but open to the LAN; firewall in the field",
}


def has_nmap():
    return bool(shutil.which("nmap"))


def nmap_scan(cidr, on_host, on_progress, stop_flag, procs=None):
    """Service/version scan of the LOCAL subnet with nmap (connect scan, no root needed).
    Parses greppable output line by line and reports each host as it finishes."""
    cmd = ["nmap", "-sV", "--version-light", "-T4", "--open", "-oG", "-", cidr]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True)
    except OSError:
        return False
    if procs is not None:
        procs.append(proc)     # so Stop / on_close can kill it without waiting for output
    me = own_ipv4()
    for line in proc.stdout:
        if stop_flag.is_set():
            try:
                proc.terminate()
            except OSError:
                pass
            break
        line = line.strip()
        if line.startswith("# ") and "scanned" in line.lower():
            on_progress("scanning…", 0.5)
        if not line.startswith("Host:") or "Ports:" not in line:
            continue
        m = re.match(r"Host:\s+(\S+)\s+\(([^)]*)\)", line)
        if not m:
            continue
        ip, name = m.group(1), m.group(2)
        ports = []
        pfield = line.split("Ports:", 1)[1].split("\t")[0]
        for entry in pfield.split(","):
            parts = entry.strip().split("/")
            if len(parts) >= 5 and parts[1] == "open":
                port = int(parts[0])
                svc = parts[4] or ""
                ver = parts[6] if len(parts) > 6 else ""
                ports.append({"port": port, "svc": svc, "ver": ver.strip()})
        on_host({"ip": ip, "name": name, "ports2": sorted(ports, key=lambda x: x["port"]),
                 "me": ip == me})
    proc.wait()
    return True


BANDS = {
    "FM broadcast (88-108)": (88e6, 108e6, 100e3),
    "Airband (118-137)": (118e6, 137e6, 50e3),
    "2m ham (144-148)": (144e6, 148e6, 25e3),
    "433 ISM (433-435)": (433e6, 435e6, 10e3),
    "70cm (420-450)": (420e6, 450e6, 100e3),
    "900 ISM (902-928)": (902e6, 928e6, 100e3),
    "ADS-B (1088-1092)": (1088e6, 1092e6, 20e3),
}


def own_ipv4():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def subnet_hosts(ip):
    """The /24 the device is on, as a list of host IPs (minus network/broadcast)."""
    if not ip:
        return [], ""
    parts = ip.split(".")
    base = ".".join(parts[:3])
    return ["%s.%d" % (base, i) for i in range(1, 255)], base + ".0/24"


def arp_hosts():
    """Hosts already known from the ARP/neighbour cache (passive, no scanning)."""
    out = {}
    try:
        r = subprocess.run(["ip", "neigh"], capture_output=True, text=True, timeout=4)
        for line in r.stdout.splitlines():
            m = re.match(r"(\d+\.\d+\.\d+\.\d+)\s+.*\s+(\w+)$", line)
            if m and m.group(2) not in ("FAILED", "INCOMPLETE"):
                out[m.group(1)] = True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return out


def tcp_open(ip, port, timeout=0.4):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        r = s.connect_ex((ip, port))
        s.close()
        return r == 0
    except OSError:
        return False


def rdns(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror):
        return ""


class NetScanner:
    """Threaded host discovery + port scan of the local subnet. Progress via callbacks."""

    def __init__(self, ports, on_host, on_done, on_progress):
        self.ports = ports
        self.on_host, self.on_done, self.on_progress = on_host, on_done, on_progress
        self.stop_flag = threading.Event()

    def stop(self):
        self.stop_flag.set()

    def run(self, ping_sweep=True):
        threading.Thread(target=self._run, args=(ping_sweep,), daemon=True).start()

    def _run(self, ping_sweep):
        ip = own_ipv4()
        hosts, cidr = subnet_hosts(ip)
        self.on_progress("scanning %s …" % cidr, 0.0)
        live = dict(arp_hosts())
        live[ip] = True if ip else None
        if ping_sweep and hosts:
            self._ping_sweep(hosts, live)
        live_ips = [h for h in hosts if h in live]
        if ip and ip not in live_ips:
            live_ips.insert(0, ip)
        total = max(1, len(live_ips))
        done = 0
        for host in live_ips:
            if self.stop_flag.is_set():
                break
            openp = self._scan_ports(host)
            done += 1
            self.on_progress("%d/%d hosts" % (done, total), done / total)
            name = rdns(host)
            self.on_host({"ip": host, "name": name, "ports": openp, "me": host == ip})
        self.on_done(not self.stop_flag.is_set())

    def _ping_sweep(self, hosts, live):
        import queue as _q
        q = _q.Queue()
        for h in hosts:
            q.put(h)

        def worker():
            while not q.empty() and not self.stop_flag.is_set():
                try:
                    h = q.get_nowait()
                except _q.Empty:
                    return
                try:
                    r = subprocess.run(["ping", "-c", "1", "-W", "1", h],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                    if r.returncode == 0:
                        live[h] = True
                except (OSError, subprocess.TimeoutExpired):
                    pass
        ts = [threading.Thread(target=worker, daemon=True) for _ in range(40)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=20)

    def _scan_ports(self, host):
        import queue as _q
        found = []
        q = _q.Queue()
        for p in self.ports:
            q.put(p)

        def worker():
            while not q.empty() and not self.stop_flag.is_set():
                try:
                    p = q.get_nowait()
                except _q.Empty:
                    return
                if tcp_open(host, p):
                    found.append(p)
        ts = [threading.Thread(target=worker, daemon=True) for _ in range(16)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=8)
        return sorted(found)


def wifi_scan(cmd):
    """Parse nmcli (preferred, no root) into a list of APs. Falls back to a helpful message."""
    if not shutil.which(cmd.split()[0]):
        return None, "%s not found - install NetworkManager (nmcli) for a no-root Wi-Fi scan." % cmd.split()[0]
    try:
        r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "scan failed: %s" % str(e)[:60]
    aps = []
    for line in r.stdout.splitlines():
        # nmcli -t escapes ':' in fields as '\:'; split on unescaped ':'
        parts = re.split(r"(?<!\\):", line)
        parts = [p.replace("\\:", ":") for p in parts]
        if len(parts) >= 4:
            ssid, signal, chan, sec = parts[0], parts[1], parts[2], parts[3]
            bssid = parts[4] if len(parts) > 4 else ""
            try:
                sig = int(signal)
            except ValueError:
                sig = 0
            aps.append({"ssid": ssid or "(hidden)", "signal": sig, "chan": chan,
                        "sec": sec or "open", "bssid": bssid})
    aps.sort(key=lambda a: -a["signal"])
    return aps, ""


# ---- detector mode: passive baseline + diff (own-network only, receive-only) -------------
BASELINE_PATH = os.path.join(os.path.expanduser("~"), ".config", "uconsole-suite", "scout_baseline.json")


def load_baseline():
    try:
        with open(BASELINE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_baseline(aps, hosts=None):
    data = {"bssids": {a["bssid"]: {"ssid": a["ssid"], "sec": a["sec"]}
                       for a in aps if a.get("bssid")},
            "t": time.time()}
    if hosts is not None:
        data["macs"] = sorted({h.get("mac") for h in hosts if h.get("mac")})
    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    with open(BASELINE_PATH, "w") as f:
        json.dump(data, f)
    return data


def wifi_findings(aps, baseline):
    """Passive anomaly flags: (severity, bssid, message). No transmit, no association."""
    out = []
    by_ssid = {}
    for a in aps:
        if a["ssid"] and a["ssid"] != "(hidden)":
            by_ssid.setdefault(a["ssid"], set()).add(a.get("bssid") or "")
    for ssid, bssids in by_ssid.items():
        real = [b for b in bssids if b]
        if len(real) > 1:
            for b in real:
                out.append(("warn", b, "%s seen on %d BSSIDs (possible twin/repeater)" % (ssid, len(real))))
    known = baseline.get("bssids", {})
    known_secure = {v["ssid"] for v in known.values() if v.get("sec") not in ("", "open", "--")}
    for a in aps:
        b, opn = a.get("bssid"), a["sec"] in ("", "open", "--")
        if known and b and b not in known:
            out.append(("new", b, "new AP not in baseline"))
        if opn and a["ssid"] in known_secure:
            out.append(("alert", b, "OPEN network using a normally-secured name: %s" % a["ssid"]))
    return out


def main():
    S.single_instance("Scout")
    s, spath = S.settings("scout", DEFAULTS)
    root, F = S.make_root("Scout")
    import tkinter as tk
    T = S.T

    top = S.top_bar(root, F, "Scout", "your own network + RF")
    tab_pill = S.pill(top, F, "NETWORK")

    tabbar = tk.Frame(root, bg=T.SURFACE)
    tabbar.pack(fill="x")
    content = tk.Frame(root, bg=S.BG)
    content.pack(fill="both", expand=True)

    tabs = {}
    cur = ["network"]
    frames = {}
    for key in ("device", "network", "wifi", "spectrum"):
        frames[key] = tk.Frame(content, bg=S.BG)

    def show_tab(name):
        cur[0] = name
        tab_pill.config(text=name.upper())
        for k, f in frames.items():
            f.pack_forget()
        frames[name].pack(fill="both", expand=True)
        for k, b in tabs.items():
            S.set_btn(b, kind="primary" if k == name else "ghost")
        builders[name]()

    for key, label in (("device", "Device"), ("network", "Network"), ("wifi", "Wi-Fi"),
                       ("spectrum", "Spectrum")):
        b = S.btn(tabbar, label, lambda k=key: show_tab(k), F, padx=16, pady=6,
                  kind="ghost")
        b.pack(side="left", padx=(14 if key == "device" else 4, 0), pady=6)
        tabs[key] = b

    q = __import__("queue").Queue()

    # ---------------------------------------------------------------- Device tab
    dev_built = [False]

    def build_device():
        if dev_built[0]:
            return
        dev_built[0] = True
        wrap = tk.Frame(frames["device"], bg=S.BG, padx=T.px(18), pady=T.px(12))
        wrap.pack(fill="both", expand=True)
        txt = tk.Text(wrap, bg=S.BG, fg=S.TXT, font=F["sm"], bd=0, highlightthickness=0, wrap="word",
                      spacing1=2, state="disabled")
        for tag, col in (("sec", T.TXT_3), ("ok", T.OK), ("fail", T.ALERT), ("info", T.TXT_3),
                         ("name", S.TXT), ("fix", T.ACCENT), ("det", T.TXT_2)):
            txt.tag_config(tag, foreground=col)
        txt.tag_config("name", font=F["smb"])
        txt.tag_config("sec", font=F["lbl"])
        txt.tag_config("fix", font=F["map"], lmargin1=T.px(40), lmargin2=T.px(40))
        txt.tag_config("det", font=F["map"], lmargin1=T.px(40), lmargin2=T.px(40))
        txt.pack(fill="both", expand=True)
        dev_run = {"on": False}

        def run():
            if dev_run["on"]:
                return
            dev_run["on"] = True
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.insert("end", "Read-only self-audit of THIS device. Nothing is transmitted.\n", "info")
            txt.config(state="disabled")

            def work():
                import doctor
                seen = {"sec": None}
                for section, name, ok, detail, fix in doctor.run_security():
                    q.put(("dev", section, name, ok, detail, fix, seen))
                q.put(("dev_done",))
                dev_run["on"] = False
            S.in_thread(work)
        frames["device"]._run = run
        frames["device"]._txt = txt      # pump() writes the audit results here

        # --- actions: re-run the audit, or show the firewall plan from harden.sh
        barf = tk.Frame(wrap, bg=S.BG)
        barf.pack(fill="x", pady=(T.px(8), 0))
        S.btn(barf, "Re-run audit", run, F, kind="ghost").pack(side="left")

        def show_harden():
            app = os.path.dirname(os.path.abspath(__file__))
            script = os.path.join(app, "harden.sh")
            txt.config(state="normal")
            txt.delete("1.0", "end")
            if not os.path.exists(script):
                txt.insert("end", "harden.sh not found in the app folder — re-run the installer.\n", "fail")
                txt.config(state="disabled")
                return
            txt.insert("end", "Firewall plan (nothing changed — this is a dry run):\n\n", "info")
            txt.config(state="disabled")

            def work():
                try:
                    r = subprocess.run(["bash", script, "--dry-run"], capture_output=True,
                                       text=True, timeout=20)
                    out = r.stdout or r.stderr or "(no output)"
                except Exception as e:
                    out = "couldn't run harden.sh: %s" % e
                q.put(("harden_out", out, script))
            S.in_thread(work)
        S.btn(barf, "Harden (firewall)…", show_harden, F, kind="ghost").pack(side="left", padx=(8, 0))
        run()

    # ---------------------------------------------------------------- Network tab
    net_state = {"scanner": None, "built": False}

    def build_network():
        if net_state["built"]:
            return
        net_state["built"] = True
        fr = frames["network"]
        bar = tk.Frame(fr, bg=S.BG, padx=T.px(18), pady=T.px(10))
        bar.pack(fill="x")
        scan_btn = S.btn(bar, "Scan my network", lambda: toggle_scan(), F, kind="primary")
        scan_btn.pack(side="left")
        net_prog = tk.Label(bar, text="", font=F["sm"], fg=T.TXT_3, bg=S.BG)
        net_prog.pack(side="left", padx=14)
        tk.Label(fr, text="Hosts on your local subnet and the ports they expose. Scoped to your own "
                 "network only.", font=F["map"], fg=T.TXT_3, bg=S.BG, anchor="w").pack(
            fill="x", padx=T.px(18))
        rows = tk.Frame(fr, bg=S.BG)
        rows.pack(fill="both", expand=True, padx=T.px(18), pady=(8, 0))
        net_state.update({"rows": rows, "btn": scan_btn, "prog": net_prog, "hosts": []})

        net_state["stop_flag"] = None

        def toggle_scan():
            if net_state.get("scanner") or net_state.get("stop_flag"):
                sc = net_state.get("scanner")
                if sc:
                    sc.stop()
                if net_state.get("stop_flag"):
                    net_state["stop_flag"].set()
                kill_nmap()
                net_state["sid"] = net_state.get("sid", 0) + 1   # ignore the old scan's output
                net_state["scanner"] = None
                net_state["stop_flag"] = None
                S.set_btn(scan_btn, "Scan my network", "primary")
                return
            for w in rows.winfo_children():
                w.destroy()
            net_state["hosts"] = []
            sid = net_state["sid"] = net_state.get("sid", 0) + 1
            S.set_btn(scan_btn, "Stop", "danger")
            ip = own_ipv4()
            _, cidr = subnet_hosts(ip)
            net_prog.config(text=("nmap " if has_nmap() else "") + "scanning %s…" % cidr)
            if has_nmap():
                sf = threading.Event()
                net_state["stop_flag"] = sf

                def work():
                    nmap_scan(cidr, lambda h: q.put(("net_host", h, sid)),
                              lambda t, f: q.put(("net_prog", t, f, sid)), sf,
                              procs=net_state.setdefault("nmap_procs", []))
                    q.put(("net_done", not sf.is_set(), sid))
                S.in_thread(work)
            else:
                sc = NetScanner(s["ports"],
                                on_host=lambda h: q.put(("net_host", h, sid)),
                                on_done=lambda ok: q.put(("net_done", ok, sid)),
                                on_progress=lambda t, f: q.put(("net_prog", t, f, sid)))
                net_state["scanner"] = sc
                sc.run(ping_sweep=s.get("ping_sweep", True))
        net_state["toggle"] = toggle_scan

        def kill_nmap():
            for p in net_state.get("nmap_procs", []):
                S.stop_group(p, grace=1.0)   # own session: it would outlive Scout otherwise
            net_state["nmap_procs"] = []
        net_state["kill_nmap"] = kill_nmap
        if os.environ.get("UCS_SCAN"):
            root.after(500, toggle_scan)

    def draw_net_host(h):
        rows = net_state["rows"]
        row = tk.Frame(rows, bg=S.BG)
        row.pack(fill="x", pady=2, anchor="w")
        ipc = T.ACCENT if h["me"] else S.TXT
        top = tk.Frame(row, bg=S.BG)
        top.pack(fill="x")
        tk.Label(top, text=h["ip"] + (" (this device)" if h["me"] else ""),
                 font=F["monob"] if "monob" in F else F["mono"], fg=ipc, bg=S.BG, width=22,
                 anchor="w").pack(side="left")
        tk.Label(top, text=h["name"][:34], font=F["map"], fg=T.TXT_3, bg=S.BG, anchor="w").pack(side="left")
        svcs = h.get("ports2")
        if svcs is not None:
            if not svcs:
                tk.Label(row, text="   no open services", font=F["map"], fg=T.TXT_3, bg=S.BG,
                         anchor="w").pack(fill="x")
            for sv in svcs:
                p = sv["port"]
                risky = p in RISKY
                line = tk.Frame(row, bg=S.BG)
                line.pack(fill="x", padx=(T.px(24), 0))
                label = "%d  %s %s" % (p, sv["svc"] or NOTABLE.get(p, ""), sv["ver"])
                tk.Label(line, text=label.strip(), font=F["mono"], fg=T.AMBER if risky else S.TXT,
                         bg=S.BG, anchor="w").pack(side="left")
                if p in EXPOSURE:
                    tk.Label(line, text="  ⚠ " + EXPOSURE[p], font=F["map"], fg=T.ALERT if risky else T.TXT_3,
                             bg=S.BG, anchor="w").pack(side="left")
        else:
            # pure-python fallback (ports is a list of ints)
            ports = h.get("ports", [])
            if ports:
                parts = ["%d %s" % (p, NOTABLE.get(p, "")) if p in NOTABLE else str(p) for p in ports]
                risky = any(p in RISKY for p in ports)
                tk.Label(row, text="   " + "  ".join(parts).strip(), font=F["map"],
                         fg=T.AMBER if risky else S.TXT, bg=S.BG, anchor="w").pack(fill="x")
                for p in ports:
                    if p in EXPOSURE:
                        tk.Label(row, text="   ⚠ %d: %s" % (p, EXPOSURE[p]), font=F["map"], fg=T.ALERT,
                                 bg=S.BG, anchor="w").pack(fill="x")
            else:
                tk.Label(row, text="   no common ports open", font=F["map"], fg=T.TXT_3, bg=S.BG,
                         anchor="w").pack(fill="x")

    # ---------------------------------------------------------------- Wi-Fi tab
    wifi_state = {"built": False}

    def build_wifi():
        if wifi_state["built"]:
            return
        wifi_state["built"] = True
        fr = frames["wifi"]
        bar = tk.Frame(fr, bg=S.BG, padx=T.px(18), pady=T.px(10))
        bar.pack(fill="x")
        S.btn(bar, "Rescan", lambda: do_wifi(), F, kind="primary").pack(side="left")

        def set_baseline():
            aps = wifi_state.get("last_aps")
            if aps:
                save_baseline(aps)
                wifi_state["msg"].config(text="baseline set (%d APs) — new/rogue APs now flagged" % len(aps),
                                         fg=T.OK)
        S.btn(bar, "Set baseline", set_baseline, F, kind="ghost").pack(side="left", padx=(8, 0))
        wifi_msg = tk.Label(bar, text="", font=F["sm"], fg=T.TXT_3, bg=S.BG)
        wifi_msg.pack(side="left", padx=14)
        hdr = tk.Frame(fr, bg=S.BG, padx=T.px(18))
        hdr.pack(fill="x", pady=(6, 2))
        for t, w in (("SSID", 26), ("Signal", 14), ("Chan", 8), ("Security", 18)):
            tk.Label(hdr, text=t, font=F["lbl"], fg=T.TXT_3, bg=S.BG, width=w, anchor="w").pack(side="left")
        rows = tk.Frame(fr, bg=S.BG)
        rows.pack(fill="both", expand=True, padx=T.px(18))
        wifi_state.update({"rows": rows, "msg": wifi_msg})

        def do_wifi():
            wifi_msg.config(text="scanning…")
            for w in rows.winfo_children():
                w.destroy()

            def work():
                aps, err = wifi_scan(s.get("wifi_cmd", DEFAULTS["wifi_cmd"]))
                try:
                    mine = S.network_status().get("ssid")   # runs iw/ip: keep it off the Tk thread
                except Exception:
                    mine = None
                q.put(("wifi", aps, err, mine))
            S.in_thread(work)
        wifi_state["do"] = do_wifi
        do_wifi()

    def draw_wifi(aps, err, mine=None):
        rows = wifi_state["rows"]
        for w in rows.winfo_children():
            w.destroy()
        if aps is None:
            wifi_state["msg"].config(text=err, fg=T.ALERT)
            return
        wifi_state["last_aps"] = aps
        # passive detector: flag new/twin/open-impersonation APs against the saved baseline
        baseline = load_baseline()
        findings = wifi_findings(aps, baseline)
        flagged = {}
        for sev, bssid, msg in findings:
            flagged.setdefault(bssid, []).append((sev, msg))
        if baseline.get("bssids"):
            n = len(set(b for _, b, _ in findings if b))
            wifi_state["msg"].config(text="%d networks · %d flagged" % (len(aps), n),
                                     fg=T.ALERT if n else T.OK)
        else:
            wifi_state["msg"].config(text="%d networks · no baseline set" % len(aps), fg=T.TXT_3)
        for a in aps:
            flags = flagged.get(a.get("bssid"), [])
            row = tk.Frame(rows, bg=S.BG)
            row.pack(fill="x", pady=1)
            is_me = a["ssid"] == mine
            bars = int(min(4, max(0, (a["signal"] + 10) / 25)))
            mark = "  ⚠" if flags else ("  ●" if is_me else "")
            tk.Label(row, text=a["ssid"][:24] + mark, font=F["smb"] if (is_me or flags) else F["sm"],
                     fg=T.ALERT if flags else (T.ACCENT if is_me else S.TXT), bg=S.BG, width=26,
                     anchor="w").pack(side="left")
            tk.Label(row, text="%d%% %s" % (a["signal"], "▂▄▆█"[:bars]), font=F["mono"], fg=S.TXT,
                     bg=S.BG, width=14, anchor="w").pack(side="left")
            tk.Label(row, text=a["chan"], font=F["mono"], fg=T.TXT_2, bg=S.BG, width=8,
                     anchor="w").pack(side="left")
            opn = a["sec"] in ("", "open", "--")
            tk.Label(row, text="OPEN" if opn else a["sec"][:16], font=F["map"],
                     fg=T.ALERT if opn else T.TXT_3, bg=S.BG, width=18, anchor="w").pack(side="left")
            if flags:
                tk.Label(rows, text="      ⚠ " + "; ".join(m for _, m in flags), font=F["map"],
                         fg=T.ALERT, bg=S.BG, anchor="w").pack(fill="x")

    # ---------------------------------------------------------------- Spectrum tab
    spec_state = {"built": False, "proc": None, "lease": None, "powers": [], "band": None}

    def build_spectrum():
        if spec_state["built"]:
            return
        spec_state["built"] = True
        fr = frames["spectrum"]
        bar = tk.Frame(fr, bg=S.BG, padx=T.px(18), pady=T.px(10))
        bar.pack(fill="x")
        band_btn = S.btn(bar, s.get("spectrum_band", "70cm (420-450)"), lambda: cycle_band(), F, kind="ghost")
        band_btn.pack(side="left")
        sweep_btn = S.btn(bar, "Sweep", lambda: do_sweep(), F, kind="primary")
        sweep_btn.pack(side="left", padx=8)
        spec_msg = tk.Label(bar, text="", font=F["sm"], fg=T.TXT_3, bg=S.BG)
        spec_msg.pack(side="left", padx=10)
        cv = tk.Canvas(fr, bg=S.MAPBG, highlightthickness=0)
        cv.pack(fill="both", expand=True, padx=T.px(18), pady=(6, 14))
        spec_state.update({"cv": cv, "msg": spec_msg, "band_btn": band_btn, "sweep_btn": sweep_btn})
        cv.bind("<Configure>", lambda e: draw_spectrum())

        def cycle_band():
            keys = list(BANDS.keys())
            i = (keys.index(s["spectrum_band"]) + 1) % len(keys) if s.get("spectrum_band") in keys else 0
            s["spectrum_band"] = keys[i]
            S.save_json(spath, s)
            S.set_btn(band_btn, s["spectrum_band"])

        def do_sweep():
            if spec_state["proc"]:
                stop_sweep()
                return
            if spec_state.get("starting"):          # second tap while taking the radio: cancel
                spec_state["starting"] = False
                S.release_bg(root, spec_state.pop("pending_lease"))
                spec_msg.config(text="cancelled", fg=T.TXT_3)
                S.set_btn(sweep_btn, "Sweep", "primary")
                return
            if not shutil.which("rtl_power"):
                spec_msg.config(text="rtl_power not found (sudo apt install rtl-sdr)", fg=T.ALERT)
                return
            lo, hi, step = BANDS[s["spectrum_band"]]
            spec_state["band"] = (lo, hi)
            spec_state["powers"] = []
            lease = S.RtlLease("Scout spectrum", log=lambda m: None)
            lease.on_preempt = lambda: spec_state["stop"]()   # another workspace wants the radio
            spec_state["starting"], spec_state["pending_lease"] = True, lease
            spec_msg.config(text="taking the SDR from the plane map…", fg=T.TXT_3)
            S.set_btn(sweep_btn, "Cancel", "quiet")

            def done(ok, err):
                if not spec_state.get("starting"):
                    return     # cancelled meanwhile; its release is queued after this acquire
                spec_state["starting"] = False
                spec_state.pop("pending_lease", None)
                if not ok:
                    spec_msg.config(text="SDR busy: %s" % str(err)[:50], fg=T.ALERT)
                    S.set_btn(sweep_btn, "Sweep", "primary")
                    return
                spec_state["lease"] = lease
                run_sweep(lo, hi, step)
            S.acquire_bg(root, lease, done)

        def run_sweep(lo, hi, step):
            cmd = ["rtl_power", "-f", "%d:%d:%d" % (int(lo), int(hi), int(step)),
                   "-g", str(int(s.get("spectrum_gain", 30))), "-i", "1", "-1", "-"]
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     stdin=subprocess.DEVNULL, text=True, start_new_session=True)
            except OSError as e:
                spec_msg.config(text=str(e)[:60], fg=T.ALERT)
                _release_spec()
                return
            spec_state["proc"] = p
            S.set_btn(sweep_btn, "Stop", "danger")
            spec_msg.config(text="sweeping %s…" % s["spectrum_band"], fg=T.TXT_3)
            threading.Thread(target=_read_sweep, args=(p,), daemon=True).start()
        spec_state["do_sweep"] = do_sweep
        if os.environ.get("UCS_SWEEP"):
            root.after(400, do_sweep)

        def stop_sweep():
            p = spec_state["proc"]
            spec_state["proc"] = None
            if p and p.poll() is None:
                S.stop_group(p)
            _release_spec()
            S.set_btn(sweep_btn, "Sweep", "primary")

        spec_state["stop"] = stop_sweep

    def _release_spec(sync=False):
        lease = spec_state.get("lease") or (spec_state.pop("pending_lease", None)
                                            if spec_state.get("starting") else None)
        spec_state["lease"], spec_state["starting"] = None, False
        if lease:
            if sync:
                S.release_now(lease)     # quitting: a background release could die with us
            else:
                S.release_bg(root, lease)

    def _read_sweep(proc):
        bins = []
        for line in proc.stdout:
            parts = [x.strip() for x in line.split(",")]
            if len(parts) < 7:
                continue
            try:
                lo = float(parts[2])
                step = float(parts[4])
                dbs = [float(x) for x in parts[6:]]
            except ValueError:
                continue
            for i, db in enumerate(dbs):
                bins.append((lo + i * step, db))
        proc.wait()
        q.put(("spectrum", bins, proc))

    def draw_spectrum():
        cv = spec_state.get("cv")
        if not cv:
            return
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 40:
            return
        bins = spec_state.get("powers") or []
        band = spec_state.get("band")
        if not bins or not band:
            cv.create_text(w / 2, h / 2, text="Press Sweep to scan the band (receive-only).",
                           fill=T.TXT_3, font=F["sm"])
            return
        lo, hi = band
        dbs = [b[1] for b in bins]
        dmin, dmax = min(dbs), max(dbs)
        rng = max(6.0, dmax - dmin)
        noise = sorted(dbs)[len(dbs) // 4]   # 25th percentile ≈ noise floor
        pad = T.px(28)
        gw, gh = w - pad - T.px(8), h - pad - T.px(8)
        x0, y0 = pad, T.px(4)
        # axes
        for frac, lab in ((0, dmin + rng), (0.5, dmin + rng / 2), (1, dmin)):
            yy = y0 + gh * frac
            cv.create_line(x0, yy, x0 + gw, yy, fill=T.RING)
            cv.create_text(x0 - 4, yy, text="%.0f" % lab, anchor="e", fill=T.TXT_3, font=F["map"])
        nf_y = y0 + gh * (1 - (noise - dmin) / rng)
        cv.create_line(x0, nf_y, x0 + gw, nf_y, fill=T.AMBER_DIM, dash=(3, 3))
        cv.create_text(x0 + gw, nf_y - 2, text="noise floor %.0f dB" % noise, anchor="se",
                       fill=T.TXT_3, font=F["map"])
        pts = []
        peaks = []
        bins = sorted(bins)                  # rtl_power hops can arrive out of order
        if len(bins) > 2 * gw:               # more bins than pixels: keep each pixel's peak
            per = {}
            for fr, db in bins:
                px = int(gw * (fr - lo) / max(1.0, hi - lo))
                if px not in per or db > per[px][1]:
                    per[px] = (fr, db)
            bins = [per[k] for k in sorted(per)]
        for fr, db in bins:
            x = x0 + gw * (fr - lo) / max(1.0, hi - lo)
            y = y0 + gh * (1 - (db - dmin) / rng)
            pts += [x, y]
            if db > noise + 10:
                peaks.append((x, y, fr, db))
        if len(pts) >= 4:
            cv.create_line(*pts, fill=S.AMBER, width=1)
        for x, y, fr, db in peaks[:12]:
            cv.create_oval(x - 2, y - 2, x + 2, y + 2, fill=T.ACCENT, outline="")
            cv.create_text(x, y - 6, text="%.1f" % (fr / 1e6), fill=T.ACCENT, font=F["map"])
        for frac in (0, 0.25, 0.5, 0.75, 1):
            fr = lo + (hi - lo) * frac
            x = x0 + gw * frac
            cv.create_text(x, y0 + gh + T.px(10), text="%.0f" % (fr / 1e6), fill=T.TXT_3, font=F["map"])
        cv.create_text(x0 + gw / 2, y0 + gh + T.px(22), text="MHz", fill=T.TXT_3, font=F["map"])

    builders = {"device": build_device, "network": build_network, "wifi": build_wifi,
                "spectrum": build_spectrum}

    # ---------------------------------------------------------------- pump
    def pump():
        while not q.empty():
            item = q.get()
            try:
                pump_item(item)
            except Exception as e:      # one bad item must not stop the pump for good
                print("scout: %s: %r" % (item[0], e), file=sys.stderr)
        root.after(200, pump)

    def pump_item(item):
        k = item[0]
        if k in ("net_host", "net_prog", "net_done") and item[-1] != net_state.get("sid"):
            return                      # from a scan that was stopped / replaced
        if k == "spectrum" and item[2] is not spec_state.get("proc"):
            return                      # a stopped sweep: its proc is no longer ours
        if True:
            if k == "dev":
                _, section, name, ok, detail, fix, seen = item
                txt = frames["device"]._txt
                txt.config(state="normal")
                if section != seen["sec"]:
                    seen["sec"] = section
                    txt.insert("end", "\n" + T.spaced(section) + "\n", "sec")
                mark, tag = ("●  ", "ok") if ok else (("○  ", "info") if ok is None else ("✕  ", "fail"))
                txt.insert("end", mark, tag)
                txt.insert("end", name + "\n", "name")
                txt.insert("end", detail + "\n", "det")
                if ok is False and fix:
                    txt.insert("end", "fix: " + fix + "\n", "fix")
                txt.config(state="disabled")
                txt.see("end")
            elif k == "harden_out":
                _, out, script = item
                txt = frames["device"]._txt
                txt.config(state="normal")
                txt.delete("1.0", "end")
                txt.insert("end", "Firewall plan (dry run — nothing changed):\n", "info")
                txt.insert("end", out + "\n", "det")
                txt.insert("end", "To apply, run this in a terminal (asks before changing anything):\n", "info")
                txt.insert("end", "  bash %s\n" % script, "fix")
                txt.insert("end", "Undo any time with:  bash %s --revert\n" % script, "fix")
                txt.config(state="disabled")
                txt.see("1.0")
            elif k == "net_host":
                net_state["hosts"].append(item[1])
                draw_net_host(item[1])
            elif k == "net_prog":
                net_state["prog"].config(text=item[1])
            elif k == "net_done":
                net_state["scanner"] = None
                net_state["stop_flag"] = None
                S.set_btn(net_state["btn"], "Scan my network", "primary")
                hosts = net_state["hosts"]
                n = len(hosts)

                def host_ports(h):
                    return [sv["port"] for sv in h["ports2"]] if h.get("ports2") is not None else h.get("ports", [])
                exp = sum(1 for h in hosts if any(p in EXPOSURE for p in host_ports(h)))
                tool = "nmap" if has_nmap() else "basic"
                net_state["prog"].config(
                    text="%s: %d hosts, %d with exposed services (⚠)" % (tool, n, exp),
                    fg=T.ALERT if exp else T.TXT_3)
            elif k == "wifi":
                draw_wifi(item[1], item[2], item[3] if len(item) > 3 else None)
            elif k == "spectrum":
                spec_state["powers"] = item[1]
                spec_state["proc"] = None
                _release_spec()
                if "sweep_btn" in spec_state:
                    S.set_btn(spec_state["sweep_btn"], "Sweep", "primary")
                    spec_state["msg"].config(text="%d bins" % len(item[1]), fg=T.TXT_3)
                draw_spectrum()

    def on_close():
        sc = net_state.get("scanner")
        if sc:
            sc.stop()
        if net_state.get("stop_flag"):
            net_state["stop_flag"].set()
        if net_state.get("kill_nmap"):
            net_state["kill_nmap"]()     # nmap runs in its own session: don't leave it scanning
        if spec_state.get("proc"):
            S.stop_group(spec_state["proc"])
        _release_spec(sync=True)
        root.destroy()

    S.bind_quit(root, on_close)
    root.bind("q", lambda e: on_close())
    show_tab(os.environ.get("UCS_TAB", "network"))
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
