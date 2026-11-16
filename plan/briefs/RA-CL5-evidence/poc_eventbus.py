"""A6: payload mutation after publish, cross-subscriber mutation, and a stalled GUI thread."""
import threading

import _harness as H
from PySide6 import QtCore
from palisade_qt.eventbus import EventBus, alert

bus = EventBus(maxlen=1000)
seen_b = []
bus.published.connect(lambda e: e["payload"].__setitem__("text", "MUTATED BY SUBSCRIBER A"),
                      QtCore.Qt.DirectConnection)
bus.published.connect(lambda e: seen_b.append(e["payload"]["text"]), QtCore.Qt.DirectConnection)

ev = alert("T", "original")
ret = bus.publish(ev)
ev["payload"]["text"] = "mutated by publisher after publish"
H.log("publisher mutation after publish reaches the log: %s" % ("mutated by publisher" in bus.recent(1)[0]["payload"]["text"]))
H.log("subscriber B saw: %r ; log now holds: %r" % (seen_b[-1], bus.recent(1)[0]["payload"]["text"]))
ret["payload"]["text"] = "mutated via publish() return value"
H.log("publish() return value aliases the log entry: %s" % (bus.recent(1)[0]["payload"]["text"] == ret["payload"]["text"]))

# stalled GUI thread: 1500 alerts published from a worker thread while the GUI loop is not running
bus2 = EventBus(maxlen=1000)
got = []
bus2.published.connect(lambda e: got.append(e))
th = threading.Thread(target=lambda: [bus2.publish(alert("W", "alert %d" % i)) for i in range(1500)])
th.start(); th.join()
H.log("stall: pending=%d dropped=%d (bounded backlog)" % (bus2.pending(), bus2.dropped()))
H.pump(1.0)
H.log("after the GUI resumes: delivered=%d of 1500 ; log holds=%d ; last delivered=%r" % (
    len(got), len(bus2.recent(5000)), got[-1]["payload"]["text"] if got else None))
