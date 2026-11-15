import sys, time
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from palisade_qt.kit import TopBar
from palisade_qt.kit.audio import AudioSink
from palisade_qt import theme
def pump(ms=50):
    t = time.time() + ms/1000
    while time.time() < t: app.processEvents()
class Mixer:
    """fake mixer: real state + scriptable failure"""
    def __init__(s, backend, vol=40, muted=False, fail_set=False, fail_get=False, delay=0.0, get_out=None, mute_out=None):
        s.__dict__.update(locals()); s.calls = []
    def which(s, n): return "/usr/bin/" + n if n == s.backend else None
    def run(s, argv, timeout=2.0):
        s.calls.append(list(argv)); time.sleep(s.delay)
        verb = argv[1] if argv[0] != "amixer" else ("sget" if "sget" in argv else "sset")
        is_get = verb.startswith("get") or verb == "sget"
        if is_get:
            if s.fail_get: return 1, ""
            if "mute" in verb: return 0, (s.mute_out if s.mute_out is not None else "Mute: %s\n" % ("yes" if s.muted else "no"))
            if s.get_out is not None: return 0, s.get_out
            if s.backend == "wpctl": return 0, "Volume: %.2f%s\n" % (s.vol/100, " [MUTED]" if s.muted else "")
            if s.backend == "pactl": return 0, "Volume: front-left: 1 / %d%% / -1 dB\n" % s.vol
            return 0, "  Front Left: Playback 1 [%d%%] [-1dB] [%s]\n" % (s.vol, "off" if s.muted else "on")
        if s.fail_set: return 1, ""
        if "mute" in verb or argv[-1] in ("mute", "unmute"): s.muted = argv[-1] in ("1", "mute")
        else: s.vol = int(round(float(argv[-1].rstrip("%")) * (100 if s.backend == "wpctl" else 1)))
        return 0, ""
def tb_for(m):
    t0 = time.time(); tb = TopBar(audio=AudioSink(which=m.which, run=m.run)); return tb, time.time() - t0
def state(tb, m, tag):
    print("  %-58s UI: vol=%3d muteChecked=%-5s enabled=%s/%s | SINK: vol=%s muted=%s" % (tag, tb.volume.value(), tb.mute.isChecked(), tb.volume.isEnabled(), tb.mute.isEnabled(), m.vol, m.muted))

print("A. backend binary present but every call fails (e.g. wpctl with no PipeWire session)")
m = Mixer("wpctl", vol=85, muted=False, fail_get=True, fail_set=True); tb, dt = tb_for(m)
state(tb, m, "after init"); print("   tooltip:", repr(tb.volume.toolTip()))
tb.volume.setValue(30); tb._apply_volume(); state(tb, m, "after slider->30")
tb.toggle_mute(); state(tb, m, "after toggle_mute (set-mute rc=1)")

print("B. get works, set fails (sink went away after start)")
m = Mixer("pactl", vol=85); tb, dt = tb_for(m); m.fail_set = True
tb.toggle_mute(); state(tb, m, "toggle_mute, set rc=1  -> UI MUTED, sink LIVE")
tb.volume.setValue(0); tb._apply_volume(); state(tb, m, "slider->0, set rc=1")

print("C. external change after start (hardware vol keys / another app)")
m = Mixer("wpctl", vol=40, muted=True); tb, dt = tb_for(m); state(tb, m, "init (sink muted)")
m.muted = False; m.vol = 100; pump(3000); state(tb, m, "3 s after external unmute + 100%")
print("   timers on topbar:", [(t.interval(), t.isSingleShot()) for t in tb.findChildren(QtCore.QTimer)])
m = Mixer("wpctl", vol=40, muted=False); tb, dt = tb_for(m)
m.muted = True; pump(200); tb.toggle_mute(); state(tb, m, "sink externally muted; operator presses M to 'unmute'?")

print("D. parse failures")
for backend, get_out, mute_out in [("wpctl", "garbage\n", None), ("wpctl", "Volume: 1.50\n", None), ("wpctl", "", None),
                                   ("pactl", "Lautstärke: vorne-links: 1 / 85% / 0 dB\n", "Stumm: ja\n"), ("pactl", "no percent here", "Mute: yes"),
                                   ("amixer", "Simple mixer control 'Master',0\n  Mono: Playback 50 [79%] [-10dB]\n", None),
                                   ("amixer", "  Front Left: Playback 1 [50%] [on]\n  Front Right: Playback 1 [50%] [off]\n", None)]:
    m = Mixer(backend, vol=85, muted=True, get_out=get_out, mute_out=mute_out); s = AudioSink(which=m.which, run=m.run)
    tb = TopBar(audio=s); print("  %-7s out=%-45r mute_out=%-12r -> get()=%s  UI vol=%d muteChecked=%s (sink truly muted=True vol=85)" % (backend, get_out[:45], mute_out, s.get(), tb.volume.value(), tb.mute.isChecked()))

print("E. hang: backend takes 2.0 s per call (the _run timeout)")
m = Mixer("pactl", delay=2.0); tb, dt = tb_for(m); print("   TopBar() constructor blocked %.1f s on the calling (UI) thread; calls=%d" % (dt, len(m.calls)))
ticks = []; t = QtCore.QTimer(); t.timeout.connect(lambda: ticks.append(time.time())); t.start(50)
pump(300); n0 = len(ticks); t0 = time.time(); tb.volume.setValue(60); pump(2600); 
gaps = [b - a for a, b in zip(ticks, ticks[1:])]
print("   slider move -> debounce -> set_volume: longest UI event-loop stall %.2f s" % max(gaps))
t0 = time.time(); tb.toggle_mute(); print("   toggle_mute() returned after %.2f s" % (time.time() - t0))

print("F. argv / injection")
for b in ("wpctl", "pactl", "amixer"):
    s = AudioSink(which=lambda n, b=b: n == b, run=lambda a, timeout=2.0: (0, ""))
    for v in (-5, 0, 50, 100, 1e9, "7", 49.9, True):
        a = s.set_volume_argv(v); assert isinstance(a, list) and all(isinstance(x, str) for x in a), a
    print("  ", b, s.set_volume_argv(-5), s.set_volume_argv(1e9), s.set_mute_argv("x"), s.set_mute_argv(0))
    for bad in ("50; rm -rf /", None, float("nan"), float("inf")):
        try: print("     set_volume_argv(%r) ->" % (bad,), s.set_volume_argv(bad))
        except Exception as e: print("     set_volume_argv(%r) raises %s" % (bad, type(e).__name__))
import inspect, palisade_qt.kit.audio as A
print("   shell=True in audio.py:", "shell=True" in inspect.getsource(A), "| os.system:", "os.system" in inspect.getsource(A))

print("G. visible mute state")
m = Mixer("pactl"); tb, _ = tb_for(m); tb.setStyleSheet(theme.qss("dark")); tb.resize(1280, tb.height()); tb.show(); pump(100)
print("   mute text unmuted=%r" % tb.mute.text(), "size", tb.mute.size().toTuple(), "vol size", tb.volume.size().toTuple()); tb.mute.grab().save("mute_off.png")
tb.toggle_mute(); pump(100); print("   mute text muted=%r" % tb.mute.text()); tb.mute.grab().save("mute_on.png")
a, b = tb.mute.grab().toImage(), None
from PySide6 import QtGui
off = QtGui.QImage("mute_off.png"); on = QtGui.QImage("mute_on.png")
print("   images differ:", off != on, "centre px off/on:", off.pixelColor(3, off.height()//2).name(), on.pixelColor(3, on.height()//2).name())
m2 = Mixer("none"); tb2 = TopBar(audio=AudioSink(which=lambda n: None)); print("   no backend: enabled", tb2.volume.isEnabled(), tb2.mute.isEnabled(), "value", tb2.volume.value(), repr(tb2.mute.toolTip()))
