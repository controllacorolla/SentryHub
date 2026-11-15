"""Shell overlays: RADIOS, ENGAGEMENT, the alerts drawer, the key map, the command palette, and the
DEMO border. They belong to the shell (global state lives in chrome, not buried in a page sub-tab —
D7) and float over the page area; Esc closes the top one.

Moved here mechanically, behaviour unchanged:
  * RADIOS  <- OVERWATCH's RADIO sub-view (holder card, FREE THE RADIO, acquire/release history)
  * ENGAGEMENT <- RECON's ENGAGE sub-tab (operator / scope form, activate / end, action trail)

CL2 (gates): the TX panel is the missing ARM / UNLOCK control (audit G8) — it calls txguard's own
arm() / unlock_session(); every gate decision stays in the engine. The ENGAGEMENT panel's operator
comes from the operator profile (read-only) and the authorization reference is never pre-filled
(audit G13). Both panels follow the engines through chrome.gate_signals() (audit G12).
"""
import time

from PySide6 import QtCore, QtGui, QtWidgets

from . import chrome, eventbus, radio_arbiter, radios, theme
from .kit import FeedTable, DetailCard, micro
from .kit.components import note


# ======================= overlay base =======================

class Overlay(QtWidgets.QFrame):
    """A panel floating over the hub's page area. Parent must be the hub's central widget."""
    closed = QtCore.Signal()
    TITLE = ""
    SIZE = (760, 520)

    def __init__(self, mode="dark", parent=None):
        super().__init__(parent)
        self.setProperty("class", "overlay")
        self._tok = theme.tokens(mode)
        self.setStyleSheet(theme.qss(mode))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.outer = QtWidgets.QVBoxLayout(self)
        self.outer.setContentsMargins(14, 10, 14, 12)
        self.outer.setSpacing(8)
        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(self.TITLE)
        title.setProperty("class", "value")
        head.addWidget(title)
        head.addStretch(1)
        esc = QtWidgets.QLabel("ESC")
        esc.setProperty("class", "keycap")
        head.addWidget(esc)
        head.addWidget(note("close"))
        self.outer.addLayout(head)
        self.hide()

    def place(self):
        par = self.parentWidget()
        if par is None:
            return
        w = min(self.SIZE[0], par.width() - 24)
        h = min(self.SIZE[1], par.height() - 56)
        self.setGeometry((par.width() - w) // 2, 48 + max(0, (par.height() - 56 - h) // 2), w, h)

    def open(self):
        self.place()
        self.refresh()
        self.show()
        self.raise_()
        self.focus_first()

    def close_overlay(self):
        if self.isVisible():
            self.hide()
            self.closed.emit()

    def refresh(self):
        pass

    def focus_first(self):
        self.setFocus()


# ======================= RADIOS =======================

class RadiosPanel(Overlay):
    """Every radio the device has: present / absent, power, and who holds the single arbitrated
    SDR — plus the manual hand-over and the acquire/release history that used to be OVERWATCH's
    RADIO sub-view. Read-only apart from FREE THE RADIO, which is the arbiter's existing release."""
    TITLE = "RADIOS"
    SIZE = (900, 560)

    def __init__(self, mode="dark", parent=None, sys_root="/sys"):
        super().__init__(mode, parent)
        self._sys_root = sys_root
        self._history = []
        self.table = FeedTable([("radio", "RADIO"), ("present", "PRESENT"),
                                ("power", "POWER"), ("owner", "OWNER")])
        self.outer.addWidget(self.table, 3)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        left = QtWidgets.QVBoxLayout()
        self.holder = DetailCard("RADIO DIRECTOR · single-SDR owner")
        self.holder.set_hero("—", "radio free")
        left.addWidget(self.holder, 1)
        self.takeover_btn = QtWidgets.QPushButton("FREE THE RADIO (release holder)")
        self.takeover_btn.clicked.connect(self._free_radio)
        left.addWidget(self.takeover_btn)
        pick = QtWidgets.QHBoxLayout()
        pick.addWidget(micro("Device"))
        self.device_pick = QtWidgets.QComboBox()
        self.device_pick.setEnabled(False)
        self.device_pick.setToolTip("Device selection and radio power control are not implemented "
                                    "yet (audit section 9 / CL6); this lists what is present.")
        pick.addWidget(self.device_pick, 1)
        left.addLayout(pick)
        row.addLayout(left, 2)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(micro("Acquire / release history"))
        self.hist_feed = FeedTable([("t", "TIME"), ("event", "EVENT"), ("owner", "LAYER")])
        right.addWidget(self.hist_feed, 1)
        row.addLayout(right, 3)
        self.outer.addLayout(row, 4)
        self.limit = note("Read-only view: presence and power come from the kernel (USB IDs, rfkill). "
                          "Power on/off and device selection arrive with CL6.")
        self.outer.addWidget(self.limit)
        radio_arbiter.arbiter.changed.connect(self._on_arbiter_change)
        # re-read the kernel while the panel is open: a dongle unplugged or an rfkill switch
        # flipped must show without closing and reopening (RA-CL1 N1). Stops when hidden.
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(self.REFRESH_MS)
        self._poll.timeout.connect(self._refresh_holder)

    REFRESH_MS = 2000

    def showEvent(self, ev):
        super().showEvent(ev)
        self._poll.start()

    def hideEvent(self, ev):
        if getattr(self, "_poll", None) is not None:      # the base hides before __init__ ends
            self._poll.stop()
        super().hideEvent(ev)

    def stop(self):
        self._poll.stop()
        try:
            radio_arbiter.arbiter.changed.disconnect(self._on_arbiter_change)
        except (TypeError, RuntimeError):
            pass

    # ---- moved from OverwatchApp, unchanged ----
    def _on_arbiter_change(self, owner):
        now = time.strftime("%H:%M:%S")
        if owner:
            lbl = radio_arbiter.OWNER_LABELS.get(owner, owner)
            self._history.insert(0, {"t": now, "event": "ACQUIRE", "owner": lbl})
        else:
            self._history.insert(0, {"t": now, "event": "RELEASE", "owner": "—"})
        self._history = self._history[:200]
        self.hist_feed.model.set_rows(self._history)
        self._refresh_holder()

    def _refresh_holder(self):
        try:
            owner = radio_arbiter.arbiter.owner()
        except Exception as e:
            # never fall back to FREE: an unreadable arbiter is UNKNOWN (amber word + its own shape)
            self.holder.set_hero("◌ UNKNOWN", "the radio arbiter could not be read")
            self.holder.hero.setStyleSheet("color:%s;" % self._tok["warn"])
            self.holder.set_rows([("STATE", "UNKNOWN — %s" % e)])
            self.takeover_btn.setEnabled(False)
            self._refresh_table()
            return
        self.holder.hero.setStyleSheet("")
        if owner:
            self.holder.set_hero(radio_arbiter.owner_label() or owner, "holds the single SDR")
            self.holder.set_rows([("LEASE", owner), ("STATE", "BUSY — one owner at a time")])
            self.takeover_btn.setEnabled(True)
        else:
            self.holder.set_hero("—", "radio free")
            self.holder.set_rows([("STATE", "FREE — any layer may acquire")])
            self.takeover_btn.setEnabled(False)
        self._refresh_table()

    def _free_radio(self):
        owner = radio_arbiter.arbiter.owner()
        if owner:
            radio_arbiter.arbiter.release(owner)      # free the dongle; the next layer acquires it
        self._refresh_holder()

    # ---- inventory ----
    def _refresh_table(self):
        try:
            rows = radios.inventory(owner_label=radio_arbiter.owner_label(), sys_root=self._sys_root)
        except Exception as e:
            warn = self._tok["warn"]
            rows = [{"radio": "◌ UNKNOWN", "present": "UNKNOWN", "power": "UNKNOWN",
                     "owner": "cannot read: %s" % e,
                     "_colors": {"radio": warn, "present": warn, "power": warn}}]
        self.table.model.set_rows(rows)
        self.device_pick.clear()
        present = [r["radio"] for r in rows if r["present"] == "PRESENT"]
        self.device_pick.addItems(present or ["no radio detected"])

    def refresh(self):
        self._refresh_holder()

    def focus_first(self):
        (self.takeover_btn if self.takeover_btn.isEnabled() else self.table.view).setFocus()


# ======================= TX (arm / unlock) =======================

class TxPanel(Overlay):
    """The master kill switch and the per-session unlock (audit G8). Arming only makes TX possible;
    a key-up still needs the unlock, the saved tx_enabled setting, the band and (for pentest tools)
    an engagement — all decided by txguard / engagement, never here."""
    TITLE = "TX — kill switch + session unlock"
    SIZE = (760, 400)

    def __init__(self, mode="dark", parent=None):
        super().__init__(mode, parent)
        self.state = DetailCard("TRANSMIT")
        self.outer.addWidget(self.state, 1)
        row = QtWidgets.QHBoxLayout()
        self.arm_btn = QtWidgets.QPushButton("ARM")
        self.arm_btn.clicked.connect(self._toggle_arm)
        row.addWidget(self.arm_btn)
        self.unlock_btn = QtWidgets.QPushButton("UNLOCK THIS SESSION")
        self.unlock_btn.clicked.connect(self._toggle_unlock)
        row.addWidget(self.unlock_btn)
        row.addStretch(1)
        self.outer.addLayout(row)
        self.outer.addWidget(note("Unlock lasts until disarm, PANIC or exit and is never saved. "
                                  "Disarming kills every running gated process."))
        chrome.gate_signals().changed.connect(self.refresh)
        self.refresh()

    def _toggle_arm(self):
        import txguard
        txguard.arm(not txguard.is_armed())
        self.refresh()

    def _toggle_unlock(self):
        import txguard
        txguard.unlock_session(not txguard.session_unlocked())
        self.refresh()

    def refresh(self):
        import txguard
        armed, unlocked = txguard.is_armed(), txguard.session_unlocked()
        locked, why = txguard.tx_locked({"tx_enabled": True})        # env hard lock only
        self.arm_btn.setText("DISARM" if armed else "ARM")
        self.unlock_btn.setEnabled(armed)
        self.unlock_btn.setText("LOCK SESSION" if unlocked else "UNLOCK THIS SESSION")
        if unlocked:
            self.state.set_hero("UNLOCKED", "armed + unlocked — each key-up still passes the band, "
                                "power, tx_enabled and engagement checks")
        elif armed:
            self.state.set_hero("ARMED", "armed, session locked — nothing can key up yet")
        else:
            self.state.set_hero("OFF", "kill switch off — every transmit is refused")
        self.state.set_rows([("KILL SWITCH", "ARMED" if armed else "OFF"),
                             ("SESSION", "UNLOCKED" if unlocked else "LOCKED"),
                             ("ENV LOCK", why if locked else "none")])

    def focus_first(self):
        self.arm_btn.setFocus()


# ======================= ENGAGEMENT =======================

def _engagement():
    import engagement
    return engagement


class EngagePanel(Overlay):
    """Operator identity + engagement scope: activate, end, and the authorized-action trail. Global
    state, so it opens from the ENGAGEMENT slot in the top strip. The gate itself is the engine's
    (engagement.start / end); this only calls it."""
    TITLE = "ENGAGEMENT"
    SIZE = (1220, 640)          # CL3: the trail gained STATE + RESULT columns; no h-scroll at 1280
    MIN_EVIDENCE_ROWS = 3
    gate_changed = QtCore.Signal()

    def __init__(self, mode="dark", parent=None):
        super().__init__(mode, parent)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        form = QtWidgets.QFrame()
        form.setProperty("class", "card2")
        fl = QtWidgets.QFormLayout(form)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        self.eng_operator = QtWidgets.QLineEdit()
        self.eng_operator.setReadOnly(True)              # from the operator profile, never typed
        self.eng_operator.setPlaceholderText("set callsign / name in the operator profile")
        self.eng_name = QtWidgets.QLineEdit()
        self.eng_auth = QtWidgets.QLineEdit()
        self.eng_auth.setPlaceholderText("ticket / ROE / written consent reference")
        self.eng_scope = QtWidgets.QLineEdit()
        self.eng_scope.setPlaceholderText("typed, comma-separated: 10.0.0.0/24, AA:BB:CC:DD:EE:FF, "
                                          "can0:0x700-0x7FF, pan:0x1A2B@15, uid:04A22B3C, LAB-1")
        self._prefill_operator()
        fl.addRow(micro("Operator"), self.eng_operator)
        fl.addRow(micro("Engagement"), self.eng_name)
        fl.addRow(micro("Authorization"), self.eng_auth)
        fl.addRow(micro("Scope"), self.eng_scope)
        btns = QtWidgets.QHBoxLayout()
        self.eng_start = QtWidgets.QPushButton("ACTIVATE ENGAGEMENT")
        self.eng_start.clicked.connect(self._activate)
        self.eng_end = QtWidgets.QPushButton("END")
        self.eng_end.clicked.connect(self._deactivate)
        btns.addWidget(self.eng_start)
        btns.addWidget(self.eng_end)
        self.eng_report = QtWidgets.QPushButton("EXPORT REPORT")
        self.eng_report.setToolTip("Write the engagement report (HTML) from the evidence chain "
                                   "to ~/.local/share/uconsole-suite/reports/")
        self.eng_report.clicked.connect(self._export_report)
        btns.addWidget(self.eng_report)
        fl.addRow(btns)
        self.eng_msg = note("")
        fl.addRow(self.eng_msg)
        split.addWidget(form, 2)
        right = QtWidgets.QVBoxLayout()
        self.eng_detail = DetailCard("ENGAGEMENT")
        self.eng_detail.set_hero("—", "no engagement")
        # the card takes the height its text needs (the whole scope list, wrapped — never clipped);
        # the evidence table gets the rest but never fewer than three rows (RA-CL1)
        self.eng_detail.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                                      QtWidgets.QSizePolicy.Minimum)
        right.addWidget(self.eng_detail)
        self.eng_chain = micro("Evidence chain")
        right.addWidget(self.eng_chain)
        self.eng_actions = FeedTable([("t", "TIME"), ("state", "STATE"), ("action", "ACTION"),
                                      ("target", "TARGET"), ("detail", "RESULT")])
        self.eng_actions.view.setMinimumHeight(theme.ROW_H * (self.MIN_EVIDENCE_ROWS + 1) + 8)
        right.addWidget(self.eng_actions, 1)
        split.addLayout(right, 3)
        self.outer.addLayout(split, 1)

        chrome.gate_signals().changed.connect(self._on_gate)

    def _prefill_operator(self):
        """The operator identity from the profile (read-only). The authorization reference is NOT
        pre-filled: it is typed for each engagement (audit G13)."""
        try:
            import opprofile
            import suite
            self.eng_operator.setText(opprofile.operator_identity(opprofile.load(suite.settings)))
        except Exception:
            pass        # no suite/profile on the dev host: leave blank, never invent an identity

    def _on_gate(self):
        if self.isVisible():
            self.refresh()

    def _activate(self):
        eng = _engagement()
        self._prefill_operator()
        scope = [s.strip() for s in self.eng_scope.text().split(",") if s.strip()]
        # operator=None: the ENGINE takes the operator from the profile (never this field's text)
        ok, why = eng.start(self.eng_name.text().strip(), self.eng_auth.text().strip(), scope, None)
        # an open engagement is a hazard state, not a healthy one: amber, never green (D9)
        self.eng_msg.setStyleSheet("color:%s;" % self._tok["warn"])
        self.eng_msg.setText(("ACTIVE — " if ok else "REFUSED — ") + why)
        self.refresh()
        self.gate_changed.emit()

    def _deactivate(self):
        _engagement().end()
        self.eng_msg.setStyleSheet("color:%s;" % self._tok["muted"])
        self.eng_msg.setText("engagement ended")
        self.refresh()
        self.gate_changed.emit()

    def refresh(self):
        try:
            info = _engagement().info()
            active = bool(info["active"])
            expired = bool(info.get("expired")) and bool(info.get("open"))
        except Exception as e:
            self.eng_detail.set_hero("\u25cc UNKNOWN", "the engagement state could not be read")
            self.eng_detail.hero.setStyleSheet("color:%s;" % self._tok["warn"])
            self.eng_detail.set_rows([("STATE", "UNKNOWN \u2014 %s" % e)])
            self.render_actions()
            return
        self.eng_detail.hero.setStyleSheet("")
        if active or expired:
            scope = list(info["scope"] or [])
            # parity with main's RECON banner: name, operator, authorization, target count
            self.eng_detail.set_hero(info["name"], "EXPIRED \u2014 END it and open a new one"
                                     if expired else "active engagement")
            self.eng_detail.set_rows([
                ("OPERATOR", info["operator"]), ("AUTHORIZATION", info["authorization"]),
                ("TARGETS", "%d" % len(scope)), ("SCOPE", ", ".join(scope)),
                ("STARTED", time.strftime("%H:%M:%S", time.localtime(info["started"]))),
                ("EXPIRES", time.strftime("%H:%M:%S", time.localtime(info["expires"])))])
        else:
            self.eng_detail.set_hero("—", "no engagement")
            self.eng_detail.set_rows([])
        self.render_actions()

    def _export_report(self):
        """E5: the report generator finally has a caller. Pure file write; nothing is sent."""
        try:
            import evidence
            path = evidence.export_engagement_report()
            self.eng_msg.setText("report written: %s" % path)
        except Exception as e:
            self.eng_msg.setText("report NOT written: %s" % e)

    def render_actions(self):
        """H9: AUTHORIZED and EXECUTED are different states; the rows come from the durable chain,
        never from an in-memory list. The caption says whether the chain verifies."""
        eng = _engagement()
        try:
            info = eng.chain_info()
            rows = eng.chain_states()
        except Exception as e:
            info = {"id": "?", "records": 0, "verified": False, "why": str(e)}
            rows = [{"t": 0, "state": "UNKNOWN", "action": "UNKNOWN — evidence trail unreadable",
                     "target": str(e)[:40], "detail": "",
                     "_colors": {"state": self._tok["warn"], "action": self._tok["warn"]}}]
        if info is None:
            self.eng_chain.setText("Evidence chain — none open")
        elif info["verified"]:
            self.eng_chain.setText("Evidence chain %s — %d records, VERIFIED" % (
                info["id"][:17], info["records"]))
        else:
            self.eng_chain.setText("Evidence chain %s — NOT VERIFIED: %s" % (
                info["id"][:17], info.get("why", "")[:60]))
        self.eng_actions.model.set_rows([
            dict(r, t=(time.strftime("%H:%M:%S", time.localtime(r["t"])) if r["t"] else "—"))
            for r in rows])

    def focus_first(self):
        self.eng_name.setFocus()


# ======================= alerts: store + drawer =======================

class AlertStore(QtCore.QObject):
    """Every alert since launch, kept until acknowledged — not a 3-item card that scrolls away
    (D10). It listens to the bus; it does not change what the bus retains.

    Each alert has a stable id; acknowledging is by id, never by list position, because a new
    alert arriving shifts every position (RA-CL1: the drawer acked an alert the operator never
    saw). The cap only ever drops ACKNOWLEDGED alerts, oldest first: an unacknowledged alert is
    never discarded, however many arrive."""
    changed = QtCore.Signal()

    def __init__(self, parent=None, cap=500):
        super().__init__(parent)
        self.items = []            # newest first: {id, ts, source, severity, text, acked}
        self._cap = cap
        self._next_id = 1
        eventbus.bus.published.connect(self._on_event)

    def _on_event(self, ev):
        if ev.get("type") != "alert":
            return
        self.items.insert(0, {"id": self._next_id, "ts": ev.get("ts", time.time()),
                              "source": ev.get("source", "?"),
                              "severity": ev.get("severity", "info"),
                              "text": ev.get("payload", {}).get("text", ""), "acked": False})
        self._next_id += 1
        self._trim()
        self.changed.emit()

    def _trim(self):
        i = len(self.items) - 1
        while len(self.items) > self._cap and i >= 0:
            if self.items[i]["acked"]:
                del self.items[i]
            i -= 1

    def unacked(self):
        return sum(1 for a in self.items if not a["acked"])

    def get(self, alert_id):
        return next((a for a in self.items if a["id"] == alert_id), None)

    def ack(self, alert_id):
        a = self.get(alert_id)
        if a is not None and not a["acked"]:
            a["acked"] = True
            self._trim()
            self.changed.emit()
            return True
        return False

    def last_id(self):
        return self._next_id - 1

    def ack_all(self, upto_id=None):
        """Acknowledge every alert (upto_id None) or only those with id <= upto_id — the ones the
        operator has seen. An alert that arrived later is never acknowledged sight unseen."""
        hit = [a for a in self.items if not a["acked"] and (upto_id is None or a["id"] <= upto_id)]
        for a in hit:
            a["acked"] = True
        if hit:
            self._trim()
            self.changed.emit()
        return len(hit)

    def clear(self):
        self.items = []
        self.changed.emit()

    def stop(self):
        try:
            eventbus.bus.published.disconnect(self._on_event)
        except (TypeError, RuntimeError):
            pass


_store = None


def alert_store():
    """The process-wide alert history (created on first use, on the GUI thread)."""
    global _store
    if _store is None:
        _store = AlertStore()
    return _store


def reset_alert_store():
    global _store
    if _store is not None:
        _store.stop()
        _store = None


class AlertsDrawer(Overlay):
    TITLE = "ALERTS"
    SIZE = (1000, 560)

    def __init__(self, mode="dark", parent=None, store=None):
        super().__init__(mode, parent)
        self.store = store or alert_store()
        self.count = note("")
        self.outer.addWidget(self.count)
        self.table = FeedTable([("t", "TIME"), ("state", "STATE"), ("sev", "SEV"),
                                ("source", "SOURCE"), ("text", "ALERT")])
        self.outer.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.ack_btn = QtWidgets.QPushButton("ACKNOWLEDGE SELECTED")
        self.ack_btn.clicked.connect(self.ack_selected)
        self.ack_all_btn = QtWidgets.QPushButton("ACKNOWLEDGE ALL SEEN")
        self.ack_all_btn.clicked.connect(self.ack_all_seen)
        self._seen_id = 0          # newest alert id on screen when the drawer was last opened
        row.addWidget(self.ack_btn)
        row.addWidget(self.ack_all_btn)
        row.addStretch(1)
        self.outer.addLayout(row)
        self.store.changed.connect(self.refresh)

    def refresh(self):
        keep = self.selected_id()
        sev_col = {"alert": self._tok["alert"], "warn": self._tok["warn"]}
        rows = []
        for a in self.store.items:
            rows.append({"_id": a["id"], "t": time.strftime("%H:%M:%S", time.localtime(a["ts"])),
                         "state": "acked" if a["acked"] else "NEW",
                         "sev": a["severity"].upper(), "source": a["source"], "text": a["text"],
                         "_colors": {"sev": sev_col.get(a["severity"], self._tok["muted"]),
                                     "state": self._tok["muted"] if a["acked"] else self._tok["warn"]}})
        self.table.model.set_rows(rows)
        self.select_id(keep)            # the cursor stays on the same ALERT, not the same row
        n = self.store.unacked()
        late = sum(1 for a in self.store.items if not a["acked"] and a["id"] > self._seen_id)
        text = ("%d alert(s) since launch · %d unacknowledged" % (len(self.store.items), n)
                if self.store.items else "No alerts since launch.")
        if late and self.isVisible():
            text += " · %d arrived since opened (not in ACK ALL SEEN; reopen to include)" % late
        self.count.setText(text)

    def selected_id(self):
        row = self.table.view.currentIndex().row()
        rows = self.table.model.rows
        return rows[row]["_id"] if 0 <= row < len(rows) else None

    def select_id(self, alert_id):
        if alert_id is None:
            return
        for i, r in enumerate(self.table.model.rows):
            if r["_id"] == alert_id:
                sm = self.table.view.selectionModel()
                sm.blockSignals(True)
                self.table.view.selectRow(i)
                sm.blockSignals(False)
                return
        self.table.view.clearSelection()
        self.table.view.setCurrentIndex(QtCore.QModelIndex())

    def open(self):
        self._seen_id = self.store.last_id()       # what the operator is about to see
        super().open()

    def ack_all_seen(self, _checked=False):
        """Acknowledge everything up to the newest alert shown when the drawer was last opened.
        Alerts that arrived after that stay NEW until the drawer is opened again."""
        return self.store.ack_all(upto_id=self._seen_id)

    def ack_selected(self):
        """Acknowledge the alert under the cursor — identified by id, so an alert that arrived
        since the operator selected cannot be acknowledged in its place."""
        alert_id = self.selected_id()
        return self.store.ack(alert_id) if alert_id is not None else False

    def focus_first(self):
        self.table.view.setFocus()
        if self.store.items and self.table.view.currentIndex().row() < 0:
            self.table.view.selectRow(0)


# ======================= key map =======================

KEYMAP = [
    ("1 – 8", "open a page"),
    ("← →", "previous / next sub-tab"),
    ("↑ ↓", "move in the list; the detail follows"),
    ("Enter", "primary action of the page"),
    ("Esc", "back: close a panel, else home (OPS)"),
    ("[  ]", "step band / channel down, up (PRISM, PROWL)"),
    ("+  −", "span wider / narrower (PRISM)"),
    ("Space", "hold / resume the scan (PROWL)"),
    ("/", "command palette: page, action, or a bare frequency"),
    ("R", "RADIOS panel"),
    ("E", "ENGAGEMENT panel"),
    ("A", "alerts drawer"),
    ("M", "mute"),
    ("?", "this key map"),
    ("Shift+Esc  (or F12)", "PANIC — disarm TX, end the engagement, kill child processes"),
    ("Tab", "move focus between controls"),
]


class KeyMapOverlay(Overlay):
    TITLE = "KEYS"
    SIZE = (820, 600)

    def __init__(self, mode="dark", parent=None):
        super().__init__(mode, parent)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for i, (key, what) in enumerate(KEYMAP):
            k = QtWidgets.QLabel(key)
            k.setProperty("class", "keycap")
            k.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(k, i, 0)
            grid.addWidget(note(what), i, 1)
        grid.setColumnStretch(1, 1)
        self.outer.addLayout(grid)
        self.outer.addStretch(1)


# ======================= command palette =======================

class CommandPalette(Overlay):
    """'/' — type a callsign, a sub-tab, an action, or a bare frequency. Enter runs the top hit."""
    TITLE = "COMMAND"
    SIZE = (760, 440)

    def __init__(self, mode="dark", parent=None):
        super().__init__(mode, parent)
        self._commands = []          # (label, callable)
        self._shown = []
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("page · sub-tab · action · or a frequency in MHz")
        self.input.textChanged.connect(self._filter)
        self.input.returnPressed.connect(self.run_current)
        self.input.installEventFilter(self)
        self.outer.addWidget(self.input)
        self.list = QtWidgets.QListWidget()
        self.list.setStyleSheet("QListWidget { font-size: %dpx; }" % theme.FONT_BODY)
        self.list.itemActivated.connect(lambda _i: self.run_current())
        self.outer.addWidget(self.list, 1)
        self._freq_actions = None    # callable(mhz) -> [(label, fn)]

    def set_commands(self, commands, freq_actions=None):
        self._commands = list(commands)
        self._freq_actions = freq_actions

    def matches(self, text):
        text = text.strip()
        out = []
        try:
            mhz = float(text)
        except ValueError:
            mhz = None
        if mhz is not None and self._freq_actions is not None and 0.001 <= mhz <= 6000:
            out += self._freq_actions(mhz)
        words = text.lower().split()
        for label, fn in self._commands:
            low = label.lower()
            if all(w in low for w in words):
                out.append((label, fn))
        return out

    def _filter(self, text):
        self._shown = self.matches(text)
        self.list.clear()
        self.list.addItems([label for label, _fn in self._shown])
        if self._shown:
            self.list.setCurrentRow(0)

    def run_current(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._shown):
            fn = self._shown[row][1]
            self.close_overlay()
            fn()
            return True
        return False

    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == QtCore.QEvent.KeyPress:
            if ev.key() in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up) and self.list.count():
                step = 1 if ev.key() == QtCore.Qt.Key_Down else -1
                self.list.setCurrentRow((self.list.currentRow() + step) % self.list.count())
                return True
        return super().eventFilter(obj, ev)

    def refresh(self):
        self.input.clear()
        self._filter("")

    def focus_first(self):
        self.input.setFocus()


# ======================= DEMO border =======================

class DemoBorder(QtWidgets.QWidget):
    """A hatched frame round the whole window while in DEMO, so synthetic data can never be mistaken
    for live — independent of which page is showing or what a page writes (H7)."""
    WIDTH = 6

    def __init__(self, mode="dark", parent=None):
        super().__init__(parent)
        self._tok = theme.tokens(mode)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        w, h, b = self.width(), self.height(), self.WIDTH
        path = QtGui.QPainterPath()
        path.addRect(0, 0, w, h)
        inner = QtGui.QPainterPath()
        inner.addRect(b, b, w - 2 * b, h - 2 * b)
        p.setClipPath(path.subtracted(inner))
        p.fillRect(0, 0, w, h, QtGui.QColor(self._tok["bg"]))
        pen = QtGui.QPen(QtGui.QColor(self._tok["warn"]))
        pen.setWidth(3)
        p.setPen(pen)
        for x in range(-h, w + h, 10):
            p.drawLine(x, h, x + h, 0)
        p.end()
