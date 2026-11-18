"""SWEEP — counter-surveillance (a page key in the left rail).

The safety-critical use gets its own key (D5/D7): the four passive / defensive detectors
(bugsweep, jammer, imsicatch, gnss), the same DetectorWorker (defined in recon.py), and a findings
table. No transmit path.

H1 (CL4): every detector has one fixed status row — OFFLINE (with the reason), LEARNING or
WATCHING, with its sample count and last-sample age — so an operator can never read "no findings"
as "nothing here" while nothing is being watched. In live mode the detectors have no wired feed
and say NOT IMPLEMENTED (E4); the findings table then shows the OFFLINE empty state (D4).
"""
import time

from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp, _retain
from . import theme, eventbus
from .kit import FeedTable, micro
from .recon import DetectorWorker
from .timebase import zulu, age_text

DETECTORS = ("bugsweep", "jammer", "imsicatch", "gnss")
STALE_AFTER_S = 10.0           # a watching detector with no sample for this long is STALE


class SweepApp(PalisadeApp):
    TITLE = "SWEEP"
    LEASE = None          # the detectors are fed sweeps; they hold no radio of their own today

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        self._det = {k: {"state": "offline", "n": 0, "ts": None,
                         "reason": "not started"} for k in DETECTORS}
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        pl.addWidget(micro("COUNTER-SURVEILLANCE · all passive/defensive detectors · NO TX"))
        self.det_feed = FeedTable([("det", "DETECTOR"), ("state", "STATE"), ("n", "SAMPLES"),
                                   ("age", "LAST SAMPLE"), ("note", "NOTE")], fit_viewport=True)
        self.det_feed.setFixedHeight(theme.ROW_H * (len(DETECTORS) + 1) + 12)   # all four, no scroll
        pl.addWidget(self.det_feed)
        pl.addWidget(micro("FINDINGS"))
        self.counter_feed = FeedTable([("time", "TIME (Z)"), ("det", "DETECTOR"),
                                       ("sev", "SEV"), ("text", "FINDING")])
        pl.addWidget(self.counter_feed, 1)
        self._ages = QtCore.QTimer(self)
        self._ages.setInterval(1000)
        self._ages.timeout.connect(self._render_detectors)
        QtCore.QTimer.singleShot(0, self._render_detectors)   # after the base finishes building
        self._render_tables()
        return page

    def start(self):
        if self._started:
            return
        super().start()
        self._workers = []
        for kind in DETECTORS:                       # all passive/defensive detectors
            w = DetectorWorker(demo=self.demo, kind=kind)
            w.row.connect(self._on_counter)
            w.status.connect(self.on_status)
            w.error.connect(self.on_error)
            w.start()
            self._workers.append(w)
        self._ages.start()

    def stop(self):
        if self._stopped:
            return
        self._ages.stop()
        for w in getattr(self, "_workers", []):
            w.stop()
            w.quit()
            w.wait(3000)
            _retain(w)
        self._workers = []
        super().stop()

    # ---- per-detector state (H1) ----
    def _detector_state(self, kind, now=None):
        """-> (STATE word, note) for one detector, with STALE derived from the last-sample age."""
        d = self._det[kind]
        if d["state"] == "offline":
            return "OFFLINE", d["reason"]
        age = (now or time.time()) - d["ts"] if d["ts"] else None
        if age is not None and age > STALE_AFTER_S:
            return "STALE", "no sample for %s" % age_text(age)
        if d["state"] == "learning":
            return "LEARNING", "learning the baseline"
        return "WATCHING", "nothing above baseline" if not d.get("hits") else \
            "%d finding(s)" % d["hits"]

    def _render_detectors(self):
        now = time.time()
        rows, watching, stale = [], 0, 0
        for kind in DETECTORS:
            d = self._det[kind]
            word, note = self._detector_state(kind, now)
            col = {"OFFLINE": self._tok["warn"], "STALE": self._tok["alert"],
                   "LEARNING": self._tok["muted"], "WATCHING": self._tok["live"]}[word]
            watching += word == "WATCHING"
            stale += word == "STALE"
            rows.append({"_id": kind, "det": kind.upper(), "state": word, "n": str(d["n"]),
                         "age": age_text(now - d["ts"]) if d["ts"] else "—",
                         "note": note + (" (demo)" if d.get("demo") else ""),
                         "_colors": {"state": col}})
        self.det_feed.model.set_rows(rows)
        self._render_findings_empty(now, watching, stale)
        if getattr(self, "_status_row", None) is None:
            return
        self.set_chip("sdr", "%d/%d WATCHING" % (watching, len(DETECTORS)),
                      state="live" if watching else "warn")

    def _render_tables(self):
        self._render_detectors()

    def _render_findings_empty(self, now, watching, stale):
        if not self.counter_feed.model.rows:            # D4: never a blank findings table
            if watching:
                n = sum(self._det[k]["n"] for k in DETECTORS)
                last = max((self._det[k]["ts"] or 0) for k in DETECTORS)
                self.counter_feed.set_empty(
                    "watching", "nothing above baseline",
                    "%d samples · last sample %s ago" % (n, age_text(now - last)))
            elif stale:
                self.counter_feed.set_empty("stale", "detector feed stopped",
                                            "no sample in the last %ds" % STALE_AFTER_S)
            else:
                self.counter_feed.set_empty(
                    "offline", "NO DETECTOR IS WATCHING",
                    "Nothing is being watched, so no findings does not mean all clear. "
                    "Live detector feeds are NOT IMPLEMENTED yet.")

    def _on_counter(self, msg):
        kind = msg.get("kind")
        if kind in self._det and msg.get("state"):
            d = self._det[kind]
            d["state"] = msg["state"]
            d["demo"] = bool(msg.get("demo"))
            if msg["state"] == "offline":
                d["reason"] = msg.get("reason", "offline")
            else:
                d["n"] = msg.get("n", d["n"])
                d["ts"] = msg.get("ts", time.time())
        alert = msg.get("alert")
        if alert:
            if kind in self._det:
                self._det[kind]["hits"] = self._det[kind].get("hits", 0) + 1
            det, text = alert
            sev = "alert" if det in ("imsi", "gnss") else "warn"
            self.counter_feed.model.prepend({"time": zulu(), "det": det.upper(),
                                             "sev": sev.upper(), "text": text,
                                             "_colors": {"sev": self._tok["warn"]}}, cap=200)
            if not msg.get("demo"):                    # a real detector finding reaches OPS
                eventbus.bus.publish(eventbus.alert("SWEEP", "%s: %s" % (det.upper(), text),
                                                    severity=sev))
        self._render_detectors()
