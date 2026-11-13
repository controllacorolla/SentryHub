"""PalisadeHub — the Qt Hub shell (QStackedWidget), hosting migrated Qt apps as embedded pages.

Phase 2 scope: the shell + OPS home. The inverted-coexistence model (per the corrected decision
memo): migrated Qt apps are embedded pages here; a not-yet-migrated app is launched as a
separate Tk **subprocess** via its standalone `main()`. Until the Qt Hub is proven, the old
`hub.py` stays runnable — this is an additive launcher, not a replacement.
"""
import os
import subprocess
import sys

from PySide6 import QtWidgets

from . import theme
from .ops import OpsHome

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# callsign -> ("qt", factory) for migrated apps, or ("tk", module) to launch as a subprocess.
# Only OPS is migrated in Phase 2; the rest resolve to their Tk hosts (launched as subprocesses).
TK_HOSTS = {
    "OVERWATCH": "overwatch", "ATLAS": "sky", "BABEL": "ais", "PRISM": "rf_explorer",
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

    def _add_page(self, name, widget):
        self.pages[name] = widget
        self.stack.addWidget(widget)

    def show_page(self, name):
        w = self.pages.get(name)
        if w is not None:
            self.stack.setCurrentWidget(w)

    def open_callsign(self, name):
        if name in self.pages:                 # already a migrated, embedded Qt page
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
