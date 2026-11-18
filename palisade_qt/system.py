"""MORE / SYSTEM — the settings + utility overflow.

Sub-tabs: SETTINGS / DOCTOR / ASSISTANT / SITREP (MESH: palisade_qt/mesh.py since 2026-11-18).
Backends reused AS-IS; every sub-feature
shows an honest standby when its backend (network / LLM / Meshtastic node / TTS) is absent.

  * SETTINGS — operator identity (opprofile), HOME position, theme, event-bus retention, lease
    override note. Persisted through the suite settings function when available.
  * DOCTOR  — doctor.run_all() health checks with honest pass / fail / info (network checks are
    skipped offscreen so tests never hit the network).
  * ASSISTANT — free-form questions to a LOCAL model (Ollama on this device, owner 2026-11-18) with
    the live picture as context; with no model it says why and still answers alerts / map /
    decodes from the bus.
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

SUBTABS = ("SETTINGS", "DOCTOR", "ASSISTANT", "SITREP")       # MESH: palisade_qt/mesh.py
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


# ======================= ASSISTANT: a local model =======================

INSTALL_HINT = ("Install it once (needs internet): curl -fsSL https://ollama.com/install.sh | sh  "
                "then: ollama pull llama3.2:3b")


def local_hosts(s):
    """Only Ollama servers on THIS device (owner 2026-11-18: "just use a local model"). A remote
    host in assistant.json is ignored here, so no question or live context leaves the device."""
    import assistant
    out = []
    for h in (s or {}).get("hosts", []):
        url = h.get("url", "")
        if not assistant.is_local(url):
            continue
        if "0.0.0.0" in url:          # a listen address, not a place to connect (RA-MESH L10)
            h = dict(h, url=url.replace("0.0.0.0", "127.0.0.1"))
        out.append(h)
    return out


class AskWorker(Worker):
    """Free-form questions to a local model (Ollama on 127.0.0.1), streamed back token by token.
    Owner 2026-11-18. Reuses the assistant.py backend (host pick, model choice, CPU-thread cap,
    power warning, system prompt). Off the GUI thread; loopback only, so NET OFFLINE allows it.

    Rows: {"kind": "model", "text"} | {"kind": "meta", "text"} | {"kind": "tok", "text"} |
    {"kind": "done", "text"} | {"kind": "no_model", "text", "q"} | {"kind": "error", "text"}."""

    PAUSE_WHEN_HIDDEN = False        # an answer keeps streaming while another page is open
    HISTORY = 8                      # turns of chat history sent back to the model

    def __init__(self, demo=False, parent=None, settings=None, power=None):
        super().__init__(demo=demo, interval_ms=250, parent=parent)
        import queue
        self._q = queue.Queue()
        self._settings = settings
        self._power = power
        self._history = []
        self._cancel = False

    def ask(self, question, context=""):
        self._cancel = False
        self._q.put((question, context))
        self.poke()

    def cancel(self):
        self._cancel = True
        self._abort()
        self.poke()

    def stop(self):
        super().stop()
        self._abort()                 # the window closes now, not when the model's first token
                                      # arrives (RA-MESH L2)

    def _abort(self):
        """Break a request that is waiting on the model: shut the connection's socket (works
        before the reply headers too: the model may still be loading)."""
        import socket
        socks = [getattr(getattr(self, "_conn", None), "sock", None)]
        r = getattr(self, "_resp", None)          # once the reply started, the response owns it
        try:
            socks.append(r.fp.raw._sock)
        except Exception:
            pass
        for sock in socks:
            if sock is None:
                continue
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass

    def _s(self):
        import assistant
        if self._settings is not None:
            return self._settings
        try:
            import suite as S
            return S.settings("assistant", assistant.DEFAULTS)[0]
        except Exception:
            return dict(assistant.DEFAULTS)

    def find_model(self, s):
        """(url, model) of a reachable local Ollama with a chat model, or (None, reason)."""
        import assistant
        hosts = local_hosts(s)
        if not hosts:
            return None, "NO LOCAL MODEL — no Ollama server on this device is configured. " + \
                INSTALL_HINT
        reason = "NO LOCAL MODEL — Ollama is not running on this device. " + INSTALL_HINT
        for h in hosts:
            url = h["url"].rstrip("/")
            try:
                tags = assistant.http_json(url + "/api/tags", timeout=1.5)
            except Exception:
                continue
            models = [m["name"] for m in tags.get("models", [])]
            if not models:
                reason = ("NO LOCAL MODEL — Ollama is running but has no model. Run once: "
                          "ollama pull %s" % (h.get("model") or "llama3.2:3b"))
                continue
            return (url, assistant.best_model(models, h.get("model") or "")), ""
        return None, reason

    def step(self):
        import queue
        try:
            q, ctx = self._q.get_nowait()
        except queue.Empty:
            return
        try:
            self._answer(q, ctx)
        except Exception as e:                   # the page's ASK must never stay greyed
            self.row.emit({"kind": "error", "text": "assistant failed: %s"
                           % " ".join(str(e).split())[:160]})

    def _answer(self, q, ctx):
        if self.demo:
            self.row.emit({"kind": "model", "text": "DEMO — no model is asked in demo mode"})
            self.row.emit({"kind": "no_model", "q": q,
                           "text": "DEMO — in live mode this goes to the local model."})
            return
        import assistant
        s = self._s()
        found, why = self.find_model(s)
        if found is None:
            self.row.emit({"kind": "model", "text": why})
            self.row.emit({"kind": "no_model", "q": q, "text": why})
            return
        url, model = found
        self.row.emit({"kind": "model", "text": "LOCAL MODEL · %s on this device" % model})
        try:
            p = self._power() if self._power else None
            if p is None:
                import suite as S
                p = S.power_status()
            warn = assistant.power_warning(p, True)
        except Exception:
            warn = ""
        if warn:
            self.row.emit({"kind": "meta", "text": warn})
        self._history.append({"role": "user", "content": q})
        msgs = [{"role": "system", "content": assistant.system_prompt(
            dict(s, system=CHAT_SYSTEM), ctx)}] + self._history[-self.HISTORY:]
        self._stream(s, url, model, msgs)

    def _stream(self, s, url, model, msgs):
        """Stream /api/chat from the local model. A plain HTTP connection held by the worker (after
        netpolicy's check and log), so STOP and page close can shut it at any moment, even while
        the model is still loading and has sent nothing yet (RA-MESHb N2); and no proxy from the
        environment ever sees the request (RA-MESH L1: it is loopback only)."""
        import json
        import urllib.parse
        import assistant
        import netpolicy
        body = json.dumps(assistant.chat_body(s, url, model, msgs)).encode()
        full = ""
        try:
            u = urllib.parse.urlsplit(url)
            conn = netpolicy.connect(url + "/api/chat", timeout=180,
                                     purpose="assistant (local model)")
            self._conn = conn
            if self.stopping or self._cancel:
                raise ConnectionAbortedError("stopped")
            conn.request("POST", (u.path.rstrip("/") or "") + "/api/chat", body=body,
                         headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            self._resp = r
            if self.stopping or self._cancel:
                self._abort()
            if r.status != 200:
                raise RuntimeError("HTTP %d from the local model" % r.status)
            for line in r:
                if self.stopping or self._cancel:
                    break
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                tok = (m.get("message") or {}).get("content", "")
                if tok:
                    full += tok
                    self.row.emit({"kind": "tok", "text": tok})
                if m.get("done"):
                    break
        except Exception as e:
            if not (self.stopping or self._cancel):
                self._close_conn()
                self._history.pop()              # the question was never answered
                self.row.emit({"kind": "error", "text": "local model failed: %s"
                               % " ".join(str(e).split())[:160]})
                return
        self._close_conn()
        if self.stopping or self._cancel:
            # a stopped answer is marked, and never kept as the model's reply (RA-MESHb N4)
            self._history.pop()
            self.row.emit({"kind": "done", "text": full + " [stopped]"})
            return
        self._history.append({"role": "assistant", "content": full})
        self.row.emit({"kind": "done", "text": full})

    def _close_conn(self):
        self._resp = None
        c, self._conn = getattr(self, "_conn", None), None
        if c is not None:
            try:
                c.close()
            except Exception:
                pass


# the on-screen assistant answers in text (the Tk push-to-talk one reads aloud)
CHAT_SYSTEM = ("You are the assistant inside PALISADE, an SDR and field-signals suite on a handheld "
               "Linux computer (ClockworkPi uConsole). Answer briefly and plainly; use short lists "
               "only when they help. If you are unsure, say so. Never invent readings: only the "
               "live status below is real.")


def live_summary(alerts, contacts, decodes, home_set, net_mode):
    """The live picture the local model may use, in plain sentences: counts and open alert texts,
    nothing else (no engagement scope or targets)."""
    out = []
    kinds = {}
    for c in contacts:
        k = c["payload"].get("kind", "?")
        kinds[k] = kinds.get(k, 0) + 1
    out.append("Contacts on the map: %s." % (", ".join("%d %s" % (n, k) for k, n in
                                                        sorted(kinds.items())) or "none"))
    if alerts:
        out.append("Unacknowledged alerts: %s." % "; ".join(a["text"] for a in alerts[:5]))
    else:
        out.append("No unacknowledged alerts.")
    srcs = {}
    for d in decodes:
        srcs[d["source"]] = srcs.get(d["source"], 0) + 1
    out.append("Decodes in the last %d minutes: %s." % (
        DECODE_WINDOW_S // 60, ", ".join("%d from %s" % (n, k) for k, n in sorted(srcs.items()))
        or "none"))
    out.append("HOME position is %s." % ("set" if home_set else "not set"))
    out.append("Network mode: %s." % net_mode)
    return " ".join(out)


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
                   "ASSISTANT": self._ask, "SITREP": self._gen_sitrep}
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
                       "ASSISTANT": self._assistant_page(),
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

    def _parse_home(self, text=None):
        """'lat, lon' -> (lat, lon) if valid, else None."""
        try:
            raw = self.set_home.text() if text is None else text
            lat, lon = [float(x.strip()) for x in raw.split(",")]
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
        # changed = a different VALUE from what the field showed, not different text: retyping the
        # same position as "39.6261,-104.9123" is not an edit (RA-UIPe E6)
        shown = getattr(self, "_home_text_shown", "")
        field_changed = (home != self._parse_home(shown)) if shown else bool(
            self.set_home.text().strip())
        cleared = not self.set_home.text().strip() and bool(shown)
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
            # clearing the field unsets the typed HOME (RA-UIPe E5); left empty, the old one stays
            "home": list(home) if home else (
                None if cleared or not typed_before else list(typed_before)),
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
        # owner 2026-11-18: "just use a local model" — free-form questions go to Ollama on this
        # device; nothing leaves it. The line says which model answers, or why none can.
        self.asst_model = QtWidgets.QLabel("LOCAL MODEL · checking on the first question")
        self.asst_model.setProperty("class", "note")
        self.asst_model.setWordWrap(True)
        self.asst_model.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        pl.addWidget(self.asst_model)
        self.asst_log = QtWidgets.QPlainTextEdit()
        self.asst_log.setReadOnly(True)
        self.asst_log.setPlainText(
            "Ask anything. Answers come from a model running on this uConsole (Ollama), and it "
            "knows the live picture: contacts, open alerts, recent decodes. Nothing you ask "
            "leaves the device.")
        pl.addWidget(self.asst_log, 1)
        row = QtWidgets.QHBoxLayout()
        self.asst_input = QtWidgets.QLineEdit()
        self.asst_input.setPlaceholderText("ask…")
        self.asst_input.returnPressed.connect(self._ask)
        row.addWidget(self.asst_input, 1)
        self.asst_ask = QtWidgets.QPushButton("ASK")
        self.asst_ask.clicked.connect(self._ask)
        row.addWidget(self.asst_ask)
        self.asst_stop = QtWidgets.QPushButton("STOP")
        self.asst_stop.setToolTip("stop the answer being written")
        self.asst_stop.setEnabled(False)
        self.asst_stop.clicked.connect(self._stop_answer)
        row.addWidget(self.asst_stop)
        pl.addLayout(row)
        self._asking = False
        return page

    def _ask(self):
        q = self.asst_input.text().strip()
        if not q or self._asking:
            return
        self.asst_input.clear()
        self.asst_log.appendPlainText("\n> %s" % q)
        w = getattr(self, "_askw", None)
        if w is None:                         # a page that never started (tests): built-ins only
            self.asst_log.appendPlainText(self._answer(q) or "NO LOCAL MODEL — page not started")
            return
        self._asking = True
        self.asst_ask.setEnabled(False)
        self.asst_stop.setEnabled(True)
        self._asst_started = False
        w.ask(q, self._live_context())

    def _stop_answer(self):
        w = getattr(self, "_askw", None)
        if w is not None:
            w.cancel()

    def _live_context(self):
        import assistant
        import netpolicy
        w = getattr(self, "_askw", None)
        try:                          # assistant.json "live_context": false -> send none (L9)
            st = w._s() if w is not None else assistant.DEFAULTS
            if not st.get("live_context", True):
                return ""
        except Exception:
            pass
        return live_summary([a for a in panels.alert_store().items if not a["acked"]],
                            eventbus.bus.contacts(), self._recent_decodes(), eventbus.home_set(),
                            netpolicy.mode())

    def _on_ask(self, r):
        k = r["kind"]
        if k == "model":
            self.asst_model.setText(r["text"])
            warn = r["text"].startswith("NO LOCAL MODEL")
            self.asst_model.setStyleSheet("color:%s;" % (self._tok["warn"] if warn
                                                         else self._tok["muted"]))
        elif k == "meta":
            self.asst_log.appendPlainText("(%s)" % r["text"])
        elif k == "tok":
            if not self._asst_started:
                self._asst_started = True
                self.asst_log.appendPlainText("")
            cur = self.asst_log.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(r["text"])
            self.asst_log.setTextCursor(cur)
            self.asst_log.ensureCursorVisible()
        elif k == "no_model":
            # no model: the built-in answers still work for the live picture
            built = self._answer(r["q"])
            self.asst_log.appendPlainText(built if built else r["text"])
            self._ask_done()
        elif k == "error":
            self.asst_log.appendPlainText(r["text"])
            self._ask_done()
        elif k == "done":
            self._ask_done()

    def _ask_done(self):
        self._asking = False
        self.asst_ask.setEnabled(True)
        self.asst_stop.setEnabled(False)

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
        return None              # free-form: the local model answers (AskWorker), not this

    @staticmethod
    def _recent_decodes():
        now = time.time()
        return [d for d in eventbus.bus.recent(eventbus.bus.retention(), "decode")
                if now - d.get("ts", now) <= DECODE_WINDOW_S and not eventbus.is_telemetry(d)]

    @staticmethod
    def _feed_note():
        return "" if eventbus.bus.feeds() else \
            " No feed is running, so nothing is being watched."

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
        if "ASSISTANT" in self.SUBTABS:     # only the ASSISTANT page runs the model worker
            self._askw = AskWorker(demo=self.demo)
            self._askw.row.connect(self._on_ask)
            self._askw.start()
            self._workers.append(self._askw)

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


class AssistantApp(MoreApp):
    """ASSISTANT as its own page (owner 2026-11-17: "assistant should be own tab")."""
    TITLE = "ASSISTANT"
    SUBTABS = ("ASSISTANT",)
