#!/usr/bin/env python3
"""buslab.py — low-level hardware bus lab: UART, JTAG/SWD, SPI-flash (hardware-hacking, pen-test).

The bench for getting a foothold on an embedded target over its debug/boot interfaces — distinct from
hwlab.py (which is the friendly serial/I2C/GPIO bench). Three pure, testable pieces:

  * UART  — autobaud by scoring candidate rates for printable output (find the console baud).
  * JTAG  — decode a 32-bit IDCODE (IEEE 1149.1): version / part / 11-bit manufacturer.
  * SPI   — decode a 3-byte JEDEC RDID (0x9F): manufacturer (JEP106) + capacity.

SAFETY LINE: probing is read-only and ungated (scan the chain, read the console, probe/dump a flash
you own). **Writing** — flashing a chip, writing memory over JTAG — is destructive and goes through
the engagement gate (scoped, authorized, evidence-logged). We build the flashrom/openocd write argv
only after the gate says yes.
"""
import os
import shutil
import sys

import engagement

COMMON_BAUDS = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1500000]

# ---- SPI-flash JEDEC manufacturer IDs (JEP106, as reported by RDID 0x9F byte 1) ------------------
JEDEC_MFR = {
    0xEF: "Winbond", 0xC2: "Macronix", 0x20: "Micron", 0x01: "Spansion/Cypress",
    0xBF: "SST", 0x1F: "Atmel/Adesto", 0x9D: "ISSI", 0xC8: "GigaDevice", 0x8C: "Micron",
}


def printable_ratio(sample):
    """Fraction of bytes that are printable ASCII or common whitespace — the autobaud score."""
    if not sample:
        return 0.0
    ok = sum(1 for b in sample if 0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D))
    return ok / len(sample)


def guess_baud(samples, threshold=0.6):
    """samples: {baud: bytes_read_at_that_baud}. Returns (best_baud, score) — the rate that yields
    the most printable output. Returns (None, score) if nothing clears the threshold (likely the
    wrong voltage/line, not just the wrong rate)."""
    best, best_score = None, 0.0
    for baud, data in samples.items():
        sc = printable_ratio(data)
        if sc > best_score:
            best, best_score = baud, sc
    if best_score < threshold:
        return None, best_score
    return best, best_score


def picocom_argv(dev, baud=115200):
    return ["picocom", "-b", str(int(baud)), dev]


def decode_idcode(idcode):
    """Decode a 32-bit JTAG IDCODE (IEEE 1149.1). bit0 must be 1."""
    idcode &= 0xFFFFFFFF
    valid = bool(idcode & 1)
    return {
        "valid": valid,
        "version": (idcode >> 28) & 0xF,
        "part": (idcode >> 12) & 0xFFFF,
        "manufacturer": (idcode >> 1) & 0x7FF,
        "manufacturer_hex": "0x%03X" % ((idcode >> 1) & 0x7FF),
        "raw": "0x%08X" % idcode,
    }


def decode_jedec_id(three_bytes):
    """Decode a 3-byte SPI-flash RDID response -> manufacturer + capacity.
    byte0 = manufacturer (JEP106), byte1 = memory type, byte2 = capacity code (size = 2**code)."""
    b = bytes(three_bytes)
    if len(b) < 3:
        raise ValueError("JEDEC RDID needs 3 bytes")
    cap_code = b[2]
    size = (1 << cap_code) if 0 < cap_code < 40 else None
    return {
        "mfr_id": b[0], "mfr": JEDEC_MFR.get(b[0], "0x%02X" % b[0]),
        "mem_type": b[1], "capacity_code": cap_code,
        "capacity_bytes": size, "capacity_mbit": ((size * 8) >> 20) if size else None,
    }


def openocd_scan_argv(interface_cfg, target_cfg=None):
    """openocd invocation that just scans the chain and prints IDCODEs (read-only)."""
    argv = ["openocd", "-f", interface_cfg]
    if target_cfg:
        argv += ["-f", target_cfg]
    return argv + ["-c", "init; scan_chain; shutdown"]


def flashrom_probe_argv(programmer):
    """Probe/identify the attached flash (read-only, ungated)."""
    return ["flashrom", "-p", programmer]


def flashrom_read_argv(programmer, out_path):
    """Dump the flash to a file (read-only, ungated)."""
    return ["flashrom", "-p", programmer, "-r", out_path]


def prepare_flash_write(programmer, in_path, target, evidence_chain=None):
    """Gate a flash WRITE. Returns (ok, reason, argv). argv is None unless an authorized, in-scope
    engagement is open — flashing is destructive and always scope-checked + evidence-logged."""
    ok, why = engagement.authorize_action("buslab:flash_write:%s" % programmer, target, evidence_chain)
    if not ok:
        return False, why, None
    return True, why, ["flashrom", "-p", programmer, "-w", in_path]


def prepare_jtag_write(interface_cfg, command, target, evidence_chain=None, target_cfg=None):
    """Gate an active JTAG write/halt/flash command. Returns (ok, reason, argv)."""
    ok, why = engagement.authorize_action("buslab:jtag:%s" % command.split()[0], target, evidence_chain)
    if not ok:
        return False, why, None
    argv = ["openocd", "-f", interface_cfg]
    if target_cfg:
        argv += ["-f", target_cfg]
    return True, why, argv + ["-c", "init; %s; shutdown" % command]


def detect(which=shutil.which):
    """Which bus tools are installed."""
    return {"uart": bool(which("picocom") or which("screen")),
            "jtag": bool(which("openocd")),
            "spi": bool(which("flashrom"))}


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("BusLab")
    S.settings("buslab", {})
    root, F = S.make_root("Bus Lab", parent=parent)
    import tkinter as tk
    T = S.T
    have = detect()

    top = S.top_bar(root, F, "Bus Lab", "UART · JTAG · SPI-flash · probe ungated · flash gated")
    status = "tools: UART %s · JTAG %s · SPI %s" % (
        "✓" if have["uart"] else "–", "✓" if have["jtag"] else "–", "✓" if have["spi"] else "–")
    tk.Label(top, text=status, bg=S.BG, fg=T.TXT_3, font=F["sm"]).pack(side="right", padx=T.px(8))

    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True, padx=T.px(10), pady=T.px(8))
    tk.Label(body, bg=S.BG, fg=T.TXT_2, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700),
             text=("Decode a JTAG IDCODE (hex, e.g. 0x4BA00477) or a SPI-flash JEDEC RDID "
                   "(3 hex bytes, e.g. EF 40 18). Probing/reading is ungated; flashing a chip "
                   "needs an open, scoped engagement and is logged to the evidence chain.")).pack(
        fill="x", pady=(0, T.px(8)))

    row = tk.Frame(body, bg=S.BG)
    row.pack(fill="x")
    ent = tk.Entry(row, bg=T.SURFACE_2, fg=T.TXT, font=F["map"], insertbackground=T.TXT, width=24)
    ent.pack(side="left", padx=(0, T.px(6)))
    out = tk.Label(body, text="", bg=T.SURFACE, fg=T.TXT, font=F["map"], anchor="w", justify="left",
                   padx=T.px(10), pady=T.px(8))
    out.pack(fill="both", expand=True, pady=(T.px(8), 0))

    def do_decode(_=None):
        txt = ent.get().strip()
        toks = txt.replace(",", " ").split()
        try:
            if len(toks) == 1 and (toks[0].lower().startswith("0x") or len(toks[0]) >= 7):
                d = decode_idcode(int(toks[0], 16))
                out.config(text="JTAG IDCODE %s\n  valid=%s  version=%d\n  part=0x%04X  mfr=%s"
                                % (d["raw"], d["valid"], d["version"], d["part"], d["manufacturer_hex"]))
            else:
                b = [int(t, 16) for t in toks[:3]]
                d = decode_jedec_id(b)
                cap = ("%d Mbit" % d["capacity_mbit"]) if d["capacity_mbit"] else "unknown"
                out.config(text="SPI JEDEC  %s\n  mfr=%s (0x%02X)  type=0x%02X\n  capacity=%s"
                                % (bytes(b).hex(" "), d["mfr"], d["mfr_id"], d["mem_type"], cap))
        except (ValueError, IndexError):
            out.config(text="enter an IDCODE hex (0x........) or 3 JEDEC bytes (EF 40 18)")

    S.btn(row, "Decode", do_decode, F, padx=12, pady=5, kind="primary").pack(side="left")
    ent.bind("<Return>", do_decode)

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    if not parent:
        S.btn(bar, "Quit", lambda: root.destroy(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))
    S.bind_quit(root, lambda: root.destroy())
    if "--demo" in sys.argv:
        ent.insert(0, "EF 40 18")
        root.after(300, do_decode)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
