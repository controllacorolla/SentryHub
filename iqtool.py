#!/usr/bin/env python3
"""iqtool.py — raw IQ recorder with metadata + playback (Phase 6 #4).

Captures raw IQ to a file with a JSON sidecar recording everything needed to reproduce or decode
it later: centre frequency, sample rate, gain, sample format, GPS position, timestamp, device.
The capture can be replayed through any decoder, and hashed into the evidence chain. Pure helpers
(sidecar read/write, command building) are unit-testable; the Tk workspace lists captures.
"""
import json
import os
import sys
import time

# sample format -> (rtl_sdr understands u8; most SDRs via SoapySDR use cf32). bytes/sample pair.
FORMATS = {"u8": 2, "cs8": 2, "cs16": 4, "cf32": 8}


def sidecar_path(iq_path):
    return iq_path + ".json"


def write_sidecar(iq_path, freq_hz, sample_rate, gain=0, fmt="cu8", device=None, gps=None,
                  duration_s=None, notes="", ts=None):
    """Write the metadata sidecar next to an IQ file. Returns the metadata dict."""
    meta = {"iq_file": os.path.basename(iq_path), "freq_hz": freq_hz,
            "sample_rate": sample_rate, "gain": gain, "format": fmt, "device": device,
            "gps": gps, "duration_s": duration_s, "notes": notes,
            "ts": time.time() if ts is None else ts}
    with open(sidecar_path(iq_path), "w") as f:
        json.dump(meta, f, indent=2)
    return meta


def read_sidecar(iq_path):
    try:
        with open(sidecar_path(iq_path)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def capture_argv(device, freq_hz, sample_rate, out_path, gain=0, seconds=None):
    """Build the capture command for a device ('rtlsdr' -> rtl_sdr, 'hackrf' -> hackrf_transfer)."""
    if device == "hackrf":
        argv = ["hackrf_transfer", "-r", out_path, "-f", str(int(freq_hz)),
                "-s", str(int(sample_rate)), "-l", "32", "-g", str(int(gain))]
        if seconds:
            argv += ["-n", str(int(seconds * sample_rate))]
        return argv
    # default: rtl_sdr (u8 IQ)
    argv = ["rtl_sdr", "-f", str(int(freq_hz)), "-s", str(int(sample_rate)),
            "-g", str(int(gain))]
    if seconds:
        argv += ["-n", str(int(seconds * sample_rate))]
    argv += [out_path]
    return argv


def playback_argv(iq_path, meta=None):
    """Replay an IQ file to stdout (rtl_sdr-style u8) for piping into a decoder."""
    # meta is accepted for symmetry/future use; byte replay is format-agnostic (decoder gets rate)
    return ["cat", iq_path]


def file_sha256(iq_path):
    """Hash the IQ file for the evidence chain (delegates to evidence.sha256_file)."""
    import evidence
    return evidence.sha256_file(iq_path)


def list_captures(directory):
    """Every IQ capture with a sidecar in `directory`, newest first."""
    out = []
    try:
        names = os.listdir(directory)
    except OSError:
        return out
    for n in names:
        if n.endswith(".json"):
            meta = read_sidecar(os.path.join(directory, n[:-5]))
            if meta:
                out.append(meta)
    return sorted(out, key=lambda m: -m.get("ts", 0))


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("IQTool")
    S.settings("iqtool", {})
    root, F = S.make_root("IQ Recorder", parent=parent)
    import tkinter as tk
    T = S.T
    capdir = os.path.join(S.DATA, "iq")
    S.top_bar(root, F, "IQ Recorder", "Raw captures + metadata")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    txt = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="word", state="disabled", padx=T.px(12), pady=T.px(8))
    txt.tag_config("f", foreground=S.AMBER)
    txt.pack(fill="both", expand=True)

    def render():
        txt.config(state="normal")
        txt.delete("1.0", "end")
        caps = list_captures(capdir)
        if not caps:
            txt.insert("end", "No IQ captures yet. Capture dir: %s\n" % capdir)
        for m in caps:
            txt.insert("end", "%s\n" % m.get("iq_file", "?"), "f")
            txt.insert("end", "   %.4f MHz · %s Sa/s · %s · %s\n" % (
                (m.get("freq_hz") or 0) / 1e6, m.get("sample_rate"), m.get("format"),
                time.strftime("%Y-%m-%d %H:%M", time.localtime(m.get("ts", 0)))))
        txt.config(state="disabled")

    render()
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
