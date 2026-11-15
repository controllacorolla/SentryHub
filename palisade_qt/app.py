"""PalisadeApp — the base workspace widget every page subclasses, and CompositeApp — a page built
from several of them.

The base bakes in the two lifecycles that caused the recurring bugs, so each app is correct by
construction:

  * Worker thread (R1/R3): started on first show, quit()/wait()-ed on close. No daemon threads.
  * SDR lease: acquired on first show, released on close — the RtlLease.release fixes, once.

and, since CL1, the page frame every page shares:

  * sub-tabs as a vertical rail at the page's left edge (SUBTABS + switch_subtab);
  * a page-owned status row under the body. set_chip() writes THERE. Pages cannot write the top
    strip: MODE / RADIO / TX / ENGAGEMENT are shell-owned slots (see chrome.py).
  * keyboard hooks the shell calls: cycle_subtab, primary_list, primary_action, handle_key.

Runs standalone (`.standalone()` wraps it in a QMainWindow) or embedded in the Qt Hub (a
QStackedWidget page; the Hub calls `.stop()` on close). Hiding does NOT stop it.

Subclass contract:
  LEASE          class attr: a lease name if the app needs the SDR, else None.
  SUBTABS        class attr: sub-tab names (empty for a single-view page).
  build_body()   return the app's content widget (composed from kit components).
  make_worker()  return a Worker (or None). Its signals are wired to on_row/on_status/on_error.
  switch_subtab(name) / current_subtab()   for pages with SUBTABS.
"""
import threading

from PySide6 import QtCore, QtWidgets

from . import theme
from .kit.subtabs import SubTabRail

_STATE_CLASS = {"neutral": "pstat", "ok": "pstat_live", "live": "pstat_live", "warn": "pstat_warn",
                "alert": "pstat_alert", "accent": "pstat_accent"}


# Pages and their finished workers are retained for the life of the process. A page that
# becomes cyclic garbage can be collected by whichever thread triggers the GC — a worker
# QThread — and shiboken then has to delete a QWidget off the GUI thread, which segfaults
# (seen 1-in-3 under Python 3.13: Shiboken::BindingManager::runDeletionInMainThread). Pages
# live until exit anyway; this just makes that explicit and deterministic.
_RETAINED = []


def _retain(obj):
    _RETAINED.append(obj)
    return obj


def retained():
    return list(_RETAINED)


class PalisadeApp(QtWidgets.QWidget):
    TITLE = "APP"
    LEASE = None
    SUBTABS = ()
    request = QtCore.Signal(str, object)      # page -> shell: ("tune_fm", mhz), ("open", "PROWL"), …

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        super().__init__(parent)
        _retain(self)
        self.demo = demo
        self.mode = mode
        self._embedded = embedded          # True when a CompositeApp hosts this page as a sub-tab
        self._host = None
        self._worker = None
        self._lease = None
        self._started = False
        self._stopped = False
        self._active = False
        self._last_status = {"sdr": {"text": "SDR DEMO" if demo else "SDR —",
                                     "state": "neutral", "ok": None}}
        self.header = self          # pages call self.header.set_chip(...) -> the page status row

        root = QtWidgets.QVBoxLayout(self)
        m = 0 if embedded else 8
        root.setContentsMargins(m, m, m, 0 if embedded else 4)
        root.setSpacing(6)
        mid = QtWidgets.QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(8)
        self._rail = None
        body = self.build_body()
        names = self.subtabs()
        if names and not embedded:
            self._rail = SubTabRail(names)
            self._rail.selected.connect(self.switch_subtab)
            mid.addWidget(self._rail)
        mid.addWidget(body, 1)
        root.addLayout(mid, 1)

        self._status_row = None
        self._status_labels = {}
        if not embedded:
            self._status_row = QtWidgets.QFrame()
            self._status_row.setObjectName("page_status")
            self._status_lay = QtWidgets.QHBoxLayout(self._status_row)
            self._status_lay.setContentsMargins(2, 2, 2, 2)
            self._status_lay.setSpacing(18)
            self._status_lay.addStretch(1)
            root.addWidget(self._status_row)

        theme.apply(self, mode)
        self._sync_rail()
        self._render_status()

    # ---- sub-tabs ----
    def subtabs(self):
        return list(self.SUBTABS)

    def current_subtab(self):
        return None

    def switch_subtab(self, name):
        """Pages with SUBTABS override this (and call _sync_rail when their view changes)."""

    def _sync_rail(self):
        if self._rail is not None:
            self._rail.set_current(self.current_subtab())
        if self._host is not None:
            self._host._child_switched(self)

    def cycle_subtab(self, delta):
        names = self.subtabs()
        if not names:
            return False
        cur = self.current_subtab()
        i = names.index(cur) if cur in names else 0
        self.switch_subtab(names[(i + delta) % len(names)])
        return True

    # ---- keyboard hooks (the shell routes keys here; all optional) ----
    def primary_list(self):
        """The list Up/Down should drive: the first visible feed table on the page."""
        from .kit.feed import FeedTable
        for t in self.findChildren(FeedTable):
            if t.isVisible():
                return t
        return None

    def primary_action(self):
        """Enter: run the page's main action. Return True if something ran."""
        return False

    def handle_key(self, text):
        """Page-specific keys ('[' ']' '+' '-' ' '). Return True if handled."""
        return False

    def on_gate_changed(self):
        """The shell calls this when the engagement / TX state changes."""

    # ---- page-owned status (never the top strip) ----
    def set_chip(self, key, text=None, state=None, ok=None):
        if state is None:
            state = "ok" if ok else "neutral"
        self._last_status[key] = {"text": text, "state": state, "ok": ok}
        if self._host is not None:
            self._host._child_status(self)
        else:
            self._render_status()

    def page_status(self):
        """{key: text} of what this page currently reports (tests + the composite read this)."""
        return {k: v["text"] for k, v in self._last_status.items() if v.get("text")}

    def _render_status(self, status=None):
        if self._status_row is None:
            return
        status = self._last_status if status is None else status
        for key in list(self._status_labels):
            if key not in status:
                self._status_labels.pop(key).deleteLater()
        for key, v in status.items():
            lbl = self._status_labels.get(key)
            if lbl is None:
                lbl = QtWidgets.QLabel("")
                self._status_labels[key] = lbl
                self._status_lay.insertWidget(self._status_lay.count() - 1, lbl)
            lbl.setText(v.get("text") or "")
            lbl.setVisible(bool(v.get("text")))
            cls = _STATE_CLASS.get(v.get("state") or "neutral", "pstat")
            if lbl.property("class") != cls:
                lbl.setProperty("class", cls)
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)

    def attach_topbar(self, topbar):
        """Kept for callers of the old API. Pages no longer write the top strip."""

    def set_active(self, active):
        self._active = active

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
                v = status[k]
                self.set_chip(k, v.get("text"), state=v.get("state"), ok=v.get("ok"))

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
            _retain(self._worker)        # joined; kept so no thread ever GC-deletes a QThread
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

    # ---- standalone wrapper (own top strip without nav keys, since there's no shell) ----
    def standalone(self):
        from .kit import TopBar
        from . import chrome
        win = QtWidgets.QMainWindow()
        win.setWindowTitle("PALISADE — " + self.TITLE)
        central = QtWidgets.QWidget()
        central.setObjectName("root")
        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        tb = TopBar(mode=self.mode)
        v.addWidget(tb)
        v.addWidget(self, 1)
        state = chrome.ChromeState(demo=self.demo, parent=win)

        def _push():
            tb.set_state(state.mode, state.radio(), state.tx(), state.engagement())
        state.changed.connect(_push)
        _push()
        self.set_active(True)
        win.setCentralWidget(central)
        win.resize(1280, 720)

        def _close(ev, _orig=win.closeEvent):
            state.stop()
            self.stop()
            _orig(ev)
        win.closeEvent = _close
        return win


class CompositeApp(PalisadeApp):
    """One page assembled from several existing apps, each contributing one or more sub-tabs.

    PARTS = ((factory, ((tab name, child sub-tab or None), …)), …). Children are built on first
    use (as hub pages always were), keep their own workers and lifecycle untouched, and are told
    they are active only while their tab is the one in front — so a child that releases the radio
    when backgrounded still does."""
    PARTS = ()

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._children = {}            # part index -> child app
        self._tab = None
        self._tabmap = {}              # tab name -> (part index, child sub-tab)
        for i, (_factory, tabs) in enumerate(self.PARTS):
            for name, sub in tabs:
                self._tabmap[name] = (i, sub)
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)
        self.switch_subtab(self.subtabs()[0])

    def subtabs(self):
        return [name for _f, tabs in self.PARTS for name, _sub in tabs]

    def current_subtab(self):
        return self._tab

    def build_body(self):
        self.stack = QtWidgets.QStackedWidget()
        return self.stack

    def child(self, index_or_cls):
        """The child app for a part (by index or class), building it if needed."""
        if not isinstance(index_or_cls, int):
            index_or_cls = [f for f, _t in self.PARTS].index(index_or_cls)
        c = self._children.get(index_or_cls)
        if c is None:
            c = self.PARTS[index_or_cls][0](demo=self.demo, mode=self.mode, embedded=True)
            c._host = self
            c.request.connect(self.request)
            self._children[index_or_cls] = c
            self.stack.addWidget(c)
        return c

    def children_apps(self):
        return list(self._children.values())

    def current_child(self):
        if self._tab is None:
            return None
        return self._children.get(self._tabmap[self._tab][0])

    def switch_subtab(self, name):
        if name not in self._tabmap:
            return
        idx, sub = self._tabmap[name]
        c = self.child(idx)
        self._tab = name
        self.stack.setCurrentWidget(c)
        if sub is not None and c.current_subtab() != sub:
            c.switch_subtab(sub)
        self._push_active()
        self._sync_rail()
        self._render_status(c._last_status)

    def _child_switched(self, child):
        """A child changed its own view (a test, the palette): follow it on the rail."""
        for name, (idx, sub) in self._tabmap.items():
            if self._children.get(idx) is child and sub == child.current_subtab():
                if name != self._tab and child is self.current_child():
                    self._tab = name
                    if self._rail is not None:
                        self._rail.set_current(name)
                return

    def _child_status(self, child):
        if child is self.current_child():
            self._render_status(child._last_status)

    def page_status(self):
        c = self.current_child()
        return c.page_status() if c is not None else {}

    def _push_active(self):
        cur = self.current_child()
        for c in self._children.values():
            c.set_active(bool(self._active and c is cur))

    def set_active(self, active):
        super().set_active(active)
        self._push_active()

    def primary_list(self):
        c = self.current_child()
        return c.primary_list() if c is not None else None

    def primary_action(self):
        c = self.current_child()
        return c.primary_action() if c is not None else False

    def handle_key(self, text):
        c = self.current_child()
        return c.handle_key(text) if c is not None else False

    def on_gate_changed(self):
        for c in self._children.values():
            c.on_gate_changed()

    def stop(self):
        if self._stopped:
            return
        for c in self._children.values():
            c.stop()
        super().stop()
