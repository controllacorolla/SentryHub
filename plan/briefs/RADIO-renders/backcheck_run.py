"""RADIO backcheck: run the REAL live path (not demo) end to end, headless, and screenshot it.

rtl_tcp is replaced by tests/rtltcp_fake.py — a TCP server that speaks the rtl_tcp protocol and
whose IQ follows the tuned frequency — because the container has no dongle. Everything above the
socket is the shipping code: RtlTcpSource, the arbiter, TunerWorker / FastScanWorker, dsp, the
PRISM / PROWL pages. Steps: PRISM live on airband (typed freq, AM audio level, gain over the
socket), REC IQ 2 s, play that recording back as an IQ file, PROWL FAST scan of the full airband
with a keyed tower + a priority channel. Prints PASS/FAIL per step; writes PNGs next to itself.
Usage: QT_QPA_PLATFORM=offscreen python3 plan/briefs/RADIO-renders/backcheck_run.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path[:0] = [REPO, os.path.join(REPO, "tests")]
os.environ["HOME"] = tempfile.mkdtemp()
os.chdir(REPO)

from PySide6 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication([])

import iqsource  # noqa: E402
from rtltcp_fake import FakeRtlTcp, FakeProc  # noqa: E402
from palisade_qt import theme, iqworker, radio_arbiter as ra  # noqa: E402

keyed = {"tower": True, "guard": False}
srv = FakeRtlTcp(signals=[(118.7, "AM", lambda t: keyed["tower"]),
                          (121.5, "AM", lambda t: keyed["guard"]),
                          (127.85, "AM", lambda t: True)])
_orig = iqsource.RtlTcpSource.__init__


def _patched(self, *a, **k):
    k["spawn"], k["port"] = FakeProc, srv.port
    _orig(self, *a, **k)


iqsource.RtlTcpSource.__init__ = _patched          # rtl_tcp process -> the fake server
iqworker._offscreen = lambda: False                 # let the worker open a "real" source
ra._make_lease = lambda n: None                     # no readsb to pause in the container
audio_peaks = []


class _Audio:
    def __init__(self, rate):
        self.rate, self.error = rate, None

    def write(self, pcm):
        audio_peaks.append(int(abs(pcm).max()) if len(pcm) else 0)

    def close(self):
        pass


iqsource.AudioOut = _Audio


def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents()
        time.sleep(0.01)


results = []


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %s  %s" % ("PASS" if ok else "FAIL", name, detail))


theme.load_fonts()
theme.set_app_font(app)
theme.set_palette(app, "dark")
app.setStyleSheet(theme.qss("dark"))
from palisade_qt.shell import PalisadeHub  # noqa: E402
hub = PalisadeHub(demo=False, mode="dark")
hub.resize(1280, 720)
hub.show()
pump(1500)

# ---- PRISM live
hub.open_callsign("PRISM")
pump(800)
p = hub.page_app("PRISM")
p.freq_edit.setText("118.7")
p.freq_edit.returnPressed.emit()
pump(2500)
check("PRISM holds the radio via the arbiter", ra.arbiter.held_by("PRISM"), ra.arbiter.state())
check("typed 118.7 retuned rtl_tcp over the socket", srv.freq_hz == 118_700_000, srv.freq_hz)
check("AM tower is demodulated to audio", max(audio_peaks[-10:] or [0]) > 3000,
      max(audio_peaks[-10:] or [0]))
p.auto_gain.setChecked(True)
p.gain_slider.setValue(10)
p.auto_gain.setChecked(False)
pump(400)
check("manual gain reached the tuner", srv.gain_mode == 1 and srv.gain is not None, srv.gain)
p.scope.set_zoom(4)
p._sync_zoom()
pump(1500)
hub.grab().save(os.path.join(HERE, "after_prism_live.png"))
rec_dir = tempfile.mkdtemp()
p._queue(rec_iq=True, rec_audio=True, rec_dir=rec_dir)
pump(2200)
p.rec_iq_btn.setChecked(False)
p.rec_audio_btn.setChecked(False)
pump(800)
files = sorted(os.listdir(rec_dir))
check("REC IQ + REC AUDIO wrote files", any(f.endswith(".cu8") for f in files)
      and any(f.endswith(".wav") for f in files), files)

# ---- IQ file playback of that recording
cu8 = os.path.join(rec_dir, next(f for f in files if f.endswith(".cu8")))
p.file_edit.setText(cu8)
p.source_combo.setCurrentIndex(1)
pump(3000)
check("playback releases the radio", ra.arbiter.owner() is None, ra.arbiter.state())
check("playback centre comes from the recording", p._centre_hz == 118_700_000, p._centre_hz)
n = len(audio_peaks)
pump(1000)
check("playback is demodulated", max(audio_peaks[n:] or [0]) > 3000)
hub.grab().save(os.path.join(HERE, "after_prism_file.png"))
p.source_combo.setCurrentIndex(0)
pump(500)

# ---- PROWL FAST scan
hub.open_callsign("PROWL", "SCAN")
pump(600)
w = hub.page_app("PROWL")
w.engine_combo.setCurrentIndex(0)
w.bank_combo.setCurrentText("Airband (full)")
w.pri_freq.setValue(121.5)
w.pri_mode.setCurrentText("AM")
w.pri_on.setChecked(True)
w.max_hold.setValue(6.0)
pump(1500)
check("PROWL FAST holds the radio", ra.arbiter.held_by("PROWL-SCAN"), ra.arbiter.state())
t0 = time.time()
while time.time() - t0 < 12 and "118.7000" not in w.active.text():
    pump(200)
check("scanner stopped on the keyed tower 118.700", "118.7000" in w.active.text(),
      w.active.text())
hub.grab().save(os.path.join(HERE, "after_prowl_fast_listen.png"))
keyed["guard"] = True
t0 = time.time()
while time.time() - t0 < 10 and "121.5000" not in w.active.text():
    pump(200)
check("priority 121.5 pre-empted the tower", "121.5000" in w.active.text(), w.active.text())
keyed["guard"] = keyed["tower"] = False
w._toggle_hold()
check("HOLD turns the SCAN button red", w.hold_btn.property("run") == "off")
w._toggle_hold()
check("resume turns it green", w.hold_btn.property("run") == "on")
t0 = time.time()
while time.time() - t0 < 20 and "full pass" not in w.scan_info.text():
    pump(250)
check("full-pass time shown", "full pass" in w.scan_info.text(), w.scan_info.text())
hub.grab().save(os.path.join(HERE, "after_prowl_fast_scan.png"))
hub.open_callsign("OPS")
pump(1500)
check("leaving the page gives the radio back", ra.arbiter.owner() is None, ra.arbiter.state())
hub.close()
pump(500)
srv.close()
print("BACKCHECK RADIO: %s (%d/%d)" % ("PASS" if all(results) else "FAIL", sum(results),
                                        len(results)))
os._exit(0 if all(results) else 1)
