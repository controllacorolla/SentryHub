"""MORE / SYSTEM — the settings + utility overflow.

Sub-tabs: SETTINGS / DOCTOR / ASSISTANT / MESH / SITREP. Backends reused AS-IS; every sub-feature
shows an honest standby when its backend (network / LLM / Meshtastic node / TTS) is absent.

  * SETTINGS — operator identity (opprofile), HOME position, theme, event-bus retention, lease
    override note. Persisted through the suite settings function when available.
  * DOCTOR  — doctor.run_all() health checks with honest pass / fail / info (network checks are
    skipped offscreen so tests never hit the network).
  * ASSISTANT — answers from the live event-bus context (contacts / alerts / decodes). A full LLM
    reply needs a reachable Ollama host (assistant.pick_host); with none it says so honestly.
  * MESH — Meshtastic node list + message log. Demo uses mesh_dash.FakeIface; no node -> standby.
  * SITREP — a plain-language situation report from the current bus state, with an optional spoken
    read-out (sitrep.speak); no TTS -> the text stands on its own.
"""
import os
import sys
import threading
import time

from PySide6 import QtWidgets

from .app import PalisadeApp, _retain
from . import theme, eventbus
from .kit import ControlBar, FeedTable, DetailCard, micro, card
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SUBTABS = ("SETTINGS", "DOCTOR", "ASSISTANT", "MESH", "SITREP")


def _offscreen():
    return bool(os.environ.get("PALISADE_OFFLINE") or
                os.environ.get("QT_QPA_PLATFORM") == "offscreen")


# ======================= workers =======================

class DoctorWorker(Worker):
    """doctor.run_all() off the GUI thread. Network checks are skipped offscreen (hermetic). Each
    check runs on a disposable helper thread the loop polls, so stop() joins promptly (the kit
    lifecycle contract) even if a check is blocking on a slow urlopen; the in-flight check is then
    abandoned (daemon, harmless) rather than making wait() time out and abort the QThread."""

    def run(self):
        import doctor
        for section, items in doctor.CHECKS:
            if self._stop:
                return
            if _offscreen() and section == "Network":
                continue                        # no HTTP in tests/CI
            for name, fn in items:
                if self._stop:
                    return
                res = self._run_check(fn)
                if res is None:                 # stopped mid-check -> exit so stop()/wait() joins
                    return
                ok, detail = res
                self.row.emit({"section": section, "name": name, "ok": ok, "detail": detail or ""})
        if not self._stop:
            self.status.emit({"sdr": {"text": "DOCTOR done", "ok": True}})

    def _run_check(self, fn):
        """Run one check on a daemon thread, polling self._stop. (ok, detail), or None if stopped
        before it finished — then the worker exits immediately and wait() joins without blocking on
        the in-flight (e.g. 5 s urlopen) check."""
        box = {}

        def job():
            try:
                box["r"] = fn()
            except Exception as e:
                box["r"] = (False, "check failed: %s" % str(e)[:60], "")
        t = threading.Thread(target=job, daemon=True)
        t.start()
        while t.is_alive():
            if self._stop:
                return None                     # abandon the in-flight check (daemon); exit promptly
            t.join(0.05)
        r = box.get("r")
        if not r:
            return None
        ok, detail, _fix = r
        return ok, detail


def _demo_mesh():
    """Static demo nodes + messages mirroring mesh_dash.FakeIface's data shape (its live chatter
    uses an unstoppable daemon thread, unsuitable for a Qt worker — so we use the shape, not it)."""
    now = time.time()

    def mk(sid, short, long_, snr, batt, heard):
        return {"user": {"id": sid, "shortName": short, "longName": long_},
                "snr": snr, "deviceMetrics": {"batteryLevel": batt}, "lastHeard": now - heard}
    nodes = {
        "!00000001": mk("!00000001", "DLTN", "uConsole (me)", None, 82, 0),
        "!a1b2c3d4": mk("!a1b2c3d4", "KAPA", "Centennial Roof", 6.25, 100, 40),
        "!b2c3d4e5": mk("!b2c3d4e5", "GLDN", "Golden Ridge Rptr", -4.5, 64, 300),
        "!c3d4e5f6": mk("!c3d4e5f6", "BIKE", "Trail bike node", 2.0, 31, 1500),
    }
    msgs = [{"fromId": "!a1b2c3d4", "decoded": {"text": "Anyone on the south mesh tonight?"}},
            {"fromId": "!b2c3d4e5", "decoded": {"text": "Copy, solid signal from Centennial"}}]
    return nodes, msgs


class MeshWorker(Worker):
    """Meshtastic node list + messages. Demo -> a static mirror of mesh_dash.FakeIface's data; live
    needs a real node (device-only) -> honest standby. Receive-only here (send is a separate action)."""

    def __init__(self, demo=True, parent=None):
        super().__init__(demo=demo, interval_ms=2000, parent=parent)
        self._iface = None
        self._emitted = False

    def step(self):
        if not self.demo:
            self.status.emit({"standby": True,
                              "sdr": {"text": "NO NODE — attach a Meshtastic device", "ok": False}})
            self._stop = True                   # live + no device: standby once, nothing to poll
            return
        if self._emitted:
            return
        self._emitted = True
        nodes, msgs = _demo_mesh()
        self.row.emit({"kind": "nodes", "nodes": nodes})
        for m in msgs:
            self.row.emit({"kind": "msg", "msg": m})


# ======================= the app =======================

class MoreApp(PalisadeApp):
    TITLE = "MORE"
    LEASE = None
    SUBTABS = SUBTABS

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._subtab = "SETTINGS"
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    def current_subtab(self):
        return self._subtab

    def switch_subtab(self, name):
        self._switch(name)

    def primary_action(self):
        actions = {"SETTINGS": self._save_settings, "DOCTOR": self._run_doctor,
                   "ASSISTANT": self._ask, "MESH": self._mesh_send, "SITREP": self._gen_sitrep}
        actions[self._subtab]()
        return True

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.stack = QtWidgets.QStackedWidget()
        self._pages = {"SETTINGS": self._settings_page(), "DOCTOR": self._doctor_page(),
                       "ASSISTANT": self._assistant_page(), "MESH": self._mesh_page(),
                       "SITREP": self._sitrep_page()}
        for t in SUBTABS:
            self.stack.addWidget(self._pages[t])
        lay.addWidget(self.stack, 1)
        self._sync_tabs()
        return body

    # ---- SETTINGS ----
    def _settings_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        c = card(2)
        fl = QtWidgets.QFormLayout(c)
        fl.setContentsMargins(14, 12, 14, 12)
        self.set_operator = QtWidgets.QLineEdit()
        self.set_home = QtWidgets.QLineEdit()
        self.set_home.setText("%.4f, %.4f" % eventbus.HOME)
        self.set_theme = QtWidgets.QComboBox()
        self.set_theme.addItems(["dark", "light", "sun"])
        self.set_theme.setCurrentText(self.mode)
        self.set_retention = QtWidgets.QSpinBox()
        self.set_retention.setRange(100, 5000)
        self.set_retention.setValue(eventbus.bus._log.maxlen)
        self._prefill_settings()
        fl.addRow(micro("Operator"), self.set_operator)
        fl.addRow(micro("HOME (lat, lon)"), self.set_home)
        fl.addRow(micro("Theme"), self.set_theme)
        fl.addRow(micro("Event-bus retention"), self.set_retention)
        self.set_msg = QtWidgets.QLabel("")
        self.set_msg.setProperty("class", "note")
        self.set_msg.setWordWrap(True)
        fl.addRow(self.set_msg)
        save = QtWidgets.QPushButton("SAVE SETTINGS")
        save.clicked.connect(self._save_settings)
        fl.addRow(save)
        pl.addWidget(c)
        pl.addStretch(1)
        return page

    def _prefill_settings(self):
        try:
            import opprofile
            import suite
            prof = opprofile.load(suite.settings)
            self.set_operator.setText(prof.get("callsign") or prof.get("name") or "")
        except Exception:
            pass        # no suite/profile on the dev host — leave blank, never invent an identity

    def _parse_home(self):
        """'lat, lon' -> (lat, lon) if valid, else None."""
        try:
            lat, lon = [float(x.strip()) for x in self.set_home.text().split(",")]
        except (ValueError, IndexError):
            return None
        return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None

    def _write_settings(self, data):
        """Persist the UI settings to the suite store. Returns True if written, False if no store.
        Seam: tests replace this to capture what would be persisted."""
        try:
            import suite
            s, path = suite.settings("palisade_ui", {})
            s.update(data)
            suite.save_json(path, s)
            return True
        except Exception:
            return False

    def _save_settings(self):
        # HOME is NOT just persisted — it is the shared geo frame, so apply it live immediately
        # (ops/atlas to_xy read eventbus.HOME). Reject an invalid HOME rather than falsely report saved.
        home = self._parse_home()
        if home is None and self.set_home.text().strip():
            self.set_msg.setStyleSheet("color:%s;" % self._tok["warn"])
            self.set_msg.setText("HOME must be 'lat, lon' (e.g. 47.6, -122.3) — nothing saved")
            return
        live = []
        if home is not None:
            eventbus.HOME = home
            live.append("HOME")
        try:
            from collections import deque
            eventbus.bus._log = deque(eventbus.bus._log, maxlen=self.set_retention.value())
            live.append("event-bus retention")
        except Exception:
            pass
        # persist ALL displayed fields (operator + HOME + theme + retention)
        persisted = self._write_settings({
            "callsign": self.set_operator.text().strip(),
            "home": list(home) if home else None,
            "theme": self.set_theme.currentText(),
            "retention": self.set_retention.value()})
        theme_changed = self.set_theme.currentText() != self.mode
        parts = ["applied now: " + ", ".join(live)] if live else []
        if persisted:                               # operator + theme take effect via the store
            parts.append("persisted: operator, theme" +
                         (" (theme applies on restart)" if theme_changed else ""))
            self.set_msg.setStyleSheet("color:%s;" % self._tok["text"])   # saved is not "receiving"
        else:                                       # honest: do NOT claim saved for discarded fields
            parts.append("NOT persisted (no settings store on this host): operator, theme")
            self.set_msg.setStyleSheet("color:%s;" % self._tok["warn"])
        self.set_msg.setText(" · ".join(parts))

    # ---- DOCTOR ----
    def _doctor_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        bar = ControlBar()
        self.doc_run = bar.add_button("RUN HEALTH CHECK", self._run_doctor)
        bar.add_stretch()
        self.doc_summary = QtWidgets.QLabel("")
        self.doc_summary.setProperty("class", "value")
        bar.lay.addWidget(self.doc_summary)
        pl.addWidget(bar)
        self.doc_feed = FeedTable([("section", "AREA"), ("name", "CHECK"),
                                   ("ok", "RESULT"), ("detail", "DETAIL")])
        pl.addWidget(self.doc_feed, 1)
        self._doc_rows = []
        return page

    def _run_doctor(self):
        self._doc_rows = []
        self.doc_feed.model.set_rows([])
        self._docw = DoctorWorker()
        self._docw.row.connect(self._on_doctor)
        self._docw.start()

    def _on_doctor(self, msg):
        ok = msg["ok"]
        verdict = "PASS" if ok is True else ("FAIL" if ok is False else "info")
        col = self._tok["live"] if ok is True else (self._tok["warn"] if ok is False
                                                    else self._tok["muted"])
        self._doc_rows.append({"section": msg["section"], "name": msg["name"], "ok": verdict,
                               "detail": msg["detail"], "_colors": {"ok": col}})
        self.doc_feed.model.set_rows(self._doc_rows)
        p = sum(1 for r in self._doc_rows if r["ok"] == "PASS")
        f = sum(1 for r in self._doc_rows if r["ok"] == "FAIL")
        self.doc_summary.setText("%d pass · %d fail" % (p, f))

    # ---- ASSISTANT ----
    def _assistant_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.asst_log = QtWidgets.QPlainTextEdit()
        self.asst_log.setReadOnly(True)
        self.asst_log.setPlainText("Ask about the live picture: 'what's on the map?', 'any alerts?',"
                                   " 'recent decodes?'. Full LLM replies need a reachable Ollama host.")
        pl.addWidget(self.asst_log, 1)
        row = QtWidgets.QHBoxLayout()
        self.asst_input = QtWidgets.QLineEdit()
        self.asst_input.setPlaceholderText("ask…")
        self.asst_input.returnPressed.connect(self._ask)
        row.addWidget(self.asst_input, 1)
        ask = QtWidgets.QPushButton("ASK")
        ask.clicked.connect(self._ask)
        row.addWidget(ask)
        pl.addLayout(row)
        return page

    def _ask(self):
        q = self.asst_input.text().strip()
        if not q:
            return
        self.asst_input.clear()
        self.asst_log.appendPlainText("\n> %s" % q)
        self.asst_log.appendPlainText(self._answer(q))

    def _answer(self, q):
        ql = q.lower()
        evs = eventbus.bus.recent(80)
        contacts = [e for e in evs if e["type"] == "contact"]
        alerts = [e for e in evs if e["type"] == "alert"]
        decodes = [e for e in evs if e["type"] == "decode"]
        if "alert" in ql:
            if not alerts:
                return "No alerts on the bus right now."
            return "%d alert(s): %s" % (len(alerts), "; ".join(a["payload"].get("text", "")
                                                              for a in alerts[-5:]))
        if "map" in ql or "contact" in ql or "overhead" in ql:
            if not contacts:
                return "No contacts on the map right now."
            kinds = {}
            for c in contacts:
                kinds[c["payload"].get("kind", "?")] = kinds.get(c["payload"].get("kind", "?"), 0) + 1
            return "%d contacts: %s" % (len(contacts), ", ".join("%d %s" % (n, k)
                                                                 for k, n in kinds.items()))
        if "decode" in ql or "signal" in ql:
            srcs = sorted({d["source"] for d in decodes})
            return ("%d recent decodes from %s" % (len(decodes), ", ".join(srcs))) if decodes \
                else "No decodes on the bus right now."
        # anything else needs the LLM backend
        host = None if _offscreen() else self._pick_host()
        if host is None:
            return ("AI backend offline — no Ollama host reachable. I can still answer from the live "
                    "bus: try 'any alerts?', 'what's on the map?', or 'recent decodes?'.")
        return "LLM host %s reachable — on-device this would answer freely." % host[0]

    def _pick_host(self):
        try:
            import assistant
            return assistant.pick_host(assistant.DEFAULTS)
        except Exception:
            return None

    # ---- MESH ----
    def _mesh_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(10)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(micro("MESH NODES"))
        self.mesh_nodes = FeedTable([("short", "NODE"), ("long", "NAME"),
                                     ("snr", "SNR"), ("batt", "BATT")])
        left.addWidget(self.mesh_nodes, 1)
        split.addLayout(left, 2)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(micro("MESSAGES"))
        self.mesh_log = QtWidgets.QPlainTextEdit()
        self.mesh_log.setReadOnly(True)
        right.addWidget(self.mesh_log, 1)
        srow = QtWidgets.QHBoxLayout()
        self.mesh_input = QtWidgets.QLineEdit()
        self.mesh_input.setPlaceholderText("send to the mesh…")
        self.mesh_input.returnPressed.connect(self._mesh_send)
        srow.addWidget(self.mesh_input, 1)
        right.addLayout(srow)
        split.addLayout(right, 3)
        pl.addLayout(split, 1)
        return page

    def _mesh_send(self):
        text = self.mesh_input.text().strip()
        if not text:
            return
        # live would hand this to the Meshtastic iface; in demo/no-node it is a local echo only
        tail = "" if self.demo else " (no node — not transmitted)"
        self.mesh_log.appendPlainText("→ (me) %s%s" % (text, tail))
        self.mesh_input.clear()

    # ---- SITREP ----
    def _sitrep_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.sitrep_card = DetailCard("SPOKEN SITREP · from the live OPS bus")
        self.sitrep_card.set_hero("—", "generate a situation report")
        pl.addWidget(self.sitrep_card, 1)
        row = QtWidgets.QHBoxLayout()
        gen = QtWidgets.QPushButton("GENERATE SITREP")
        gen.clicked.connect(self._gen_sitrep)
        row.addWidget(gen)
        self.speak_btn = QtWidgets.QPushButton("SPEAK")
        self.speak_btn.clicked.connect(self._speak)
        row.addWidget(self.speak_btn)
        row.addStretch(1)
        pl.addLayout(row)
        self._sitrep_text = ""
        return page

    def _sitrep_lines(self):
        evs = eventbus.bus.recent(100)
        contacts = [e for e in evs if e["type"] == "contact"]
        alerts = [e for e in evs if e["type"] == "alert"]
        decodes = [e for e in evs if e["type"] == "decode"]
        lines = ["Situation report, %s." % time.strftime("%H:%M")]
        if contacts:
            lines.append("%d contacts tracked." % len({c["payload"]["id"] for c in contacts}))
        if decodes:
            lines.append("%d decodes across %s." % (len(decodes),
                                                    ", ".join(sorted({d["source"] for d in decodes}))))
        if alerts:
            lines.append("%d alerts. %s" % (len(alerts), " ".join(a["payload"].get("text", "")
                                                                  for a in alerts[-3:])))
        if len(lines) == 1:
            lines.append("All quiet — no contacts, decodes, or alerts on the bus.")
        return lines

    def _gen_sitrep(self):
        lines = self._sitrep_lines()
        self._sitrep_text = " ".join(lines)
        self.sitrep_card.set_hero("SITREP", time.strftime("%H:%M"))
        self.sitrep_card.set_rows([("", ln) for ln in lines])

    def _speak(self):
        if not self._sitrep_text:
            self._gen_sitrep()
        if _offscreen():
            return                              # tests never invoke TTS
        try:
            import sitrep
            sitrep.speak(self._sitrep_text)     # no TTS backend -> the text still stands on screen
        except Exception:
            pass

    # ---- switching + lifecycle ----
    def _switch(self, tab):
        self._subtab = tab
        self.stack.setCurrentWidget(self._pages[tab])
        self._sync_tabs()

    def _sync_tabs(self):
        self._sync_rail()

    def start(self):
        if self._started:
            return
        super().start()
        self._workers = []
        self._meshw = MeshWorker(demo=self.demo)
        self._meshw.row.connect(self._on_mesh)
        self._meshw.status.connect(self.on_status)
        self._meshw.start()
        self._workers.append(self._meshw)

    def stop(self):
        if self._stopped:
            return
        for w in getattr(self, "_workers", []):
            w.stop()
            w.quit()
            w.wait(3000)
        docw = getattr(self, "_docw", None)
        if docw is not None:
            docw.stop()
            docw.quit()
            docw.wait(3000)
            _retain(docw)
        for w in getattr(self, "_workers", []):
            _retain(w)
        self._workers = []
        super().stop()

    def on_status(self, status):
        super().on_status(status)
        if status.get("standby"):
            self.mesh_log.setPlainText(status.get("sdr", {}).get("text", "NO NODE"))

    def _on_mesh(self, msg):
        if msg["kind"] == "nodes":
            rows = []
            for n in msg["nodes"].values():
                u = n.get("user", {})
                dm = n.get("deviceMetrics", {})
                rows.append({"short": u.get("shortName", "?"), "long": u.get("longName", ""),
                             "snr": "%.1f" % n["snr"] if n.get("snr") is not None else "—",
                             "batt": "%d%%" % dm.get("batteryLevel", 0)})
            self.mesh_nodes.model.set_rows(rows)
        elif msg["kind"] == "msg":
            m = msg["msg"]
            txt = m.get("decoded", {}).get("text", "")
            self.mesh_log.appendPlainText("%s: %s" % (m.get("fromId", "?"), txt))
