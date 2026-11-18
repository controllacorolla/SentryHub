"""Radio cluster (device-fix plan Stage 4): PRISM SDR++-style receiver + PROWL scanner controls.

One regression test (or more) per owed feature:
  PRISM  — typed frequency, click / drag / wheel VFO, AM NFM WFM USB LSB CW demod with audio,
           bandwidth, squelch, gain / tuner AGC / RTL AGC / PPM, sample rate, zoom, waterfall
           levels, bookmarks + preset banks, audio + IQ recording, IQ file playback, START/STOP.
  PROWL  — preset banks (airband first), range scan + step, dwell, resume delay, max hold,
           per-bank squelch, lockouts, priority channel, HOLD, green/red SCAN button.
  Radio ownership — the IQ workers take the dongle only through radio_arbiter (HELD before the
           source opens, give-back closes rtl_tcp then releases, OFF status on give-back).
The live path is exercised against tests/rtltcp_fake.py: a real TCP server speaking the rtl_tcp
protocol (header + 5-byte commands) whose IQ follows the tuned frequency.
"""
import json
import os
import struct
import sys
import time
import wave

import numpy as np
import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (SUITE_DIR, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import banks  # noqa: E402
import dsp  # noqa: E402
import iqsource  # noqa: E402
from rtltcp_fake import FakeProc, FakeRtlTcp  # noqa: E402

FS = 2048000


def _app():
    from PySide6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _pump(ms):
    app = _app()
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents()
        time.sleep(0.005)


def _until(pred, ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        _app().processEvents()
        v = pred()
        if v:
            return v
        time.sleep(0.01)
    return pred()


@pytest.fixture
def arb(monkeypatch):
    _app()
    from palisade_qt import radio_arbiter as ra, eventbus
    ra.arbiter.reset_for_tests()
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    eventbus.bus.clear()
    yield ra
    ra.arbiter.reset_for_tests()
    eventbus.bus.clear()


# ============================================================================ DSP
def _tone(a, rate):
    a = np.asarray(a, dtype=float)[len(a) // 3:]
    F = np.abs(np.fft.rfft(a * np.hanning(a.size)))
    f = np.fft.rfftfreq(a.size, 1 / rate)
    i = int(np.argmax(F[5:])) + 5
    thd = 1 - np.sum(F[i - 3:i + 4] ** 2) / np.sum(F ** 2)
    return f[i], thd


def _signal(mode, off, n=FS // 2, seed=0):
    t = np.arange(n) / FS
    if mode == "NFM":
        s = np.exp(1j * (2 * np.pi * off * t + 3.0 * np.sin(2 * np.pi * 1000 * t)))
    elif mode == "WFM":
        s = np.exp(1j * (2 * np.pi * off * t + 50.0 * np.sin(2 * np.pi * 1000 * t)))
    elif mode == "AM":
        s = (1 + 0.5 * np.sin(2 * np.pi * 1000 * t)) * np.exp(2j * np.pi * off * t)
    elif mode in ("USB", "RAW"):             # RAW: the I channel of a carrier 1 kHz up
        s = np.exp(2j * np.pi * (off + 1000) * t)
    elif mode == "LSB":
        s = np.exp(2j * np.pi * (off - 1000) * t)
    else:                                   # CW: a bare carrier at the VFO
        s = np.exp(2j * np.pi * off * t)
    rng = np.random.default_rng(seed)
    x = 0.3 * s + 0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    return dsp.cu8_to_iq(dsp.iq_to_cu8(x))      # through the 8-bit path the radio uses


@pytest.mark.parametrize("mode,want", [("NFM", 1000), ("WFM", 1000), ("AM", 1000),
                                       ("USB", 1000), ("LSB", 1000), ("CW", dsp.CW_PITCH),
                                       ("RAW", 1000)])
def test_every_demod_mode_recovers_the_audio(mode, want):
    off = -310000.0                          # VFO well away from the centre, like a real tune
    d = dsp.Demodulator(FS, mode, offset_hz=off)
    iq = _signal(mode, off)
    a = np.concatenate([d.process(x)[0] for x in np.array_split(iq, 9)])
    f, thd = _tone(a, d.audio_rate)
    assert abs(f - want) < 15, (mode, f)
    assert thd < 0.05, (mode, thd)
    assert 44000 <= d.audio_rate <= 52000


def test_demod_output_does_not_depend_on_how_the_stream_is_cut():
    iq = _signal("NFM", 125000.0, n=FS // 4)
    a = dsp.Demodulator(FS, "NFM", offset_hz=125000.0)
    b = dsp.Demodulator(FS, "NFM", offset_hz=125000.0)
    one = a.process(iq)[0]
    many = np.concatenate([b.process(x)[0] for x in np.array_split(iq, 13)])
    assert one.size == many.size
    # after the filters' start-up (the first ~5 ms, where the discriminator sees ~zero input and
    # float rounding decides the angle) every sample matches
    assert np.max(np.abs(one[400:].astype(int) - many[400:].astype(int))) <= 2


def test_ssb_sidebands_are_separated():
    """USB passes the upper sideband only: a tone 1 kHz BELOW the carrier is rejected."""
    d = dsp.Demodulator(FS, "USB", offset_hz=0, agc=False)
    lsb_only = _signal("LSB", 0.0)
    usb_only = _signal("USB", 0.0)
    rms = lambda a: float(np.sqrt(np.mean(a.astype(float) ** 2)))     # noqa: E731
    wrong = rms(d.process(lsb_only)[0][2000:])
    d2 = dsp.Demodulator(FS, "USB", offset_hz=0, agc=False)
    right = rms(d2.process(usb_only)[0][2000:])
    assert right > 20 * wrong


def test_bandwidth_is_clamped_per_mode_and_changes_the_filter():
    d = dsp.Demodulator(FS, "NFM", bw=999999)
    assert d.bw == dsp.BW_LIMITS["NFM"][1]
    d.configure("CW", 10)
    assert d.bw == dsp.BW_LIMITS["CW"][0]
    # a 6 kHz-off carrier is inside a 25 kHz NFM channel and outside a 5 kHz one
    t = np.arange(FS // 4) / FS
    x = dsp.cu8_to_iq(dsp.iq_to_cu8(0.3 * np.exp(2j * np.pi * 6000 * t)))
    wide = dsp.Demodulator(FS, "NFM", bw=25000).process(x)[1]
    narrow = dsp.Demodulator(FS, "NFM", bw=5000).process(x)[1]
    assert wide - narrow > 20


def test_squelch_mutes_noise_opens_on_signal_with_hysteresis():
    rng = np.random.default_rng(1)
    noise = (0.005 * (rng.standard_normal(FS // 4) + 1j * rng.standard_normal(FS // 4))) \
        .astype(np.complex64)
    d = dsp.Demodulator(FS, "AM", squelch_db=-30.0)
    pcm, level, open_ = d.process(noise)
    assert level < -30 and not open_ and not pcm.any()
    pcm, level, open_ = d.process(_signal("AM", 0.0, n=FS // 4))
    assert level > -30 and open_ and pcm.any()
    d.squelch_db = level + 1.0               # inside the 2 dB hysteresis: stays open
    assert d.process(_signal("AM", 0.0, n=FS // 4, seed=2))[2]
    d.squelch_db = None                      # off: always open
    assert d.process(noise)[2]


def test_audio_agc_levels_weak_and_strong_signals_and_never_clips_past_full_scale():
    for amp in (0.02, 0.4):
        t = np.arange(FS // 2) / FS
        x = amp * (1 + 0.5 * np.sin(2 * np.pi * 800 * t)) * np.exp(2j * np.pi * 0 * t)
        d = dsp.Demodulator(FS, "AM", agc=True)
        a = np.concatenate([d.process(b)[0] for b in np.array_split(
            dsp.cu8_to_iq(dsp.iq_to_cu8(x)), 10)]).astype(float) / 32767
        tail = a[a.size // 2:]
        assert 0.1 < np.sqrt(np.mean(tail ** 2)) < 0.6
        assert np.max(np.abs(a)) <= 1.0


def test_spectrum_puts_a_tone_in_the_right_bin_at_about_0_dbfs():
    n = 8192 * 4
    off = 300000.0
    t = np.arange(n) / FS
    x = np.exp(2j * np.pi * off * t).astype(np.complex64)
    sp = dsp.Spectrum(8192)
    db = sp.process(x)
    freqs = dsp.Spectrum.bin_freqs(8192, FS, 100e6)
    k = int(np.argmax(db))
    assert abs(freqs[k] - (100e6 + off)) <= FS / 8192
    assert -1.5 < db[k] < 0.5
    lv = dsp.channel_levels(db, FS, 100e6, [100e6 + off, 100e6 + 5e6], 10000)
    assert lv[0] > -2 and lv[1] is None                    # out-of-band channel -> None
    assert dsp.noise_floor_db(db) < -60


def test_cu8_round_trip():
    x = np.array([0.5 - 0.25j, -1 + 0.99j, 0j], dtype=np.complex64)
    y = dsp.cu8_to_iq(dsp.iq_to_cu8(x))
    assert np.allclose(x, y, atol=1 / 127)


# ============================================================================ frequency entry
@pytest.mark.parametrize("text,hz", [("121.5", 121_500_000), ("446M", 446_000_000),
                                     ("144.39 MHz", 144_390_000), ("162550000", 162_550_000),
                                     ("118 000 000", 118_000_000), ("30000k", 30_000_000)])
def test_typed_frequencies_parse(text, hz):
    assert iqsource.parse_freq(text) == hz


@pytest.mark.parametrize("text", ["", "abc", "10", "2000", "nan", "inf"])
def test_bad_frequencies_are_refused(text):
    with pytest.raises(ValueError):
        iqsource.parse_freq(text)


def test_frequency_readout_grouping():
    assert iqsource.fmt_freq(121_500_000) == "121.500 000"
    assert iqsource.fmt_freq(162_550_000) == "162.550 000"


# ============================================================================ rtl_tcp
def test_rtl_tcp_is_bound_to_localhost_and_commands_are_the_protocol_bytes():
    argv = iqsource.rtl_tcp_argv(5555, 121_500_000, 2048000, 33.8)
    assert argv[:3] == ["rtl_tcp", "-a", "127.0.0.1"] and "-p" in argv
    assert "0.0.0.0" not in argv
    assert iqsource.rtl_tcp_cmd(0x01, 121_500_000) == b"\x01" + struct.pack(">I", 121_500_000)
    assert iqsource.rtl_tcp_cmd(0x05, -12) == b"\x05" + struct.pack(">i", -12)


def test_rtl_tcp_source_retunes_and_sets_gain_over_the_socket_without_a_restart():
    srv = FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
    spawned = []
    src = iqsource.RtlTcpSource(119_000_000, FS, gain_db=33.8, ppm=-3, agc=True,
                                spawn=lambda argv: spawned.append(FakeProc(argv)) or spawned[-1],
                                port=srv.port)
    try:
        src.open()
        assert len(spawned) == 1 and src.tuner == 5
        sp = dsp.Spectrum(8192)
        for _ in range(4):
            db = sp.process(src.read(0.05)[1])
        f = dsp.Spectrum.bin_freqs(8192, FS, src.centre_hz)[int(np.argmax(db))]
        assert abs(f - 119.1e6) < 1000
        src.set_freq(119_600_000)
        src.set_gain(None)                       # tuner auto gain
        src.set_gain(20.7)
        time.sleep(0.05)
        src.flush(0.06)
        for _ in range(4):
            db = sp.process(src.read(0.05)[1])
        f = dsp.Spectrum.bin_freqs(8192, FS, src.centre_hz)[int(np.argmax(db))]
        assert abs(f - 119.1e6) < 1000, "the same carrier, now 500 kHz below the centre"
        assert srv.freq_hz == 119_600_000 and srv.gain == 207 and srv.gain_mode == 1
        assert (0x03, 0) in srv.cmds and srv.ppm == -3 and srv.agc == 1
        assert len(spawned) == 1 and srv.connections == 1, "retune/gain never restart rtl_tcp"
    finally:
        src.close()
        srv.close()
    assert spawned[0].terminated == 1


def test_rtl_tcp_that_dies_is_a_source_error_not_a_hang():
    class Dead(FakeProc):
        def poll(self):
            return 1
    src = iqsource.RtlTcpSource(121_500_000, FS, spawn=Dead, port=1,
                                connect=lambda p: (_ for _ in ()).throw(OSError("refused")))
    t = time.time()
    with pytest.raises(iqsource.SourceError):
        src.open()
    assert time.time() - t < 2


# ============================================================================ files / recording
def test_iq_recording_plays_back_with_its_centre_and_rate(tmp_path):
    rec = iqsource.IqRecorder(146_520_000, FS, directory=str(tmp_path))
    x = _signal("NFM", 0.0, n=FS // 4)
    rec.write(dsp.iq_to_cu8(x))
    rec.close()
    assert rec.path.endswith(".cu8") and os.path.getsize(rec.path) == x.size * 2
    meta = json.load(open(os.path.splitext(rec.path)[0] + ".json"))
    assert meta["centre_hz"] == 146_520_000 and meta["rate"] == FS
    src = iqsource.FileSource(rec.path, realtime=False).open()
    assert src.centre_hz == 146_520_000 and src.rate == FS
    d = dsp.Demodulator(src.rate, "NFM", offset_hz=0)
    a = np.concatenate([d.process(src.read(0.05)[1])[0] for _ in range(5)])
    assert abs(_tone(a, d.audio_rate)[0] - 1000) < 15
    for _ in range(10):                       # loops at the end instead of stopping
        assert src.read(0.05)[1].size > 0
    src.close()


def test_sdrpp_style_wav_baseband_and_filename_metadata(tmp_path):
    p = tmp_path / "baseband_118700000Hz_12-00-00_18-11-2026.wav"
    x = _signal("AM", 0.0, n=48000)
    pcm = np.empty(x.size * 2, dtype="<i2")
    pcm[0::2] = np.round(x.real * 32000)
    pcm[1::2] = np.round(x.imag * 32000)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(250000)
        w.writeframes(pcm.tobytes())
    meta = iqsource.file_meta(str(p))
    assert meta == {"centre_hz": 118_700_000, "rate": 250000, "format": "wav", "width": 2}
    src = iqsource.FileSource(str(p), realtime=False).open()
    assert src.read(0.05)[1].size == 12500
    bad = tmp_path / "mono.wav"
    with wave.open(str(bad), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\0\0" * 10)
    with pytest.raises(iqsource.SourceError):
        iqsource.file_meta(str(bad))


def test_audio_recording_is_a_valid_wav(tmp_path):
    r = iqsource.AudioRecorder(121_500_000, "AM", 48762, directory=str(tmp_path))
    r.write(np.arange(1000, dtype=np.int16))
    r.close()
    with wave.open(r.path) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == \
            (1, 2, 48762, 1000)


def test_recordings_default_to_the_suite_data_dir():
    import suite
    assert iqsource.rec_dir() == os.path.join(suite.DATA, "recordings")


def test_audio_out_never_blocks_the_receiver():
    class Stuck:
        def __init__(self):
            import threading
            self.ev = threading.Event()

        def write(self, b):
            self.ev.wait(5)                   # the sound server has stalled

        def flush(self):
            pass

        def close(self):
            self.ev.set()

    class P:
        pid = 999999

        def __init__(self, *a, **k):
            self.stdin = Stuck()

        def wait(self, timeout=None):
            return 0

    out = iqsource.AudioOut(48000, argv_fn=lambda r: ["sink"], popen=P)
    t = time.time()
    for _ in range(100):
        out.write(np.zeros(2400, dtype=np.int16))
    assert time.time() - t < 0.5 and out.dropped > 0
    out._p.stdin.ev.set()
    out.close()


# ============================================================================ banks
def test_banks_follow_the_owner_priority_airband_first_then_ham():
    order = banks.BANK_ORDER
    assert order[0] == "Airband (full)"
    first_ham = next(i for i, n in enumerate(order) if n.startswith("Ham"))
    assert all(not n.startswith("Ham") for n in order[:first_ham])
    assert all("Air" in n or "air" in n for n in order[:first_ham])
    for need in ("NOAA Wx", "FRS/GMRS", "MURS", "Marine VHF", "Public safety VHF",
                 "Public safety UHF", "Data: ADS-B / APRS / AIS", "ISM / devices"):
        assert need in banks.BANKS


def test_full_airband_is_every_25khz_channel_118_to_137():
    b = banks.BANKS["Airband (full)"]
    assert b["mode"] == "AM" and b["ranges"] == [(118.0, 136.975, 25000.0)]
    rng = banks.range_channels(118.0, 136.975, 25000)
    assert len(rng) == 760 and rng[0] == 118.0 and rng[-1] == 136.975
    allc = banks.expand(b)
    assert any(lb.startswith("Guard") and f == 121.5 for f, lb in allc)
    assert len({round(f, 4) for f, _ in allc}) == len(allc), "named channels are not doubled"


def test_every_bank_frequency_is_tunable_and_huge_ranges_are_refused():
    for name, b in banks.BANKS.items():
        for f, _ in b["channels"]:
            assert 24.0 <= f <= 1766.0, (name, f)
        assert b["mode"] in dsp.MODES
    with pytest.raises(ValueError):
        banks.range_channels(24, 1766, 1)
    with pytest.raises(ValueError):
        banks.range_channels(10, 20, 25000)


# ============================================================================ fast scanner logic
def _scanner(chans, src_signals, **kw):
    """Drive a FastScanWorker block by block on a synthetic source (stream time, no thread)."""
    _app()
    from palisade_qt.iqworker import FastScanWorker
    audio = []

    class A:
        def __init__(self, rate):
            self.rate = rate
            self.error = None

        def write(self, pcm):
            audio.append(pcm)

        def close(self):
            pass

    w = FastScanWorker(demo=True, channels=chans, audio_factory=A, **kw)
    srv = FakeRtlTcp(signals=src_signals, realtime=False)
    srv._stop = True                                       # use only its signal generator
    srv.close()

    class Src:
        rate = FS
        centre_hz = w.centre_hz

        def set_freq(self, hz):
            self.centre_hz = srv.freq_hz = hz

        def set_gain(self, g):
            pass

        set_ppm = set_agc = set_rate = set_gain

        def flush(self, s):
            pass

        def read(self, s):
            n = int(s * FS)
            raw = srv._block(n)
            return raw, dsp.cu8_to_iq(raw)

    src = Src()
    srv.freq_hz = w.centre_hz
    w._src = src
    w.on_source_opened(src)
    rows, hits = [], []
    from PySide6 import QtCore
    w.row.connect(lambda r: (hits if r.get("kind") == "hit" else rows).append(r),
                  QtCore.Qt.DirectConnection)

    def run(seconds):
        for _ in range(int(seconds / 0.05)):
            w._apply(w._take_pending())
            raw, iq = src.read(0.05)
            w.process_block(raw, iq)
    return w, run, rows, hits, audio


AIR = [(f, lb, "AM", 8330) for f, lb in banks.expand(banks.BANKS["Airband (full)"])]


def test_windows_cover_the_airband_in_12_retunes_and_avoid_the_dc_spike():
    from palisade_qt.iqworker import plan_windows
    hz = [int(round(c[0] * 1e6)) for c in AIR]
    wins = plan_windows(hz, FS)
    assert len(wins) <= 12
    assert sorted(k for _c, g in wins for k in g) == list(range(len(hz)))
    for c, g in wins:
        for k in g:
            assert 8000 <= abs(hz[k] - c) <= 0.42 * FS


def test_scanner_stops_on_activity_plays_it_and_resumes_after_the_resume_delay():
    keyed = {"on": True}
    w, run, rows, hits, audio = _scanner(AIR, [(124.35, "AM", lambda t: keyed["on"])],
                                         squelch_db=10, resume_s=1.0, max_hold_s=0)
    run(6)
    assert hits and abs(hits[0]["mhz"] - 124.35) < 1e-6
    assert w._state == "LISTEN" and w.channels[w._listen][0] == 124.35
    assert any(np.abs(a).max() > 1000 for a in audio[-5:]), "the channel is heard"
    keyed["on"] = False
    run(0.6)
    assert w._listen is not None, "still inside the resume delay"
    assert not any(np.abs(a).max() > 0 for a in audio[-3:]), "muted once the carrier drops"
    run(0.8)
    assert w._listen is None and w._state == "SEARCH", "resumed after 1 s of quiet"
    assert w.pass_s is None or w.pass_s < 6


def test_full_airband_pass_takes_seconds_not_minutes():
    w, run, rows, hits, audio = _scanner(AIR, [], dwell_s=0.15)
    run(8)
    assert w.pass_s is not None and w.pass_s < 4.0, w.pass_s
    assert rows[-1]["floor"] is not None and rows[-1]["windows"] <= 12


def test_max_hold_leaves_a_continuous_carrier_and_skips_it_for_the_pass():
    w, run, rows, hits, audio = _scanner(AIR, [(127.85, "AM", lambda t: True)],
                                         max_hold_s=1.0, resume_s=2.0)
    run(3)
    assert hits
    run(2)
    assert w._listen is None or w.channels[w._listen][0] != 127.85
    assert w._skip_until.get(127.85, 0) > w._clock, "benched after its max hold"


def test_lockout_is_never_stopped_on_and_skip_current_locks_it():
    w, run, rows, hits, audio = _scanner(AIR, [(124.35, "AM", lambda t: True)],
                                         lockouts=[124.35])
    run(6)
    assert not hits
    w2, run2, _r, hits2, _a = _scanner(AIR, [(124.35, "AM", lambda t: True)])
    run2(4)
    assert hits2
    assert w2.skip_current() == 124.35
    run2(4)
    assert 124.35 in w2.lockouts and len(hits2) == 1


def test_priority_channel_preempts_a_lower_channel():
    pri = (121.5, "AM", 8330)
    keyed = {"pri": False}
    w, run, rows, hits, audio = _scanner(
        AIR, [(131.55, "AM", lambda t: True), (121.5, "AM", lambda t: keyed["pri"])],
        priority=pri, priority_every_s=1.0, max_hold_s=0, resume_s=3)
    run(5)
    assert w._listen is not None and w.channels[w._listen][0] == 131.55
    keyed["pri"] = True
    run(4)
    assert w._listen is not None and w.channels[w._listen][0] == 121.5, \
        "the priority channel took over"


def test_hold_freezes_the_scanner_on_the_channel():
    keyed = {"on": True}
    w, run, rows, hits, audio = _scanner(AIR, [(124.35, "AM", lambda t: keyed["on"])],
                                         resume_s=0.5)
    run(5)
    assert w._listen is not None
    w.set_hold(True)
    keyed["on"] = False
    run(3)
    assert w._listen is not None and rows[-1]["state"] == "HOLD"
    w.set_hold(False)
    run(1.5)
    assert w._listen is None


def test_squelch_and_timing_change_while_scanning():
    w, run, rows, hits, audio = _scanner(AIR, [(124.35, "AM", lambda t: True)], squelch_db=10)
    w.queue(squelch_db=90.0, dwell_s=0.3, resume_s=4.0, max_hold_s=12.0)
    run(5)
    assert not hits, "a 90 dB squelch opens on nothing"
    assert (w.squelch_db, w.dwell_s, w.resume_s, w.max_hold_s) == (90.0, 0.3, 4.0, 12.0)


# ============================================================================ the IQ worker + arbiter
def test_tuner_worker_owns_the_radio_through_the_arbiter_and_retunes_live(arb):
    from palisade_qt.iqworker import TunerWorker
    srv = FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
    procs = []

    def factory(w):
        src = iqsource.RtlTcpSource(w.centre_hz, w.rate, w.gain_db, w.ppm, w.rtl_agc,
                                    spawn=lambda a: procs.append(FakeProc(a)) or procs[-1],
                                    port=srv.port)
        return src
    audio = []
    w = TunerWorker(source="rtl", centre_hz=119_000_000, vfo_hz=119_100_000, mode="AM",
                    source_factory=factory,
                    audio_factory=lambda r: type("A", (), {"rate": r, "error": None,
                                                           "write": lambda s, p: audio.append(p),
                                                           "close": lambda s: None})())
    rows, status = [], []
    w.row.connect(rows.append)
    w.status.connect(status.append)
    w.start()
    try:
        assert _until(lambda: any(r.get("kind") == "spec" for r in rows), 5000)
        assert arb.arbiter.held_by("PRISM") and len(procs) == 1
        assert any(np.abs(a).max() > 1000 for a in audio[-5:]), "the VFO is demodulated"
        n_spec = len(rows)
        w.queue(centre_hz=120_000_000, vfo_hz=119_100_000, gain_db=12.5, mode="NFM")
        assert _until(lambda: srv.freq_hz == 120_000_000 and srv.gain == 125, 3000)
        assert _until(lambda: len(rows) > n_spec + 3, 3000)
        last = [r for r in rows if r.get("kind") == "spec"][-1]
        assert last["centre_hz"] == 120_000_000 and last["mode"] == "NFM"
        assert len(procs) == 1 and srv.connections == 1, "no restart on retune"
        assert any(s.get("live") for s in status)
        w.hold_off("stopped by operator")          # STOP: rtl_tcp closed, then radio released
        assert _until(lambda: arb.arbiter.owner() is None, 3000)
        assert procs[0].terminated >= 1
        assert _until(lambda: any(s.get("off") for s in status), 1000)
        w.set_active(True)                         # START again
        assert _until(lambda: arb.arbiter.held_by("PRISM") and len(procs) == 2, 4000)
    finally:
        w.stop()
        w.wait(4000)
        srv.close()
    assert arb.arbiter.owner() is None and all(p.terminated for p in procs)


def test_tuner_worker_waits_for_held_and_respects_a_busy_radio(arb):
    from palisade_qt.iqworker import TunerWorker
    assert arb.arbiter.request("ATLAS-APRS") and arb.wait_held("ATLAS-APRS")
    opened = []
    w = TunerWorker(source="rtl", source_factory=lambda w: opened.append(1))
    status = []
    w.status.connect(status.append)
    w.start()
    try:
        assert _until(lambda: any(s.get("busy") for s in status), 2000)
        assert not opened, "never opens the radio while another holder has it"
    finally:
        w.stop()
        w.wait(3000)
        arb.arbiter.release("ATLAS-APRS")


def test_file_playback_needs_no_radio_and_clamps_the_vfo(arb, tmp_path):
    from palisade_qt.iqworker import TunerWorker
    rec = iqsource.IqRecorder(146_520_000, FS, directory=str(tmp_path))
    rec.write(dsp.iq_to_cu8(_signal("NFM", 0.0, n=FS // 2)))
    rec.close()
    w = TunerWorker(source="file", file_path=rec.path, mode="NFM", vfo_hz=146_520_000,
                    audio=False)
    rows = []
    w.row.connect(rows.append)
    w.start()
    try:
        assert _until(lambda: any(r.get("kind") == "spec" for r in rows), 4000)
        assert arb.arbiter.owner() is None, "playback never takes the dongle"
        w.queue(vfo_hz=160_000_000)                   # outside the recording
        assert _until(lambda: rows[-1].get("vfo_hz", 0) and
                      abs(rows[-1]["vfo_hz"] - 146_520_000) <= 0.45 * FS + 1, 3000)
        assert rows[-1]["centre_hz"] == 146_520_000
    finally:
        w.stop()
        w.wait(3000)


def test_recording_from_the_worker_writes_audio_and_iq(arb, tmp_path):
    from palisade_qt.iqworker import TunerWorker
    w = TunerWorker(demo=True, centre_hz=118_700_000, vfo_hz=118_700_000, mode="AM",
                    audio=False)
    rows = []
    w.row.connect(rows.append)
    w.start()
    try:
        assert _until(lambda: any(r.get("kind") == "spec" for r in rows), 4000)
        w.queue(rec_audio=True, rec_iq=True, rec_dir=str(tmp_path))
        assert _until(lambda: sum(1 for r in rows if r.get("kind") == "rec" and r["on"]) == 2,
                      3000)
        _pump(600)
        w.queue(rec_audio=False, rec_iq=False)
        assert _until(lambda: sum(1 for r in rows if r.get("kind") == "rec"
                                  and not r["on"]) == 2, 3000)
    finally:
        w.stop()
        w.wait(3000)
    wavs = [p for p in os.listdir(tmp_path) if p.endswith(".wav")]
    cu8s = [p for p in os.listdir(tmp_path) if p.endswith(".cu8")]
    assert wavs and cu8s
    with wave.open(str(tmp_path / wavs[0])) as wv:
        assert wv.getnframes() > 10000
    assert os.path.getsize(tmp_path / cu8s[0]) > FS        # > 0.5 s of baseband


# ============================================================================ pages
def _prism(demo=True):
    _app()
    from palisade_qt.prism import PrismApp
    return PrismApp(demo=demo, mode="dark")


def test_prism_typed_frequency_recentres_and_bad_input_is_refused():
    p = _prism()
    try:
        p.freq_edit.setText("162.55")
        p.freq_edit.returnPressed.emit()
        assert p._vfo_hz == p._centre_hz == 162_550_000
        assert p.freq_edit.text() == "162.550 000"
        p.freq_edit.setText("3 MHz")
        p.freq_edit.returnPressed.emit()
        assert p._vfo_hz == 162_550_000 and "refused" in p.busy.text()
    finally:
        p.stop()


def test_prism_click_drag_and_wheel_move_the_vfo():
    p = _prism()
    try:
        p.step_combo.setCurrentIndex([s for s, _ in __import__(
            "palisade_qt.prism", fromlist=["STEPS"]).STEPS].index("25 kHz"))
        p.scope.push(np.full(8192, -80.0), 118_000_000, 120_048_000)
        p.scope._clicked(119.312)                       # a click at 119.312 MHz
        assert p._vfo_hz == 119_300_000, "snapped to the 25 kHz step"
        p.scope.vline.setValue(119.4)
        p.scope.vline.sigDragged.emit(p.scope.vline)    # dragging the VFO line
        assert p._vfo_hz == 119_400_000
        p.scope.wheel_step.emit(1)
        assert p._vfo_hz == 119_425_000
        assert p.handle_key("[") and p._vfo_hz == 119_400_000
        c = p._centre_hz
        p._tune(c + 2_000_000)                          # past the band edge -> recentre
        assert p._centre_hz == c + 2_000_000
    finally:
        p.stop()


def test_prism_mode_bandwidth_zoom_levels_and_keys():
    p = _prism()
    try:
        p.mode_combo.setCurrentText("WFM")
        assert p.bw_spin.value() == pytest.approx(200.0)
        assert p.step_combo.currentData() == 100000
        p.bw_spin.setValue(150)
        assert p.scope.bw_hz == 150000
        p.mode_combo.setCurrentText("USB")
        assert p.bw_spin.maximum() == 5.0
        a, b = p.scope._passband()
        assert a == p._vfo_hz and b > a, "USB passband is one-sided"
        assert p.handle_key("+") and p.scope.zoom == 2 and p.zoom_lbl.text() == "2×"
        assert p.handle_key("-") and p.scope.zoom == 1
        assert p.handle_key("m") and p.mode_combo.currentText() == "LSB"
        p.wf_lo.setValue(-100)
        p.wf_hi.setValue(-30)
        assert p.scope.levels == (-100.0, -30.0)
        p.scope.push(np.r_[np.full(8000, -70.0), np.full(192, -20.0)], 118e6, 120e6)
        lo, hi = p.scope.auto_levels()
        assert lo < -70 < -20 < hi
    finally:
        p.stop()


def test_prism_zoom_shows_the_vfo_neighbourhood_at_full_resolution():
    p = _prism()
    try:
        db = np.full(8192, -80.0)
        db[5000] = -20.0
        p.scope.push(db, 118e6, 120.048e6)
        p._tune(int(118e6 + 5000 * 2.048e6 / 8192))
        p.scope.set_zoom(8)
        lo, hi = p.scope.window()
        assert hi - lo == pytest.approx(2.048e6 / 8)
        rows, *_ = p.scope._cols()
        assert rows.shape[1] == 1024 and rows[-1].max() == -20.0
    finally:
        p.stop()


def test_prism_bookmarks_are_saved_and_banks_tune_with_their_mode():
    import suite
    p = _prism(demo=False)
    try:
        p._tune(146_520_000, recentre=True)
        p.mode_combo.setCurrentText("NFM")
        p.bm_name.setText("2m calling")
        p.bm_add.click()
        saved = json.load(open(os.path.join(suite.CFG, "prism.json")))["bookmarks"]
        assert saved[-1]["hz"] == 146_520_000 and saved[-1]["label"] == "2m calling"
        assert p.bm_list.count() == 1
        p.bank_combo.setCurrentText("Airband (full)")
        it = next(p.bm_list.item(i) for i in range(p.bm_list.count())
                  if "Guard" in p.bm_list.item(i).text())
        p._bm_tune(it)
        assert p._vfo_hz == 121_500_000 and p.mode_combo.currentText() == "AM"
        assert any(abs(hz - 121.5e6) < 1 for hz, _ in p.scope.bookmarks)
        p.bank_combo.setCurrentIndex(0)
        p.bm_list.setCurrentRow(0)
        p.bm_del.click()
        assert p.bm_list.count() == 0
    finally:
        p.stop()


def test_prism_settings_persist_and_feed_the_worker():
    import suite
    p = _prism(demo=False)
    try:
        p.auto_gain.setChecked(True)
        p.sq_on.setChecked(True)
        p.sq_slider.setValue(-45)
        p.ppm.setValue(7)
        p.rtl_agc.setChecked(True)
        p.rate_combo.setCurrentIndex(list(dsp.SAMPLE_RATES).index(1024000))
        cfg = json.load(open(os.path.join(suite.CFG, "prism.json")))
        assert cfg["auto_gain"] and cfg["squelch_on"] and cfg["squelch_db"] == -45
        assert cfg["ppm"] == 7 and cfg["rtl_agc"] and cfg["rate"] == 1024000
        w = p.make_worker()
        assert w.gain_db is None and w.ppm == 7 and w.rtl_agc and w.rate == 1024000
        assert w.squelch_db == -45 and w.NAME == "PRISM"
    finally:
        p.stop()


def test_prism_start_stop_button_is_green_running_red_stopped():
    p = _prism(demo=True)          # demo receives (synthetic IQ); offscreen live is STANDBY = red
    try:
        p.start()
        p.set_active(True)
        _pump(600)
        assert p.run_btn.property("run") == "on" and p.run_btn.text() == "STOP"
        p.run_btn.click()
        _pump(100)
        assert p.run_btn.property("run") == "off" and p.run_btn.text() == "START"
        assert p._worker.held_off
        p.set_active(False)
        p.set_active(True)                          # re-showing the page keeps it stopped
        assert p._worker.held_off and p.run_btn.property("run") == "off"
        p.run_btn.click()
        assert not p._worker.held_off and p.run_btn.property("run") == "on"
    finally:
        p.stop()


def test_prism_standby_without_a_radio_tool_is_red_not_green():
    p = _prism(demo=False)         # offscreen: no capture -> STANDBY
    try:
        p.start()
        p.set_active(True)
        assert _until(lambda: p.run_btn.property("run") == "off", 3000)
        assert p.run_btn.text() == "START"
    finally:
        p.stop()


def test_prism_wide_sweep_source_keeps_the_old_band_keys():
    from palisade_qt.prism import SweepWorker
    p = _prism()
    try:
        p.source_combo.setCurrentIndex(2)
        assert p._source == "sweep" and isinstance(p.make_worker(), SweepWorker)
        c0, s0 = p.centre.value(), p.span.value()
        assert p.handle_key("]") and p.centre.value() == pytest.approx(c0 + s0)
        assert p.handle_key("+") and p.span.value() == pytest.approx(s0 / 2)
        assert not p.freq_edit.isEnabled()
    finally:
        p.stop()


def test_run_state_qss_exists_in_every_theme():
    from palisade_qt import theme
    for mode in ("dark", "light", "sun"):
        q = theme.qss(mode)
        assert 'QPushButton[run="on"]' in q and 'QPushButton[run="off"]' in q
        tok = theme.tokens(mode)
        on = q.split('QPushButton[run="on"] {')[1].split("}")[0]
        off = q.split('QPushButton[run="off"] {')[1].split("}")[0]
        assert tok["live"] in on and tok["alert"] in off


def _prowl(demo=False, engine="fast"):
    _app()
    import suite
    from palisade_qt.prowl import ProwlApp
    path = os.path.join(suite.CFG, "prowl_scan.json")
    os.makedirs(suite.CFG, exist_ok=True)
    cfg = {}
    try:
        cfg = json.load(open(path))
    except (OSError, ValueError):
        pass
    cfg["engine"] = engine
    json.dump(cfg, open(path, "w"))
    return ProwlApp(demo=demo, mode="dark")


def test_prowl_banks_list_airband_first_and_build_the_range():
    from palisade_qt.prowl import CUSTOM_RANGE
    p = _prowl()
    try:
        assert p.bank_combo.itemText(0) == "Airband (full)"
        assert p.bank_combo.itemText(p.bank_combo.count() - 1) == CUSTOM_RANGE
        p.bank_combo.setCurrentText("Airband (full)")
        ch = p._scan_channels()
        assert len(ch) >= 760 and ch[0][0] == 118.0 and ch[-1][0] == 136.975
        p.include_ranges.setChecked(False)
        assert len(p._scan_channels()) == len(banks.BANKS["Airband (full)"]["channels"])
        p.range_lo.setValue(462.55)
        p.range_hi.setValue(462.725)
        p.range_mode.setCurrentText("NFM")
        p.step_combo.setCurrentIndex([s for s, _ in __import__(
            "palisade_qt.prowl", fromlist=["SCAN_STEPS"]).SCAN_STEPS].index("12.5 kHz"))
        p._scan_range()
        ch = p._scan_channels()
        assert p.bank_combo.currentText() == CUSTOM_RANGE
        assert [c[0] for c in ch] == banks.range_channels(462.55, 462.725, 12500)
        assert all(c[2] == "NFM" for c in ch)
    finally:
        p.stop()


def test_prowl_per_bank_squelch_timing_priority_and_lockouts_persist_and_reach_the_worker():
    import suite
    from palisade_qt.iqworker import FastScanWorker
    p = _prowl()
    try:
        p.bank_combo.setCurrentText("Ham 2m")
        p.fast_sq.setValue(17)
        p.bank_combo.setCurrentText("Marine VHF")
        p.fast_sq.setValue(6)
        p.bank_combo.setCurrentText("Ham 2m")
        assert p.fast_sq.value() == 17, "squelch is remembered per bank"
        p.dwell.setValue(0.3)
        p.resume.setValue(4.0)
        p.max_hold.setValue(45.0)
        p.pri_freq.setValue(146.52)
        p.pri_mode.setCurrentText("NFM")
        p.pri_on.setChecked(True)
        p._set_locks([146.55, 147.42])
        cfg = json.load(open(os.path.join(suite.CFG, "prowl_scan.json")))
        assert cfg["bank_squelch"] == {"Ham 2m": 17, "Marine VHF": 6}
        assert (cfg["dwell"], cfg["resume"], cfg["max_hold"]) == (0.3, 4.0, 45.0)
        assert cfg["priority_on"] and cfg["priority_mhz"] == 146.52
        assert cfg["lockouts"] == [146.55, 147.42] and p.lock_list.count() == 2
        w = p.make_worker()
        assert isinstance(w, FastScanWorker)
        assert (w.squelch_db, w.dwell_s, w.resume_s, w.max_hold_s) == (17.0, 0.3, 4.0, 45.0)
        assert w.priority == (146.52, "NFM", 12500) and w.lockouts == {146.55, 147.42}
        p.lock_list.setCurrentRow(0)
        p._lock_remove()
        assert p._locks() == [147.42]
        p._lock_clear()
        assert p._locks() == []
    finally:
        p.stop()


def test_prowl_classic_engine_gets_the_bank_timing_and_lockouts():
    from palisade_qt.prowl import ScanWorker
    p = _prowl(engine="classic")
    try:
        p.bank_combo.setCurrentText("MURS")
        p.dwell.setValue(0.8)
        p.resume.setValue(3.0)
        p.max_hold.setValue(25.0)
        p._set_locks([151.94])
        w = p.make_worker()
        assert isinstance(w, ScanWorker)
        assert [c[0] for c in w._channels_override] == [151.82, 151.88, 151.94, 154.57, 154.6]
        assert w._timing == {"dwell": 0.8, "hold": 3.0, "max_active": 25.0}
        assert w._skip == {151.94}
        import scanner as engine
        assert w._bank_list(engine, {})[0] == (151.82, "MURS 1", "nfm")
    finally:
        p.stop()


def test_prowl_scan_button_green_scanning_red_hold():
    p = _prowl(demo=True, engine="classic")
    try:
        p.start()
        _pump(400)
        assert p.hold_btn.text() == "SCAN" and p.hold_btn.property("run") == "on"
        p._toggle_hold()
        assert p.hold_btn.text() == "HOLD" and p.hold_btn.property("run") == "off"
        p._toggle_hold()
        assert p.hold_btn.property("run") == "on"
        p.on_status({"off": True, "sdr": {"text": "SCAN OFF — page hidden"}})
        assert p.hold_btn.property("run") == "off", "radio off reads red"
    finally:
        p.stop()


def test_prowl_fast_demo_scans_the_synthetic_airband():
    p = _prowl(demo=True, engine="classic")
    try:
        p.engine_combo.setCurrentIndex(0)                 # FAST in demo: synthetic IQ
        p.bank_combo.setCurrentText("Airband (full)")
        p.heard_only.setChecked(False)
        p.start()
        p.set_active(True)
        assert _until(lambda: p.feed.model.rowCount() >= 760, 4000)
        p.heard_only.setChecked(True)
        assert _until(lambda: 0 < p.feed.model.rowCount() < 100, 3000), "named + heard only"
        assert _until(lambda: "LISTEN" in p.scan_info.text() or "SEARCH" in p.scan_info.text(),
                      3000)
    finally:
        p.stop()


# ============================================================================ backcheck gaps
@pytest.mark.parametrize("pos,hz", [(0, 100_000_000), (2, 1_000_000), (3, 100_000),
                                    (4, 100_000), (6, 1000), (7, 100), (8, 100), (10, 1)])
def test_digit_under_the_wheel_maps_to_its_place_value(pos, hz):
    from palisade_qt.kit.tuner import digit_step_hz
    assert digit_step_hz("121.500 000", pos) == hz      # pos 7 is the space -> next digit


def test_prism_wheel_over_a_frequency_digit_steps_that_digit():
    from PySide6 import QtCore, QtGui
    p = _prism()
    try:
        p._tune(121_500_000, recentre=True)
        p.resize(1280, 720)
        p.show()
        _pump(50)
        e = p.freq_edit
        e.setCursorPosition(6)                            # the 1 kHz digit
        pt = QtCore.QPointF(e.cursorRect().center()) + QtCore.QPointF(4, 0)
        ev = QtGui.QWheelEvent(pt, e.mapToGlobal(pt), QtCore.QPoint(0, 0),
                               QtCore.QPoint(0, 120), QtCore.Qt.NoButton,
                               QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
        QtWidgets_app = _app()
        QtWidgets_app.sendEvent(e, ev)
        assert p._vfo_hz == 121_501_000, p._vfo_hz
        e.digit_step.emit(-1_000_000)                     # wheel down over the MHz digit
        assert p._vfo_hz == 120_501_000 and e.text() == "120.501 000"
    finally:
        p.stop()


def test_prism_dragging_a_passband_edge_sets_the_bandwidth():
    p = _prism()
    try:
        p._tune(121_500_000, recentre=True)
        p.mode_combo.setCurrentText("AM")
        p.bw_spin.setValue(8.33)
        sc = p.scope
        sc.push(np.full(8192, -80.0), 120_476_000, 122_524_000)
        a, b = sc._passband()
        sc.band.setRegion((a / 1e6, (b + 2000) / 1e6))   # upper edge out by 2 kHz
        assert abs(p.bw_spin.value() * 1000 - (8330 + 4000)) < 20, "symmetric: +2 kHz each side"
        assert p._vfo_hz == 121_500_000, "an edge drag never moves the VFO"
        a, b = sc._passband()
        assert abs((b - a) - p.bw_spin.value() * 1000) < 20, "region snapped to the new bw"
        p.mode_combo.setCurrentText("USB")
        p.bw_spin.setValue(2.8)
        a, b = sc._passband()
        sc.band.setRegion((a / 1e6, (b - 600) / 1e6))
        assert abs(p.bw_spin.value() * 1000 - 2200) < 20, "USB is one-sided"
        a, b = sc._passband()
        sc.band.setRegion(((a + 25000) / 1e6, (b + 25000) / 1e6))   # whole band dragged
        assert p._vfo_hz == 121_525_000
        sc.band.setRegion((a / 1e6, (b + 10_000_000) / 1e6))         # absurd -> clamped
        assert p.bw_spin.value() * 1000 <= dsp.BW_LIMITS["USB"][1]
    finally:
        p.stop()


def test_prism_fft_smoothing_averages_the_line_not_the_waterfall():
    import suite
    p = _prism(demo=False)
    try:
        sc = p.scope
        p.smooth_combo.setCurrentIndex(3)                  # heavy
        assert json.load(open(os.path.join(suite.CFG, "prism.json")))["smooth"] == 0.9
        sc.push(np.full(4096, -80.0), 118e6, 120e6)
        sc.push(np.full(4096, -40.0), 118e6, 120e6)
        y = sc.curve.getData()[1]
        assert abs(float(np.median(y)) - (-76.0)) < 0.5, "0.9*-80 + 0.1*-40"
        assert float(sc.buf[-1].max()) == -40.0, "waterfall keeps the raw frame"
        p.smooth_combo.setCurrentIndex(0)
        sc.push(np.full(4096, -40.0), 118e6, 120e6)
        assert abs(float(np.median(sc.curve.getData()[1])) + 40.0) < 0.1
    finally:
        p.stop()


def test_prowl_scans_the_prism_bookmarks():
    import suite
    os.makedirs(suite.CFG, exist_ok=True)
    path = os.path.join(suite.CFG, "prism.json")
    try:
        cfg = json.load(open(path))
    except (OSError, ValueError):
        cfg = {}
    cfg["bookmarks"] = [{"hz": 146_520_000, "label": "2m calling", "mode": "NFM", "bw": 12500},
                        {"hz": 50_125_000, "label": "6m SSB", "mode": "USB", "bw": 2800},
                        {"hz": "junk"}]
    json.dump(cfg, open(path, "w"))
    p = _prowl(demo=False, engine="fast")
    try:
        from palisade_qt.prowl import MY_BOOKMARKS
        p.bank_combo.setCurrentText(MY_BOOKMARKS)
        ch = p._scan_channels()
        assert [(c[0], c[1], c[2]) for c in ch] == [(50.125, "6m SSB", "USB"),
                                                     (146.52, "2m calling", "NFM")]
        assert "2 bookmarks" in p.scan_info.text()
    finally:
        p.stop()


def test_prowl_fm_tab_tunes_am_and_keeps_am_in_the_weather_band():
    import fm
    rtl, _mid, _sink = fm.pipeline(121.5, "am", 30, 0)
    assert rtl[rtl.index("-M") + 1] == "am" and "121.5000M" in rtl
    p = _prowl(demo=True, engine="classic")
    try:
        assert p.fm_mode.findText("am") >= 0
        p.fm_mode.setCurrentText("am")
        p.fm_freq.setValue(162.55)
        p._fm_retune()
        assert p.fm_mode.currentText() == "am", "only WFM is forced to NFM in the NWR band"
        p.fm_mode.setCurrentText("wbfm")
        p._fm_retune()
        assert p.fm_mode.currentText() == "nbfm"
    finally:
        p.stop()


# ============================================================================ RA-RADIO findings
FAKE_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_bin")


def test_n1_rtl_tcp_output_is_drained_so_retunes_keep_applying(tmp_path, monkeypatch):
    """rtl_tcp prints a line per retune; an unread pipe fills and it stops retuning (~3,400)."""
    monkeypatch.setenv("PATH", FAKE_BIN + os.pathsep + os.environ["PATH"])
    state = tmp_path / "state"
    monkeypatch.setenv("FAKE_STATE", str(state))
    s = iqsource.RtlTcpSource(121_500_000, 2048000).open()
    try:
        last = None
        for n in range(5000):
            last = 118_000_000 + (n % 760) * 25_000
            s.set_freq(last)
            if n % 500 == 499:
                s.read(0.02)
        assert _until(lambda: state.exists() and state.read_text() == str(last), 5000), \
            "rtl_tcp stopped applying retunes (output pipe full?)"
        assert s.alive()
    finally:
        s.close()


def test_n2_a_dead_control_socket_is_a_source_error():
    import socket
    a, b = socket.socketpair()
    b.sendall(b"RTL0" + struct.pack(">II", 5, 29))
    src = iqsource.RtlTcpSource(121_500_000, 2048000, spawn=FakeProc, port=1,
                                connect=lambda p: a).open()
    b.close()
    with pytest.raises(iqsource.SourceError):
        for n in range(100000):
            src.set_freq(118_000_000 + n)
    src.close()


def test_n2_worker_survives_a_broken_pipe_and_a_bug_and_shows_the_fault(arb):
    from palisade_qt.iqworker import TunerWorker
    srv = FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
    procs, holder = [], {}

    class Src(iqsource.RtlTcpSource):
        def set_freq(self, hz):
            if getattr(self, "dead", False):
                raise BrokenPipeError(32, "Broken pipe")
            super().set_freq(hz)

    def factory(w):
        holder["s"] = Src(w.centre_hz, w.rate, spawn=lambda av: procs.append(FakeProc(av))
                          or procs[-1], port=srv.port)
        return holder["s"]
    w = TunerWorker(source="rtl", centre_hz=119_000_000, mode="AM", source_factory=factory,
                    audio=False)
    rows, status = [], []
    w.row.connect(rows.append)
    w.status.connect(status.append)
    w.start()
    try:
        assert _until(lambda: rows, 4000)
        holder["s"].dead = True
        w.queue(centre_hz=120_000_000)
        assert _until(lambda: any(s.get("fault") for s in status), 3000)
        assert w.isRunning(), "the worker thread is still alive"
        assert procs[0].terminated >= 1
        # an internal error in the block processing is a fault too, not a dead thread
        w._fault = None
        status.clear()
        orig = w.process_block
        w.process_block = lambda raw, iq: (_ for _ in ()).throw(IndexError("boom"))
        assert _until(lambda: any("IndexError" in str(s.get("fault")) for s in status), 9000)
        assert w.isRunning()
        w.process_block = orig
    finally:
        w.stop()
        w.wait(4000)
        srv.close()
    assert arb.arbiter.owner() is None


def test_n2_prism_run_button_goes_red_on_a_fault():
    p = _prism()
    try:
        p.start()
        p.set_active(True)
        _pump(100)
        p.on_status({"sdr": {"text": "SDR PRISM", "state": "live"}, "live": True})
        assert p.run_btn.property("run") == "on"
        p.on_status({"sdr": {"text": "SDR FAULT — x", "state": "alert"}, "fault": "x",
                     "live": False})
        assert p.run_btn.property("run") == "off" and p.run_btn.text() == "START"
        p.run_btn.click()                                  # START retries at once
        assert p.run_btn.property("run") == "on"
    finally:
        p.stop()


def test_n3_changing_the_bank_during_a_priority_check_does_not_crash():
    w, run, rows, hits, audio = _scanner(AIR, [(131.55, "AM", lambda t: True)],
                                         priority=(121.5, "AM", 8330), priority_every_s=1.0,
                                         max_hold_s=0, resume_s=3)
    for _ in range(400):
        run(0.05)
        if w._detour is not None:
            break
    assert w._detour is not None, "reached a priority check"
    b = banks.BANKS["NOAA Wx"]
    w.queue(channels=[(f, lb, b["mode"], b["bw"]) for f, lb in banks.expand(b)], priority=None)
    run(2.0)
    assert w._detour is None and w._win < len(w._windows)


@pytest.mark.parametrize("chans,strong,weak", [
    ("NOAA", 162.4, 162.475),          # a one-window bank
    ("AIR", 124.35, 124.6),            # two channels in the same airband capture
])
def test_n4_max_hold_lets_weaker_channels_in_the_same_capture_be_heard(chans, strong, weak):
    if chans == "NOAA":
        b = banks.BANKS["NOAA Wx"]
        chans = [(f, lb, b["mode"], b["bw"]) for f, lb in banks.expand(b)]
        mode = "NFM"
    else:
        chans, mode = AIR, "AM"
    w, run, rows, hits, audio = _scanner(chans, [(strong, mode, lambda t: True),
                                                 (strong, mode, lambda t: True),
                                                 (weak, mode, lambda t: True)],
                                         max_hold_s=2.0, resume_s=2.0, squelch_db=10)
    run(20)
    heard = {round(h["mhz"], 4) for h in hits}
    assert strong in heard and weak in heard, [round(h["mhz"], 4) for h in hits]


def test_n5_a_revoke_while_rtl_tcp_starts_kills_it_before_the_radio_is_freed(arb):
    import socket
    from palisade_qt.iqworker import TunerWorker
    log = []
    arb.arbiter.transition.connect(lambda e, o, n: log.append((time.monotonic(), "ARB", e)))

    class P(FakeProc):
        def terminate(self):
            log.append((time.monotonic(), "PROC", "terminate"))
            super().terminate()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                              # nothing listens: still starting
    procs = []
    w = TunerWorker(source="rtl", audio=False, source_factory=lambda w: iqsource.RtlTcpSource(
        w.centre_hz, w.rate, spawn=lambda a: procs.append(P(a)) or procs[-1], port=port))
    w.start()
    try:
        assert _until(lambda: procs, 3000)
        _pump(300)
        t0 = time.monotonic()
        arb.arbiter.revoke("PRISM")
        assert _until(lambda: arb.arbiter.owner() is None, 6000)
        kill = [t for t, k, e in log if k == "PROC" and t >= t0]
        free = [t for t, k, e in log if k == "ARB" and e in ("RELEASE", "FORCED_FREE",
                                                              "FREE") and t >= t0]
        assert kill and kill[0] - t0 < 2.0, "rtl_tcp killed promptly"
        assert not free or kill[0] <= free[0], "killed before the radio is freed"
    finally:
        w.stop()
        w.wait(4000)


def test_n6_two_recordings_in_the_same_second_get_different_files(tmp_path):
    a = iqsource.IqRecorder(121_500_000, 2048000, directory=str(tmp_path))
    b = iqsource.IqRecorder(121_500_000, 2048000, directory=str(tmp_path))
    c = iqsource.AudioRecorder(121_500_000, "AM", 48000, directory=str(tmp_path))
    d = iqsource.AudioRecorder(121_500_000, "AM", 48000, directory=str(tmp_path))
    try:
        assert a.path != b.path and c.path != d.path
        a.write(b"\x80" * 4000)
        b.write(b"\x80" * 2000)
        a.close()
        b.close()
        assert os.path.getsize(a.path) == 4000 and os.path.getsize(b.path) == 2000
        assert iqsource.file_meta(b.path)["centre_hz"] == 121_500_000
    finally:
        c.close()
        d.close()


def test_n7_recording_stops_itself_when_the_disk_is_nearly_full(tmp_path, monkeypatch):
    monkeypatch.setattr(iqsource, "MIN_FREE_BYTES", 1 << 62)
    r = iqsource.IqRecorder(121_500_000, 2048000, directory=str(tmp_path))
    r.write(b"\x80" * 4000)
    assert r.stopped_reason == "disk nearly full" and r.bytes == 0
    a = iqsource.AudioRecorder(121_500_000, "AM", 48000, directory=str(tmp_path))
    a.write(np.zeros(4800, dtype=np.int16))
    assert a.stopped_reason == "disk nearly full" and a.frames == 0


def test_n9_raw_is_labelled_mono_in_the_ui():
    from PySide6 import QtCore
    p = _prism()
    try:
        tip = p.mode_combo.itemData(dsp.MODES.index("RAW"), QtCore.Qt.ToolTipRole)
        assert "mono" in tip and "mono" in p.mode_combo.toolTip()
    finally:
        p.stop()


def test_n11_locking_out_one_channel_never_ends_a_different_listen():
    w, run, rows, hits, audio = _scanner(AIR, [(124.35, "AM", lambda t: True)])
    run(4)
    assert w._listen is not None and w.channels[w._listen][0] == 124.35
    w.queue(lockout_add=118.0)                 # the page locked out a channel it last showed
    run(0.2)
    assert w._listen is not None and w.channels[w._listen][0] == 124.35


def test_n11_prowl_hold_does_not_write_the_worker_flag_from_the_gui():
    p = _prowl(demo=True, engine="fast")
    try:
        p.start()
        p.set_active(True)
        w = p._worker
        assert _until(lambda: w.isRunning(), 2000)
        p._toggle_hold()
        assert p.hold_btn.text() == "HOLD" and p.hold_btn.property("run") == "off"
        assert _until(lambda: w.hold, 2000), "the worker applied it on its own thread"
        p._toggle_hold()
        assert p.hold_btn.text() == "SCAN" and _until(lambda: not w.hold, 2000)
    finally:
        p.stop()


# ============================================================================ RA-RADIOb findings
class _NoProc:
    stdout = None

    def poll(self):
        return None

    def terminate(self):
        pass


def _pair_source():
    import socket
    a, b = socket.socketpair()
    b.sendall(b"RTL0" + struct.pack(">II", 5, 29))
    s = iqsource.RtlTcpSource(121_500_000, FS, spawn=lambda av: _NoProc(), port=1,
                              connect=lambda p: a).open()
    return s, b


@pytest.mark.parametrize("split", [100000, 100001, 100002, 100003])
def test_b1_dropping_stale_iq_keeps_i_and_q_aligned(split):
    """A retune can land mid-sample (TCP splits anywhere): the tone must stay on its side."""
    s, b = _pair_source()
    try:
        n = np.arange(400_000)
        z = 0.5 * np.exp(2j * np.pi * 200_000.0 * n / FS)
        data = dsp.iq_to_cu8(z)
        b.sendall(data[:split])                # (socketpair buffer: keep sends < ~200 KB)
        time.sleep(0.1)
        s.set_freq(122_000_000)                # -> drop_buffered()
        b.sendall(data[split:split + 200_000])
        time.sleep(0.1)
        _raw, iq = s.read(0.05)
        sp = np.fft.fftshift(np.abs(np.fft.fft(iq[:65536])))
        fr = np.fft.fftshift(np.fft.fftfreq(65536, 1 / FS))
        assert abs(fr[np.argmax(sp)] - 200_000) < 2000, "spectrum mirrored: I/Q swapped"
    finally:
        s.close()
        b.close()


def test_b2_a_repeating_fault_leaves_the_radio_free_and_backs_off(arb):
    from palisade_qt.iqworker import TunerWorker
    srv = FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
    opens = []

    def factory(w):
        opens.append(time.monotonic())
        return iqsource.RtlTcpSource(w.centre_hz, w.rate, spawn=FakeProc, port=srv.port)
    w = TunerWorker(source="rtl", centre_hz=119_000_000, mode="AM", source_factory=factory,
                    audio=False)
    w.process_block = lambda raw, iq: (_ for _ in ()).throw(ValueError("bug"))
    held_idle = []
    w.start()
    try:
        t_end = time.monotonic() + 9
        while time.monotonic() < t_end:
            _pump(50)
            held_idle.append(arb.arbiter.held_by("PRISM") and w._src is None)
        assert sum(held_idle) / len(held_idle) < 0.15, "radio kept while faulted"
        assert len(opens) <= 2, "retry backs off (5 s, then 10 s)"
        assert w._retry_s() >= 10
    finally:
        w.stop()
        w.wait(4000)
        srv.close()


def test_b3_a_missing_iq_file_is_a_fault_and_start_restarts(arb, tmp_path):
    from palisade_qt.iqworker import TunerWorker
    missing = str(tmp_path / "iq_20261118-000000Z_121500000Hz_2048000sps.cu8")
    w = TunerWorker(source="file", file_path=missing, audio=False)
    st = []
    w.status.connect(st.append)
    w.start()
    try:
        assert _until(lambda: any("FileNotFoundError" in str(s.get("fault")) for s in st), 3000)
        assert w.isRunning(), "the thread survives an open error"
    finally:
        w.stop()
        w.wait(3000)
    # PRISM: a finished worker reads red, and START makes a new one
    p = _prism()
    try:
        p.start()
        p.set_active(True)
        _pump(200)
        old = p._worker
        old.stop()
        old.wait(3000)
        p._sync_run_btn()
        assert p.run_btn.property("run") == "off"
        p.run_btn.click()
        assert _until(lambda: p._worker is not None and p._worker is not old
                      and p._worker.isRunning(), 3000)
        assert _until(lambda: p.run_btn.property("run") == "on", 2000)
    finally:
        p.stop()


def test_b3_prowl_enter_restarts_a_finished_fast_scanner():
    p = _prowl(demo=False, engine="fast")
    try:
        p.start()
        p.set_active(True)
        _pump(200)
        old = p._worker
        old.stop()
        old.wait(3000)
        assert p.primary_action()
        assert _until(lambda: p._worker is not None and p._worker is not old, 3000)
    finally:
        p.stop()


def test_b5_rtl_tcp_closing_during_the_header_is_an_error_not_a_spin():
    import socket
    a, b = socket.socketpair()
    b.sendall(b"RTL0")
    b.close()
    t = time.monotonic()
    with pytest.raises(iqsource.SourceError):
        iqsource.RtlTcpSource(121_500_000, FS, spawn=lambda av: _NoProc(), port=1,
                              connect=lambda p: a).open()
    assert time.monotonic() - t < 0.5


def test_b6_the_output_drain_survives_undecodable_bytes(tmp_path, monkeypatch):
    """rtl_tcp printing non-UTF-8 must not stop the drain (else N1's stall comes back)."""
    monkeypatch.setenv("PATH", FAKE_BIN + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_GARBAGE", "1")
    state = tmp_path / "state"
    monkeypatch.setenv("FAKE_STATE", str(state))
    s = iqsource.RtlTcpSource(121_500_000, 2048000).open()
    try:
        last = None
        for n in range(5000):
            last = 118_000_000 + (n % 760) * 25_000
            s.set_freq(last)
            if n % 500 == 499:
                s.read(0.02)
        assert _until(lambda: state.exists() and state.read_text() == str(last), 5000)
        assert any("tuner" in ln for ln in s.err_tail) or s.err_tail[-1].startswith("set freq")
    finally:
        s.close()


def test_b7_settings_queued_when_the_source_fails_are_applied_after_the_reopen(arb):
    """Through run(): a bank change queued with a gain change that hits a dead rtl_tcp is not
    lost; a setting whose VALUE raises is dropped instead of looping (RA-RADIOc C4)."""
    from palisade_qt.iqworker import FastScanWorker
    srv = FakeRtlTcp(signals=[])
    b = banks.BANKS["NOAA Wx"]
    noaa = [(f, lb, b["mode"], b["bw"]) for f, lb in banks.expand(b)]
    made = []

    class Src(iqsource.RtlTcpSource):
        def set_gain(self, g):
            if made.index(self) == 0 and g == 20.0:
                raise iqsource.SourceError("rtl_tcp control socket: broken pipe")
            super().set_gain(g)

    def factory(w):
        made.append(Src(w.centre_hz, w.rate, spawn=FakeProc, port=srv.port))
        return made[-1]
    w = FastScanWorker(source="rtl", channels=AIR[:10], source_factory=factory, audio=False)
    w.start()
    try:
        assert _until(lambda: made and w._src is not None, 4000)
        w.queue(gain_db=20.0, channels=noaa)
        assert _until(lambda: w.faulted, 3000)
        w.retry_now()
        assert _until(lambda: len(made) == 2 and [c[0] for c in w.channels] ==
                      [c[0] for c in noaa], 6000), "the bank change survived the fault"
        assert _until(lambda: srv.gain == 200, 3000)
        w.queue(squelch_db="not a number")       # a VALUE that raises: dropped, not looped
        assert _until(lambda: w.faulted, 3000)
        assert "squelch_db" not in w._pending
        w.retry_now()
        assert _until(lambda: not w.faulted and len(made) == 3, 6000)
    finally:
        w.stop()
        w.wait(4000)
        srv.close()


def test_c1_start_and_enter_retry_a_faulted_worker_at_once_and_say_when(arb):
    from palisade_qt.iqworker import TunerWorker
    opens, st = [], []
    w = TunerWorker(source="file", file_path="/nonexistent/x_121500000Hz_2048000sps.cu8",
                    audio=False, source_factory=lambda w: opens.append(1) or (_ for _ in ()
                                                                            ).throw(OSError("x")))
    w.status.connect(st.append)
    w.start()
    try:
        assert _until(lambda: w.faulted and len(opens) == 1, 3000)
        assert _until(lambda: any("retry in" in (s.get("sdr") or {}).get("text", "")
                                  for s in st), 2000)
        w._fault_n = 6                            # deep in the back-off: 60 s
        w.retry_now()
        assert _until(lambda: len(opens) == 2, 1500), "START / Enter skips the wait"
    finally:
        w.stop()
        w.wait(3000)


def test_c2_prowl_enter_restarts_a_finished_scanner_even_if_it_was_held_off():
    p = _prowl(demo=False, engine="fast")
    try:
        p.start()
        p.set_active(True)
        _pump(200)
        old = p._worker
        old.hold_off("radio given back")
        old.stop()
        old.wait(3000)
        assert p.primary_action()
        assert _until(lambda: p._worker is not None and p._worker is not old, 3000)
    finally:
        p.stop()


def test_c3_back_off_resets_after_a_good_block(arb):
    from palisade_qt.iqworker import TunerWorker
    srv = FakeRtlTcp(signals=[(119.1, "AM", lambda t: True)])
    w = TunerWorker(source="rtl", centre_hz=119_000_000, mode="AM", audio=False,
                    source_factory=lambda w: iqsource.RtlTcpSource(w.centre_hz, w.rate,
                                                                   spawn=FakeProc,
                                                                   port=srv.port))
    rows = []
    w.row.connect(rows.append)
    w._fault_n = 5                               # earlier faults this session
    w.start()
    try:
        assert _until(lambda: rows, 4000)
        assert w._fault_n == 0 and w._retry_s() == 5.0
    finally:
        w.stop()
        w.wait(4000)
        srv.close()


def test_c4_a_cancelled_start_closes_the_half_open_source(arb):
    from palisade_qt.iqworker import TunerWorker
    closed = []

    class Half:
        kind = "rtl"

        def open(self, abort=None):
            w.set_active(False)                  # page hidden at the instant it fails
            raise iqsource.SourceError("rtl_tcp exited")

        def close(self):
            closed.append(1)
    w = TunerWorker(source="rtl", audio=False, source_factory=lambda _w: Half())
    w.start()
    try:
        assert _until(lambda: closed, 3000), "half-open rtl_tcp closed on cancel"
    finally:
        w.stop()
        w.wait(3000)
