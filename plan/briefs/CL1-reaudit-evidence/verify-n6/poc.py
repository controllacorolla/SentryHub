import sys
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
from palisade_qt.kit.audio import AudioSink
from palisade_qt.kit.topbar import TopBar
app = QtWidgets.QApplication([])
calls=[]
# A: wpctl present, every call rc=1
def run_fail(argv, timeout=2.0):
    calls.append(argv); return 1, ""
s = AudioSink(which=lambda b: "/usr/bin/"+b if b=="wpctl" else None, run=run_fail)
print("A sink.available", s.available, "get", s.get())
tb = TopBar(audio=s)
print("A UI vol", tb.volume.value(), "mute", tb.mute.isChecked(), "enabled", tb.volume.isEnabled(), tb.mute.isEnabled(), "tip", tb.volume.toolTip())
tb.volume.setValue(30); tb._apply_volume()
print("A after slide UI", tb.volume.value(), "set_volume rc ok?", s.set_volume(30), "calls", calls[-1])
# A2: all three present, wpctl fails, pactl would work -> no fallback
def run_w(argv, timeout=2.0):
    if argv[0]=="wpctl": return 1,""
    if argv[:2]==["pactl","get-sink-volume"]: return 0,"Volume: front-left: 55705 / 85% / -4.2 dB"
    if argv[:2]==["pactl","get-sink-mute"]: return 0,"Mute: no"
    return 0,""
s2 = AudioSink(which=lambda b: "/usr/bin/"+b, run=run_w)
print("A2 backend", s2.backend, "get", s2.get())
# D parse cases
def mk(backend, outs):
    def run(argv, timeout=2.0):
        for k,v in outs.items():
            if k in " ".join(argv): return 0, v
        return 0, ""
    return AudioSink(which=lambda b: b==backend, run=run)
print("D wpctl garbage", mk("wpctl", {"get-volume":"garbage"}).get())
print("D wpctl empty", mk("wpctl", {"get-volume":""}).get())
print("D pactl localized", mk("pactl", {"get-sink-volume":"Lautstärke: 85%", "get-sink-mute":"Stumm: ja"}).get())
print("D amixer no switch", mk("amixer", {"sget":"  Mono: Playback 79 [79%]"}).get())
s5 = mk("wpctl", {"get-volume":"Volume: 1.50"})
print("D wpctl 1.50", s5.get()); tb5 = TopBar(audio=s5); print("   UI", tb5.volume.value())
s6 = mk("wpctl", {"get-volume":"garbage"}); tb6=TopBar(audio=s6); print("garbage UI", tb6.volume.value(), tb6.mute.isChecked(), tb6.volume.isEnabled())
