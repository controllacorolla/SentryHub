import sys, time, threading
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication([])
from palisade_qt.kit.topbar import TopBar
from palisade_qt.kit import audio
from palisade_qt.kit.audio import AudioSink

class Sink:
    """fake real sink: 85%, unmuted"""
    def __init__(s, present=("wpctl","pactl","amixer"), fail=(), garbage=False, delay=0):
        s.vol, s.muted, s.calls, s.present, s.fail, s.garbage, s.delay = 85, False, [], present, fail, garbage, delay
        s.threads=set()
    def which(s, n): return "/usr/bin/"+n if n in s.present else None
    def run(s, argv, timeout=2.0):
        s.calls.append(list(argv)); s.threads.add(threading.current_thread().name)
        if s.delay: time.sleep(s.delay)
        if argv[0] in s.fail: return 1, ""
        if s.garbage: return 0, "???"
        if argv[0]=="pactl":
            if argv[1]=="get-sink-volume": return 0, "Volume: front-left: 1 / %d%% / x"%s.vol
            if argv[1]=="get-sink-mute": return 0, "Mute: %s"%("yes" if s.muted else "no")
            if argv[1]=="set-sink-volume": s.vol=int(argv[3][:-1]); return 0,""
            if argv[1]=="set-sink-mute": s.muted=argv[3]=="1"; return 0,""
        if argv[0]=="amixer":
            if "sget" in argv: return 0,"Front Left: Playback 1 [%d%%] [%s]"%(s.vol,"off" if s.muted else "on")
            if argv[-1] in("mute","unmute"): s.muted=argv[-1]=="mute"; return 0,""
            s.vol=int(argv[-1][:-1]); return 0,""
        return 1,""
def show(tag, tb, s):
    print("%-34s backend=%s UI vol=%d mute_checked=%s enabled=%s/%s | SINK vol=%d muted=%s"%(tag, tb.audio.backend, tb.volume.value(), tb.mute.isChecked(), tb.volume.isEnabled(), tb.mute.isEnabled(), s.vol, s.muted))

# control: working pactl
s=Sink(present=("pactl",)); tb=TopBar(audio=AudioSink(which=s.which, run=s.run)); show("ctl init",tb,s)
tb.volume.setValue(30); tb._apply_volume(); tb.mute.setChecked(True); show("ctl after",tb,s)
# A: wpctl binary present but failing (e.g. no PipeWire session), amixer would work
s=Sink(present=("wpctl","amixer"), fail=("wpctl",)); tb=TopBar(audio=AudioSink(which=s.which, run=s.run)); show("A init (wpctl fails, amixer ok)",tb,s)
tb.volume.setValue(30); tb._apply_volume(); tb.mute.setChecked(True); show("A after slide30+mute",tb,s)
print("   calls:", s.calls, "set_volume ret:", tb.audio.set_volume(30), "set_mute ret:", tb.audio.set_mute(True))
# B: external change never resynced
s=Sink(present=("pactl",)); tb=TopBar(audio=AudioSink(which=s.which, run=s.run)); s.muted=True; s.vol=10
ncalls=len(s.calls); 
t0=time.time()
while time.time()-t0<3: app.processEvents(); time.sleep(0.05)
show("B external mute, 3s of event loop",tb,s); print("   mixer polls during 3 s:", len(s.calls)-ncalls)
# B2: sink muted externally, UI unchecked -> user presses mute => checked, set-mute 1; fine. Sink UNmuted externally while UI checked:
s=Sink(present=("pactl",)); s.muted=True; tb=TopBar(audio=AudioSink(which=s.which, run=s.run)); s.muted=False
show("B2 UI says MUTE, sink unmuted ext",tb,s)
# C: garbage parse
s=Sink(present=("pactl",), garbage=True); tb=TopBar(audio=AudioSink(which=s.which, run=s.run)); show("C unparseable get",tb,s)
# D: thread + blocking, real _run with a hanging child
def hang(argv, timeout=2.0):
    return audio._run(["sleep","10"])
s=Sink(present=("pactl",))
t0=time.time(); tb=TopBar(audio=AudioSink(which=s.which, run=hang)); t1=time.time()
print("D construct w/ hung pactl: %.2fs"%(t1-t0))
t0=time.time(); tb._apply_volume(); print("D _apply_volume hung: %.2fs (thread=%s)"%(time.time()-t0, threading.current_thread().name))
t0=time.time(); tb.mute.setChecked(True); print("D mute toggle hung: %.2fs; mute_checked=%s"%(time.time()-t0, tb.mute.isChecked()))
t0=time.time(); print("real _run sleep10 timeout=.5 ->", audio._run(["sleep","10"],timeout=0.5), "%.2fs"%(time.time()-t0))
