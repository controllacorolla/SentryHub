#!/usr/bin/env python3
"""CW / Morse keyer (Phase 5 #13). Build-and-gate TX: encode + policy only.

Encodes text to Morse and builds the key-up/key-down timing for a given speed, and decodes
received timing back to text (practice / off-air copy). Any actual transmission is gated by
txguard (callsign + amateur band + armed kill switch + per-session unlock) and needs detected TX
hardware; with neither it is a receive-only Morse practice tool. This module never keys a radio on
its own — real carrier generation is left to an authorized key-up in the field.

Pure helpers (encode/decode/timing) are unit-testable; the Tk workspace follows the module pattern.
"""
import os
import sys

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....",
    "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "/": "-..-.", "=": "-...-", "+": ".-.-.",
    "-": "-....-", "(": "-.--.", ")": "-.--.-", ":": "---...", "'": ".----.", "@": ".--.-.",
    "!": "-.-.--", "&": ".-...",
}
MORSE_REV = {v: k for k, v in MORSE.items()}


def encode_morse(text):
    """Text -> Morse string: letters separated by spaces, words by ' / '."""
    words = []
    for word in str(text).upper().split():
        words.append(" ".join(MORSE[c] for c in word if c in MORSE))
    return " / ".join(w for w in words if w)


def decode_morse(morse):
    """Morse string (letters space-separated, words by '/') -> text."""
    out = []
    for word in str(morse).split("/"):
        letters = [MORSE_REV.get(sym, "") for sym in word.split()]
        out.append("".join(letters))
    return " ".join(w for w in out if w)


def dot_ms(wpm):
    """Duration of one dot at `wpm` words/minute (PARIS standard: 1200/wpm ms)."""
    return 1200.0 / max(1, wpm)


def key_timing(text, wpm=20):
    """Return the keying as a list of (on: bool, ms: float) elements.
    dot=1u on, dash=3u on; 1u gap between elements, 3u between letters, 7u between words."""
    u = dot_ms(wpm)
    seq = []
    morse = encode_morse(text)
    tokens = morse.split(" ")
    for i, tok in enumerate(tokens):
        if tok == "/":
            seq.append((False, 7 * u))          # word gap (replaces the 3u letter gap)
            continue
        if i > 0 and tokens[i - 1] != "/":
            seq.append((False, 3 * u))           # inter-letter gap
        for j, el in enumerate(tok):
            if j > 0:
                seq.append((False, u))           # intra-letter gap
            seq.append((True, (1 if el == "." else 3) * u))
    return seq


def decode_timing(elements, wpm=20):
    """Inverse of key_timing for practice/copy: classify on-durations as dot/dash and off-durations
    as element/letter/word gaps, using thresholds scaled to `wpm`."""
    u = dot_ms(wpm)
    morse = []
    for on, ms in elements:
        if on:
            morse.append("." if ms < 2 * u else "-")
        else:
            if ms >= 5 * u:
                morse.append(" / ")
            elif ms >= 2 * u:
                morse.append(" ")
    return decode_morse("".join(morse))


DEFAULTS = {"wpm": 20, "freq_mhz": 7.030, "callsign": "", "tx_enabled": False}


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    import radio
    if parent is None:
        S.single_instance("CW")
    s, spath = S.settings("cw", DEFAULTS)
    root, F = S.make_root("CW Keyer", parent=parent)
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("cw")
    st = {"tx_ok": bool(radio.tx_hardware_available())}

    top = S.top_bar(root, F, "CW Keyer", "Morse encode/decode · TX gated by txguard")
    S.pill(top, F, "TX ready" if st["tx_ok"] else "RX practice")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    entry = S.entry(body, F) if hasattr(S, "entry") else tk.Entry(body)
    entry.pack(fill="x", padx=T.px(12), pady=T.px(8))
    out = tk.Label(body, text="", font=F["mono"], fg=S.AMBER, bg=S.BG, anchor="w",
                   justify="left", wraplength=T.px(700))
    out.pack(fill="x", padx=T.px(12))
    status = tk.Label(body, text="", font=F["sm"], fg=T.TXT_3, bg=S.BG, anchor="w",
                      justify="left", wraplength=T.px(700))
    status.pack(fill="x", padx=T.px(12), pady=T.px(6))

    def refresh(_=None):
        txt = entry.get()
        out.config(text=encode_morse(txt))
    entry.bind("<KeyRelease>", refresh)

    def send():
        txt = entry.get().strip()
        if not txt:
            return
        freq_hz = float(s.get("freq_mhz", 7.030)) * 1e6
        req = radio.TxRequest("cw", freq_hz, callsign=s.get("callsign", ""),
                              settings={"tx_enabled": s.get("tx_enabled", False),
                                        "callsign": s.get("callsign", "")})
        ok, why, power = req.authorize()
        if not ok:
            status.config(text="TX blocked: " + why, fg=S.RED)
            return
        # authorized: build the keying plan, log the intent. Real carrier key-up happens here on
        # hardware; this build does not auto-key.
        seq = key_timing(txt, s.get("wpm", 20))
        dur = sum(ms for _, ms in seq) / 1000.0
        req.log(dur, power_dbm=power)
        slog.event("cw", "TX %.3f MHz %d el" % (freq_hz / 1e6, len(seq)), id="cw")
        status.config(text="Authorized: %s · %d elements · %.1fs @ %d dBm (keying is manual)"
                      % (why, len(seq), dur, power), fg=S.GREEN)

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
    if not st["tx_ok"]:
        status.config(text="No TX hardware — Morse practice only. (TX also needs txguard armed + "
                           "unlocked + your callsign on an amateur band.)")
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
