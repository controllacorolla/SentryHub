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

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp, _retain
from . import theme, eventbus, panels
from .timebase import zulu
from .kit import ControlBar, FeedTable, DetailCard, micro, card
from .worker import Worker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SUBTABS = ("SETTINGS", "DOCTOR", "ASSISTANT", "MESH", "SITREP")
DECODE_WINDOW_S = 600                 # decodes "recent" = the last 10 minutes (H17)


from .kit.seams import offscreen as _offscreen  # noqa: E402  (C5: one copy)


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

    def __init__(self, demo=False, parent=None):
        super().__init__(demo=demo, interval_ms=2000, parent=parent)
        self._iface = None
        self._emitted = False

    def step(self):
        if not self.demo:
            self.status.emit({"standby": True,
                              "sdr": {"text": "MESH NOT IMPLEMENTED — the Meshtastic link is not wired"
                                              " into this screen", "ok": False}})
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
    """SYSTEM's settings / diagnostics (SETTINGS, DOCTOR, SITREP). ASSISTANT and MESH were tabs here
    until the owner promoted them to pages of their own (2026-11-17): AssistantApp and MeshApp
    below are this class showing one view each, so the code behind every view is unchanged."""
    TITLE = "MORE"
    LEASE = None
    SUBTABS = ("SETTINGS", "DOCTOR", "SITREP")

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._subtab = self.SUBTABS[0]
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    def subtabs(self):
        return list(self.SUBTABS) if len(self.SUBTABS) > 1 else []     # one view: no sub-tabs

    def current_subtab(self):
        return self._subtab

    def switch_subtab(self, name):
        self._switch(name)

    def primary_action(self):
        actions = {"SETTINGS": self._save_settings, "DOCTOR": self._run_doctor,
                   "ASSISTANT": self._ask, "MESH": self._mesh_send, "SITREP": self._gen_sitrep}
        actions[self._subtab]()
        return True

    def current_view(self):
        return self._subtab

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
        self.stack.setCurrentWidget(self._pages[self._subtab])
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
        # the field is the TYPED HOME (the fallback), never the GPS position: SAVE would otherwise
        # pin a GPS fix the operator has since left as "typed", and persist it (RA-UIPc H1)
        h = self._typed_home()
        if h:
            self.set_home.setText("%.4f, %.4f" % h)
        # what the field showed: SAVE with it untouched keeps the stored typed HOME at full precision
        # instead of the 4-decimal text, and never moves HOME (RA-UIPd N3)
        self._home_text_shown = self.set_home.text().strip()
        self.set_home.setPlaceholderText("HOME NOT SET — enter lat, lon (e.g. 47.6, -122.3)")
        self.set_theme = QtWidgets.QComboBox()
        self.set_theme.addItems(["dark", "light", "sun"])
        self.set_theme.setCurrentText(self.mode)
        self.set_retention = QtWidgets.QSpinBox()
        self.set_retention.setRange(100, 5000)
        self.set_retention.setValue(eventbus.bus.retention())
        self._prefill_settings()
        fl.addRow(micro("Operator"), self.set_operator)
        home_row = QtWidgets.QHBoxLayout()
        home_row.setSpacing(8)
        home_row.addWidget(self.set_home, 1)
        # owner 2026-11-17: location should be automatic. Minimal GPS path (the rest of GPS-fed
        # HOME is CL6): read one gpsd fix and OFFER it in the field; SAVE still applies it, and
        # typing a HOME by hand stays the fallback.
        self.gps_btn = QtWidgets.QPushButton("USE GPS")
        self.gps_btn.setToolTip("read one fix from gpsd and put it in HOME (press SAVE to use it)")
        self.gps_btn.clicked.connect(lambda _=False: self.read_gps())
        home_row.addWidget(self.gps_btn)
        fl.addRow(micro("HOME (lat, lon)"), home_row)
        # owner 2026-11-17 ("location should be automatic", v0.1): HOME follows gpsd when it has a
        # trustworthy fix; the typed HOME above is the fallback (palisade_qt/gpshome.py)
        from . import gpshome
        self.set_follow = QtWidgets.QCheckBox("HOME follows GPS (typed HOME is the fallback)")
        self.set_follow.setChecked(gpshome.follows_gps())
        fl.addRow(micro("Location"), self.set_follow)
        self.gps_status = QtWidgets.QLabel("")
        self.gps_status.setProperty("class", "note")
        self.gps_status.setWordWrap(True)
        fl.addRow(self.gps_status)
        QtCore.QTimer.singleShot(0, self._wire_gps_status)
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
        if not eventbus.home_set() and not self.demo and "SETTINGS" in self.SUBTABS \
                and not self.set_follow.isChecked():     # following GPS sets HOME by itself
            from .kit.seams import offscreen
            if not offscreen():          # tests never touch a real gpsd
                QtCore.QTimer.singleShot(0, lambda: self.read_gps(auto=True))
        return page

    # ---- GPS -> HOME (minimal; device notes 2026-11-17) ----
    _gps_done = QtCore.Signal(object, bool)      # (fix dict or None, auto) -> GUI thread
    _gps_last = None                             # (lat, lon) of the last USE GPS fix
    HEMI_MARGIN = 2.0                            # degrees: no sign check closer than this

    @staticmethod
    def _gps_reader():
        """Seam: one gpsd TPV with a 2D/3D fix, or None. Tests replace it."""
        import suite
        return suite.gps_fix(timeout=3.0)

    def read_gps(self, auto=False):
        """Read one fix off the GUI thread; the result fills the HOME field (never saves it)."""
        if getattr(self, "_gps_busy", False):
            return
        self._gps_busy = True
        self.gps_btn.setEnabled(False)
        self.gps_btn.setText("GPS …")
        if not getattr(self, "_gps_wired", False):
            self._gps_done.connect(self._on_gps)
            self._gps_wired = True
        reader = self._gps_reader

        def run():
            try:
                fix = reader()
            except Exception:
                fix = None
            self._gps_done.emit(fix, auto)
        threading.Thread(target=run, daemon=True).start()

    def _on_gps(self, fix, auto):
        self._gps_busy = False
        self.gps_btn.setEnabled(True)
        self.gps_btn.setText("USE GPS")
        lat = lon = None
        if isinstance(fix, dict):
            lat, lon = fix.get("lat"), fix.get("lon")
        ok = (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
              and not isinstance(lat, bool) and not isinstance(lon, bool)
              and -90 <= lat <= 90 and -180 <= lon <= 180)
        if not ok:
            if not auto:                 # the automatic read stays quiet when there is no fix
                self.set_msg.setStyleSheet("color:%s;" % self._tok["warn"])
                self.set_msg.setText("NO GPS FIX — gpsd is not running or has no 2D/3D fix. "
                                     "Enter HOME by hand (west longitudes are negative).")
            return
        fix_ll = (float(lat), float(lon))
        if auto and self.set_home.text().strip():
            return                       # never overwrite what the operator typed
        if not auto:
            # only a fix the operator asked for (USE GPS) arms the hemisphere check: the silent read
            # at launch could be a cold-start junk fix nobody saw (RA-UIP M3)
            self._gps_last = fix_ll
        self.set_home.setText("%.4f, %.4f" % fix_ll)
        self.set_msg.setStyleSheet("color:%s;" % self._tok["text"])
        self.set_msg.setText("HOME filled from GPS (%dD fix) — press SAVE SETTINGS to use it"
                             % (fix.get("mode") if fix.get("mode") in (2, 3) else 2))

    @staticmethod
    def _saved_settings():
        """Seam: the palisade_ui settings dict (tests replace it)."""
        import suite
        s, _p = suite.settings("palisade_ui", {})
        return s

    def _typed_home(self):
        """The operator's typed HOME: the saved one, else a HOME set from SETTINGS this session.
        Never a GPS or demo HOME."""
        try:
            v = self._saved_settings().get("home")
            if v is not None:
                lat, lon = float(v[0]), float(v[1])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return (lat, lon)
        except Exception:
            pass
        return eventbus.home() if eventbus.HOME_SOURCE == "settings" else None

    def _gps_follower(self):
        w = self.window()
        return getattr(w, "gpshome", None)

    def _wire_gps_status(self):
        g = self._gps_follower()
        if g is not None and not getattr(self, "_gps_status_wired", False):
            g.status_changed.connect(self._show_gps_status)
            self._gps_status_wired = True
        self._show_gps_status(*(g.status if g is not None else
                                (("GPS follow: not available in demo" if self.demo else
                                  "GPS follow: not running"), "neutral")))

    def _show_gps_status(self, text, state):
        tok = {"live": "live", "warn": "warn"}.get(state, "muted")
        self.gps_status.setStyleSheet("color:%s;" % self._tok.get(tok, self._tok["text"]))
        self.gps_status.setText(text)

    def _hemisphere_mismatch(self, home):
        """A typed HOME on the other side of the equator / prime meridian from the GPS fix the
        operator read with USE GPS: almost always a dropped minus sign (39.7, 104.9 is in China,
        not Denver). Only well clear of the equator / prime meridian (HEMI_MARGIN degrees on both
        sides), and a warning, not a lock: SAVE again with the same HOME saves it (RA-UIP M3/L5)."""
        g = self._gps_last
        if g is None or home is None or home == getattr(self, "_hemi_confirm", None):
            return None
        m = self.HEMI_MARGIN
        for i, axis, neg in ((1, "longitude", "west"), (0, "latitude", "south")):
            if abs(g[i]) > m and abs(home[i]) > m and (g[i] < 0) != (home[i] < 0):
                self._hemi_confirm = home
                return ("HOME %s %+.4f is in the other hemisphere from your GPS fix (%+.4f); "
                        "%s is negative — nothing saved. SAVE again to keep it as typed"
                        % (axis, home[i], g[i], neg))
        return None

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

    def _write_operator(self, text):
        """N-op1: persist the operator identity to the operator profile (operator.json, read by
        opprofile.load), the one store engagement._profile_operator() reads. The single Operator
        field holds the callsign, else the name (opprofile.operator_identity), so:
          * a valid ham callsign -> profile callsign (upper case); the name is kept;
          * any other text      -> profile name, and the callsign is CLEARED, so the identity the
                                   engagement records is exactly what was typed;
          * empty               -> callsign and name both cleared (no operator; engagements refused).
        Only 'callsign' and 'name' are written: tx_enabled and every other key are left untouched
        (CL2 strict default: a callsign alone never enables TX).
        Returns (persisted, kind) with kind in {"callsign", "name", "cleared"}; persisted is False
        when there is no settings store. Seam: tests replace this to capture the write."""
        text = str(text or "").strip()
        try:
            import opprofile
            import suite
            prof, path = suite.settings("operator", opprofile.DEFAULTS)
            if not text:
                prof["callsign"], prof["name"], kind = "", "", "cleared"
            elif opprofile.valid_callsign(text):
                prof["callsign"], kind = text.upper(), "callsign"
            else:
                prof["callsign"], prof["name"], kind = "", text, "name"
            suite.save_json(path, prof)
            return True, kind
        except Exception:
            return False, None

    def _save_settings(self):
        # HOME is NOT just persisted — it is the shared geo frame, so apply it live immediately
        # (ops/atlas to_xy read eventbus.HOME). Reject an invalid HOME rather than falsely report saved.
        home = self._parse_home()
        if home is None and self.set_home.text().strip():
            self.set_msg.setStyleSheet("color:%s;" % self._tok["warn"])
            self.set_msg.setText("HOME must be 'lat, lon' (e.g. 47.6, -122.3) — nothing saved")
            return
        why = self._hemisphere_mismatch(home)
        if why:
            self.set_msg.setStyleSheet("color:%s;" % self._tok["warn"])
            self.set_msg.setText(why)
            return
        live = []
        follow = self.set_follow.isChecked()
        g = self._gps_follower()
        following = follow and g is not None and eventbus.HOME_SOURCE == "gps"
        typed_before = self._typed_home()
        field_changed = self.set_home.text().strip() != getattr(self, "_home_text_shown", "")
        if not field_changed and home is not None and typed_before is not None:
            home = typed_before                  # untouched: the stored value, not its rounding
        # RA-UIPc H1: the typed HOME goes live only when it is what HOME should be now. While HOME
        # follows a GPS fix, an unchanged typed HOME is only the fallback: SAVE keeps it on disk and
        # does not drag HOME back to it.
        if home is not None and (not following or field_changed):
            eventbus.set_home(home, "settings")
            live.append("HOME")
        try:
            eventbus.bus.set_retention(self.set_retention.value())
            live.append("event-bus retention")
        except Exception:
            pass
        # persist ALL displayed fields. The operator goes to the operator profile (N-op1: the
        # engagement gate reads operator.json, never palisade_ui.json); HOME/theme/retention to
        # the UI store.
        op_ok, op_kind = self._write_operator(self.set_operator.text())
        parts_note = None
        if g is not None and g.enabled != follow:
            g.set_enabled(follow)
            if not follow and eventbus.HOME_SOURCE == "gps":
                # follow turned off (RA-UIPc L2): HOME goes back to the typed one; with none typed it
                # stays on the last GPS fix and says so (never saved, never called "typed")
                if home is not None:
                    eventbus.set_home(home, "settings")
                    live.append("HOME (typed)")
                else:
                    parts_note = "HOME stays at the last GPS fix until you type one (not saved)"
        if g is not None and not follow:
            if eventbus.HOME_SOURCE == "gps":
                g._set_status("GPS follow off — HOME is the last GPS fix until you type one",
                              "warn")
            else:
                g._set_status("HOME: typed (GPS follow off)" if eventbus.home_set()
                              else "GPS follow off — HOME NOT SET", "neutral")
        if follow and home is not None and parts_note is None:
            parts_note = "HOME follows GPS: a confirmed fix replaces the typed HOME"
        persisted = self._write_settings({
            "home_follows_gps": follow,
            # only ever the TYPED HOME (the field), never a GPS position (RA-UIPc H1)
            "home": list(home) if home else (list(typed_before) if typed_before else None),
            "theme": self.set_theme.currentText(),
            "retention": self.set_retention.value()})
        if persisted:
            self._home_text_shown = self.set_home.text().strip()
        theme_changed = self.set_theme.currentText() != self.mode
        parts = ["applied now: " + ", ".join(live)] if live else []
        if parts_note:
            parts.append(parts_note)
        warn = False
        if op_ok and op_kind == "callsign":
            parts.append("operator saved: callsign %s" % self.set_operator.text().strip().upper())
        elif op_ok and op_kind == "name":
            parts.append("operator saved: name %s (not a valid ham callsign — engagements OK, "
                         "TX needs a callsign)" % self.set_operator.text().strip())
        elif op_ok:
            parts.append("operator cleared — engagements will be refused until one is set")
            warn = True
        else:                                       # honest: do NOT claim saved for discarded fields
            parts.append("operator NOT saved (no operator profile store on this host)")
            warn = True
        if persisted:                               # theme takes effect via the store
            parts.append("persisted: theme, location source" +
                         (" (theme applies on restart)" if theme_changed else ""))
        else:
            parts.append("NOT persisted (no settings store on this host): theme, location source")
            warn = True
        # saved is not "receiving": plain text colour on success, warn on any loss
        self.set_msg.setStyleSheet("color:%s;" % self._tok["warn" if warn else "text"])
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
                                   " 'recent decodes?'. Free-form questions: NOT IMPLEMENTED here.")
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
        """Answers from the live state only (H17/H18): contacts from the latest-state store,
        alerts from the store that keeps them until acknowledged. Anything else is NOT
        IMPLEMENTED here — no network probe, and never on the GUI thread."""
        ql = q.lower()
        if "alert" in ql:
            items = panels.alert_store().items
            open_ = [a for a in items if not a["acked"]]
            if not open_:
                return "No unacknowledged alerts (%d acknowledged this session)." % (
                    len(items) - len(open_))
            return "%d unacknowledged alert(s): %s" % (
                len(open_), "; ".join(a["text"] for a in open_[:5]))
        if "map" in ql or "contact" in ql or "overhead" in ql:
            contacts = eventbus.bus.contacts()
            if not contacts:
                return "No contacts on the map right now." + self._feed_note()
            kinds = {}
            for c in contacts:
                k = c["payload"].get("kind", "?")
                kinds[k] = kinds.get(k, 0) + 1
            return "%d contacts heard in the last %d min: %s" % (
                len(contacts), int(eventbus.CONTACT_TTL_S // 60),
                ", ".join("%d %s" % (n, k) for k, n in kinds.items()))
        if "decode" in ql or "signal" in ql:
            decodes = self._recent_decodes()
            srcs = sorted({d["source"] for d in decodes})
            return ("%d decodes in the last %d min from %s" % (
                len(decodes), DECODE_WINDOW_S // 60, ", ".join(srcs))) if decodes \
                else "No decodes in the last %d min." % (DECODE_WINDOW_S // 60) + self._feed_note()
        return ("NOT IMPLEMENTED — free-form questions are not wired into this screen. I answer "
                "from the live state only: try 'any alerts?', 'what's on the map?', or "
                "'recent decodes?'.")

    @staticmethod
    def _recent_decodes():
        now = time.time()
        return [d for d in eventbus.bus.recent(eventbus.bus.retention(), "decode")
                if now - d.get("ts", now) <= DECODE_WINDOW_S and not eventbus.is_telemetry(d)]

    @staticmethod
    def _feed_note():
        return "" if eventbus.bus.feeds() else \
            " No feed is running, so nothing is being watched."

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
        tail = "" if self.demo else " (NOT IMPLEMENTED — not transmitted)"
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
        """H17: contacts from the latest-state store, decodes from their own log, alerts from the
        acknowledgement store. With no feed running it says so — never "all quiet"."""
        contacts = eventbus.bus.contacts()
        decodes = self._recent_decodes()
        alerts = [a for a in panels.alert_store().items if not a["acked"]]
        feeds = eventbus.bus.feeds()
        lines = ["Situation report, %s." % zulu(secs=False)]
        if not feeds:
            lines.append("No feed is running — nothing is being watched. This is not an "
                         "all-clear.")
        if contacts:
            lines.append("%d contacts tracked." % len(contacts))
        if decodes:
            lines.append("%d decodes in the last %d minutes across %s." % (
                len(decodes), DECODE_WINDOW_S // 60,
                ", ".join(sorted({d["source"] for d in decodes}))))
        if alerts:
            lines.append("%d unacknowledged alerts. %s" % (
                len(alerts), " ".join(a["text"] for a in alerts[:3])))
        if feeds and not (contacts or decodes or alerts):
            lines.append("Watching %s: no contacts, decodes, or open alerts." %
                         ", ".join(sorted(feeds)))
        return lines

    def _gen_sitrep(self):
        lines = self._sitrep_lines()
        self._sitrep_text = " ".join(lines)
        self.sitrep_card.set_hero("SITREP", zulu(secs=False))
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
        if tab not in self.SUBTABS:
            return                      # a view this page does not show (ASSISTANT/MESH: own pages)
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
        if "MESH" in self.SUBTABS:          # only the MESH page runs the mesh worker
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


class AssistantApp(MoreApp):
    """ASSISTANT as its own page (owner 2026-11-17: "assistant should be own tab")."""
    TITLE = "ASSISTANT"
    SUBTABS = ("ASSISTANT",)


class MeshApp(MoreApp):
    """MESH as its own page (owner 2026-11-17: "why is mesh buried in system settings")."""
    TITLE = "MESH"
    SUBTABS = ("MESH",)
