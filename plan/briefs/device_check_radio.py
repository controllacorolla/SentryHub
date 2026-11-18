#!/usr/bin/env python3
"""Device check for the radio cluster (PRISM receiver + PROWL fast scanner) — real RTL-SDR.

Close PALISADE first (the dongle can have one owner). Run from ~/SentryHub:
    python3 plan/briefs/device_check_radio.py
What it does (receive only, about 40 s):
  1. rtl_tcp starts on 127.0.0.1 and streams IQ (checks the dongle, tuner type, sample rate).
  2. Sweeps the FM broadcast band 88-108 MHz in 2 MHz steps over the control socket (no restart),
     finds the strongest station, plays it as WFM for 5 s on the speaker and saves a WAV.
  3. Times one full 118-137 MHz airband pass with the FAST scanner logic (12 retunes).
  4. Checks that rtl_tcp is gone afterwards (the dongle is free again).
Expected last line: DEVICE CHECK RADIO: PASS (n/n)
"""
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import numpy as np  # noqa: E402

import dsp  # noqa: E402
import iqsource  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("%s  %s  %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)


def main():
    check("rtl_tcp installed", shutil.which("rtl_tcp"), shutil.which("rtl_tcp") or
          "sudo apt install rtl-sdr")
    check("audio sink (pacat/aplay)", iqsource.audio_sink_argv(48000) is not None)
    if not shutil.which("rtl_tcp"):
        return
    rate = 2048000
    src = iqsource.RtlTcpSource(98_000_000, rate, gain_db=33.8)
    try:
        src.open()
    except iqsource.SourceError as e:
        check("rtl_tcp opened the dongle", False, "%s  (is PALISADE or readsb holding it?)" % e)
        return
    check("rtl_tcp opened the dongle", True, "tuner type %s" % src.tuner)
    t0 = time.time()
    raw, iq = src.read(0.5)
    dt = time.time() - t0
    check("IQ streams at the sample rate", iq.size > 0.4 * rate, "%d samples in %.2f s"
          % (iq.size, dt))

    # 2. FM broadcast: find the strongest station
    best = (-999, None)
    sp = dsp.Spectrum(8192)
    for c in range(89_000_000, 108_000_001, 1_600_000):
        src.set_freq(c)
        src.flush(0.08)
        sp.reset()
        db = None
        for _ in range(3):
            db = sp.process(src.read(0.05)[1]) if db is None else np.maximum(
                db, sp.process(src.read(0.05)[1]))
        f = dsp.Spectrum.bin_freqs(8192, rate, c)
        ok = (f >= 87.9e6) & (f <= 108e6) & (np.abs(f - c) > 20000)
        k = int(np.argmax(np.where(ok, db, -999)))
        snr = float(db[k] - np.median(db))
        if snr > best[0]:
            best = (snr, round(f[k] / 100000) * 100000)
    check("strongest FM station found", best[0] > 15, "%.1f MHz, %.0f dB over floor"
          % (best[1] / 1e6, best[0]))
    src.set_freq(int(best[1]) - 300000)
    src.flush(0.08)
    d = dsp.Demodulator(rate, "WFM", offset_hz=300000)
    out = iqsource.AudioOut(d.audio_rate)
    rec = iqsource.AudioRecorder(best[1], "WFM", d.audio_rate)
    peak = 0
    t0 = time.time()
    while time.time() - t0 < 5:
        pcm, _lvl, _o = d.process(src.read(0.05)[1])
        out.write(pcm)
        rec.write(pcm)
        peak = max(peak, int(np.abs(pcm).max()))
    out.close()
    rec.close()
    check("WFM audio demodulated (you should have heard the station)", peak > 3000,
          "peak %d, saved %s" % (peak, rec.path))

    # 3. FAST airband pass timing (retune + settle + dwell per capture)
    import banks
    from palisade_qt.iqworker import plan_windows, SETTLE_S
    hz = [int(f * 1e6) for f, _ in banks.expand(banks.BANKS["Airband (full)"])]
    wins = plan_windows(hz, rate)
    t0 = time.time()
    floors = []
    for c, _g in wins:
        src.set_freq(c)
        src.flush(SETTLE_S)
        sp.reset()
        db = sp.process(src.read(0.15)[1])
        floors.append(float(np.median(db)))
    took = time.time() - t0
    check("full airband pass (760 ch, %d retunes)" % len(wins), took < 6,
          "%.1f s, floor %.0f dBFS" % (took, np.median(floors)))
    src.close()
    time.sleep(0.5)
    left = subprocess.run(["pgrep", "-x", "rtl_tcp"], capture_output=True, text=True).stdout
    check("rtl_tcp stopped, dongle free", not left.strip(), left.strip())


if __name__ == "__main__":
    try:
        main()
    finally:
        print("DEVICE CHECK RADIO: %s (%d/%d)" % ("PASS" if results and all(results) else "FAIL",
                                                  sum(results), len(results)))
