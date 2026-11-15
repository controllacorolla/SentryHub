import os, sys, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtCore, QtGui, QtWidgets
from palisade_qt import theme
theme.configure_scale(os.environ)
app=QtWidgets.QApplication([])
theme.load_fonts(); theme.set_app_font(app); theme.set_palette(app,"dark"); app.setStyleSheet(theme.qss("dark"))
from palisade_qt.kit import TopBar
from palisade_qt.kit.audio import AudioSink
from palisade_qt.ops import CALLSIGNS
tb=TopBar(mode="dark",nav=CALLSIGNS,audio=AudioSink(which=lambda b:None)); tb.resize(1280,40); tb.show(); app.processEvents()
for owner in ("PRISM","PROWL scan","PROWL fm","ATLAS adsb","BABEL","SWEEP"):
    tb.set_state("LIVE",("HELD",owner),"ARMED",("ACTIVE","10.0.0.0/24","Op"))
    print(repr(owner),"-> RADIO slot shows",repr(tb.slots["radio"].value.text()),"| ENGAGE shows",repr(tb.slots["engagement"].value.text()),"| TX",repr(tb.slots["tx"].value.text()))
tb.set_state("DEMO",("ACQUIRING","PROWL"),"PERMITTED",("ACTIVE","aa:*",""))
print({k:s.value.text() for k,s in tb.slots.items()})
for k,s in tb.slots.items():
    s.value.ensurePolished(); print(k,"slot w",s.width(),"value px",s.value.fontInfo().pixelSize(),"glyph",s.glyph.width(),s.glyph.height())
print("strip minimumSizeHint",tb.minimumSizeHint().width())
# sky dome
from palisade_qt.overwatch import SkyDome
d=SkyDome(theme.tokens("dark")); d.resize(500,500); d.show(); app.processEvents(); d.ensurePolished()
print("SkyDome widget font px",d.fontInfo().pixelSize(), "label rect heights: cardinal 16, sun 14, sat 16 (overwatch.py:86,101,119)")
fm=QtGui.QFontMetrics(d.font()); print("font height",fm.height(),"ascent",fm.ascent(),"descent",fm.descent(),"width('ISS (ZARYA)')",fm.horizontalAdvance("ISS (ZARYA)"),"width('NOAA-19 (demo)')",fm.horizontalAdvance("NOAA-19 (demo)"),"rect w 120")
d.set_sky((120,30),(200,40,0.5),[{"label":"NOAA-19 (demo)","az":10,"el":45,"demo":True},{"label":"ISS (ZARYA)","az":250,"el":30,"demo":False}],[])
app.processEvents(); d.grab().save(os.path.join("out2","skydome_dark.png"))
sys.stdout.flush(); os._exit(0)
