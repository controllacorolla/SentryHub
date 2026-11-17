"""PalisadeHub — the Qt Hub shell: one top strip, eight page keys, keyboard-first.

Structure (CL1, owner decision in plan/audit/AUDIT_INDEX.md):

    1 OPS home · 2 ATLAS map · 3 PRISM spectrum · 4 PROWL listen · 5 RECON survey + assess
    6 FORGE hardware · 7 SYSTEM settings
    (SWEEP counter-surveillance is hidden in v0.1 — release.HIDDEN_PAGES; back with CL7.)

There is no left rail and no footer: navigation and the four shell-owned status slots (MODE / RADIO /
TX / ENGAGEMENT) share one ≤ 40 px strip, and the page gets everything below it. The shell owns the
global panels (RADIOS, ENGAGEMENT, alerts, key map, command palette), routes the keyboard, and draws
a hatched border round the window in DEMO.

The shell reads engine state and calls existing engine functions (arbiter release, txguard.arm /
unlock_session from the TX panel, engagement.end(), executor.kill_all()); it adds no gate, changes no
gate, and touches no decode path. The four slots follow the engines through chrome.gate_signals().
"""
import os
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from . import theme, chrome, eventbus, panels, procs, release, sessionlog
from .kit import TopBar
from .ops import OpsHome, CALLSIGNS
from .prism import PrismApp
from .forge import ForgeApp
from .recon import ReconApp
from .sweep import SweepApp
from .pages import AtlasPage, ProwlPage, SystemPage
from .atlas import AtlasApp
from .overwatch import OverwatchApp
from .prowl import ProwlApp
from .babel import BabelApp
from .system import MoreApp, AssistantApp, MeshApp
from .bench_app import BenchApp

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

QT_PAGES = {
    "ATLAS": AtlasPage, "PRISM": PrismApp, "PROWL": ProwlPage, "SWEEP": SweepApp,
    "RECON": ReconApp, "FORGE": ForgeApp, "SYSTEM": SystemPage,
    "ASSISTANT": AssistantApp, "MESH": MeshApp,         # own pages since 2026-11-17 (owner)
}
# Callsigns that used to be pages and are now sub-tabs: old name -> (page, sub-tab, child class).
FOLDED = {
    "OVERWATCH": ("ATLAS", "SKY DOME", OverwatchApp),
    "BABEL": ("PROWL", "DECODE", BabelApp),
    "BENCH": ("SYSTEM", "BENCH", BenchApp),
    "MORE": ("SYSTEM", "SETTINGS", MoreApp),
}
_INNER = {"ATLAS": AtlasApp, "PROWL": ProwlApp}        # the app behind a composite's first part
PANIC_KEY = "F12"                    # alias
PANIC_CHORD = "Shift+Esc"            # primary: no Fn layer on the uConsole keyboard, one hand
SCREEN = (1280, 720)

_TEXT_INPUTS = (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QPlainTextEdit,
                QtWidgets.QTextEdit)


def child_pids(pid=None):
    """Direct child processes of this app (the decoders / tools it spawned). Best effort."""
    return procs.child_pids(pid)


class _NetBridge(QtCore.QObject):
    """netpolicy calls its listeners on the requesting thread; this queues a mode change onto the
    GUI thread for the NET slot."""
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import netpolicy
        self._np = netpolicy
        netpolicy.add_listener(self._on)

    def _on(self, ev):
        if ev and ev[0] == "mode":
            try:
                self.changed.emit()
            except RuntimeError:
                pass

    def stop(self):
        self._np.remove_listener(self._on)


class PalisadeHub(QtWidgets.QMainWindow):
    def __init__(self, demo=False, mode="dark"):
        super().__init__()
        self.demo = demo
        self.mode = mode
        if demo and eventbus.home() is None:
            eventbus.set_home(eventbus.DEMO_HOME, "demo")     # H5: a demo frame, flagged as such
        self.setWindowTitle("PALISADE")
        self.resize(*SCREEN)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        central = QtWidgets.QWidget()
        central.setObjectName("root")
        central.setStyleSheet(theme.qss(mode))    # the chrome is themed even without main()
        self.setCentralWidget(central)
        vbox = QtWidgets.QVBoxLayout(central)
        b = panels.DemoBorder.WIDTH if demo else 0      # the DEMO hatch frames the window; content
        vbox.setContentsMargins(b, b, b, b)             # sits inside it, never underneath
        vbox.setSpacing(0)

        self.topbar = TopBar(mode=mode, nav=CALLSIGNS)      # the one strip: nav + status slots
        self.topbar.nav_requested.connect(self.open_callsign)
        self.topbar.slot_clicked.connect(self._slot_clicked)
        vbox.addWidget(self.topbar)
        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.nav_rail = self.topbar.nav_rail           # page keys down the left edge (2026-11-17)
        body.addWidget(self.nav_rail)
        self.stack = QtWidgets.QStackedWidget()
        body.addWidget(self.stack, 1)
        vbox.addLayout(body, 1)

        # shell-owned state -> the four fixed slots (a page can never write these)
        self.state = chrome.ChromeState(demo=demo, parent=self)
        self.state.changed.connect(self._on_state)
        self.alerts = panels.alert_store()
        self.alerts.changed.connect(self._on_alerts)

        # global panels float over the page area
        self.radios_panel = panels.RadiosPanel(mode, central)
        self.engage_panel = panels.EngagePanel(mode, central)
        self.engage_panel.gate_changed.connect(self._gate_changed)
        self.tx_panel = panels.TxPanel(mode, central)
        self.alerts_drawer = panels.AlertsDrawer(mode, central, store=self.alerts)
        self.keymap = panels.KeyMapOverlay(mode, central)
        self.palette = panels.CommandPalette(mode, central)
        self.log_panel = panels.SessionLogPanel(mode, central)
        self._overlays = [self.radios_panel, self.engage_panel, self.tx_panel, self.alerts_drawer,
                          self.keymap, self.palette, self.log_panel]
        # C4 + L3: the fault indicator and the NET slot follow the session log / network mode
        self._net_bridge = _NetBridge(self)
        self._net_bridge.changed.connect(self._on_net)
        sessionlog.log().changed.connect(self._on_log)
        self.panic_banner = QtWidgets.QLabel("", central)
        self.panic_banner.setProperty("class", "value")
        self.panic_banner.setAlignment(QtCore.Qt.AlignCenter)
        self.panic_banner.setWordWrap(True)
        self.panic_banner.hide()
        self.demo_border = panels.DemoBorder(mode, central) if demo else None

        self.pages = {}
        self._current = None
        self.ops = OpsHome(demo=demo, mode=mode)
        self._add_page("OPS", self.ops)
        self.show_page("OPS")
        self._on_state()
        self._on_alerts()
        self._on_net()
        self._on_log()

        # device notes 2026-11-17: OPS showed nothing until ATLAS had been opened, because ATLAS's
        # worker is the contact source. Start it in the background at launch (passive feeds only
        # while hidden: AtlasLiveWorker.step). Tests open this seam explicitly.
        from .kit.seams import offscreen
        if not offscreen():
            QtCore.QTimer.singleShot(0, self.start_background_feeds)
        # owner 2026-11-17: HOME follows GPS when there is a trustworthy fix (gpshome.py); the typed
        # HOME stays the fallback. Never in demo, never under the test seam (tests start it).
        self.gpshome = None
        if not demo and not offscreen():
            self.start_gps_home()

        # keyboard: one filter for the whole window (D8)
        QtWidgets.QApplication.instance().installEventFilter(self)
        # test / automation seams for PANIC's process stop
        self._list_children = child_pids
        self._stop_tree = procs.stop_tree

    # ------------------------------------------------------------------ pages
    def _add_page(self, name, widget):
        self.pages[name] = widget
        self.stack.addWidget(widget)
        if hasattr(widget, "request"):
            widget.request.connect(self._on_request)

    def show_page(self, name):
        w = self.pages.get(name)
        if w is None or self.stack.indexOf(w) < 0:
            return
        self._current = name
        self.stack.setCurrentWidget(w)
        self.topbar.set_active_page(name)
        self.set_nav_hidden(bool(getattr(w, "side_hidden", lambda: False)()))
        self.setFocus()        # keys go to the page, not to whichever nav key was last focused
        for n, page in self.pages.items():
            if self.stack.indexOf(page) >= 0 and hasattr(page, "set_active"):
                page.set_active(n == name)
        self._sync_nested_tabs()

    def _sync_nested_tabs(self):
        """Each page's sub-tab list sits under its key in the left rail; only the current page's
        is shown (and not while F has the map full width)."""
        cur = self.pages.get(self._current)
        for n, page in self.pages.items():
            rail = getattr(page, "_rail", None)
            if rail is None or n not in self.topbar.nav_keys:
                continue
            self.nav_rail.attach_sub(n, rail)
            rail.setVisible(page is cur and not page.side_hidden())

    def start_background_feeds(self):
        """Build ATLAS (not shown) and start its worker, so OPS gets contacts from launch."""
        if self.release_hidden("ATLAS"):
            return False
        if "ATLAS" not in self.pages:
            self._add_page("ATLAS", QT_PAGES["ATLAS"](demo=self.demo, mode=self.mode))
            inner = _INNER.get("ATLAS")
            if inner is not None:
                self.pages["ATLAS:inner"] = self.pages["ATLAS"].child(inner)
        app = self.pages.get("ATLAS:inner", self.pages["ATLAS"])
        app.start()
        if hasattr(app, "set_background"):
            app.set_background(True)
        return True

    @staticmethod
    def release_hidden(name):
        return name not in QT_PAGES or release.page_hidden(name)

    def current_page(self):
        return self.pages.get(self._current)

    def open_callsign(self, name, subtab=None):
        """Open a page by key name. Folded callsigns (OVERWATCH, BABEL, BENCH, MORE) still resolve:
        they open their new home on the right sub-tab."""
        if name in FOLDED:
            page, sub, cls = FOLDED[name]
            self.open_callsign(page, sub)
            self.pages[name] = self.pages[page].child(cls)      # the folded app itself
            return
        if name not in self.pages:
            if name not in QT_PAGES or release.page_hidden(name):
                return                 # v0.1: a hidden page is not built, by key or by name
            self._add_page(name, QT_PAGES[name](demo=self.demo, mode=self.mode))
            inner = _INNER.get(name)
            if inner is not None:
                self.pages[name + ":inner"] = self.pages[name].child(inner)
        self.show_page(name)
        if subtab:
            self.pages[name].switch_subtab(subtab)

    def page_app(self, name):
        """The app behind a key or a folded callsign (ATLAS -> AtlasApp, BABEL -> BabelApp …)."""
        if name in FOLDED:
            self.open_callsign(name)
            return self.pages[name]
        self.open_callsign(name)
        return self.pages.get(name + ":inner", self.pages.get(name))

    def set_nav_hidden(self, hidden):
        """F on a map page: the page rail goes with the side panels (1-7 still switch pages)."""
        self.nav_rail.setVisible(not hidden)

    # ------------------------------------------------------------------ shell-owned chrome
    def _on_state(self):
        self.topbar.set_state(self.state.mode, self.state.radio(), self.state.tx(),
                              self.state.engagement())
        self._gate_changed()

    def _on_alerts(self):
        self.topbar.set_alerts(self.alerts.unacked())

    def _gate_changed(self):
        for name, page in list(self.pages.items()):
            if self.stack.indexOf(page) >= 0 and hasattr(page, "on_gate_changed"):
                page.on_gate_changed()
        if self.engage_panel.isVisible():
            self.engage_panel.refresh()

    def _slot_clicked(self, key):
        # MODE opens the session log while it carries the fault indicator, else the key map
        if key == "mode":
            key = "log" if sessionlog.log().faults_unseen() else "keys"
        self.open_panel({"radio": "radios", "engagement": "engagement", "alerts": "alerts",
                         "tx": "tx", "keys": "keys", "net": "log", "log": "log"}[key])

    def _on_log(self):
        self.topbar.set_faults(sessionlog.log().faults_unseen())

    def _on_net(self, *_):
        import netpolicy
        self.topbar.set_net(netpolicy.mode())

    def open_panel(self, which):
        panel = {"radios": self.radios_panel, "engagement": self.engage_panel,
                 "tx": self.tx_panel, "alerts": self.alerts_drawer, "keys": self.keymap,
                 "palette": self.palette, "log": self.log_panel}.get(which)
        if panel is None:
            return
        if panel.isVisible():
            panel.close_overlay()
            return
        for o in self._overlays:
            o.close_overlay()
        if panel is self.palette:
            self.palette.set_commands(self._commands(), self._freq_commands)
        panel.open()

    def top_overlay(self):
        for o in self._overlays:
            if o.isVisible():
                return o
        return None

    def _on_request(self, what, arg):
        if what == "tune_fm":
            self.tune_fm(arg)
        elif what == "open_panel":
            self.open_panel(arg)
        elif what == "gate_changed":
            if self.engage_panel.isVisible():
                self.engage_panel.render_actions()

    def tune_fm(self, mhz):
        """'Send to' (D10): open PROWL's FM tuner on a frequency (from PRISM's peak or the palette)."""
        self.open_callsign("PROWL")
        self.pages["PROWL"].tune_fm(mhz)

    def tune_prism(self, mhz):
        self.open_callsign("PRISM")
        self.pages["PRISM"].tune(mhz)

    # ------------------------------------------------------------------ command palette
    def _commands(self):
        cmds = []
        for i, (name, label) in enumerate(CALLSIGNS, start=1):
            cmds.append(("%d %s — %s" % (i, name, label), lambda n=name: self.open_callsign(n)))
            cls = QT_PAGES.get(name)
            tabs = []
            if cls is not None:
                if getattr(cls, "PARTS", None):
                    tabs = [t for _f, ts in cls.PARTS for t, _s in ts]
                else:
                    tabs = list(cls.SUBTABS)
            for t in tabs:
                cmds.append(("%s › %s" % (name, t), lambda n=name, tt=t: self.open_callsign(n, tt)))
        cmds += [
            ("RADIOS panel", lambda: self.open_panel("radios")),
            ("ENGAGEMENT panel", lambda: self.open_panel("engagement")),
            ("TX panel — arm / unlock", lambda: self.open_panel("tx")),
            ("ALERTS drawer", lambda: self.open_panel("alerts")),
            ("Acknowledge all alerts", self.alerts_drawer.ack_all_seen),   # seen ones only
            ("Mute / unmute audio", self.topbar.toggle_mute),
            ("Key map", lambda: self.open_panel("keys")),
            ("PANIC — disarm TX, end engagement, kill child processes", self.panic),
        ]
        return cmds

    def _freq_commands(self, mhz):
        return [("Tune PROWL FM to %.3f MHz" % mhz, lambda: self.tune_fm(mhz)),
                ("Centre PRISM on %.3f MHz" % mhz, lambda: self.tune_prism(mhz))]

    # ------------------------------------------------------------------ PANIC
    def panic(self):
        """One key, no confirmation: disarm TX, end the engagement, stop child processes. Uses the
        engines' own functions; it is a stop, never an authorization. Every step runs even if an
        earlier one fails, and the banner says only what was verified: the TX slot is re-read from
        the gates (never cleared), and a process counts as stopped only once it is gone."""
        did = []
        try:
            import txguard
            txguard.arm(False)                     # also drops the session unlock
            did.append("TX disarmed")
        except Exception as e:
            did.append("TX disarm FAILED: %s" % e)
        try:
            import engagement
            was = engagement.end()
            did.append("engagement %s ended" % was if was else "no engagement was open")
        except Exception as e:
            did.append("engagement end FAILED: %s" % e)
        # RA-CL5b N-h: what was running BEFORE the pages stopped their own decoders, so the
        # banner counts those stops too instead of "no child processes were running"
        try:
            pre_kids = list(self._list_children())
        except Exception:
            pre_kids = []
        try:
            from . import radio_arbiter as _ra
            pre_owner = _ra.arbiter.owner()
        except Exception:
            pre_owner = None
        try:
            import executor
            n = executor.kill_all("PANIC")             # every registered gated process group
            if n:
                did.append("%d gated process(es) stopped" % n)
        except Exception as e:
            did.append("executor kill FAILED: %s" % e)
        try:
            for name, page in list(self.pages.items()):     # UI-held permits (BENCH's ack)
                if self.stack.indexOf(page) >= 0:
                    did += page.on_panic()
        except Exception as e:
            did.append("permit revoke FAILED: %s" % e)
        try:
            roots = list(self._list_children())
            res = self._stop_tree(roots)
            by_pages = [p for p in pre_kids if p not in roots and not procs.alive(p)]
            if by_pages and not res.get("targets"):
                did.append("%d child process(es) stopped by their pages (verified gone)"
                           % len(by_pages))
            else:
                did.append(procs.describe(res))
                if by_pages:
                    did.append("%d more stopped by their pages" % len(by_pages))
        except Exception as e:
            did.append("child process stop FAILED: %s" % e)
        try:
            # CL5-fix 5 / N3: the pages were told to stay off the radio (on_panic, above) BEFORE
            # the process tree was killed, so nothing respawns; now free the arbiter at once and
            # report what the arbiter says afterwards, not what we asked for
            from . import radio_arbiter
            was = radio_arbiter.arbiter.panic_free()
            st, owner = radio_arbiter.arbiter.state()
            was = was or pre_owner                 # its page may have released it first
            if st == "FREE":
                did.append("radio released (was %s)" % radio_arbiter.OWNER_LABELS.get(was, was)
                           if was else "radio was free")
            else:
                did.append("radio STILL %s by %s" % (st, radio_arbiter.OWNER_LABELS.get(owner, owner)))
        except Exception as e:
            did.append("radio release FAILED: %s" % e)
        try:
            self._gate_changed()                   # pages re-read their own gates (BENCH …)
            self.state.poll()
        except Exception as e:
            did.append("gate re-read FAILED: %s" % e)
        # the banner says what the gates say after the re-read, never what PANIC hoped for
        tx = chrome.read_tx()
        if tx == "OFF":
            did.append("TX OFF")
        elif tx == "PERMITTED":
            did.append("TX still PERMITTED (%s)" % ", ".join(chrome.tx_permit_sources()))
        else:
            did.append("TX %s" % tx)
        text = "PANIC — " + " · ".join(did)
        try:
            eventbus.bus.publish(eventbus.alert("SHELL", text, severity="alert"))
        finally:
            self._show_banner(text)
        return did

    def _show_banner(self, text):
        tok = theme.tokens(self.mode)
        self.panic_banner.setStyleSheet(
            "background:%s; color:%s; border:%s solid %s; border-radius:8px; padding:10px;"
            % (tok["p1"], tok["alert"], tok["focus_w"], tok["alert"]))
        self.panic_banner.setText(text)
        par = self.centralWidget()
        self.panic_banner.setGeometry(40, 60, par.width() - 80, 90)
        self.panic_banner.show()
        self.panic_banner.raise_()
        QtCore.QTimer.singleShot(6000, self.panic_banner.hide)

    # ------------------------------------------------------------------ keyboard (D8)
    def eventFilter(self, obj, ev):
        if not isinstance(obj, QtCore.QObject) or not isinstance(ev, QtCore.QEvent):
            # RA-UIP M5: PySide can hand an app-wide filter a stale wrapper (a QWidgetItem whose
            # address Qt reused) for obj or ev; such a pair is never a key press of ours
            return False
        if ev.type() == QtCore.QEvent.KeyPress:
            if self._is_panic(ev) and self._ours(obj):
                # PANIC first, before any focus/target test: an open combo dropdown or context
                # menu is its own popup window and grabs the keyboard, so the ordinary routing
                # never sees the key (RA-CL1). Consuming it stops propagation, so it runs once.
                popup = QtWidgets.QApplication.activePopupWidget()
                if popup is not None:
                    popup.close()
                self.panic()
                return True
            if self._is_key_target(obj) and self.handle_key(ev):
                return True
        try:
            return super().eventFilter(obj, ev)
        except (TypeError, AttributeError, RuntimeError):
            return False         # same stale-wrapper case, caught by type in the base call

    @staticmethod
    def _is_panic(ev):
        K = QtCore.Qt
        return ev.key() == QtGui.QKeySequence(PANIC_KEY)[0].key() or (
            ev.key() == K.Key_Escape and bool(ev.modifiers() & K.ShiftModifier))

    def _ours(self, obj):
        """A widget in this window, or a popup (dropdown list, menu) opened from it."""
        if not isinstance(obj, QtWidgets.QWidget):
            return False
        w = obj.window()
        if w is self:
            return True
        if w.windowType() in (QtCore.Qt.Popup, QtCore.Qt.ToolTip) or isinstance(w, QtWidgets.QMenu):
            par = w.parentWidget()
            while par is not None:
                if par.window() is self:
                    return True
                par = par.parentWidget()
            return self.isActiveWindow() or QtWidgets.QApplication.activePopupWidget() is w
        return False

    def _is_key_target(self, obj):
        """True only for the widget the key was sent to. An unhandled key also propagates up through
        every parent, and each hop passes this filter again — acting on those would run one press
        twice (e.g. Enter in the palette, then again on whatever took focus when it closed)."""
        if not isinstance(obj, QtWidgets.QWidget) or obj.window() is not self:
            return False
        focus = QtWidgets.QApplication.focusWidget()
        if focus is not None and focus.window() is self:
            return obj is focus
        return obj is self

    def handle_key(self, ev):
        """Route one key press. Returns True if the shell consumed it."""
        key, text, mods = ev.key(), ev.text(), ev.modifiers()
        K = QtCore.Qt
        if self._is_panic(ev):                    # works everywhere, even while typing
            self.panic()
            return True
        if mods & (K.ControlModifier | K.AltModifier | K.MetaModifier):
            return False
        focus = QtWidgets.QApplication.focusWidget()
        typing = isinstance(focus, _TEXT_INPUTS) or (
            isinstance(focus, QtWidgets.QComboBox) and focus.isEditable())
        overlay = self.top_overlay()

        if key == K.Key_Escape:
            if overlay is not None:
                overlay.close_overlay()
                self.setFocus()
            elif typing:
                focus.clearFocus()
            else:
                self.show_page("OPS")
            return True
        if overlay is not None:
            if overlay is self.alerts_drawer and key in (K.Key_Return, K.Key_Enter) and not typing:
                self.alerts_drawer.ack_selected()
                return True
            return False                # the open panel gets the keyboard (Tab, arrows, typing)
        if typing:
            return False                # never steal characters from a text field

        page = self.current_page()
        if text and len(text) == 1 and text.isdigit() and 1 <= int(text) <= len(CALLSIGNS):
            self.open_callsign(CALLSIGNS[int(text) - 1][0])
            return True
        if key in (K.Key_Left, K.Key_Right):
            if isinstance(focus, (QtWidgets.QSlider, QtWidgets.QComboBox)):
                return False
            return bool(page is not None and page.cycle_subtab(1 if key == K.Key_Right else -1))
        if key in (K.Key_Up, K.Key_Down):
            if isinstance(focus, (QtWidgets.QComboBox, QtWidgets.QSlider, QtWidgets.QListWidget)):
                return False
            lst = page.primary_list() if page is not None else None
            if lst is None:
                return False
            return lst.move_cursor(1 if key == K.Key_Down else -1)
        if key in (K.Key_Return, K.Key_Enter):
            if isinstance(focus, QtWidgets.QAbstractButton):
                focus.click()
                return True
            if isinstance(focus, QtWidgets.QComboBox):
                return False
            return bool(page is not None and page.primary_action())
        if text == " ":
            if isinstance(focus, QtWidgets.QAbstractButton):
                return False            # Space still presses the focused button / checkbox
            return bool(page is not None and page.handle_key(" "))
        if text and text in "[]+-=_":
            return bool(page is not None and page.handle_key(text))
        if text == "/":
            self.open_panel("palette")
            return True
        if text == "?":
            self.open_panel("keys")
            return True
        low = text.lower() if text else ""
        if low == "r":
            self.open_panel("radios")
            return True
        if low == "e":
            self.open_panel("engagement")
            return True
        if low == "a":
            self.open_panel("alerts")
            return True
        if low == "m":
            self.topbar.toggle_mute()
            return True
        if low == "f":                           # full map: hide / show the side panels
            return bool(page is not None and page.handle_key("f"))
        if low == "v":                           # ATLAS: cycle the views (RA-UIPc M2)
            return bool(page is not None and page.handle_key("v"))
        return False

    # ------------------------------------------------------------------ geometry + lifecycle
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        par = self.centralWidget()
        if self.demo_border is not None:
            self.demo_border.setGeometry(0, 0, par.width(), par.height())
            self.demo_border.raise_()
        for o in self._overlays:
            if o.isVisible():
                o.place()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.demo_border is not None:
            par = self.centralWidget()
            self.demo_border.setGeometry(0, 0, par.width(), par.height())
            self.demo_border.show()
            self.demo_border.raise_()

    def start_gps_home(self, reader=None, enabled=None):
        from . import gpshome
        if self.gpshome is None:
            on = gpshome.follows_gps() if enabled is None else enabled
            self.gpshome = gpshome.GpsHome(reader=reader, enabled=on, parent=self)
        self.gpshome.start()
        return self.gpshome

    def closeEvent(self, ev):
        if getattr(self, "gpshome", None) is not None:
            self.gpshome.stop()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.state.stop()
        self.topbar.stop()
        self.radios_panel.stop()
        try:
            self.alerts.changed.disconnect(self._on_alerts)
        except (TypeError, RuntimeError):
            pass
        self._net_bridge.stop()
        for sig, slot in ((sessionlog.log().changed, self._on_log),
                          (self.log_panel.log.changed, self.log_panel._changed)):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        seen = set()
        for w in self.pages.values():
            if id(w) in seen or self.stack.indexOf(w) < 0:
                continue                 # folded apps are stopped by the composite that hosts them
            seen.add(id(w))
            if hasattr(w, "stop"):
                w.stop()
        super().closeEvent(ev)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    demo = "--demo" in argv
    mode = "sun" if "--sun" in argv else "light" if "--light" in argv else "dark"
    if QtWidgets.QApplication.instance() is None:
        theme.configure_scale(os.environ)      # must run before the QApplication exists
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    theme.load_fonts()
    theme.set_app_font(app)
    theme.set_palette(app, mode)
    app.setStyleSheet(theme.qss(mode))
    eventbus.load_home(demo=demo)              # H5: the saved HOME, before any page reads it
    sessionlog.install_hooks()                 # C4: uncaught exceptions reach the session log
    sessionlog.watch_network()                 # L3: every outbound request is logged
    hub = PalisadeHub(demo=demo, mode=mode)
    hub.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
