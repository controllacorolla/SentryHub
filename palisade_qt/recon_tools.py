"""recon_tools.py — the internal-pentest toolkit pages for RECON (TOOLKIT cluster).

New RECON surfaces wired on top of the RX executor path:

  * CAPTURE  — passive packet capture (tcpdump pcap / tshark live view) and Responder in ANALYZE
               mode. All receive-only, so UNGATED by design (CLAUDE.md), but every run is LOGGED to
               the evidence/session chain. These run through PassiveRunPane, NOT the engagement
               executor, because there is no gate to re-check — the same reasoning as the live
               Wi-Fi/BLE scans. Responder POISON (active) sits here too, but behind the engagement
               gate via the shared GatedTool.
  * ENUM     — AD/SMB enumeration (adtools: smbmap / netexec / enum4linux-ng / impacket) and web/TLS
               triage (webtriage: testssl / whatweb / nuclei). Every action is engagement-gated and
               runs through the executor, reusing GatedTool + RunPane.

Layout deliberately self-contained (each page is one QWidget of cards) so the RECON layout pass
(items 11/13, the UI thread) can drop these into the shared tile standard without reshaping them.
GatedTool is imported lazily to avoid a recon.py <-> recon_tools.py import cycle.
"""
import collections
import os
import re
import shutil
import signal
import subprocess
import threading
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .kit import micro, card
from .runpane import RunPane, clean, MAX_LINES, LINE_SHOWN


def _offscreen():
    from .kit.seams import offscreen
    return offscreen()


class PassiveRunPane(QtWidgets.QFrame):
    """Output pane for a PASSIVE, ungated tool (capture / Responder analyze). It spawns the tool in
    its own process group, streams its output, records start/stop to the evidence chain, and offers
    STOP. It mints no ticket and re-checks no gate — passive tools are ungated by design — but it is
    the one place a passive capture is started, so a close / PANIC / app stop can reliably kill it.

    Offscreen (tests / CI) the app's spawner refuses, so nothing is ever spawned."""
    finished = QtCore.Signal(object)

    def __init__(self, title, tok, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self._tok = tok
        self._title = title
        self._proc = None
        self._chain_id = None
        self._label = ""
        self.saved = None
        self._stopped = None
        self._pending = collections.deque(maxlen=MAX_LINES)
        self._reader = None
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
        self.out.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.out.setPlaceholderText("passive tool output appears here")
        lay.addWidget(self.out, 1)
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._check)

    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def _set_state(self, text, colour):
        self.state.setText(text)
        self.state.setStyleSheet("color:%s;" % self._tok[colour])

    def _record(self, event, **fields):
        try:
            import chain as _chain
            ch = _chain.for_id(self._chain_id) if self._chain_id else _chain.current()
            ch.record(event, **fields)
            return ch.id
        except Exception:
            return self._chain_id

    def _reader_body(self, proc):
        try:
            out = proc.stdout
            if out is not None:
                for line in out:
                    self._pending.append(clean(line).rstrip("\r\n")[:LINE_SHOWN])
        except Exception:
            pass

    def run(self, argv, spawner=None, label="", out=None):
        """Start a passive tool. `argv` is already built and validated by the engine. -> (ok, msg).
        Nothing is spawned when the program is not installed, or when the (offscreen) spawner
        refuses."""
        if self.running():
            return False, "a tool is already running here — STOP it first"
        prog = (list(argv) or [""])[0]
        if spawner is None and not shutil.which(prog):
            self._set_state("NOT INSTALLED", "alert")
            self.out.setPlainText("! %s is not installed — nothing was run" % prog)
            return False, "%s is not installed" % prog
        self.out.clear()
        self._pending.clear()
        self.saved = out if out else None
        self._stopped = None
        self._label = label or prog
        self.out.appendPlainText("$ " + " ".join(str(a) for a in argv))
        if out:
            try:
                os.makedirs(os.path.dirname(out), exist_ok=True)
            except OSError:
                pass
        self._chain_id = self._record("passive.start", label=self._label, argv=list(argv),
                                       out=out or "")
        try:
            proc = (spawner or _spawn_passive)(list(argv))
        except OSError as e:
            self._set_state("FAILED TO START", "alert")
            self.out.appendPlainText("! could not start: %s" % e)
            self._record("passive.error", label=self._label, reason=str(e))
            return False, "could not start: %s" % e
        self._proc = proc
        self._reader = threading.Thread(target=self._reader_body, args=(proc,), daemon=True)
        self._reader.start()
        self._set_state("CAPTURING · pid %s" % getattr(proc, "pid", "?"), "warn")
        self.stop_btn.setEnabled(True)
        self._poll.start()
        return True, "running"

    def _drain(self):
        lines = []
        while self._pending:
            lines.append(self._pending.popleft())
        if lines:
            self.out.appendPlainText("\n".join(lines))

    def stop(self, reason="operator STOP"):
        proc = self._proc
        if proc is not None and proc.poll() is None:
            if self._stopped is None:
                self._stopped = reason
            _kill_group(proc)
        self._check()

    def _check(self):
        self._drain()
        proc = self._proc
        if proc is None or proc.poll() is None:
            return
        self._poll.stop()
        self.stop_btn.setEnabled(False)
        code = proc.returncode
        if self._stopped:
            self._set_state("STOPPED (%s) · exit %s" % (self._stopped, code), "muted")
        elif code == 0:
            self._set_state("DONE · exit 0", "muted")
        else:
            self._set_state("ENDED · exit %s" % code, "alert" if code not in (0, None) else "muted")
        tail = (" — stopped: %s" % self._stopped) if self._stopped else ""
        self.out.appendPlainText("[exit %s%s]" % (code, tail))
        if self.saved:
            ok = os.path.isfile(self.saved) and os.path.getsize(self.saved) > 0
            self.out.appendPlainText(("[pcap saved: %s]" % self.saved) if ok else
                                     ("[no packets written: %s]" % self.saved))
            self.saved = self.saved if ok else None
        self._record("passive.exit", label=self._label, exit_code=code, stopped=self._stopped,
                     pcap=self.saved or "")
        done = proc
        self._proc = None
        self.finished.emit(done)


def _spawn_passive(argv):
    """The real passive spawner: a process in its own session (group), output captured."""
    return subprocess.Popen(list(argv), start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)


def _kill_group(proc, grace=1.0):
    """SIGTERM then SIGKILL the passive process's group. Best-effort — a passive capture holds no
    gate, so this is only lifecycle hygiene (close / PANIC / app stop must not leak a tcpdump)."""
    if proc is None or proc.poll() is not None:
        return
    pg = getattr(proc, "pid", None)
    own = isinstance(pg, int) and pg > 1 and pg != os.getpgrp()
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 1.0)):
        try:
            if own:
                os.killpg(pg, sig)
            else:
                proc.send_signal(sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=wait)
            return
        except Exception:
            continue


# ============================ CAPTURE page ============================

def capture_group(app):
    """CAPTURE group (on NET): passive packet capture + Responder analyze. All panes are registered on the
    app (app._tool_panes) so RECON.stop() / PANIC stop them."""
    tok = app._tok
    page = QtWidgets.QWidget()
    pl = QtWidgets.QVBoxLayout(page)
    pl.setContentsMargins(0, 0, 0, 0)
    pl.setSpacing(10)

    # --- packet capture card ---
    c = card(2)
    cl = QtWidgets.QVBoxLayout(c)
    cl.setContentsMargins(12, 10, 12, 10)
    cl.setSpacing(6)
    cl.addWidget(micro("CAPTURE · passive packet capture (tcpdump / tshark) — ungated, logged"))
    row = QtWidgets.QHBoxLayout()
    row.addWidget(micro("IFACE"))
    cap_iface = QtWidgets.QLineEdit(_default_iface())
    cap_iface.setMaximumWidth(120)
    row.addWidget(cap_iface)
    row.addWidget(micro("FILTER"))
    cap_filter = QtWidgets.QLineEdit()
    cap_filter.setPlaceholderText("optional BPF, e.g. port 445 or host 10.0.0.1")
    row.addWidget(cap_filter, 1)
    cl.addLayout(row)
    cap_note = QtWidgets.QLabel("")
    cap_note.setProperty("class", "note")
    cap_note.setWordWrap(True)
    cl.addWidget(cap_note)
    brow = QtWidgets.QHBoxLayout()
    pcap_btn = QtWidgets.QPushButton("PCAP")
    live_btn = QtWidgets.QPushButton("LIVE")
    brow.addWidget(pcap_btn)
    brow.addWidget(live_btn)
    brow.addStretch(1)
    cl.addLayout(brow)
    cap_pane = PassiveRunPane("CAPTURE", tok)
    pl.addWidget(c)
    pl.addWidget(cap_pane, 1)

    def _start_capture(use_tshark):
        import capture
        if cap_pane.running():
            cap_note.setText("a capture is already running — STOP it first")
            return
        iface = cap_iface.text().strip()
        bpf = cap_filter.text().strip()
        if use_tshark:
            argv, err = capture.live_argv(iface, bpf)
            out = None
        else:
            out = _unique(capture.pcap_dir(), "cap-%s" % (iface or "if"), ".pcap")
            argv, err = capture.pcap_argv(iface, out, bpf)
        if err:
            cap_note.setStyleSheet("color:%s;" % tok["muted"])
            cap_note.setText("NOT RUN: %s" % err)
            return
        cap_note.setStyleSheet("color:%s;" % tok["warn"])
        cap_note.setText("capturing on %s%s" % (iface, (" · %s" % bpf) if bpf else ""))
        ok, msg = cap_pane.run(argv, spawner=app._spawner(), label="capture",
                               out=out)
        if not ok:
            cap_note.setStyleSheet("color:%s;" % tok["alert"])
            cap_note.setText("NOT RUN: %s" % msg)

    pcap_btn.clicked.connect(lambda: _start_capture(False))
    live_btn.clicked.connect(lambda: _start_capture(True))

    # --- Responder analyze card (passive) ---
    rc = card(2)
    rl = QtWidgets.QVBoxLayout(rc)
    rl.setContentsMargins(12, 10, 12, 10)
    rl.setSpacing(6)
    rl.addWidget(micro("RESPONDER · ANALYZE (passive) — logs who asks for names, answers nothing"))
    rrow = QtWidgets.QHBoxLayout()
    rrow.addWidget(micro("IFACE"))
    resp_iface = QtWidgets.QLineEdit(_default_iface())
    resp_iface.setMaximumWidth(120)
    rrow.addWidget(resp_iface)
    rrow.addStretch(1)
    analyze_btn = QtWidgets.QPushButton("ANALYZE")
    rrow.addWidget(analyze_btn)
    rl.addLayout(rrow)
    resp_note = QtWidgets.QLabel("Needs root; the installer grants it (Responder rule). Poisoning is "
                                 "on the ENUM tab, behind the engagement gate.")
    resp_note.setProperty("class", "note")
    resp_note.setWordWrap(True)
    rl.addWidget(resp_note)
    resp_pane = PassiveRunPane("RESPONDER", tok)
    pl.addWidget(rc)
    pl.addWidget(resp_pane, 1)

    def _start_analyze():
        import responder
        if resp_pane.running():
            resp_note.setText("Responder is already running — STOP it first")
            return
        argv, err = responder.analyze_argv(resp_iface.text().strip())
        if err:
            resp_note.setStyleSheet("color:%s;" % tok["muted"])
            resp_note.setText("NOT RUN: %s" % err)
            return
        resp_note.setStyleSheet("color:%s;" % tok["warn"])
        resp_note.setText("analyze (passive) on %s" % resp_iface.text().strip())
        ok, msg = resp_pane.run(argv, spawner=app._spawner(), label="responder:analyze")
        if not ok:
            resp_note.setStyleSheet("color:%s;" % tok["alert"])
            resp_note.setText("NOT RUN: %s" % msg)

    analyze_btn.clicked.connect(_start_analyze)

    app._tool_panes += [cap_pane, resp_pane]
    page._panes = [cap_pane, resp_pane]
    return page


# ============================ ENUM page ============================

def enum_group(app):
    """ENUM group (on NET): AD/SMB enumeration + web/TLS triage + Responder poison. Every card is
    engagement-gated (GatedTool + the executor). Panes register on the app for stop()/PANIC."""
    from .recon import GatedTool          # lazy: avoids the recon <-> recon_tools import cycle
    tok = app._tok
    import adtools
    import webtriage
    import responder
    page = QtWidgets.QWidget()
    pl = QtWidgets.QVBoxLayout(page)
    pl.setContentsMargins(0, 0, 0, 0)
    pl.setSpacing(10)

    top = QtWidgets.QHBoxLayout()
    top.setSpacing(10)

    ad_run = RunPane("AD/SMB", tok)
    ad_card = GatedTool("AD / SMB ENUM", "target", adtools.prepare,
                        ["shares", "netexec", "enum", "samr", "rpc"], app, tok,
                        "target host / IP", runner=ad_run)

    web_run = RunPane("WEB/TLS", tok)
    web_scheme = QtWidgets.QComboBox()
    web_scheme.addItems(["https", "http"])
    web_port = QtWidgets.QLineEdit()
    web_port.setPlaceholderText("port (default)")
    web_port.setMaximumWidth(120)

    def _web_extra(action):
        port = web_port.text().strip()
        return {"scheme": web_scheme.currentText(), "port": port or None}, None

    web_card = GatedTool("WEB / TLS TRIAGE", "target", webtriage.prepare,
                         ["whatweb", "testssl", "nuclei"], app, tok,
                         "target host / IP", runner=web_run, extra=_web_extra,
                         fields=[("SCHEME", web_scheme), ("PORT", web_port)])

    top.addWidget(ad_card, 1)
    top.addWidget(web_card, 1)
    pl.addLayout(top)
    pl.addWidget(ad_run, 1)
    pl.addWidget(web_run, 1)

    # Responder POISON — active, gated. Target = the local segment the operator is authorized to
    # poison (in scope). iface comes from the card's field; GatedTool passes it through extra().
    resp_iface = QtWidgets.QLineEdit(_default_iface())
    resp_iface.setMaximumWidth(120)

    def _poison_prepare(action, target, evidence_chain=None, **kw):
        return responder.poison_prepare(kw.get("iface"), target, evidence_chain=evidence_chain)

    def _poison_extra(action):
        return {"iface": resp_iface.text().strip()}, None

    poison_run = RunPane("RESPONDER POISON", tok)
    poison_card = GatedTool("RESPONDER · POISON", "segment", _poison_prepare,
                            ["poison"], app, tok, "authorized segment, e.g. 10.0.0.0/24",
                            runner=poison_run, extra=_poison_extra,
                            fields=[("IFACE", resp_iface)])
    pl.addWidget(poison_card)
    pl.addWidget(poison_run, 1)

    app._gated += [ad_card, web_card, poison_card]
    app._tool_panes += [ad_run, web_run, poison_run]
    page._panes = [ad_run, web_run, poison_run]
    return page


# ============================ helpers ============================

def _default_iface():
    """A sensible default capture interface: the first non-loopback interface that is up, else
    eth0. Never switches anything — just a prefill."""
    base = "/sys/class/net"
    try:
        names = sorted(n for n in os.listdir(base) if n != "lo")
    except OSError:
        return "eth0"
    for n in names:
        try:
            with open(os.path.join(base, n, "operstate")) as fh:
                if fh.read().strip() == "up":
                    return n
        except OSError:
            continue
    return names[0] if names else "eth0"


def _unique(d, stem, ext):
    import uuid
    from .timebase import zulu
    ts = re.sub(r"[^0-9]", "", zulu())[:14] or str(int(time.time()))
    return os.path.join(d, "%s-%s-%s%s" % (stem, ts, uuid.uuid4().hex[:6], ext))
