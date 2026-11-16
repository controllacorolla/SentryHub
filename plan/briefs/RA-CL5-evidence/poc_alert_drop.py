"""A6 fix side effect: the bounded queued backlog drops the NEWEST events silently. During a short
GUI stall with a busy sky (ATLAS publishes every ADS-B contact each step), a weather alert
published by the NWR worker never reaches the OPS alert store / drawer."""
import threading
import time

import _harness as H
from palisade_qt import eventbus
from palisade_qt.panels import AlertStore

store = AlertStore()


def atlas_like():                       # 300 aircraft contacts per second from a worker thread
    for i in range(1200):
        eventbus.bus.publish(eventbus.contact("ATLAS", "AC%04d" % (i % 300), 47.0, -122.0))
        time.sleep(1 / 300.0)


th = threading.Thread(target=atlas_like)
th.start()
time.sleep(3.6)                          # GUI thread stalled ~3.6 s (e.g. a 3 s worker join on close)
eventbus.bus.publish(eventbus.alert("PROWL", "Tornado Warning — King, WA", severity="alert",
                                    event="TOR"))          # what NwrWorker._emit_alert publishes
th.join()
H.pump(1.5)                              # the GUI thread resumes and drains its queue
texts = [a["text"] for a in store.items]
H.log("bus pending=%d dropped=%d ; alert store has the TOR warning: %s ; bus log has it: %s" % (
    eventbus.bus.pending(), eventbus.bus.dropped(), any("Tornado" in t for t in texts),
    any(e["payload"].get("text", "").startswith("Tornado") for e in eventbus.bus.recent(2000,
                                                                                         "alert"))))
