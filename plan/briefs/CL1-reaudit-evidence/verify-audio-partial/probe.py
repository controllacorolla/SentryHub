import sys; sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets, QtCore, QtTest
app=QtWidgets.QApplication([])
from palisade_qt.kit import TopBar
from palisade_qt.kit.audio import AudioSink
calls=[]
def ok(argv,timeout=2.0):
    calls.append(list(argv))
    if argv[1]=="get-sink-volume": return 0,"Volume: front-left: 1 / 40% / x"
    if argv[1]=="get-sink-mute": return 0,"Mute: no"
    return 0,""
tb=TopBar(audio=AudioSink(which=lambda n:"/x" if n=="pactl" else None, run=ok))
tb.volume.setValue(33); QtTest.QTest.qWait(300)
print("A working path:", calls[-1])
calls.clear()
def bad(argv,timeout=2.0):
    calls.append(list(argv)); return 1,""
s=AudioSink(which=lambda n:"/x" if n=="pactl" else None, run=bad)
tb=TopBar(audio=s)
print("B failing mixer: enabled",tb.volume.isEnabled(),tb.mute.isEnabled(),"value",tb.volume.value(),"tip",tb.volume.toolTip())
tb.volume.setValue(75); QtTest.QTest.qWait(300)
print("  after setValue(75): set_volume ->",s.set_volume(75),"slider",tb.volume.value(),"enabled",tb.volume.isEnabled())
tb.mute.setChecked(True)
print("  mute: set_mute ->",s.set_mute(True),"checked",tb.mute.isChecked(), "calls",calls)
