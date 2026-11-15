"""SWEEP — counter-surveillance (key 5).

The safety-critical use gets its own key instead of living two clicks down inside the pentest page
(D5/D7). This is the COUNTER view promoted out of RECON, moved mechanically: the same four passive /
defensive detectors (bugsweep, jammer, imsicatch, gnss), the same DetectorWorker (still defined in
recon.py), the same findings table. No transmit path.

What this cluster did NOT change, on purpose (it is CL4 / CL7): in live mode the detectors still
have no real feed and report standby, and the findings table is still empty while they are offline
(audit H1, D5, K1-K6). Promoting the page makes that gap easier to see, not smaller.
"""
import time

from PySide6 import QtWidgets

from .app import PalisadeApp, _retain
from . import theme, eventbus
from .kit import FeedTable, micro
from .recon import DetectorWorker

DETECTORS = ("bugsweep", "jammer", "imsicatch", "gnss")


class SweepApp(PalisadeApp):
    TITLE = "SWEEP"
    LEASE = None          # the detectors are fed sweeps; they hold no radio of their own today

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        pl.addWidget(micro("COUNTER-SURVEILLANCE · all passive/defensive detectors · NO TX"))
        self.counter_feed = FeedTable([("time", "TIME"), ("det", "DETECTOR"),
                                       ("sev", "SEV"), ("text", "FINDING")])
        pl.addWidget(self.counter_feed, 1)
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

    def _on_counter(self, msg):
        alert = msg.get("alert")
        if not alert:
            return
        det, text = alert
        sev = "alert" if det in ("imsi", "gnss") else "warn"
        self.counter_feed.model.prepend({"time": time.strftime("%H:%M:%S"), "det": det.upper(),
                                         "sev": sev.upper(), "text": text,
                                         "_colors": {"sev": self._tok["warn"]}}, cap=200)
        if not msg.get("demo"):                        # a real detector finding reaches the OPS strip
            eventbus.bus.publish(eventbus.alert("SWEEP", "%s: %s" % (det.upper(), text),
                                                severity=sev))
