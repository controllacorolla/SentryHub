import os, sys, time
HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=sys.argv[1]; TAG=sys.argv[2]
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["HOME"]=os.path.join(HERE,"home")
sys.dont_write_bytecode=True
sys.path.insert(0, ROOT)
import subprocess
def _blk(*a,**k): raise OSError("blocked by auditor")
subprocess.Popen=_blk; subprocess.run=_blk; subprocess.check_output=_blk; subprocess.call=_blk
import urllib.request; urllib.request.urlopen=_blk
from PySide6 import QtWidgets, QtCore, QtGui
app=QtWidgets.QApplication([])
from palisade_qt import theme, ops
from palisade_qt.kit import DetailCard
try:
    from palisade_qt.kit import tiles; tiles.urlopen=_blk
except Exception as e: print("tiles", e)
from palisade_qt.shell import PalisadeHub
try: theme.load_fonts(); theme.set_app_font(app)
except Exception as e: print("fonts", e)
app.setStyleSheet(theme.qss("dark"))
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.01)
# standalone card
c=DetailCard("X"); c.set_hero("—","select a contact"); c.show(); pump(50)
print("standalone empty card: sizeHint", c.sizeHint().toTuple(), "minHint", c.minimumSizeHint().toTuple(), "hero visible", c.hero.isVisible(), "hero h", c.hero.height() if c.hero.isVisible() else 0, "vpolicy", c.sizePolicy().verticalPolicy())
c.close()
for demo in (False, True):
    try: hub=PalisadeHub(demo=demo, mode="dark")
    except TypeError: hub=PalisadeHub(demo=demo)
    hub.resize(1280,720); hub.show(); pump(300)
    print("== hub demo=%s size %s" % (demo, hub.size().toTuple()))
    names=[n for n,_ in ops.CALLSIGNS] if hasattr(ops,"CALLSIGNS") else list(hub.pages)
    for name in names:
        try: hub.open_callsign(name)
        except Exception as e: print("open", name, e); continue
        pump(250)
        page=hub.pages[name]
        subs = (page.subtabs() if hasattr(page,"subtabs") else None) or [None]
        for t in subs:
            if t:
                page.switch_subtab(t); pump(250)
            hub.resize(1280,720); pump(60)
            for c in hub.findChildren(DetailCard):
                if c.isVisible() and c.isVisibleTo(hub) and not c.visibleRegion().isEmpty():
                    empty = c.is_empty() if hasattr(c,"is_empty") else (c.hero.text().strip() in ("","—"))
                    print("   %-9s %-9s empty=%-5s card %dx%d hero_vis=%s hero=%r sub=%r" % (name, t, empty, c.width(), c.height(), c.hero.isVisible(), c.hero.text()[:20], c.sub.text()))
                    if empty and not demo:
                        hub.grab().save(os.path.join(HERE,"out","%s_%s_%s.png"%(TAG,name,t)))
    hub.close(); pump(200)
os._exit(0)
