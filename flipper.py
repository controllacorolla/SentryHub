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

RF_APPS = {"subghz", "nfc", "rfid", "ir", "ibutton"}
EMIT_VERBS = {"tx", "tx_from_file", "emulate", "write", "send"}


def classify_command(cli):
    """'read' (passive/receive, ungated) or 'emit' (transmits/impersonates/injects, gated)."""
    toks = cli.split()
    if not toks:
        return "read"
    app = toks[0].lower()
    rest = [t.lower() for t in toks[1:]]
    if app == "badusb":
        return "emit"
    if app == "gpio" and "set" in rest:
        return "emit"
    if app in RF_APPS and any(v in rest for v in EMIT_VERBS):
        return "emit"
    return "read"


def prepare_command(cli, target=None, evidence_chain=None):
    """Gate a Flipper CLI command. Returns (ok, reason, cli). Read commands pass ungated; emit
    commands need an authorized, in-scope engagement and are logged."""
    if classify_command(cli) == "emit":
        ok, why = engagement.authorize_action("flipper:" + cli.split()[0], target, evidence_chain)
        if not ok:
            return False, why, None
        return True, why, cli
    return True, "read command (ungated)", cli


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
        ok, why, _cmd = prepare_command(cli, target=None)
        kind = classify_command(cli)
        if kind == "emit" and not ok:
            out.config(text="⟶ %s\n  EMIT command — %s" % (cli, why), fg=S.AMBER)
        elif kind == "emit":
            out.config(text="⟶ %s\n  %s" % (cli, why), fg=S.GREEN)
        else:
            out.config(text="⟶ %s\n  read command — would run on the Flipper (ungated)" % cli,
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
