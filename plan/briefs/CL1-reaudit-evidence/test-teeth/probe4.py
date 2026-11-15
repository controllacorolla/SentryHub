"""Audio: what does the strip show when the mixer exists but rejects / cannot be read?"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = "/Users/daltonhayes/SentryHub/.claude/worktrees/wf_aa62e8f8-bfc-8"
sys.path.insert(0, ROOT)
from PySide6 import QtWidgets, QtTest
app = QtWidgets.QApplication([])
from palisade_qt.kit import TopBar
from palisade_qt.kit.audio import AudioSink
calls = []
def run_fail(argv, timeout=2.0):
    calls.append(list(argv)); return 1, ""          # e.g. no PulseAudio server / no default sink
sink = AudioSink(which=lambda n: "/usr/bin/pactl" if n == "pactl" else None, run=run_fail)
tb = TopBar(audio=sink)
print("available:", sink.available, "get():", sink.get())
print("slider enabled:", tb.volume.isEnabled(), "value:", tb.volume.value(), "tooltip:", tb.volume.toolTip())
tb.volume.setValue(75); tb._apply_volume()
print("set_volume(75) returned:", sink.set_volume(75), "| slider now:", tb.volume.value(), "enabled:", tb.volume.isEnabled(), "tooltip:", tb.volume.toolTip())
tb.mute.setChecked(True)
print("set_mute(True) returned:", sink.set_mute(True), "| MUTE button checked:", tb.mute.isChecked(), "text:", tb.mute.text())
# real signal path: does moving the slider reach the mixer without calling the slot by hand?
calls.clear()
ok = AudioSink(which=lambda n: "/usr/bin/pactl" if n == "pactl" else None, run=lambda argv, timeout=2.0: (calls.append(list(argv)) or (0, "50%")))
tb2 = TopBar(audio=ok)
calls.clear()
tb2.volume.setValue(33)
QtTest.QTest.qWait(300)
print("signal path calls after setValue(33)+300ms:", calls)
