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
from .kit import TopBar
from .ops import OpsHome, CALLSIGNS, GROUPS
from .prism import PrismApp
from .babel import BabelApp
from .atlas import AtlasApp
from .prowl import ProwlApp
from .forge import ForgeApp
from .more import OverwatchApp, ReconApp, BenchApp

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

QT_PAGES = {
    "OVERWATCH": OverwatchApp, "ATLAS": AtlasApp, "BABEL": BabelApp, "PRISM": PrismApp,
    "PROWL": ProwlApp, "FORGE": ForgeApp, "RECON": ReconApp, "BENCH": BenchApp,
}
TK_HOSTS = {}


class NavRail(QtWidgets.QFrame):
    """Persistent left callsign rail, grouped OVERVIEW / SENSE / FIELD; active one violet."""

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.setObjectName("nav_rail")
        self.setFixedWidth(136)
        self.hub = hub
        self.btns = {}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 8)
        lay.setSpacing(1)
        for group, names in GROUPS:
            g = QtWidgets.QLabel(group)
            g.setProperty("class", "navgroup")
            lay.addWidget(g)
            for name in names:
                b = QtWidgets.QPushButton(name)
                b.setProperty("class", "nav_item")
                b.clicked.connect(lambda _, n=name: self.hub.open_callsign(n))
                lay.addWidget(b)
                self.btns[name] = b
        lay.addStretch(1)
        self.set_active("OPS")

    def set_active(self, name):
        for n, b in self.btns.items():
            b.setProperty("class", "nav_active" if n == name else "nav_item")
            b.style().unpolish(b)
            b.style().polish(b)


class PalisadeHub(QtWidgets.QMainWindow):
    def __init__(self, demo=False, mode="dark"):
        super().__init__()
        self.demo = demo
        self.mode = mode
        self.setWindowTitle("PALISADE")
        self.resize(1280, 480)

        central = QtWidgets.QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        vbox = QtWidgets.QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self.topbar = TopBar(mode=mode)          # one app-wide top bar (logo/chips/vol/clock)
        vbox.addWidget(self.topbar)

        hbox = QtWidgets.QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)
        self.rail = NavRail(self)
        hbox.addWidget(self.rail)
        self.stack = QtWidgets.QStackedWidget()
        hbox.addWidget(self.stack, 1)
        vbox.addLayout(hbox, 1)

        vbox.addWidget(self._foot())

        self.pages = {}
        self.ops = OpsHome(demo=demo, mode=mode)
        self.ops.launch.connect(self.open_callsign)
        self._add_page("OPS", self.ops)
        self.show_page("OPS")

        QtGui.QShortcut(QtGui.QKeySequence("Escape"), self,
                        activated=lambda: self.show_page("OPS"))
        for i, (name, _) in enumerate(CALLSIGNS):
            QtGui.QShortcut(QtGui.QKeySequence(str(i + 1)),
                            self, activated=lambda n=name: self.open_callsign(n))

    def _foot(self):
        f = QtWidgets.QFrame()
        f.setObjectName("foot_bar")
        f.setFixedHeight(26)
        h = QtWidgets.QHBoxLayout(f)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(16)
        for key, txt in (("⌘K", "JUMP"), ("ESC", "HOME"), ("⌘R", "RECORD")):
            k = QtWidgets.QLabel(key)
            k.setProperty("class", "footkey")
            t = QtWidgets.QLabel(txt)
            t.setProperty("class", "foottxt")
            h.addWidget(k)
            h.addWidget(t)
        h.addStretch(1)
        return f

    def _add_page(self, name, widget):
        if hasattr(widget, "attach_topbar"):
            widget.attach_topbar(self.topbar)
        self.pages[name] = widget
        self.stack.addWidget(widget)

    def show_page(self, name):
        w = self.pages.get(name)
        if w is None:
            return
        self.stack.setCurrentWidget(w)
        self.rail.set_active(name)
        for n, page in self.pages.items():     # only the visible page drives the shared top bar
            if hasattr(page, "set_active"):
                page.set_active(n == name)

    def open_callsign(self, name):
        if name in self.pages:
            self.show_page(name)
            return
        if name in QT_PAGES:
            page = QT_PAGES[name](demo=self.demo, mode=self.mode)
            self._add_page(name, page)
            self.show_page(name)
            return
        mod = TK_HOSTS.get(name)
        if mod:
            self.launch_tk(mod)

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
    theme.load_fonts()
    theme.set_app_font(app)
    theme.set_palette(app, mode)
    app.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=demo, mode=mode)
    hub.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
