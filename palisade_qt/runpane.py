"""RunPane — the output pane for a gated RECON tool (cluster RX: RECON NET + Wi-Fi execution).

A gate (netpent.prepare / wifipent.prepare -> engagement.issue) hands RECON a single-use executor
ticket. This pane is the only RECON code that turns that ticket into a process, and it does so
ONLY through executor.start(): the executor redeems the ticket (single use, unexpired, argv hash
equal), RE-RUNS THE ENGAGEMENT GATE at spawn, spawns the tool in its own process group, records
`spawn` (pid + process start time, for the N16 orphan rule) and `exit` (the real exit code) in the
chain the ticket was issued under, and kills the group when the gate stops passing (END, expiry,
scope change) or on PANIC (executor.kill_all). The pane adds no gate and decides nothing: it shows
the tool's output and exit, and offers STOP (which is executor Handle.stop, recorded as a kill).

Output arrives on the executor's reader thread; it is handed to the GUI thread through a Qt signal
(queued), so no widget is touched off the GUI thread.
"""
import collections
import re
import shutil

from PySide6 import QtCore, QtGui, QtWidgets

from .kit import micro

MAX_LINES = 2000
LINE_SHOWN = 1000                  # characters of one output line the pane shows
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-Z\\-_]|[\x00-\x08\x0b-\x1f\x7f]")


def clean(line):
    """Terminal escapes / control characters out (airodump-ng redraws its screen with them)."""
    return _ANSI.sub("", str(line))


class RunPane(QtWidgets.QFrame):
    finished = QtCore.Signal(object)    # the Handle, once its exit is recorded

    def __init__(self, title, tok, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self._tok = tok
        self._handle = None
        self.saved = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(micro("%s · output" % title))
        top.addStretch(1)
        self.state = QtWidgets.QLabel("IDLE — nothing running")
        self.state.setProperty("class", "note")
        top.addWidget(self.state)
        self.stop_btn = QtWidgets.QPushButton("STOP")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(lambda: self.stop("operator STOP"))
        top.addWidget(self.stop_btn)
        lay.addLayout(top)
        self.out = QtWidgets.QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumBlockCount(MAX_LINES)
        self.out.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.out.setFont(f)
        self.out.setPlaceholderText("authorized tool output appears here")
        lay.addWidget(self.out, 1)
        # RA-RX M1: the reader thread only queues lines (bounded); the GUI drains them in batches on
        # the poll timer, so a flood of output never floods the event loop
        self._pending = collections.deque(maxlen=MAX_LINES)
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._check)

    # ---- state ----
    def running(self):
        return self._handle is not None and self._handle.running()

    def handle(self):
        return self._handle

    def _set_state(self, text, colour):
        self.state.setText(text)
        self.state.setStyleSheet("color:%s;" % self._tok[colour])

    def _append(self, text):
        self.out.appendPlainText(text)

    def _on_line(self, line):              # executor reader thread: never touch widgets here
        self._pending.append(clean(line)[:LINE_SHOWN])

    def _drain(self):
        lines = []
        while self._pending:
            lines.append(self._pending.popleft())
        if lines:
            self._append("\n".join(lines))

    # ---- run ----
    def run(self, ticket, spawner=None):
        """Start the ticket's process through the executor. -> (ok, message). Nothing is spawned
        when the program is not installed (checked before the ticket is redeemed, so the trail
        shows an unused ticket, not a phantom spawn), or when the executor refuses the ticket."""
        import executor
        if self.running():
            return False, "a tool is already running here — STOP it first"
        prog = (ticket.argv or ("",))[0]
        if spawner is None and not shutil.which(prog):
            self._set_state("NOT INSTALLED", "alert")
            self._append("! %s is not installed — nothing was run" % prog)
            return False, "%s is not installed" % prog
        self.out.clear()
        self._pending.clear()
        self.saved = None
        self._append("$ " + ticket.display())
        try:
            h = executor.start(ticket, spawner=spawner, on_line=self._on_line)
        except executor.TicketRefused as e:
            self._set_state("REFUSED", "alert")
            self._append("! refused by the executor: %s" % e)
            return False, "refused: %s" % e
        except OSError as e:
            self._set_state("FAILED TO START", "alert")
            self._append("! could not start: %s" % e)
            return False, "could not start: %s" % e
        self._handle = h
        self._set_state("RUNNING · pid %s" % getattr(h.proc, "pid", "?"), "warn")
        self.stop_btn.setEnabled(True)
        self._poll.start()
        return True, "running"

    def stop(self, reason="operator STOP"):
        h = self._handle
        if h is not None and h.running():
            h.stop(reason)
        self._check()

    @staticmethod
    def _scanned_nothing(h):
        return h.exit_code == 0 and any("No targets were specified" in ln for ln in h.lines[-50:])

    def _check(self):
        self._drain()
        h = self._handle
        if h is None or h.running():
            return
        self._poll.stop()
        self.stop_btn.setEnabled(False)
        code = h.exit_code
        if h.stopped:
            self._set_state("STOPPED (%s) · exit %s" % (h.stopped, code), "muted")
        elif code == 0 and self._scanned_nothing(h):
            # nmap exits 0 when it scanned nothing (no route, unresolvable target): never "DONE"
            self._set_state("NOTHING SCANNED · exit 0", "alert")
        elif code == 0:
            self._set_state("DONE · exit 0", "muted")
        else:
            self._set_state("FAILED · exit %s" % code, "alert")
        self._append("[exit %s%s]" % (code, (" — stopped: %s" % h.stopped) if h.stopped else ""))
        argv = list(getattr(h, "argv", ()) or ())
        if "-oN" in argv[:-1]:                # RX-fix2: where the results were kept, honestly
            import os
            path = argv[argv.index("-oN") + 1]
            if self._scanned_nothing(h):         # RA-RXc N6: a header-only file is no result
                self.saved = None
                self._append("[nothing scanned — no results in %s]" % path)
            else:
                self.saved = path if os.path.isfile(path) else None
                self._append("[results saved: %s]" % path if self.saved else
                             "[results file NOT written: %s]" % path)
        self.finished.emit(h)
