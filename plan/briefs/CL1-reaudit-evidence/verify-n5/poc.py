import sys, time
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore
from palisade_qt.kit.audio import AudioSink
from palisade_qt.kit.topbar import TopBar
app = QtWidgets.QApplication([])
class Mixer:
    def __init__(s, vol, muted, fail=False): s.vol, s.muted, s.fail, s.calls = vol, muted, fail, []
    def which(s, n): return "/usr/bin/pactl" if n == "pactl" else None
    def run(s, argv, timeout=2.0):
        s.calls.append(argv)
        if argv[1] == "get-sink-volume": return 0, "Volume: front-left: 1 / %d%% / 0 dB" % s.vol
        if argv[1] == "get-sink-mute": return 0, "Mute: %s" % ("yes" if s.muted else "no")
        if s.fail: return 1, ""
        if argv[1] == "set-sink-volume": s.vol = int(argv[3].rstrip("%"))
        if argv[1] == "set-sink-mute": s.muted = argv[3] == "1"
        return 0, ""
def pump(sec):
    t = time.time() + sec
    while time.time() < t: app.processEvents(); time.sleep(0.01)
def show(tag, tb, m): print(tag, "UI: vol=%d muteChecked=%s | SINK: vol=%d muted=%s" % (tb.volume.value(), tb.mute.isChecked(), m.vol, m.muted))
m = Mixer(85, False, fail=True); tb = TopBar(audio=AudioSink(which=m.which, run=m.run))
tb.toggle_mute(); show("B1", tb, m)
tb.volume.setValue(0); pump(0.4); show("B2", tb, m); print("  set calls:", [c for c in m.calls if c[1].startswith("set")])
m = Mixer(40, True); tb = TopBar(audio=AudioSink(which=m.which, run=m.run))
n = len(m.calls); m.muted = False; m.vol = 100; pump(3.0); show("C ", tb, m); print("  mixer calls during 3s:", m.calls[n:])
print("timers:", [(t.interval(), t.isSingleShot()) for t in tb.findChildren(QtCore.QTimer)])
m = Mixer(40, False); tb = TopBar(audio=AudioSink(which=m.which, run=m.run))
m.muted = True; pump(1.5); show("C'", tb, m)
