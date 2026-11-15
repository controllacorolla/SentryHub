import os, sys, time
HERE=os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["HOME"]=os.path.join(HERE,"home")
sys.dont_write_bytecode=True
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets, QtCore
app=QtWidgets.QApplication([])
from palisade_qt import theme, eventbus, radio_arbiter, ops
from palisade_qt.kit import tiles, DetailCard
def _no(*a,**k): raise OSError("blocked")
tiles.urlopen=_no
from palisade_qt.shell import PalisadeHub
theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss("dark"))
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete); time.sleep(0.01)
out=os.path.join(HERE,"poc"); os.makedirs(out,exist_ok=True)
hub=PalisadeHub(demo=False, mode="dark"); hub.resize(1280,720); hub.show(); pump(300)
hub._list_children=lambda: []; hub._kill=lambda p: False

print("== (b) strip slot display for every arbiter owner")
for owner in list(radio_arbiter.OWNER_LABELS)+["PRISM","ATLAS","FORGE-RTL433"]:
    radio_arbiter.arbiter.changed.emit(owner); pump(20)
    s=hub.topbar.slots["radio"]
    print("   owner=%-12s full=%-20r shown=%r" % (owner, s.text(), s.value.text()))
radio_arbiter.arbiter.changed.emit(""); pump(20)
import engagement
for scope in (["192.168.1.0/24"], ["AA:BB:CC:*"], ["Net-*","10.0.0.0/8"], ["a"]):
    engagement.reset(); print("   start:", engagement.start("ACME Q4", "SOW-114", scope, "K7"))
    hub.state.poll(); pump(20)
    s=hub.topbar.slots["engagement"]
    print("   scope=%-28r full=%-30r shown=%r" % (scope, s.text(), s.value.text()))
hub.topbar.set_state("LIVE", ("ACQUIRING","PROWL scan"), "PERMITTED", ("NONE","",""))
print("   ACQUIRING shown=%r  PERMITTED shown=%r" % (hub.topbar.slots["radio"].value.text(), hub.topbar.slots["tx"].value.text()))
engagement.reset(); hub.state.poll(); pump(20)

print("== (a) alerts drawer: ack after a new alert arrives")
eventbus.bus.publish(eventbus.alert("SWEEP","A: IMSI catcher suspected",severity="alert")); pump(30)
hub.open_panel("alerts"); pump(50)
d=hub.alerts_drawer
print("   selected row", d.table.view.currentIndex().row(), "->", hub.alerts.items[d.table.view.currentIndex().row()]["text"])
eventbus.bus.publish(eventbus.alert("SWEEP","B: GNSS jamming detected",severity="alert")); pump(30)
r=d.table.view.currentIndex().row()
print("   after B arrives selected row", r, "->", hub.alerts.items[r]["text"])
from PySide6 import QtGui
ev=QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier)
hub.handle_key(ev); pump(30)
print("   after Enter:", [(a["text"], "acked" if a["acked"] else "NEW") for a in hub.alerts.items])
hub.open_panel("alerts"); pump(30)
hub.alerts.clear()

print("== (c) empty DetailCard footprint per view")
for name,_l in ops.CALLSIGNS:
    hub.open_callsign(name); pump(250)
    page=hub.pages[name]
    for t in (page.subtabs() or [None]):
        if t: page.switch_subtab(t); pump(200)
        hub.resize(1280,720); pump(60)
        for c in hub.findChildren(DetailCard):
            if c.isVisible() and c.isVisibleTo(hub):
                print("   %-6s %-9s empty=%-5s card %dx%d hero_visible=%s sub=%r" % (name, t, c.is_empty(), c.width(), c.height(), c.hero.isVisible(), c.sub.text()))

print("== (d) engagement panel with realistic strings")
hub.open_callsign("OPS")
cases={"short":("ACME Q4","SOW-114",["192.168.1.0/24"],"K7"),
       "realistic":("ACME HQ wireless assessment","SOW-2026-114 J.Doe CISO",["192.168.10.0/24","AA:BB:CC:*","ACME-Guest-*","ACME-Corp"],"K7ABC"),
       "many-scope":("ACME Q4","SOW-114",["10.0.%d.0/24"%i for i in range(12)],"K7")}
for k,(n,a,s,o) in cases.items():
    engagement.reset(); engagement.start(n,a,s,o); hub.state.poll(); pump(30)
    hub.open_panel("engagement"); pump(150)
    p=hub.engage_panel; c=p.eng_detail
    res=[]
    for lab in c.findChildren(QtWidgets.QLabel):
        if lab.isVisible() and lab.wordWrap():
            need=lab.heightForWidth(lab.width())
            if need>lab.height()+1: res.append((lab.text()[:40], "needs %d has %d"%(need,lab.height())))
    print("   %-10s card %dx%d (min %s) actions-table h=%d clipped=%s" % (k, c.width(), c.height(), c.minimumSizeHint().toTuple(), p.eng_actions.height(), res))
    hub.grab().save(os.path.join(out,"engage_%s.png"%k))
    hub.open_panel("engagement"); pump(30)
engagement.reset(); hub.state.poll()

print("== (e) BENCH: test sensitivity — unwrapped long label in the control bar")
bench=hub.page_app("BENCH"); pump(150)
print("   before mutation hub min", hub.minimumSizeHint().toTuple())
lab=QtWidgets.QLabel("conducted-bench TX needs the conducted-only acknowledgment: confirm the output goes to a dummy load/attenuator or a cabled receiver, not an antenna")
bench.bar.lay.addWidget(lab); pump(100)
print("   after  mutation hub min", hub.minimumSizeHint().toTuple())
lab.setParent(None); pump(50)
print("== (f) BENCH long RESULT message")
bench.card.set_rows([("TXGUARD","GATED/BLOCKED"),("RESULT","/usr/local/bin/hackrf_transfer -t /home/operator/.local/share/uconsole-suite/bench/conducted_replay_20m_cw_0dBm.iq -f 14060000 -s 2000000 -x 0 exited 1: "+"x"*200)])
pump(80); hub.resize(1280,720); pump(50)
print("   hub min", hub.minimumSizeHint().toTuple(), "size", hub.size().toTuple(), "card", bench.card.size().toTuple(), "card min", bench.card.minimumSizeHint().toTuple())
hub.grab().save(os.path.join(out,"bench_longresult.png"))
hub.close(); pump(300); engagement.reset()
