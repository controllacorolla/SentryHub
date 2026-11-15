import sys, time, threading
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication([])
from palisade_qt.kit.audio import AudioSink
from palisade_qt.kit.topbar import TopBar
main = threading.get_ident()
calls = []
def slow(argv, timeout=2.0):
    calls.append((argv, threading.get_ident() == main)); time.sleep(2.0); return 1, ""
sink = AudioSink(which=lambda b: "/usr/bin/pactl" if b == "pactl" else None, run=slow)
t = time.time(); tb = TopBar(audio=sink); print("ctor %.2fs calls=%d" % (time.time()-t, len(calls)), calls)
# event loop stall
gaps = []; last = [time.time()]
tick = QtCore.QTimer(); tick.setInterval(10)
def on():
    n = time.time(); gaps.append(n-last[0]); last[0] = n
tick.timeout.connect(on); tick.start()
n0 = len(calls)
tb.volume.setValue((tb.volume.value()+7) % 100)
end = time.time()+3.5
while time.time() < end: app.processEvents(); time.sleep(0.002)
print("slider: max loop gap %.2fs, calls=%d on_main=%s" % (max(gaps), len(calls)-n0, [c[1] for c in calls[n0:]]))
t = time.time(); tb.toggle_mute(); print("toggle_mute %.2fs" % (time.time()-t), calls[-1])
# real _run with a hung binary: does timeout=2 apply?
from palisade_qt.kit import audio
t = time.time(); print(audio._run(["sleep", "10"]), "real _run on hung proc %.2fs" % (time.time()-t))
