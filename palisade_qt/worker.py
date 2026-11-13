"""The kit's worker contract — a QThread with a cooperative stop flag.

This is the R1/R3 fix made reusable: a worker emits results to the GUI thread via signals and
is quit()/wait()-ed on close, so there are no unjoined daemon threads and nothing touches a
widget off the GUI thread. Apps subclass Worker and implement step() (periodic) or run() (own
loop); PalisadeApp owns start/stop.
"""
from PySide6 import QtCore


class Worker(QtCore.QThread):
    row = QtCore.Signal(object)       # one feed row / sample to the GUI thread
    status = QtCore.Signal(dict)      # periodic status (SDR/GPS/PWR …) to the header
    error = QtCore.Signal(str)        # a fault the app should surface (R2: never swallowed)

    def __init__(self, demo=False, interval_ms=500, parent=None):
        super().__init__(parent)
        self.demo = demo
        self.interval_ms = interval_ms
        self._stop = False

    def stop(self):
        self._stop = True

    @property
    def stopping(self):
        return self._stop

    # Subclasses override step(); the default run() calls it on a timer. A subclass that needs
    # its own loop can override run() instead (still honouring self._stop).
    def step(self):
        return None

    def run(self):
        while not self._stop:
            try:
                self.step()
            except Exception as e:                 # R2: surface, don't swallow
                self.error.emit(str(e)[:200])
            waited = 0
            while waited < self.interval_ms and not self._stop:
                self.msleep(10)
                waited += 10
