#!/usr/bin/env python3
"""flipper.py — Flipper Zero serial-CLI bridge + NFC relay detector (pen-test / hardware).

Two pieces:

  * Bridge — the Flipper Zero exposes a text CLI over USB serial. This passes commands through and
    parses the responses (device_info, storage list, subghz/nfc/ir/rfid). Reading state and
    *receiving* RF are passive and ungated; anything that **emits** — subghz tx, nfc/rfid/ibutton
    emulate or write, ir tx, badusb, driving a GPIO — transmits or impersonates, so it goes through
    the engagement gate (scoped, authorized, evidence-logged). We only hand the CLI string to the
    device after the gate says yes.

  * NFC relay detector — a defensive check. An NFC relay/mole attack tunnels the card↔reader
    exchange over a second link, which adds round-trip latency. We score ISO-14443 APDU exchange
    timings against a baseline and flag the excess. Pure + testable.
"""
import os
import sys

import engagement

# ---- the read-only allowlist (audit G3). Anything not listed is "emit" and goes through the
# engagement gate. Key: leading tokens; value: how many further arguments may follow.
READ_ALLOW = {
    ("device_info",): 0, ("info", "device"): 0, ("info", "power"): 0, ("help",): 0, ("?",): 0,
    ("uptime",): 0, ("free",): 0, ("free_blocks",): 0, ("ps",): 0, ("date",): 0,
    ("power", "info"): 0, ("bt", "hci_info"): 0, ("log",): 1,
    ("storage", "info"): 1, ("storage", "list"): 1, ("storage", "tree"): 1, ("storage", "stat"): 1,
    ("storage", "read"): 1, ("storage", "md5"): 1, ("storage", "timestamp"): 1,
    ("subghz", "rx"): 2, ("ir", "rx"): 1, ("rfid", "read"): 1, ("nfc", "detect"): 0,
}

# USB VID:PID -> device class for the serial console (audit G2). Anything else is "unknown".
# A Flipper is trusted as a Flipper only when the product string says so (0483:5740 is the generic
# STM32 virtual COM port).
USB_CLASSES = {
    "0483:5740": "flipper",
    "10c4:ea60": "esp32", "1a86:7523": "esp32", "1a86:55d4": "esp32", "303a:1001": "esp32",
    "303a:0002": "esp32", "0403:6001": "esp32",
    "1d50:606f": "slcan", "16d0:117e": "slcan", "ad50:60c4": "slcan",
}
EMITTER_CLASSES = ("flipper", "esp32", "slcan")


def _has_control(cli):
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in str(cli))


def classify_command(cli):
    """'read' only for an allowlisted read-only Flipper command; everything else - including any
    command carrying CR / LF / another control character (a second command after a newline) - is
    'emit' (transmits / impersonates / injects / changes state, gated)."""
    cli = str(cli)
    if _has_control(cli):
        return "emit"
    low = [t.lower() for t in cli.split()]
    if not low:
        return "emit"
    for n in (2, 1):
        key = tuple(low[:n])
        if len(key) == n and key in READ_ALLOW:
            return "read" if len(low) - n <= READ_ALLOW[key] else "emit"
    return "emit"


def identify_port(port, sys_root="/sys"):
    """(device class, device label) for a serial port, from its USB VID:PID in sysfs.
    label is 'usb:vvvv:pppp' for a USB device, else 'port:<name>'; class is one of
    flipper / esp32 / slcan / unknown (or demo for the synthetic device)."""
    if port in (None, "", "demo"):
        return "demo", "demo"
    name = os.path.basename(os.path.realpath(str(port))) or os.path.basename(str(port))
    d = os.path.realpath(os.path.join(sys_root, "class", "tty", name, "device"))
    for _ in range(5):
        if not d or not os.path.isdir(d):
            break
        vid, pid = os.path.join(d, "idVendor"), os.path.join(d, "idProduct")
        if os.path.isfile(vid) and os.path.isfile(pid):
            try:
                v = open(vid).read().strip().lower()
                p = open(pid).read().strip().lower()
                prod = ""
                if os.path.isfile(os.path.join(d, "product")):
                    prod = open(os.path.join(d, "product")).read().strip().lower()
            except OSError:
                break
            key = "%s:%s" % (v, p)
            cls = USB_CLASSES.get(key, "unknown")
            if cls == "flipper" and "flipper" not in prod:
                cls = "unknown"
            return cls, "usb:" + key
        d = os.path.dirname(d)
    return "unknown", "port:" + name


NEWLINES = ("\r\n", "\n", "\r")


def prepare_command(cli, target=None, evidence_chain=None, device="demo", kind="flipper",
                    newline="\r\n"):
    """Gate one line for a serial device. Returns (ok, reason, ticket); the ticket authorizes
    exactly cli + CRLF, written by executor.write().

      * any control character (CR / LF / ...)              -> refused outright
      * the synthetic demo device (kind 'demo')            -> allowed (no hardware)
      * a Flipper and an allowlisted read command          -> allowed, ungated
      * anything else (Flipper emit; ESP32 / slcan / unknown devices are read-only until an
        engagement is active)                              -> engagement gate, label-only:
        the scope must name the device (usb:vvvv:pppp / port:name) or the given target label."""
    import executor
    cli = str(cli)
    if _has_control(cli):
        return False, "refused: control characters (CR/LF) in a serial command", None
    if newline not in NEWLINES:
        return False, "refused: line ending must be CRLF, LF or CR", None
    payload = (cli + newline).encode("utf-8", "replace")
    meta = {"device": device, "class": kind}
    if kind == "demo":
        t = executor.issue(payload=payload, recheck=lambda: (True, "demo device"),
                           label="serial:demo", binding="demo", reason="demo device", meta=meta)
        return True, "demo device (synthetic, no hardware)", t
    if kind == "flipper" and classify_command(cli) == "read":
        t = executor.issue(payload=payload, recheck=lambda: (True, "allowlisted read"),
                           label="serial:flipper:read", binding="read-only",
                           reason="read command (allowlisted)", meta=meta)
        return True, "read command (allowlisted, ungated)", t
    verb = (cli.split() or ["?"])[0]
    tgt, tkind = (target, "label") if target else (device, "device")
    return engagement.issue("serial:%s:%s" % (kind, verb), tgt, payload=payload, kind=tkind,
                            evidence_chain=evidence_chain, label="serial:%s" % kind, meta=meta)


def parse_device_info(text):
    """Parse Flipper `device_info` output ('key    : value' per line) into a dict."""
    info = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k:
                info[k] = v
    return info


def find_port(ports):
    """Pick the Flipper's serial device from a list of /dev/serial/by-id entries (or similar)."""
    for p in ports:
        if "flipper" in p.lower():
            return p
    return ports[0] if ports else None


def relay_latency_suspect(timings_ms, baseline_ms=20.0, margin_ms=8.0):
    """Flag a likely NFC relay from APDU round-trip timings (ms). A relay tunnels the exchange over a
    second hop, inflating latency; if the median sits more than `margin` above the known-good
    `baseline`, it's suspicious. Returns a dict (suspect, median_ms, excess_ms, n)."""
    import statistics
    if not timings_ms:
        return {"suspect": False, "median_ms": None, "excess_ms": None, "n": 0}
    med = statistics.median(timings_ms)
    return {"suspect": med > baseline_ms + margin_ms, "median_ms": med,
            "excess_ms": med - baseline_ms, "n": len(timings_ms)}


class Demo:
    """Synthetic Flipper responses for offline UI + tests."""

    DEVICE_INFO = ("hardware_model       : Flipper Zero\n"
                   "hardware_name        : Yosemite\n"
                   "firmware_version     : 0.98.3\n"
                   "radio_stack_type     : 1\n"
                   "battery_level        : 87\n")

    def device_info(self):
        return self.DEVICE_INFO

    def normal_timings(self):
        return [18.0, 21.0, 19.5, 20.5, 22.0]        # direct read, ~baseline

    def relay_timings(self):
        return [44.0, 51.0, 47.5, 49.0, 46.0]        # tunnelled, inflated


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Flipper")
    S.settings("flipper", {})
    root, F = S.make_root("Flipper Bridge", parent=parent)
    import tkinter as tk
    T = S.T
    demo = Demo()

    top = S.top_bar(root, F, "Flipper Bridge", "Serial CLI · read ungated · emit gated")
    S.pill(top, F, "Demo")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True, padx=T.px(10), pady=T.px(8))

    info = parse_device_info(demo.device_info())
    tk.Label(body, bg=S.BG, fg=T.TXT_2, font=F["map"], anchor="w", justify="left",
             text="device: %s  fw %s  batt %s%%"
                  % (info.get("hardware_model", "?"), info.get("firmware_version", "?"),
                     info.get("battery_level", "?"))).pack(fill="x")

    row = tk.Frame(body, bg=S.BG)
    row.pack(fill="x", pady=(T.px(8), 0))
    ent = tk.Entry(row, bg=T.SURFACE_2, fg=T.TXT, font=F["map"], insertbackground=T.TXT, width=28)
    ent.pack(side="left", padx=(0, T.px(6)))
    ent.insert(0, "nfc detect")
    out = tk.Label(body, text="", bg=T.SURFACE, fg=T.TXT, font=F["map"], anchor="w", justify="left",
                   padx=T.px(10), pady=T.px(8))
    out.pack(fill="both", expand=True, pady=(T.px(8), 0))

    def send(_=None):
        cli = ent.get().strip()
        # demo screen: classify + gate only, nothing is written anywhere (no device here)
        ok, why, _t = prepare_command(cli, target=None, device="usb:0483:5740", kind="flipper")
        kind = classify_command(cli)
        if kind == "emit" and not ok:
            out.config(text="⟶ %s\n  EMIT command — %s" % (cli, why), fg=S.AMBER)
        elif kind == "emit":
            out.config(text="⟶ %s\n  %s (demo: not sent)" % (cli, why), fg=S.AMBER)
        else:
            out.config(text="⟶ %s\n  read command — allowlisted (demo: not sent)" % cli,
                       fg=T.TXT)

    S.btn(row, "Send", send, F, padx=12, pady=5, kind="primary").pack(side="left")
    ent.bind("<Return>", send)

    def relay_check():
        r = relay_latency_suspect(demo.relay_timings())
        verdict = "⚠ RELAY SUSPECTED" if r["suspect"] else "clean"
        out.config(text="NFC relay check (demo relayed exchange)\n  median %.1f ms (+%.1f over baseline)  →  %s"
                        % (r["median_ms"], r["excess_ms"], verdict),
                   fg=S.RED if r["suspect"] else S.GREEN)

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "NFC relay check", relay_check, F, padx=12, pady=5, kind="ghost").pack(
        side="left", padx=(10, 6), pady=6)
    if not parent:
        S.btn(bar, "Quit", lambda: root.destroy(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))
    S.bind_quit(root, lambda: root.destroy())
    if "--demo" in sys.argv:
        root.after(300, send)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
