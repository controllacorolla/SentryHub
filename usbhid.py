#!/usr/bin/env python3
"""usbhid.py — USB-HID keystroke-injection assessment / "BadUSB" (authorized engagements only).

The CM5 can present itself as a USB keyboard (Linux HID gadget) to a host you are authorized to
test, to assess whether that host trusts attached USB devices (locked screen? device control?).
Payloads are written in a Ducky-style script; this module parses them to HID reports. Running a
payload is gated on an open engagement with the target HOST in scope and is logged. Parsing +
report-building are pure and unit-testable; the gadget itself needs the hardware + root.
"""
import os
import sys

import engagement

# HID usage IDs (US keyboard).
_KEYS = {**{chr(c): 0x04 + (c - ord('a')) for c in range(ord('a'), ord('z') + 1)},
         **{str(d): (0x1E + (d - 1) if d else 0x27) for d in range(0, 10)}}
_KEYS.update({"ENTER": 0x28, "ESC": 0x29, "BACKSPACE": 0x2A, "TAB": 0x2B, "SPACE": 0x2C,
              "DELETE": 0x4C, "F4": 0x3D, "-": 0x2D, "/": 0x38, ".": 0x37})
_MODS = {"CTRL": 0x01, "CONTROL": 0x01, "SHIFT": 0x02, "ALT": 0x04, "GUI": 0x08, "WINDOWS": 0x08,
         "META": 0x08}


def keycode(name):
    return _KEYS.get(str(name).lower() if len(str(name)) == 1 else str(name).upper())


def parse_ducky(script):
    """Parse a Ducky-style script into a list of actions:
    {'type':'string','text':..} | {'type':'key','mods':[..],'keys':[..]} | {'type':'delay','ms':..}."""
    actions = []
    for raw in str(script).splitlines():
        line = raw.strip()
        if not line or line.startswith("REM"):
            continue
        parts = line.split(" ", 1)
        cmd = parts[0].upper()
        rest = parts[1] if len(parts) > 1 else ""
        if cmd == "STRING":
            actions.append({"type": "string", "text": rest})
        elif cmd in ("DELAY", "DEFAULTDELAY"):
            try:
                actions.append({"type": "delay", "ms": int(rest)})
            except ValueError:
                pass
        else:
            tokens = line.split()
            mods = [t.upper() for t in tokens if t.upper() in _MODS]
            keys = [t for t in tokens if t.upper() not in _MODS]
            actions.append({"type": "key", "mods": mods, "keys": keys})
    return actions


def hid_report(mods=(), keys=()):
    """Build an 8-byte USB HID keyboard report: [modifier, 0, k1..k6]."""
    mod_byte = 0
    for m in mods:
        mod_byte |= _MODS.get(str(m).upper(), 0)
    codes = [keycode(k) or 0 for k in keys][:6]
    codes += [0] * (6 - len(codes))
    return bytes([mod_byte, 0] + codes)


def prepare(script, target, evidence_chain=None):
    """Gate running a payload against a host. Returns (ok, reason, actions). actions only when an
    engagement with `target` (the host) is open and in scope."""
    ok, why = engagement.authorize_action("usbhid:inject", target, evidence_chain)
    if not ok:
        return False, why, None
    return True, why, parse_ducky(script)


DEMO_PAYLOAD = "REM lock-screen check\nGUI r\nDELAY 300\nSTRING notepad\nENTER"


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    import engagement as E
    if parent is None:
        S.single_instance("USBHID")
    s, spath = S.settings("usbhid", {"target": "", "payload": DEMO_PAYLOAD})
    root, F = S.make_root("USB-HID", parent=parent)
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("usbhid")
    gadget = os.path.isdir("/sys/kernel/config/usb_gadget")

    S.top_bar(root, F, "USB-HID", "Keystroke-injection · engagement-gated")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True, padx=T.px(12), pady=T.px(6))
    trow = tk.Frame(body, bg=S.BG)
    trow.pack(fill="x")
    tk.Label(trow, text="target host", width=12, anchor="w", bg=S.BG, fg=T.TXT_3,
             font=F["sm"]).pack(side="left")
    target = tk.Entry(trow, font=F["mono"])
    target.insert(0, s.get("target", ""))
    target.pack(side="left", fill="x", expand=True)
    tk.Label(body, text="Ducky payload:", anchor="w", bg=S.BG, fg=T.TXT_3, font=F["sm"]).pack(
        fill="x", pady=(T.px(6), 0))
    editor = tk.Text(body, bg=T.SURFACE, fg=S.TXT, font=F["mono"], height=7, bd=0,
                     highlightthickness=0)
    editor.insert("1.0", s.get("payload", DEMO_PAYLOAD))
    editor.pack(fill="x")
    tk.Label(body, text="Parsed actions:", anchor="w", bg=S.BG, fg=T.TXT_3, font=F["sm"]).pack(
        fill="x", pady=(T.px(6), 0))
    preview = tk.Text(body, bg=S.BG, fg=T.TXT_2, font=F["map"], height=8, bd=0,
                      highlightthickness=0, state="disabled")
    preview.pack(fill="both", expand=True)
    status = tk.Label(body, text="", font=F["sm"], fg=T.TXT_3, bg=S.BG, anchor="w",
                      justify="left", wraplength=T.px(700))
    status.pack(fill="x", pady=T.px(4))

    def refresh(_=None):
        acts = parse_ducky(editor.get("1.0", "end"))
        preview.config(state="normal")
        preview.delete("1.0", "end")
        for a in acts:
            if a["type"] == "string":
                preview.insert("end", "TYPE  %s\n" % a["text"])
            elif a["type"] == "delay":
                preview.insert("end", "WAIT  %d ms\n" % a["ms"])
            else:
                preview.insert("end", "KEY   %s\n" % "+".join(a["mods"] + a["keys"]))
        preview.config(state="disabled")
    editor.bind("<KeyRelease>", refresh)

    def run():
        tgt = target.get().strip()
        if not tgt:
            status.config(text="set a target host first", fg=S.AMBER)
            return
        ok, why, actions = prepare(editor.get("1.0", "end"), tgt)
        if not ok:
            status.config(text="BLOCKED: " + why, fg=S.RED)
            return
        slog.event("usbhid", "payload -> %s (%d actions)" % (tgt, len(actions)), id=tgt)
        status.config(text="Authorized: %s — %d actions %s (gadget %s)" % (
            why, len(actions), "sent" if gadget else "built (no gadget hw)",
            "ready" if gadget else "absent"), fg=S.GREEN)

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Run payload (gated)", run, F, padx=14, pady=5, kind="danger").pack(
        side="left", padx=(10, 6), pady=6)
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))

    def on_close():
        s["target"], s["payload"] = target.get().strip(), editor.get("1.0", "end").strip()
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()
    S.bind_quit(root, on_close)
    refresh()
    if not E.is_active():
        status.config(text="No engagement open — Run is gated until you open a scoped engagement.")
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
