"""PalisadeApp — the base workspace widget every migrated app subclasses.

It bakes in the two lifecycles that caused the recurring bugs, so each app is correct by
construction:

  * Worker thread (R1/R3): started on first show, quit()/wait()-ed on close. No daemon threads.
  * SDR lease: acquired on first show, released on close — the RtlLease.release fixes, once.

Runs standalone (`.standalone()` wraps it in a QMainWindow) or embedded in the Qt Hub (added as
a QStackedWidget page; the Hub calls `.stop()` when the page closes). Hiding does NOT stop it —
like the Tk workspaces, an embedded app keeps running in the background.

Subclass contract:
  LEASE          class attr: a lease name if the app needs the SDR, else None.
  build_body()   return the app's content widget (composed from kit components).
  make_worker()  return a Worker (or None). Its signals are wired to on_row/on_status/on_error.
"""
import threading

from PySide6 import QtCore, QtWidgets

from . import theme
from .kit import StatusHeader


class PalisadeApp(QtWidgets.QWidget):
    TITLE = "APP"
    LEASE = None

    def __init__(self, demo=False, mode="dark", parent=None):
        super().__init__(parent)
        self.demo = demo
        self.mode = mode
        self._worker = None
        self._lease = None
        self._started = False
        self._stopped = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        self.header = StatusHeader(self.TITLE)
        root.addWidget(self.header)
        self.header.set_chip("sdr", "SDR" + (" DEMO" if demo else ""), ok=demo)
        body = self.build_body()
        root.addWidget(body, 1)

        theme.apply(self, mode)

    # ---- subclass hooks (defaults keep the base usable on its own) ----
    def build_body(self):
        return QtWidgets.QWidget()

    def make_worker(self):
        return None

    def on_row(self, row):
        pass

    def on_status(self, status):
        for k in ("sdr", "gps", "pwr", "tx"):
            if k in status:
                self.header.set_chip(k, status[k].get("text"), status[k].get("ok"))

    def on_error(self, msg):
        # R2: surface, don't swallow. Subclasses can show it in the UI; default routes to stderr.
        import sys
        print("[%s] %s" % (self.TITLE, msg), file=sys.stderr)

    # ---- lifecycle (the baked-in correctness) ----
    def start(self):
        if self._started:
            return
        self._started = True
        self._acquire_lease()
        self._worker = self.make_worker()
        if self._worker is not None:
            self._worker.row.connect(self.on_row)
            self._worker.status.connect(self.on_status)
            self._worker.error.connect(self.on_error)
            self._worker.start()

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        if self._worker is not None:
            self._worker.stop()
            self._worker.quit()
            self._worker.wait(3000)      # join the worker before we go — no leaked QThread
            self._worker = None
        self._release_lease()

    def _acquire_lease(self):
        if not self.LEASE or self.demo:
            return                       # demo / no-radio apps never touch the dongle

        def work():
            try:
                import suite
                lease = suite.RtlLease(self.LEASE)
                lease.acquire()
                self._lease = lease
            except Exception as e:       # no suite / no radio in this env: degrade, don't crash
                import sys
                print("[%s] lease unavailable: %s" % (self.TITLE, e), file=sys.stderr)
        threading.Thread(target=work, daemon=True).start()

    def _release_lease(self):
        if self._lease is not None:
            try:
                self._lease.release()
            except Exception:
                pass
            self._lease = None

    # ---- Qt events ----
    def showEvent(self, ev):
        super().showEvent(ev)
        self.start()

    def closeEvent(self, ev):
        self.stop()
        super().closeEvent(ev)

    # ---- standalone wrapper ----
    def standalone(self):
        win = QtWidgets.QMainWindow()
        win.setWindowTitle("PALISADE — " + self.TITLE)
        win.setCentralWidget(self)
        win.resize(1280, 480)

        # ensure the app stops when the window closes (closeEvent is on the central widget)
        def _close(ev, _orig=win.closeEvent):
            self.stop()
            _orig(ev)
        win.closeEvent = _close
        return win
