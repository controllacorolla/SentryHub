import os, sys, time
D=os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["HOME"]=D+"/home"
sys.path.insert(0, D+"/main"); sys.dont_write_bytecode=True
from PySide6 import QtWidgets
app=QtWidgets.QApplication([])
from palisade_qt import recon, radio_arbiter
print("module from", recon.__file__)
cls=[c for c in vars(recon).values() if isinstance(c,type) and hasattr(c,"start") and getattr(c,"TITLE",None)=="RECON"][0]
sent=[]
class TB:
    def set_chip(self,k,text,state=None,ok=None): sent.append((k,text))
p=cls(demo=False); p.attach_topbar(TB()); p.set_active(True); p.start()
t=0
while t<6000:
    app.processEvents(); time.sleep(0.01); t+=10
print("MAIN top-chip sdr texts:", {x[1] for x in sent if x[0]=="sdr"})
p.stop()
