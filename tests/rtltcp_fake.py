"""A protocol-faithful stand-in for rtl_tcp, for tests (and the backcheck run).

Listens on 127.0.0.1, sends the 12-byte RTL0 header, parses the 5-byte control commands the way
rtl_tcp does (and records them), and streams uint8 I/Q synthesised for the CURRENTLY tuned
frequency — so a retune over the socket really changes what the client receives. Signals are
(MHz, mode, keyed) like iqsource.SynthSource; `signals` can be swapped while it runs.
"""
import socket
import struct
import threading
import time

import numpy as np

import dsp


class FakeRtlTcp:
    def __init__(self, signals=(), rate=2048000, freq_hz=100_000_000, realtime=True, seed=3):
        self.signals = list(signals)            # [(MHz, mode, on_fn(t) -> bool)]
        self.rate = rate
        self.freq_hz = freq_hz
        self.realtime = realtime
        self.cmds = []                          # [(code, value)]
        self.gain_mode = None
        self.gain = None
        self.agc = None
        self.ppm = None
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self._stop = False
        self._n = 0
        self._rng = np.random.default_rng(seed)
        self.connections = 0
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    # -- what a client sees
    def _block(self, n):
        t = (self._n + np.arange(n)) / self.rate
        t0 = self._n / self.rate
        self._n += n
        x = (self._rng.standard_normal(n) + 1j * self._rng.standard_normal(n)) * 0.006
        for mhz, mode, on in list(self.signals):
            off = mhz * 1e6 - self.freq_hz
            if abs(off) > 0.45 * self.rate or not on(t0):
                continue
            if mode == "AM":
                s = (1 + 0.6 * np.sin(2 * np.pi * 1000 * t)) * np.exp(2j * np.pi * off * t)
            elif mode == "NFM":
                s = np.exp(1j * (2 * np.pi * off * t + 2.5 * np.sin(2 * np.pi * 1000 * t)))
            else:
                s = np.exp(2j * np.pi * off * t)
            x = x + 0.12 * s
        return dsp.iq_to_cu8(x)

    def _serve(self):
        while not self._stop:
            try:
                self._srv.settimeout(0.2)
                c, _ = self._srv.accept()
            except (socket.timeout, OSError):
                continue
            self.connections += 1
            c.sendall(b"RTL0" + struct.pack(">II", 5, 29))
            c.setblocking(False)
            buf = b""
            t_next = time.monotonic()
            try:
                while not self._stop:
                    try:
                        d = c.recv(4096)
                        if d == b"":
                            break
                        buf += d
                    except BlockingIOError:
                        pass
                    except OSError:
                        break
                    while len(buf) >= 5:
                        code, val = struct.unpack(">BI", buf[:5])
                        buf = buf[5:]
                        self.cmds.append((code, val))
                        if code == 0x01:
                            self.freq_hz = val
                        elif code == 0x02:
                            self.rate = val
                        elif code == 0x03:
                            self.gain_mode = val
                        elif code == 0x04:
                            self.gain = val
                        elif code == 0x05:
                            self.ppm = struct.unpack(">i", struct.pack(">I", val))[0]
                        elif code == 0x08:
                            self.agc = val
                    n = int(self.rate * 0.01)
                    try:
                        c.sendall(self._block(n))
                    except (BlockingIOError, BrokenPipeError, ConnectionResetError, OSError):
                        if self._stop:
                            break
                        time.sleep(0.002)
                        continue
                    if self.realtime:
                        t_next += 0.01
                        w = t_next - time.monotonic()
                        if w > 0:
                            time.sleep(w)
            finally:
                try:
                    c.close()
                except OSError:
                    pass

    def close(self):
        self._stop = True
        try:
            self._srv.close()
        except OSError:
            pass


class FakeProc:
    """Stands in for the rtl_tcp process (Pipeline): records argv, terminate() kills it."""

    def __init__(self, argv):
        self.argv = argv
        self.rc = None
        self.terminated = 0
        self.stderr = None

    def poll(self):
        return self.rc

    def terminate(self):
        self.terminated += 1
        self.rc = -15
