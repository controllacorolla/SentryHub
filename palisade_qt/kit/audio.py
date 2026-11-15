"""The real audio sink behind the top-strip volume slider and mute (audit section 9: the slider was
connected to nothing).

Drives whichever mixer CLI the device has — PipeWire (wpctl), PulseAudio (pactl) or ALSA (amixer) —
with argv lists, never a shell string. With none of them installed the sink reports unavailable and
the controls are disabled; a slider that moves but changes nothing is the bug this replaces.
`which` and `run` are injectable so tests drive a fake mixer.
"""
import re
import shutil
import subprocess


def _run(argv, timeout=2.0):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


class AudioSink:
    BACKENDS = ("wpctl", "pactl", "amixer")

    def __init__(self, which=shutil.which, run=_run):
        self._run = run
        self.backend = next((b for b in self.BACKENDS if which(b)), None)

    @property
    def available(self):
        return self.backend is not None

    def set_volume_argv(self, pct):
        pct = max(0, min(100, int(pct)))
        if self.backend == "wpctl":
            return ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "%.2f" % (pct / 100.0)]
        if self.backend == "pactl":
            return ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%d%%" % pct]
        if self.backend == "amixer":
            return ["amixer", "-M", "sset", "Master", "%d%%" % pct]
        return None

    def set_mute_argv(self, muted):
        if self.backend == "wpctl":
            return ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if muted else "0"]
        if self.backend == "pactl":
            return ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"]
        if self.backend == "amixer":
            return ["amixer", "sset", "Master", "mute" if muted else "unmute"]
        return None

    def _get_argv(self):
        return {"wpctl": ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                "pactl": ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                "amixer": ["amixer", "-M", "sget", "Master"]}.get(self.backend)

    def set_volume(self, pct):
        """True if the mixer accepted it. False (and nothing changed) with no backend."""
        argv = self.set_volume_argv(pct)
        return bool(argv) and self._run(argv)[0] == 0

    def set_mute(self, muted):
        argv = self.set_mute_argv(muted)
        return bool(argv) and self._run(argv)[0] == 0

    def get(self):
        """(volume 0-100 or None, muted bool or None) as the mixer reports it."""
        argv = self._get_argv()
        if not argv:
            return None, None
        rc, out = self._run(argv)
        if rc != 0:
            return None, None
        if self.backend == "wpctl":
            m = re.search(r"Volume:\s*([0-9.]+)", out)
            return (int(round(float(m.group(1)) * 100)) if m else None), "[MUTED]" in out
        m = re.search(r"(\d+)%", out)
        vol = int(m.group(1)) if m else None
        if self.backend == "amixer":
            return vol, "[off]" in out
        rc2, out2 = self._run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        return vol, ("yes" in out2.lower()) if rc2 == 0 else None


# ---------------------------------------------------------------------------------------------
# Off the GUI thread. A mixer CLI can hang (a wedged PipeWire daemon) for its whole timeout; on
# the GUI thread that froze the strip for 2-4 s per call (RA-CL1). Every set is followed by a
# read-back, and the strip shows only what the read-back says.

import queue        # noqa: E402
import threading    # noqa: E402

from PySide6 import QtCore  # noqa: E402

# Controllers and their threads live for the process (the `_retain` rule in app.py): nothing a
# worker thread holds may become garbage that a non-GUI thread then has to delete.
_RETAINED = []


class AudioController(QtCore.QObject):
    """Queues mixer operations onto one daemon thread. Emits `state` after each operation with what
    the mixer reported: {"volume": int|None, "muted": bool|None, "fault": str, "op": str}.
    A daemon thread rather than a QThread: a hung mixer call must never hold up process exit, and a
    QThread that outlives its join aborts the process (audit A2)."""
    state = QtCore.Signal(object)

    def __init__(self, sink):
        super().__init__()                    # unparented and retained: see _RETAINED
        _RETAINED.append(self)
        self.sink = sink
        self._q = queue.Queue()
        self._thread = None
        self.pending = 0

    def request(self, op, arg=None):
        """op: 'get' | 'volume' (arg pct) | 'mute' (arg bool)."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="palisade-mixer", daemon=True)
            _RETAINED.append(self._thread)
            self._thread.start()
        self.pending += 1
        self._q.put((op, arg))

    def _loop(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            op, arg = item
            fault = ""
            try:
                if op == "volume" and not self.sink.set_volume(arg):
                    fault = "volume change refused by %s" % self.sink.backend
                elif op == "mute" and not self.sink.set_mute(arg):
                    fault = "%s refused by %s" % ("mute" if arg else "unmute", self.sink.backend)
                vol, muted = self.sink.get()
            except Exception as e:            # a broken seam must surface, not kill the thread
                vol, muted, fault = None, None, "mixer error: %s" % e
            if vol is None and muted is None:
                fault = (fault + "; " if fault else "") + "cannot read %s" % self.sink.backend
            try:
                self.state.emit({"volume": vol, "muted": muted, "fault": fault, "op": op})
            except RuntimeError:
                return

    def stop(self):
        if self._thread is not None:
            self._q.put(None)
