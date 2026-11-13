"""PalisadeHub — the Qt Hub shell (QStackedWidget), hosting migrated Qt apps as embedded pages.

Phase 2 scope: the shell + OPS home. The inverted-coexistence model (per the corrected decision
memo): migrated Qt apps are embedded pages here; a not-yet-migrated app is launched as a
separate Tk **subprocess** via its standalone `main()`. Until the Qt Hub is proven, the old
`hub.py` stays runnable — this is an additive launcher, not a replacement.
"""
import os
import subprocess
import sys

from PySide6 import QtGui, QtWidgets

from . import theme
from .ops import OpsHome
from .prism import PrismApp

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Migrated callsigns -> a factory; the Hub builds them lazily and embeds them as pages.
QT_PAGES = {
    "PRISM": PrismApp,
}
# Not-yet-migrated callsigns -> a Tk host module, launched as a separate process (inverted
# coexistence). As each cluster migrates, it moves from here into QT_PAGES.
TK_HOSTS = {
    "OVERWATCH": "overwatch", "ATLAS": "sky", "BABEL": "ais",
    "PROWL": "scanner", "FORGE": "hwlab", "RECON": "wifisurvey", "BENCH": "loopback",
}


class PalisadeHub(QtWidgets.QMainWindow):
    def __init__(self, demo=False, mode="dark"):
        super().__init__()
        self.demo = demo
        self.mode = mode
        self.setWindowTitle("PALISADE")
        self.resize(1280, 480)
        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)

        self.pages = {}
        self.ops = OpsHome(demo=demo, mode=mode)
        self.ops.launch.connect(self.open_callsign)
        self._add_page("OPS", self.ops)
        self.show_page("OPS")

        QtGui.QShortcut(QtGui.QKeySequence("Escape"), self,
                        activated=lambda: self.show_page("OPS"))     # esc -> home (chrome spec)

    def _add_page(self, name, widget):
        self.pages[name] = widget
        self.stack.addWidget(widget)

    def show_page(self, name):
        w = self.pages.get(name)
        if w is not None:
            self.stack.setCurrentWidget(w)

    def open_callsign(self, name):
        if name in self.pages:                 # already-built migrated Qt page
            self.show_page(name)
            return
        if name in QT_PAGES:                   # migrated but not built yet: build + embed lazily
            page = QT_PAGES[name](demo=self.demo, mode=self.mode)
            self._add_page(name, page)
            self.show_page(name)
            return
        mod = TK_HOSTS.get(name)
        if mod:
            self.launch_tk(mod)                # not migrated yet: run its Tk standalone as a subprocess

    def launch_tk(self, module):
        """Launch a not-yet-migrated Tk app as its own process (inverted coexistence)."""
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            return None
        args = [sys.executable, path]
        if self.demo:
            args.append("--demo")
        try:
            return subprocess.Popen(args, start_new_session=True,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return None

    def closeEvent(self, ev):
        for w in self.pages.values():
            if hasattr(w, "stop"):
                w.stop()
        super().closeEvent(ev)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    demo = "--demo" in argv
    mode = "light" if "--light" in argv else "dark"
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    theme.apply(app.activeWindow() or QtWidgets.QWidget(), mode)  # ensure font loads
    hub = PalisadeHub(demo=demo, mode=mode)
    hub.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
