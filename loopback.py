#!/usr/bin/env python3
"""loopback.py — closed-loop self-test (test your own chain against ground truth).

Two layers:
  * SOFTWARE loopback — encode a known message and decode it straight back through the suite's own
    codecs (CW, RTTY, AIS, OpenDroneID). This validates encode↔decode end-to-end with zero
    hardware, so a regression anywhere in the chain is caught immediately.
  * HARDWARE loopback — build the gated plan to transmit a known signal (into your own RX / a
    dummy load) and confirm the live decoder recovers it. TX is txguard-gated; nothing auto-keys.

Pure; unit-testable. This is how you prove the decoders work on your bench, not just on demo data.
"""
import os
import sys


def software_selftests():
    """Run every in-software encode→decode round-trip. Returns [(name, ok, detail)]."""
    out = []

    import cw
    txt = "CQ TEST DE SENTRY"
    got = cw.decode_timing(cw.key_timing(txt, 20), 20)
    out.append(("CW keyer round-trip", got == txt, "%r -> %r" % (txt, got)))

    import rtty
    rt = "RYRY TEST 599"
    got = rtty.decode_codes(rtty.encode_codes(rt))
    out.append(("RTTY/Baudot round-trip", got == rt, "%r -> %r" % (rt, got)))

    import ais
    # AIS: decode the verified reference sentence (ground-truth MMSI).
    m = ais.decode_sentence("!AIVDM,1,1,,B,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C")
    out.append(("AIS decode reference", m is not None and m["mmsi"] == 477553000,
                "mmsi=%s" % (m or {}).get("mmsi")))

    import dronewatch as D
    pack = D.encode_pack([D.encode_basic_id("SELFTEST-1", ua_type=2),
                          D.encode_location(39.6, -104.9, alt_geo=100.0)])
    msgs = D.decode_service_data(D.service_data(pack))
    ids = {msg["type"] for msg in msgs}
    uas = next((msg.get("uas_id") for msg in msgs if msg["type"] == 0), None)
    out.append(("OpenDroneID pack round-trip",
                {D.MSG_BASIC_ID, D.MSG_LOCATION} <= ids and uas == "SELFTEST-1",
                "uas=%s types=%s" % (uas, sorted(ids))))
    return out


def all_pass(results=None):
    results = software_selftests() if results is None else results
    return all(ok for _, ok, _ in results)


def hardware_loopback_plan(mode, freq_hz, settings, iq_file="/tmp/selftest.iq", sample_rate=2_000_000):
    """Build the gated plan to TX a known burst and capture it back. Returns
    (ok, reason, {tx_argv, rx_argv}) — argv only when txguard authorizes (into your own RX / load)."""
    import radio
    req = radio.TxRequest(mode, freq_hz, settings=settings,
                          callsign=(settings or {}).get("callsign", ""))
    ok, reason, power = req.authorize()
    if not ok:
        return False, reason, None
    import iqtool
    return True, reason, {
        "tx_argv": ["hackrf_transfer", "-t", iq_file, "-f", str(int(freq_hz)),
                    "-s", str(int(sample_rate)), "-x", "0"],
        "rx_argv": iqtool.capture_argv("rtlsdr", freq_hz, sample_rate, iq_file + ".rx", seconds=2),
        "power_dbm": power,
    }


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Loopback")
    S.settings("loopback", {})
    root, F = S.make_root("Self-Test", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Self-Test", "Closed-loop decoder validation")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    txt = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="word", state="disabled", padx=T.px(12), pady=T.px(8))
    txt.tag_config("ok", foreground=S.GREEN)
    txt.tag_config("bad", foreground=S.RED)
    txt.pack(fill="both", expand=True)

    def run():
        txt.config(state="normal")
        txt.delete("1.0", "end")
        for name, ok, detail in software_selftests():
            txt.insert("end", ("PASS  " if ok else "FAIL  "), "ok" if ok else "bad")
            txt.insert("end", "%s\n   %s\n" % (name, detail))
        txt.config(state="disabled")

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Run self-test", run, F, padx=14, pady=5, kind="primary").pack(side="left",
                                                                              padx=(10, 6), pady=6)
    run()
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
