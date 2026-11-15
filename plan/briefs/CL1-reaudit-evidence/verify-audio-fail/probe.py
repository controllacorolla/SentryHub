import sys
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt.kit.topbar import TopBar
from palisade_qt.kit.audio import AudioSink
calls=[]
def run(argv, timeout=2.0):
    calls.append(argv); return (1, "")
s = AudioSink(which=lambda n: "/usr/bin/pactl" if n=="pactl" else None, run=run)
print("available", s.available, "get", s.get())
tb = TopBar(audio=s)
print("slider enabled", tb.volume.isEnabled(), tb.volume.value(), tb.volume.toolTip())
tb.volume.setValue(75); tb._apply_volume()
print("set_volume ret", s.set_volume(75), "slider", tb.volume.value(), tb.volume.isEnabled())
tb.mute.setChecked(True)
print("mute checked", tb.mute.isChecked(), tb.mute.text(), "enabled", tb.mute.isEnabled(), "tip", tb.mute.toolTip())
tb.toggle_mute(); tb.toggle_mute()
print("after hotkey toggle x2 checked", tb.mute.isChecked())
print(calls)
