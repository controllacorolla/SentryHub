"""FORGE — hardware & IO bench (the physical-layer pentest callsign).

Sub-tabs: SERIAL / BUS / RFID / RADIO / SENSORS. Every backend is reused AS-IS — UI + wiring only.

Two gate types, same model as RECON (the engine enforces them, the UI only reflects state):
  * engagement-gated (touch-the-target): canbus TX (`canbus.prepare_send`), proxmark write/clone/sim
    (`proxmark.prepare`), usbhid inject (`usbhid.prepare`), flipper emit, buslab flash/JTAG write —
    all call `engagement.authorize_action(...)` and produce no command without an active, in-scope
    engagement (opened in RECON's ENGAGE tab).
  * txguard-gated (RF TX): replay (`replay.prepare_replay` → `txguard.authorize`) — needs an explicit
    per-burst confirm AND txguard armed/unlocked/band. Shown as a "TX GATED" banner.

Passive read/monitor is always available: canbus monitor, proxmark/flipper reads, rollcode RX
analysis, sensors readout. The SERIAL console is NOT ungated (audit G2): every typed line goes through
flipper.prepare_command (device identified by USB VID:PID — allowlisted Flipper reads pass; any other
line, and any line to an ESP32 / slcan / unknown device, needs an engagement naming the device) and
is written only by the executor, which logs it. No device → an honest "NO DEVICE" standby per tab;
demo is the only synthetic path (flagged). Offscreen/offline seams mean tests never open real
serial/USB/CAN.

Gate state follows the engines (audit G12): cards and the replay banner subscribe to
chrome.gate_signals(); the replay banner shows the engine's own answer for its frequency. A passed
gate yields a single-use executor ticket (audit G11); this UI shows it and never spawns it
(the executor output pane is CL6).
"""
import os
import sys
import threading
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .app import PalisadeApp, _retain
from . import chrome, theme, eventbus
from .kit import ControlBar, FeedTable, DetailCard, micro, card
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SUBTABS = ("SERIAL", "BUS", "RFID", "RADIO", "SENSORS")


def _offscreen():
    return bool(os.environ.get("PALISADE_OFFLINE") or
                os.environ.get("QT_QPA_PLATFORM") == "offscreen")


def _engagement():
    import engagement
    return engagement


def _ticket_text(payload):
    """What a gate produced, for display: a ticket's command + its binding, or plain text."""
    if payload is None:
        return ""
    if hasattr(payload, "display"):
        bind = getattr(payload, "binding", "") or ""
        tail = " · LABEL-ONLY authorization" if bind == "label-only" else ""
        return "%s\n(single-use ticket%s — runs only through the executor)" % (payload.display(), tail)
    if isinstance(payload, (list, tuple)):
        return " ".join(str(x) for x in payload)
    return str(payload)


# ======================= colored console (the multiplexer pane) =======================

class ConsolePane(QtWidgets.QFrame):
    """One device's console: colored scrollback + an optional input line. The 'colored multiplexed
    console' is a tab of these, one per connected device."""

    KIND_TOKEN = {"tx": "accent", "rx": "text", "sys": "muted", "ok": "live", "deny": "warn"}

    def __init__(self, tok, on_input=None, parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
        self._tok = tok
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(600)
        self.view.setStyleSheet("QPlainTextEdit { background:transparent; border:none; }")
        lay.addWidget(self.view, 1)
        if on_input is not None:
            self.input = QtWidgets.QLineEdit()
            self.input.setPlaceholderText("send to device…")
            self.input.returnPressed.connect(lambda: self._send(on_input))
            lay.addWidget(self.input)
        else:
            self.input = None

    def _send(self, on_input):
        text = self.input.text()
        if not text:
            return
        self.append(text, "tx")
        on_input(text)
        self.input.clear()

    def append(self, text, kind="rx"):
        cursor = self.view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QtGui.QColor(self._tok[self.KIND_TOKEN.get(kind, "text")]))
        prefix = {"tx": "⟶ ", "sys": "· ", "ok": "✓ ", "deny": "✗ "}.get(kind, "  ")
        cursor.insertText(prefix + text + "\n", fmt)
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def clear(self):
        self.view.clear()


def _no_device(tok, text):
    """A standby panel for a tab whose device is absent."""
    f = QtWidgets.QFrame()
    f.setProperty("class", "well")
    v = QtWidgets.QVBoxLayout(f)
    v.addStretch(1)
    lbl = QtWidgets.QLabel("NO DEVICE")
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    lbl.setProperty("class", "value")
    lbl.setStyleSheet("color:%s; letter-spacing:2px;" % tok["muted"])
    v.addWidget(lbl)
    hint = QtWidgets.QLabel(text)
    hint.setAlignment(QtCore.Qt.AlignCenter)
    hint.setProperty("class", "note")
    hint.setWordWrap(True)
    v.addWidget(hint)
    v.addStretch(1)
    return f


# ======================= workers (hermetic) =======================

class SerialWorker(Worker):
    """hwlab serial console — DemoSerial in demo, SerialReader live (via a seam). Reuses read_lines
    / write / clean_text AS-IS. No device -> standby; tests never open a real port."""

    def __init__(self, demo=False, port=None, baud=115200, parent=None):
        super().__init__(demo=demo, interval_ms=300, parent=parent)
        self.port, self.baud = port, baud
        self._reader = None
        self.device = ("demo", "demo") if demo else ("unknown", "port:?")
        self._pending = []
        self._lock = threading.Lock()           # guards _pending across GUI/worker threads

    def _open(self):
        import hwlab
        if self.demo:
            return hwlab.DemoSerial()           # pure synthetic ESP32, safe offscreen
        if _offscreen() or not self.port:
            return None
        try:
            return hwlab.SerialReader(self.port, self.baud)
        except Exception:
            return None

    def write(self, text):
        with self._lock:
            self._pending.append(text)

    def step(self):
        import hwlab
        if self._reader is None:
            if self._stop:                      # don't re-open a port while shutting down (leak)
                return
            self._reader = self._open()
            if self._reader is None:
                self.status.emit({"standby": True,
                                  "sdr": {"text": "NO DEVICE — plug a USB-serial adapter", "ok": False}})
                return
            if not self.demo:
                import flipper
                try:
                    self.device = flipper.identify_port(self.port)
                except Exception:
                    self.device = ("unknown", "port:?")
            self.row.emit({"kind": "sys", "line": "connected %s (%s %s)" % (
                self.port or "demo ESP32", self.device[1], self.device[0])})
            if not self.demo:
                eventbus.bus.publish(eventbus.decode("FORGE", "SERIAL", self.port or "demo",
                                                     "serial device connected"))
        with self._lock:                        # atomic drain -> no lost keystroke on the swap
            pending, self._pending = self._pending, []
        for text in pending:                    # every line through the one serial gate (G2)
            try:
                ok, why = hwlab.gated_send(self._reader, text, self.device, port_name=self.port or "demo")
            except Exception as e:
                ok, why = False, "NOT SENT — %s" % e
            if not ok:
                self.row.emit({"kind": "deny", "line": why})
        try:
            for line in self._reader.read_lines():
                self.row.emit({"kind": "rx", "line": hwlab.clean_text(line)})
        except Exception:
            pass

    def run(self):
        try:
            super().run()
        finally:                                # close the reader on the WORKER thread, after the
            self._close_reader()                # loop has exited — no stop()/step() reopen race

    def stop(self):
        super().stop()                          # set _stop; the run() finally closes the reader
        if not self.isRunning():                # direct-step tests (no run loop) still clean up
            self._close_reader()

    def _close_reader(self):
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None


class CanWorker(Worker):
    """canbus monitor — candump stream parsed + decoded AS-IS (parse_candump/decode). Demo uses
    canbus.Demo(); live needs SocketCAN (device-only) -> standby here. Receive-only."""

    def __init__(self, demo=False, iface="can0", parent=None):
        super().__init__(demo=demo, interval_ms=500, parent=parent)
        self.iface = iface
        self._demo = None
        self._bus = None

    def step(self):
        import canbus
        if self._bus is None:
            self._bus = canbus.Bus()
        if not self.demo:
            up = False if _offscreen() else bool(canbus.detect())
            self.status.emit({"standby": True, "sdr": {
                "text": ("CAN NOT IMPLEMENTED — SocketCAN is up; live candump is not wired here"
                         if up else "NO DEVICE — bring up SocketCAN (can0)"), "ok": False}})
            self._stop = True                    # E4: say so once; nothing to poll
            return
        if self._demo is None:
            self._demo = canbus.Demo()
        for _ in range(3):
            frame = canbus.parse_candump(self._demo.line())
            if not frame:
                continue
            self._bus.add(frame) if hasattr(self._bus, "add") else None
            dec = canbus.decode(frame)
            self.row.emit({"frame": frame, "decode": dec, "demo": True})


class SensorWorker(Worker):
    """sensors readout — rtl_433 ISM decode (parse_report) AS-IS. Demo uses demo_report(); live
    needs rtl_433 + the SDR (device-only) -> standby. Receive-only."""

    def __init__(self, demo=False, parent=None):
        super().__init__(demo=demo, interval_ms=1500, parent=parent)
        self._t0 = time.time()

    def step(self):
        import sensors
        if not self.demo:
            import shutil
            have = False if _offscreen() else bool(shutil.which("rtl_433"))
            self.status.emit({"standby": True, "sdr": {
                "text": ("SENSORS NOT IMPLEMENTED — rtl_433 is installed; live decode is not "
                         "wired here" if have else "NO DEVICE — rtl_433 not installed"),
                "ok": False}})
            self._stop = True                    # E4: say so once; nothing to poll
            return
        rep = sensors.parse_report(sensors.demo_report(self._t0))
        if rep:
            key, title, data = rep
            self.row.emit({"key": key, "title": title, "reading": sensors.primary_reading(data),
                           "data": data, "demo": True})


# ======================= gate cards =======================

class _GateCardBase(QtWidgets.QFrame):
    """Shared chrome for a gated action: a title, a status line reflecting the gate, and a result
    line. Subclasses add inputs + an action that calls the engine's prepare() AS-IS."""

    def __init__(self, title, app, tok, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self._app = app
        self._tok = tok
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(12, 10, 12, 10)
        self.lay.setSpacing(6)
        self.lay.addWidget(micro(title))
        self.state = QtWidgets.QLabel("")
        self.state.setWordWrap(True)
        self.lay.addWidget(self.state)
        self._controls = []

    def _add(self, w):
        self.lay.addWidget(w)
        self._controls.append(w)
        return w

    def _result_label(self):
        self.result = QtWidgets.QLabel("")
        self.result.setProperty("class", "note")
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.lay.addWidget(self.result)

    def _show_result(self, ok, reason, payload=None):
        # AUTHORIZED is a hazard state, not a healthy one: amber, never green (D9)
        self.result.setStyleSheet("color:%s;" % (self._tok["warn"] if ok else self._tok["muted"]))
        if ok:
            tail = ("\n$ %s" % _ticket_text(payload)) if payload else ""
            self.result.setText("AUTHORIZED: %s%s" % (reason, tail))
            self._app.on_authorized(reason)
        else:
            self.result.setText("DENIED: %s" % reason)


class EngagementCard(_GateCardBase):
    """A card whose action is gated by engagement.authorize_action (via the tool's own prepare()).
    Locked with 'REQUIRES ENGAGEMENT' when no engagement is active."""

    def __init__(self, title, app, tok, fields, run_label, run_fn, parent=None):
        super().__init__(title, app, tok, parent)
        self._run_fn = run_fn
        self._inputs = {}
        for key, hint in fields:
            e = QtWidgets.QLineEdit()
            e.setPlaceholderText(hint)
            self._add(e)
            self._inputs[key] = e
        self._btn = QtWidgets.QPushButton(run_label)
        self._btn.clicked.connect(self._run)
        self._add(self._btn)
        self._result_label()
        chrome.gate_signals().changed.connect(self.refresh)      # follows the engine (G12)
        self.refresh()

    def values(self):
        return {k: e.text().strip() for k, e in self._inputs.items()}

    def refresh(self):
        eng = _engagement()
        active = eng.is_active()
        self._btn.setEnabled(active)
        for e in self._inputs.values():
            e.setEnabled(active)
        if active:
            self.state.setStyleSheet("color:%s;" % self._tok["warn"])     # amber: armed, not healthy
            self.state.setText("◆ engagement active — actions authorized against the scope")
        elif eng.expired():
            self.state.setStyleSheet("color:%s;" % self._tok["alert"])
            self.state.setText("▲ engagement EXPIRED — END it and open a new one (E)")
            self.result.setText("")
        else:
            self.state.setStyleSheet("color:%s;" % self._tok["muted"])
            self.state.setText("○ REQUIRES ENGAGEMENT — open ENGAGEMENT in the top strip (E)")
            self.result.setText("")

    def _run(self):
        ok, reason, payload = self._run_fn(self.values(), self._app.evidence)
        self._show_result(ok, reason, payload)


class ReplayTxCard(_GateCardBase):
    """Signal replay — RF TX gated by txguard (via replay.prepare_replay). Needs an explicit
    per-burst confirm AND the txguard chain. The banner is the ENGINE's answer for this frequency
    with the saved replay settings (never a separate reading of arm / unlock), so it cannot claim
    "armed + unlocked" while the engine says DENIED (G12). A passing gate yields a ticket, shown,
    never executed here."""

    def __init__(self, app, tok, parent=None):
        super().__init__("REPLAY · RF TX — txguard-gated", app, tok)
        self.freq = QtWidgets.QDoubleSpinBox()
        self.freq.setRange(1.0, 6000.0)
        self.freq.setValue(915.0)
        self.freq.setSuffix(" MHz")
        self.freq.setDecimals(3)
        self.freq.valueChanged.connect(lambda _v: self.refresh())
        self._add(self.freq)
        self.confirm = QtWidgets.QCheckBox("I confirm this single authorized burst")
        self._add(self.confirm)
        self._btn = QtWidgets.QPushButton("AUTHORIZE REPLAY")
        self._btn.clicked.connect(self._run)
        self._add(self._btn)
        self._result_label()
        chrome.gate_signals().changed.connect(self.refresh)
        self.refresh()

    def _saved(self):
        """The saved replay settings (fail closed: tx_enabled defaults to False)."""
        try:
            import suite
            s, _p = suite.settings("replay", {"tx_enabled": False, "tx_gain": 0, "tx_region": "US"})
            return s
        except Exception:
            return {"tx_enabled": False}

    def refresh(self):
        import txguard
        ok, why, _p = txguard.authorize("replay", int(self.freq.value() * 1e6),
                                        settings=self._saved(), sample_rate=2_000_000)
        if ok:
            self.state.setStyleSheet("color:%s;" % self._tok["alert"])    # red: armed, never green
            self.state.setText("■ TX armed + unlocked — replay PERMITTED at %.3f MHz (per-burst "
                               "confirm still required)" % self.freq.value())
        else:
            self.state.setStyleSheet("color:%s;" % self._tok["muted"])
            self.state.setText("○ TX GATED — DENIED: %s" % why)

    def _run(self):
        import replay
        ok, reason, ticket = replay.prepare_replay(
            "capture.iq", int(self.freq.value() * 1e6), 2_000_000, self.confirm.isChecked(),
            settings=self._saved())
        self._show_result(ok, reason, ticket)
        self.refresh()


# ======================= the app =======================

class ForgeApp(PalisadeApp):
    TITLE = "FORGE"
    LEASE = None            # serial/I2C/CAN/USB bench — never holds the SDR
    SUBTABS = SUBTABS

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._subtab = "SERIAL"
        self._cards = []
        self.evidence = None      # CL3: the ONE chain lives with the engagement (engagement.chain_states)
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    def current_subtab(self):
        return self._subtab

    def switch_subtab(self, name):
        self._switch(name)

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.lines_lbl = QtWidgets.QLabel("")       # placed on the SERIAL bar by _serial_page
        self.lines_lbl.setProperty("class", "note")

        self.stack = QtWidgets.QStackedWidget()
        self._pages = {"SERIAL": self._serial_page(), "BUS": self._bus_page(),
                       "RFID": self._rfid_page(), "RADIO": self._radio_page(),
                       "SENSORS": self._sensors_page()}
        for t in SUBTABS:
            self.stack.addWidget(self._pages[t])
        lay.addWidget(self.stack, 1)
        self._line_count = 0
        self._sync_tabs()
        return body

    # ---- SERIAL: the multiplexed console ----
    def _serial_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        bar = ControlBar()
        self.ser_port = QtWidgets.QComboBox()
        self.ser_port.addItems(self._serial_ports())
        bar.add_field("port", self.ser_port, "Port")
        self.ser_baud = QtWidgets.QComboBox()
        self.ser_baud.addItems(["115200", "9600", "57600", "250000"])
        bar.add_field("baud", self.ser_baud, "Baud")
        bar.add_stretch()
        bar.lay.addWidget(self.lines_lbl)
        bar.lay.addWidget(micro("console multiplexer"))
        pl.addWidget(bar)
        # the colored multiplexed console: a tab per connected device
        self.console_mux = QtWidgets.QTabWidget()
        self.serial_console = ConsolePane(self._tok, on_input=self._serial_send)
        self.console_mux.addTab(self.serial_console, "serial")
        pl.addWidget(self.console_mux, 1)
        return page

    def _serial_ports(self):
        try:
            import hwlab
            ports = [p for p, _ in hwlab.list_serial_ports()]
            if ports:
                return ports
        except Exception:
            pass
        return ["demo"]

    def _serial_send(self, text):
        w = getattr(self, "_serial_worker", None)
        if w is not None:
            w.write(text)

    # ---- BUS: CAN monitor + gated TX ----
    def _bus_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(micro("CANBUS · monitor (passive) · OBD/UDS decoded"))
        self.can_console = ConsolePane(self._tok)
        left.addWidget(self.can_console, 1)
        split.addLayout(left, 3)
        import canbus
        can_tx = EngagementCard(
            "CANBUS TX / inject", self, self._tok,
            [("id", "arbitration ID (hex, e.g. 7DF)"), ("data", "data bytes (hex)"),
             ("target", "interface in scope (can0 — scope can0:0x700-0x7FF)")], "SEND FRAME",
            lambda v, ev: self._can_send(canbus, v, ev))
        self._cards.append(can_tx)
        split.addWidget(can_tx, 2)
        pl.addLayout(split, 1)
        return page

    def _can_send(self, canbus, v, ev):
        try:
            can_id = int(v.get("id", ""), 16)
            data = bytes.fromhex(v.get("data", "").replace(" ", ""))
        except ValueError:
            return False, "id/data must be hex", None
        # prepare_send binds the scope to interface + arbitration ID (G5) and returns a ticket
        return canbus.prepare_send(v.get("target", "") or "can0", can_id, data, evidence_chain=ev)

    # ---- RFID: proxmark read + gated write ----
    def _rfid_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(micro("PROXMARK3 · reads (passive) + gated clone/write/sim"))
        self.rfid_console = ConsolePane(self._tok)
        left.addWidget(self.rfid_console, 1)
        import proxmark
        reads = QtWidgets.QHBoxLayout()
        for op in [o for o, v in proxmark.OPS.items() if not v[0]][:4]:
            b = QtWidgets.QPushButton(op)
            b.clicked.connect(lambda _=False, o=op: self._pm_read(proxmark, o))
            reads.addWidget(b)
        reads.addStretch(1)
        left.addLayout(reads)
        split.addLayout(left, 3)
        # active ops with no template {param} work from the single op field; parameterised ops
        # (clone/write/sim needing an id/uid/block) are device-only and fail-closed as 'missing
        # parameter' until a per-op param UI is added.
        noparam = [o for o, v in proxmark.OPS.items() if v[0] and "{" not in v[1]]
        pm_write = EngagementCard(
            "PROXMARK write / clone / sim", self, self._tok,
            [("op", "active op: %s" % " / ".join(noparam)),
             ("target", "card UID in scope (uid:04A22B3C)")],
            "AUTHORIZE", lambda v, ev: self._pm_write(proxmark, v, ev))
        self._cards.append(pm_write)
        split.addWidget(pm_write, 2)
        pl.addLayout(split, 1)
        return page

    def _pm_read(self, proxmark, op):
        self.rfid_console.append("pm3 → %s" % proxmark.pm3_command(op), "tx")
        if self.demo:
            self.rfid_console.append("[+] UID 04 A2 2B 3C  SAK 08  (demo)", "rx")
        elif _offscreen() or not proxmark.detect():
            self.rfid_console.append("NO DEVICE — attach a Proxmark3", "sys")
        else:
            self.rfid_console.append("(reading… device-only)", "sys")
            eventbus.bus.publish(eventbus.decode("FORGE", "RFID", op, "proxmark read"))

    def _pm_write(self, proxmark, v, ev):
        op = v.get("op", "")
        ok, reason, ticket = proxmark.prepare(op, v.get("target", ""), evidence_chain=ev,
                                              read_uid=self._read_uid)
        return ok, reason, ticket

    def _read_uid(self):
        """Read back the card on the antenna before an active op (G5). Demo: the synthetic card.
        Live: no read-back path is wired in this UI yet (executor pane is CL6) -> None -> refused."""
        return "04A22B3C" if self.demo else None

    # ---- RADIO: rollcode (RX) + replay (txguard) + usbhid (engagement) ----
    def _radio_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)
        self.replay_card = ReplayTxCard(self, self._tok)
        self._cards.append(self.replay_card)
        top.addWidget(self.replay_card, 1)
        import usbhid
        hid = EngagementCard(
            "USB-HID inject (BadUSB)", self, self._tok,
            [("target", "target HOST in scope")], "AUTHORIZE INJECT",
            lambda v, ev: self._hid(usbhid, v, ev))
        self._cards.append(hid)
        top.addWidget(hid, 1)
        pl.addLayout(top)
        # rollcode RX analyzer (passive)
        c = card(2)
        cl = QtWidgets.QVBoxLayout(c)
        cl.addWidget(micro("ROLLCODE · keyfob RX analysis (no TX, no key recovery)"))
        self.roll_note = QtWidgets.QLabel("Load several captured presses of one remote to classify "
                                          "FIXED vs ROLLING and flag replay risk. Analysis only — "
                                          "standby until captures are loaded on-device.")
        self.roll_note.setProperty("class", "note")
        self.roll_note.setWordWrap(True)
        cl.addWidget(self.roll_note)
        pl.addWidget(c)
        pl.addStretch(1)
        return page

    def _hid(self, usbhid, v, ev):
        ok, reason, ticket = usbhid.prepare(usbhid.DEMO_PAYLOAD, v.get("target", ""),
                                            evidence_chain=ev)
        detail = ("%d HID reports · LABEL-ONLY authorization · single-use ticket"
                  % (len(ticket.payload) // 8)) if ok and ticket else None
        return ok, reason, detail

    # ---- SENSORS ----
    def _sensors_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        self.sensor_feed = FeedTable([("title", "DEVICE"), ("reading", "READING"),
                                      ("age", "AGE")])
        split.addWidget(self.sensor_feed, 3)
        self.sensor_detail = DetailCard("SENSOR")
        self.sensor_detail.set_hero("—", "no reports")
        split.addWidget(self.sensor_detail, 2)
        pl.addLayout(split, 1)
        return page

    # ---- gate reflection ----
    def refresh_gates(self):
        for c in self._cards:
            c.refresh()

    def on_authorized(self, reason):
        eventbus.bus.publish(eventbus.alert("FORGE", "authorized: %s" % reason, severity="warn"))

    # ---- sub-tab switching ----
    def _switch(self, tab):
        self._subtab = tab
        self.stack.setCurrentWidget(self._pages[tab])
        self._sync_tabs()
        self.refresh_gates()

    def _sync_tabs(self):
        self._sync_rail()

    # ---- lifecycle ----
    def start(self):
        if self._started:
            return
        super().start()
        self._workers = []
        self._serial_worker = self._spawn(SerialWorker(demo=self.demo,
                                                       port=None if self.demo else
                                                       self.ser_port.currentText()), self._on_serial)
        self._workers.append(self._serial_worker)
        self._workers.append(self._spawn(CanWorker(demo=self.demo), self._on_can))
        self._workers.append(self._spawn(SensorWorker(demo=self.demo), self._on_sensor))
        self.refresh_gates()

    def _spawn(self, worker, on_row):
        worker.row.connect(on_row)
        worker.status.connect(self.on_status)
        worker.error.connect(self.on_error)
        worker.start()
        return worker

    def stop(self):
        if self._stopped:
            return
        for w in getattr(self, "_workers", []):
            w.stop()
            w.quit()
            w.wait(3000)
            _retain(w)
        self._workers = []
        super().stop()

    def on_status(self, status):
        super().on_status(status)
        if status.get("standby"):
            self.header.set_chip("sdr", status.get("sdr", {}).get("text", "NO DEVICE"),
                                 state="neutral")

    # ---- worker outputs ----
    def _on_serial(self, msg):
        self.serial_console.append(msg["line"], msg.get("kind", "rx"))
        self._line_count += 1
        self.lines_lbl.setText("%d lines" % self._line_count)

    def _on_can(self, msg):
        frame, dec = msg["frame"], msg.get("decode") or {}
        fid = frame.get("id")
        label = dec.get("name") or dec.get("service") or "frame"
        data = frame.get("data", b"")
        hexd = data.hex(" ") if isinstance(data, (bytes, bytearray)) else str(data)
        kind = "ok" if dec.get("name") else ("deny" if dec.get("writes") else "rx")
        self.can_console.append("%03X  %-18s %s" % (fid or 0, label, hexd), kind)
        if not msg.get("demo"):
            eventbus.bus.publish(eventbus.decode("FORGE", "CAN", "%03X" % (fid or 0), label))

    def _on_sensor(self, msg):
        rows = [{"title": msg["title"], "reading": msg["reading"], "age": "now"}]
        self.sensor_feed.model.set_rows(rows)
        self.sensor_detail.set_hero(msg["reading"], msg["title"])
        self.sensor_detail.set_rows([(k.upper(), str(v)) for k, v in
                                     list(msg.get("data", {}).items())[:6]])
        if not msg.get("demo"):
            eventbus.bus.publish(eventbus.decode("FORGE", "SENSOR", msg["key"], msg["reading"]))
