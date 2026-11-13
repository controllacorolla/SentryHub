#!/usr/bin/env python3
"""RTTY — Baudot/ITA2 radioteletype (Phase 5 #6). Build-and-gate TX: encode + policy only.

Encodes text to the ITA2 5-bit code (with LTRS/FIGS shift handling) and builds the mark/space bit
stream (start bit + 5 data bits + stop bits) for AFSK/FSK keying; decodes codes back to text. Any
transmission is gated by txguard (callsign + amateur band + armed + per-session unlock) and needs
TX hardware; otherwise it is a receive/encode display tool. Never auto-keys a radio.

ITA2 codes verified against the standard Baudot-Murray table (bits 1-5 as transmitted; 1=mark).
Pure helpers are unit-testable; the Tk workspace follows the module pattern.
"""
import os
import sys

# Letters shift (A-Z). Each value is the 5-bit code, bit 1 first (MSB of the 5-bit field).
LETTERS = {
    "A": 0b11000, "B": 0b10011, "C": 0b01110, "D": 0b10010, "E": 0b10000, "F": 0b10110,
    "G": 0b01011, "H": 0b00101, "I": 0b01100, "J": 0b11010, "K": 0b11110, "L": 0b01001,
    "M": 0b00111, "N": 0b00110, "O": 0b00011, "P": 0b01101, "Q": 0b11101, "R": 0b01010,
    "S": 0b10100, "T": 0b00001, "U": 0b11100, "V": 0b01111, "W": 0b11001, "X": 0b10111,
    "Y": 0b10101, "Z": 0b10001,
}
# Figures shift (US TTY variant).
FIGURES = {
    "0": 0b01101, "1": 0b11101, "2": 0b11001, "3": 0b10000, "4": 0b01010, "5": 0b00001,
    "6": 0b10101, "7": 0b11100, "8": 0b01100, "9": 0b00011, "-": 0b11000, ",": 0b00110,
    ".": 0b00111, "/": 0b10111, ":": 0b01110, "?": 0b10011, "'": 0b10100, "(": 0b11110,
    ")": 0b01001, "=": 0b01111, "+": 0b10001, "$": 0b10010, "!": 0b10110, "&": 0b01011,
    "#": 0b00101,
}
CONTROLS = {" ": 0b00100, "\r": 0b00010, "\n": 0b01000}      # same code in both shifts
LTRS = 0b11111
FIGS = 0b11011
BAUD = 45.45


def encode_codes(text):
    """Text -> list of 5-bit codes, inserting LTRS/FIGS shift codes as needed (starts in LTRS)."""
    codes = [LTRS]
    shift = "L"
    for ch in str(text).upper():
        if ch in CONTROLS:
            codes.append(CONTROLS[ch])
        elif ch in LETTERS:
            if shift != "L":
                codes.append(LTRS)
                shift = "L"
            codes.append(LETTERS[ch])
        elif ch in FIGURES:
            if shift != "F":
                codes.append(FIGS)
                shift = "F"
            codes.append(FIGURES[ch])
    return codes


def decode_codes(codes):
    """Inverse of encode_codes (tracks the LTRS/FIGS shift)."""
    revL = {v: k for k, v in LETTERS.items()}
    revF = {v: k for k, v in FIGURES.items()}
    out = []
    shift = "L"
    for c in codes:
        if c == LTRS:
            shift = "L"
        elif c == FIGS:
            shift = "F"
        elif c == CONTROLS[" "]:
            out.append(" ")
        elif c in (CONTROLS["\r"], CONTROLS["\n"]):
            continue
        else:
            out.append((revL if shift == "L" else revF).get(c, ""))
    return "".join(out)


def encode_bits(text, stop_bits=2):
    """Full mark/space bit stream: per code, start bit (space=0) + 5 data bits (1=mark) + stop
    bits (mark=1). Idle is mark."""
    stop = "1" * stop_bits
    return "".join("0" + format(c, "05b") + stop for c in encode_codes(text))


def duration_s(text, stop_bits=2, baud=BAUD):
    return len(encode_bits(text, stop_bits)) / baud


DEFAULTS = {"freq_mhz": 14.085, "callsign": "", "tx_enabled": False, "stop_bits": 2}


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    import radio
    if parent is None:
        S.single_instance("RTTY")
    s, spath = S.settings("rtty", DEFAULTS)
    root, F = S.make_root("RTTY", parent=parent)
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("rtty")
    tx_ok = bool(radio.tx_hardware_available())

    top = S.top_bar(root, F, "RTTY", "Baudot/ITA2 · TX gated by txguard")
    S.pill(top, F, "TX ready" if tx_ok else "encode only")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    ent = tk.Entry(body, font=F["mono"])
    ent.pack(fill="x", padx=T.px(12), pady=T.px(8))
    out = tk.Label(body, text="", font=F["mono"], fg=T.TXT_3, bg=S.BG, anchor="w",
                   justify="left", wraplength=T.px(700))
    out.pack(fill="x", padx=T.px(12))
    status = tk.Label(body, text="", font=F["sm"], fg=T.TXT_3, bg=S.BG, anchor="w",
                      justify="left", wraplength=T.px(700))
    status.pack(fill="x", padx=T.px(12), pady=T.px(6))

    def refresh(_=None):
        txt = ent.get()
        bits = encode_bits(txt, s.get("stop_bits", 2))
        out.config(text="%d codes · %d bits · %.1fs @ %.2f baud" % (
            len(encode_codes(txt)), len(bits), duration_s(txt, s.get("stop_bits", 2)), BAUD))
    ent.bind("<KeyRelease>", refresh)

    def send():
        txt = ent.get().strip()
        if not txt:
            return
        req = radio.TxRequest("rtty", float(s.get("freq_mhz", 14.085)) * 1e6,
                              callsign=s.get("callsign", ""),
                              settings={"tx_enabled": s.get("tx_enabled", False),
                                        "callsign": s.get("callsign", "")})
        ok, why, power = req.authorize()
        if not ok:
            status.config(text="TX blocked: " + why, fg=S.RED)
            return
        dur = duration_s(txt, s.get("stop_bits", 2))
        req.log(dur, power_dbm=power)
        slog.event("rtty", "TX %.3f MHz %.1fs" % (float(s.get("freq_mhz", 14.085)), dur), id="rtty")
        status.config(text="Authorized: %s · %.1fs @ %d dBm (keying is manual)" % (why, dur, power),
                      fg=S.GREEN)

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Send (gated)", send, F, padx=14, pady=5, kind="primary").pack(side="left",
                                                                              padx=(10, 6), pady=6)
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))

    def on_close():
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()
    S.bind_quit(root, on_close)
    if not tx_ok:
        status.config(text="No TX hardware — encode/decode only.")
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
