import sys; sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import panels, eventbus
import inspect
print("publish sig:", inspect.signature(eventbus.bus.publish))
st = panels.AlertStore()
def pub(t):
    st._on_event({"type":"alert","source":"t","severity":"warn","payload":{"text":t}})
pub("X-first")
# mix: ack some later ones to see whether acked are preferred for eviction
for i in range(520): pub(f"n{i}")
print("items", len(st.items), "unacked", st.unacked(), "X present", any(a["text"]=="X-first" for a in st.items), "oldest", st.items[-1]["text"])
# variant: acked alerts present, unacked oldest still evicted first?
st2 = panels.AlertStore()
def pub2(t): st2._on_event({"type":"alert","source":"t","severity":"warn","payload":{"text":t}})
pub2("OLD-unacked")
for i in range(499): pub2(f"a{i}")
for i in range(0,499): st2.ack(i)   # ack all newer 499, leave OLD unacked
print("before: unacked", st2.unacked(), len(st2.items))
pub2("new")
print("after: OLD present", any(a["text"]=="OLD-unacked" for a in st2.items), "unacked", st2.unacked(), "acked kept", sum(a["acked"] for a in st2.items))
