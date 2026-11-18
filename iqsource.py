"""IQ sources, recorders and the audio sink for PRISM / PROWL — no Qt.

  RtlTcpSource — the live RTL-SDR through `rtl_tcp` bound to 127.0.0.1 only. One process holds
                 the dongle for the whole session; frequency, sample rate, gain, tuner AGC and PPM
                 change over the control socket with no restart (SDR++'s rtl_tcp source).
  FileSource   — plays back a recording (.cu8/.raw/.bin = uint8 I/Q as rtl_sdr writes it; .wav =
                 2-channel int16 I/Q as SDR++ writes baseband) at real time, looping.
  SynthSource  — DEMO only: synthesised carriers at fixed absolute frequencies (AM airband,
                 NFM, WFM broadcast, CW, USB) plus noise. Never used in live mode.
  IqRecorder / AudioRecorder — baseband (.cu8 + .json sidecar) and audio (.wav) recording.
  AudioOut     — int16 mono to pacat/aplay on a writer thread; drops (never blocks) when behind.

Every source returns IQ as complex64 via read(seconds) and never blocks longer than its timeout.
"""
import json
import math
import os
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import wave
import queue

import numpy as np

import dsp

HOME = os.path.expanduser("~")
REC_DIR = os.path.join(HOME, ".local", "share", "uconsole-suite", "recordings")


def rec_dir():
    """Recordings live under the suite data dir (suite.DATA/recordings; tests redirect DATA)."""
    try:
        import suite
        return os.path.join(suite.DATA, "recordings")
    except Exception:
        return REC_DIR
MIN_FREE_BYTES = 300 * 1024 * 1024      # recording stops itself below this much free disk


class SourceError(Exception):
    pass


# --------------------------------------------------------------------------- rtl_tcp

def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def rtl_tcp_cmd(code, value):
    """One rtl_tcp control command: 1 byte code + 4 byte big-endian value."""
    if value < 0:
        return struct.pack(">Bi", code, int(value))
    return struct.pack(">BI", code, int(value))


CMD_FREQ, CMD_RATE, CMD_GAIN_MODE, CMD_GAIN, CMD_PPM, CMD_AGC = 0x01, 0x02, 0x03, 0x04, 0x05, 0x08


def rtl_tcp_argv(port, freq_hz, rate, gain_db=None):
    argv = ["rtl_tcp", "-a", "127.0.0.1", "-p", str(int(port)), "-f", str(int(freq_hz)),
            "-s", str(int(rate))]
    if gain_db is not None:
        argv += ["-g", "%.1f" % float(gain_db)]
    return argv


class RtlTcpSource:
    """Live IQ from an rtl_tcp it spawns (own session via kit.procs.Pipeline when given, so the
    radio arbiter / PANIC can kill it). `spawn` and `connect` are injectable for tests."""
    kind = "rtl"
    CONNECT_TIMEOUT_S = 6.0

    def __init__(self, freq_hz, rate=2048000, gain_db=None, ppm=0, agc=False, spawn=None,
                 connect=None, port=None):
        self.centre_hz = int(freq_hz)
        self.rate = int(rate)
        self.gain_db = gain_db
        self.ppm = int(ppm)
        self.agc = bool(agc)
        self._spawn = spawn
        self._connect = connect or (lambda port: socket.create_connection(("127.0.0.1", port),
                                                                           timeout=1.0))
        self.port = port
        self.proc = None
        self.sock = None
        self.tuner = None
        self._carry = b""
        self.err_tail = []

    def open(self):
        self.port = self.port or _free_port()
        argv = rtl_tcp_argv(self.port, self.centre_hz, self.rate, self.gain_db)
        if self._spawn is not None:
            self.proc = self._spawn(argv)
        else:
            if not shutil.which("rtl_tcp"):
                raise SourceError("rtl_tcp not installed (apt install rtl-sdr)")
            from palisade_qt.kit.procs import Pipeline
            self.proc = Pipeline([argv], stderr_last=subprocess.PIPE)
            threading.Thread(target=self._read_err, daemon=True).start()
        deadline = time.monotonic() + self.CONNECT_TIMEOUT_S
        last = None
        while time.monotonic() < deadline:
            if self.proc is not None and getattr(self.proc, "poll", lambda: None)() is not None:
                raise SourceError("rtl_tcp exited (%s)%s" % (
                    self.proc.poll(), (": " + " · ".join(self.err_tail[-2:])) if self.err_tail
                    else " — is the SDR plugged in and free?"))
            try:
                self.sock = self._connect(self.port)
                break
            except OSError as e:
                last = e
                time.sleep(0.1)
        if self.sock is None:
            self.close()
            raise SourceError("could not connect to rtl_tcp: %s" % last)
        self.sock.settimeout(2.0)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
        except OSError:
            pass
        hdr = self._recv_exact(12)
        if len(hdr) < 12 or hdr[:4] != b"RTL0":
            self.close()
            raise SourceError("rtl_tcp sent no RTL0 header")
        self.tuner = struct.unpack(">I", hdr[4:8])[0]
        self.sock.settimeout(0.5)
        # apply everything over the control socket (also what retunes do later)
        self.set_rate(self.rate)
        self.set_freq(self.centre_hz)
        self.set_gain(self.gain_db)
        self.set_ppm(self.ppm)
        self.set_agc(self.agc)
        return self

    def _read_err(self):
        p = self.proc
        err = getattr(p, "stderr", None)
        if err is None:
            return
        try:
            for line in err:
                line = line.strip() if isinstance(line, str) else line.decode(
                    "utf-8", "replace").strip()
                if line:
                    self.err_tail = (self.err_tail + [line])[-6:]
        except Exception:
            pass

    def _recv_exact(self, n):
        out = b""
        while len(out) < n:
            try:
                d = self.sock.recv(n - len(out))
            except socket.timeout:
                break
            if not d:
                break
            out += d
        return out

    def _send(self, code, value):
        if self.sock is not None:
            self.sock.sendall(rtl_tcp_cmd(code, value))

    def set_freq(self, hz):
        self.centre_hz = int(hz)
        self._send(CMD_FREQ, self.centre_hz)

    def set_rate(self, rate):
        self.rate = int(rate)
        self._send(CMD_RATE, self.rate)

    def set_gain(self, gain_db):
        """None = tuner auto gain; a number = manual gain in dB."""
        self.gain_db = gain_db
        if gain_db is None:
            self._send(CMD_GAIN_MODE, 0)
        else:
            self._send(CMD_GAIN_MODE, 1)
            self._send(CMD_GAIN, int(round(float(gain_db) * 10)))

    def set_ppm(self, ppm):
        self.ppm = int(ppm)
        self._send(CMD_PPM, self.ppm)

    def set_agc(self, on):
        """RTL2832 digital AGC (separate from tuner auto gain)."""
        self.agc = bool(on)
        self._send(CMD_AGC, 1 if self.agc else 0)

    def flush(self, seconds):
        """Drop samples for `seconds` (settling after a retune)."""
        self.read_bytes(int(seconds * self.rate) * 2)

    def read_bytes(self, n):
        out = self._carry
        self._carry = b""
        while len(out) < n:
            try:
                d = self.sock.recv(min(1 << 18, n - len(out)))
            except socket.timeout:
                break
            except OSError as e:
                raise SourceError("rtl_tcp connection lost: %s" % e)
            if not d:
                raise SourceError("rtl_tcp closed the stream%s" % (
                    (": " + " · ".join(self.err_tail[-2:])) if self.err_tail else ""))
            out += d
        if len(out) % 2:
            out, self._carry = out[:-1], out[-1:]
        return out

    def read(self, seconds):
        """(raw cu8 bytes, complex64 iq) for about `seconds` of signal."""
        raw = self.read_bytes(int(seconds * self.rate) * 2)
        return raw, dsp.cu8_to_iq(raw)

    def alive(self):
        p = self.proc
        return self.sock is not None and (p is None or p.poll() is None)

    def close(self):
        s, self.sock = self.sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass
        p, self.proc = self.proc, None
        if p is not None:
            try:
                p.terminate()            # Pipeline: SIGTERM group, wait, SIGKILL, wait
            except Exception:
                pass


# --------------------------------------------------------------------------- file playback

_FREQ_RE = re.compile(r"(\d{6,10})\s*Hz", re.I)
_RATE_RE = re.compile(r"(\d{5,8})\s*sps", re.I)


def file_meta(path):
    """{'centre_hz', 'rate', 'format'} for a recording: sidecar JSON first, then the WAV header,
    then numbers in the filename (`..._121500000Hz_2048000sps.cu8`, SDR++ `baseband_<f>Hz_...`)."""
    meta = {"centre_hz": None, "rate": None,
            "format": "wav" if path.lower().endswith(".wav") else "cu8"}
    side = os.path.splitext(path)[0] + ".json"
    try:
        with open(side) as f:
            j = json.load(f)
        meta["centre_hz"] = int(j.get("centre_hz")) if j.get("centre_hz") else None
        meta["rate"] = int(j.get("rate")) if j.get("rate") else None
    except (OSError, ValueError, TypeError):
        pass
    if meta["format"] == "wav":
        try:
            with wave.open(path) as w:
                if w.getnchannels() != 2 or w.getsampwidth() not in (1, 2):
                    raise SourceError("WAV baseband must be 2-channel 8/16-bit I/Q")
                meta["rate"] = meta["rate"] or w.getframerate()
                meta["width"] = w.getsampwidth()
        except wave.Error as e:
            raise SourceError("not a WAV I/Q file: %s" % e)
    name = os.path.basename(path)
    if meta["centre_hz"] is None:
        m = _FREQ_RE.search(name)
        if m:
            meta["centre_hz"] = int(m.group(1))
    if meta["rate"] is None:
        m = _RATE_RE.search(name)
        if m:
            meta["rate"] = int(m.group(1))
    return meta


class FileSource:
    """Real-time playback of an IQ recording, looping at the end. No radio involved."""
    kind = "file"

    def __init__(self, path, centre_hz=None, rate=None, loop=True, realtime=True):
        self.path = path
        meta = file_meta(path)
        self.format = meta["format"]
        self.centre_hz = int(centre_hz or meta["centre_hz"] or 100_000_000)
        self.rate = int(rate or meta["rate"] or 2048000)
        self.loop = loop
        self.realtime = realtime
        self._f = None
        self._t_next = None
        self.ended = False

    def open(self):
        if self.format == "wav":
            self._f = wave.open(self.path)
            self._width = self._f.getsampwidth()
        else:
            self._f = open(self.path, "rb")
        return self

    def _read_raw(self, nsamp):
        if self.format == "wav":
            d = self._f.readframes(nsamp)
            if not d:
                return None
            if self._width == 2:
                a = np.frombuffer(d, dtype="<i2").astype(np.float32) / 32768.0
            else:
                a = (np.frombuffer(d, dtype=np.uint8).astype(np.float32) - 127.5) / 127.5
            return (a[0::2] + 1j * a[1::2]).astype(np.complex64), None
        d = self._f.read(nsamp * 2)
        if not d:
            return None
        return dsp.cu8_to_iq(d), d

    def _rewind(self):
        if self.format == "wav":
            self._f.rewind()
        else:
            self._f.seek(0)

    def read(self, seconds):
        n = max(1, int(seconds * self.rate))
        got = self._read_raw(n)
        if got is None:
            if not self.loop:
                self.ended = True
                return b"", np.zeros(0, dtype=np.complex64)
            self._rewind()
            got = self._read_raw(n)
            if got is None:
                self.ended = True
                return b"", np.zeros(0, dtype=np.complex64)
        iq, raw = got
        if raw is None:
            raw = dsp.iq_to_cu8(iq)
        if self.realtime:                                   # pace to the recording's rate
            now = time.monotonic()
            if self._t_next is None or self._t_next < now - 1.0:
                self._t_next = now
            self._t_next += iq.size / self.rate
            wait = self._t_next - time.monotonic()
            if wait > 0:
                time.sleep(min(wait, 1.0))
        return raw, iq

    # a file has a fixed centre: retunes only move the VFO inside it
    def set_freq(self, hz):
        pass

    def set_gain(self, g):
        pass

    def set_ppm(self, p):
        pass

    def set_agc(self, on):
        pass

    def set_rate(self, r):
        pass

    def flush(self, seconds):
        pass

    def alive(self):
        return self._f is not None and not self.ended

    def close(self):
        f, self._f = self._f, None
        if f is not None:
            try:
                f.close()
            except Exception:
                pass


# --------------------------------------------------------------------------- demo synth

DEMO_SIGNALS = [
    # (MHz, mode, label, keyed duty) — audible tones so every demod mode can be heard in demo
    (118.700, "AM", "Tower (demo)", 0.5), (119.100, "AM", "Approach (demo)", 0.35),
    (121.500, "AM", "Guard (demo)", 0.15), (127.850, "AM", "ATIS (demo)", 1.0),
    (146.520, "NFM", "2m simplex (demo)", 0.4), (162.550, "NFM", "NOAA WX1 (demo)", 1.0),
    (462.5625, "NFM", "FRS 1 (demo)", 0.3), (97.300, "WFM", "FM broadcast (demo)", 1.0),
    (50.125, "USB", "6m SSB (demo)", 0.5), (50.090, "CW", "6m CW beacon (demo)", 1.0),
    (156.800, "NFM", "Marine 16 (demo)", 0.25),
]


class SynthSource:
    """DEMO ONLY. Synthesised IQ around the tuned centre: the DEMO_SIGNALS that fall inside the
    band, keyed on and off, plus receiver noise. Real time paced."""
    kind = "demo"

    def __init__(self, freq_hz, rate=2048000, realtime=True, seed=1):
        self.centre_hz = int(freq_hz)
        self.rate = int(rate)
        self.realtime = realtime
        self._n = 0
        self._rng = np.random.default_rng(seed)
        self._t_next = None
        self.gain_db = None

    def open(self):
        return self

    def set_freq(self, hz):
        self.centre_hz = int(hz)

    def set_rate(self, r):
        self.rate = int(r)

    def set_gain(self, g):
        self.gain_db = g

    def set_ppm(self, p):
        pass

    def set_agc(self, on):
        pass

    def flush(self, seconds):
        pass

    def alive(self):
        return True

    def _keyed(self, i, duty, t):
        if duty >= 1.0:
            return True
        period = 6.0 + 2.0 * i
        return ((t + 1.7 * i) % period) < duty * period

    def read(self, seconds):
        n = max(1, int(seconds * self.rate))
        t = (self._n + np.arange(n)) / self.rate
        t0 = self._n / self.rate
        self._n += n
        x = (self._rng.standard_normal(n) + 1j * self._rng.standard_normal(n)) * 0.006
        half = self.rate * 0.45
        for i, (mhz, mode, _lb, duty) in enumerate(DEMO_SIGNALS):
            off = mhz * 1e6 - self.centre_hz
            if abs(off) > half or not self._keyed(i, duty, t0):
                continue
            tone = 400.0 + 150.0 * (i % 5)
            if mode == "AM":
                s = (1 + 0.6 * np.sin(2 * np.pi * tone * t)) * np.exp(2j * np.pi * off * t)
            elif mode == "NFM":
                s = np.exp(1j * (2 * np.pi * off * t + (2500 / tone) * np.sin(2 * np.pi * tone * t)))
            elif mode == "WFM":
                s = np.exp(1j * (2 * np.pi * off * t + (50000 / tone) * np.sin(2 * np.pi * tone * t)))
            elif mode == "USB":
                s = np.exp(2j * np.pi * (off + tone) * t)
            else:
                s = np.exp(2j * np.pi * off * t)
            x = x + 0.12 * s
        iq = x.astype(np.complex64)
        if self.realtime:
            now = time.monotonic()
            if self._t_next is None or self._t_next < now - 1.0:
                self._t_next = now
            self._t_next += n / self.rate
            wait = self._t_next - time.monotonic()
            if wait > 0:
                time.sleep(min(wait, 1.0))
        return dsp.iq_to_cu8(iq), iq

    def close(self):
        pass


# --------------------------------------------------------------------------- recording

def _stamp():
    return time.strftime("%Y%m%d-%H%M%SZ", time.gmtime())


def _disk_ok(path):
    try:
        st = os.statvfs(os.path.dirname(path) or ".")
        return st.f_bavail * st.f_frsize >= MIN_FREE_BYTES
    except OSError:
        return True


class IqRecorder:
    """Baseband recording: raw uint8 I/Q exactly as received, plus a .json sidecar with the
    centre frequency and rate, so FileSource (or rtl tools) can play it back."""

    def __init__(self, centre_hz, rate, directory=None):
        d = directory or rec_dir()
        os.makedirs(d, exist_ok=True)
        base = os.path.join(d, "iq_%s_%dHz_%dsps" % (_stamp(), int(centre_hz), int(rate)))
        self.path = base + ".cu8"
        with open(base + ".json", "w") as f:
            json.dump({"centre_hz": int(centre_hz), "rate": int(rate), "format": "cu8",
                       "started_utc": _stamp()}, f)
        self._f = open(self.path, "wb")
        self.bytes = 0
        self.stopped_reason = None

    def write(self, raw):
        if self._f is None or not raw:
            return
        if self.bytes % (64 << 20) < len(raw) and not _disk_ok(self.path):
            self.stopped_reason = "disk nearly full"
            self.close()
            return
        self._f.write(raw)
        self.bytes += len(raw)

    def seconds(self, rate):
        return self.bytes / 2.0 / rate

    def close(self):
        f, self._f = self._f, None
        if f is not None:
            f.close()


class AudioRecorder:
    """Demodulated audio to a mono 16-bit WAV."""

    def __init__(self, freq_hz, mode, rate, directory=None):
        d = directory or rec_dir()
        os.makedirs(d, exist_ok=True)
        self.path = os.path.join(d, "audio_%s_%dHz_%s.wav" % (_stamp(), int(freq_hz), mode))
        self._w = wave.open(self.path, "wb")
        self._w.setnchannels(1)
        self._w.setsampwidth(2)
        self._w.setframerate(int(rate))
        self.rate = int(rate)
        self.frames = 0
        self.stopped_reason = None

    def write(self, pcm):
        if self._w is None or pcm is None or len(pcm) == 0:
            return
        if self.frames % (self.rate * 60) < len(pcm) and not _disk_ok(self.path):
            self.stopped_reason = "disk nearly full"
            self.close()
            return
        self._w.writeframes(np.asarray(pcm, dtype="<i2").tobytes())
        self.frames += len(pcm)

    def close(self):
        w, self._w = self._w, None
        if w is not None:
            w.close()


# --------------------------------------------------------------------------- audio out

def audio_sink_argv(rate):
    if shutil.which("pacat"):
        return ["pacat", "--raw", "--format=s16le", "--rate=%d" % int(rate), "--channels=1",
                "--stream-name=PALISADE", "--latency-msec=120"]
    if shutil.which("aplay"):
        return ["aplay", "-q", "-r", str(int(rate)), "-f", "S16_LE", "-t", "raw", "-c", "1"]
    return None


class AudioOut:
    """int16 mono PCM to the sound card through pacat/aplay. write() never blocks: a bounded
    queue feeds a writer thread, and blocks are dropped (counted) if the sink falls behind.
    `argv_fn`/`popen` are injectable; under tests nothing is spawned."""

    def __init__(self, rate, argv_fn=audio_sink_argv, popen=subprocess.Popen, enabled=True):
        self.rate = int(rate)
        self.dropped = 0
        self.error = None
        self._q = queue.Queue(maxsize=16)
        self._p = None
        argv = argv_fn(self.rate) if enabled else None
        if argv:
            try:
                self._p = popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as e:
                self.error = "audio sink failed: %s" % e
        else:
            self.error = "no audio sink (pacat/aplay)" if enabled else None
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    @property
    def available(self):
        return self._p is not None

    def write(self, pcm):
        if self._p is None or pcm is None or len(pcm) == 0:
            return
        try:
            self._q.put_nowait(np.asarray(pcm, dtype="<i2").tobytes())
        except queue.Full:
            self.dropped += 1

    def _run(self):
        while True:
            b = self._q.get()
            if b is None:
                return
            p = self._p
            if p is None:
                continue
            try:
                p.stdin.write(b)
                p.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                self.error = "audio sink closed"
                self._p = None

    def close(self):
        try:
            self._q.put_nowait(None)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            self._q.put_nowait(None)
        p, self._p = self._p, None
        if p is not None:
            try:
                p.stdin.close()
            except Exception:
                pass
            try:
                os.killpg(p.pid, 15)
            except Exception:
                pass
            try:
                p.wait(timeout=1.0)
            except Exception:
                try:
                    os.killpg(p.pid, 9)
                    p.wait(timeout=1.0)
                except Exception:
                    pass


def fmt_freq(hz):
    """121.500 000 MHz style readout (SDR++ digit grouping)."""
    mhz = int(hz) // 1_000_000
    rest = int(hz) % 1_000_000
    return "%d.%03d %03d" % (mhz, rest // 1000, rest % 1000)


def parse_freq(text, unit_mhz=True):
    """Typed frequency -> Hz. '121.5' (MHz), '121.5M', '7030k', '446000000', '144.39 MHz'.
    ValueError on anything outside 24-1766 MHz or unparseable."""
    t = str(text).strip().lower().replace(" ", "").replace(",", "")
    if not t:
        raise ValueError("empty frequency")
    mult = None
    for suf, m in (("mhz", 1e6), ("khz", 1e3), ("ghz", 1e9), ("hz", 1.0), ("m", 1e6),
                   ("k", 1e3), ("g", 1e9)):
        if t.endswith(suf):
            t, mult = t[:-len(suf)], m
            break
    v = float(t)
    if not math.isfinite(v):
        raise ValueError("not a frequency")
    if mult is None:
        mult = 1e6 if (unit_mhz and v < 1e5) else 1.0
    hz = int(round(v * mult))
    if not 24_000_000 <= hz <= 1_766_000_000:
        raise ValueError("%.4f MHz is outside the RTL-SDR range (24-1766 MHz)" % (hz / 1e6))
    return hz
