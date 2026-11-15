from common import *
from palisade_qt import radio_arbiter
hub=mkhub(demo=False)
print("OWNER_LABELS", radio_arbiter.OWNER_LABELS)
tb=hub.topbar
for o in sorted(set(radio_arbiter.OWNER_LABELS.values())):
    tb.set_state("LIVE",("HELD",o),"PERMITTED",("ACTIVE","10.0.0.0/24","Op"))
    print("owner %-12s radio slot shows %r | tx %r | engage %r"%(o, tb.slots["radio"].value.text(), tb.slots["tx"].value.text(), tb.slots["engagement"].value.text()))
for scope in ("lab","a","AA:BB:CC:*"):
    tb.set_state("LIVE",("FREE",""),"OFF",("ACTIVE",scope,"Op")); print("scope %r -> %r"%(scope, tb.slots["engagement"].value.text()))
pump(100)
for n,k in tb.nav_keys.items():
    fm=k.label.fontMetrics(); print(n, "label", repr(k.label.text()), "px", k.label.font().pixelSize(), "label w", k.label.width(), "needs", fm.horizontalAdvance(k.label.text()), "| call needs", k.call.fontMetrics().horizontalAdvance(k.call.text()), "has", k.call.width())
print("strip minimumSizeHint", tb.minimumSizeHint().width(), "width", tb.width())
# Esc while typing then digit
hub.open_callsign("PROWL"); pump(200); f=hub.page_app("PROWL").fdb_input; f.setFocus(); pump(20)
key(hub,text="3"); print("typed 3 in field:", repr(f.text()), state(hub)); key(hub,K.Key_Escape); print("after Esc focus:", fw(), state(hub)); key(hub,text="3"); print("then 3 ->", state(hub))
hub.close(); pump(200)
