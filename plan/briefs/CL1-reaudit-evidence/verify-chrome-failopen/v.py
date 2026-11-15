import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["HOME"]=tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"]=os.environ["HOME"]
REPO="/Users/daltonhayes/SentryHub"
mode=sys.argv[1]
from PySide6 import QtWidgets
app=QtWidgets.QApplication([])
if mode=="nopath":
    # only the package's parent on path? package is palisade_qt under REPO, so REPO must be on path to import it at all.
    # Simulate: import package via importlib from a path entry that is then removed.
    sys.path.insert(0,REPO)
    from palisade_qt import chrome
    sys.path.remove(REPO)
    print("txguard in sys.modules:", "txguard" in sys.modules, "engagement:", "engagement" in sys.modules)
    print("read_tx:", chrome.read_tx(), "read_engagement:", chrome.read_engagement())
    sys.exit()
sys.path.insert(0,REPO)
from palisade_qt import chrome
import txguard, engagement
print("engagement.start sig:", engagement.start.__doc__ and engagement.start.__doc__[:80])
txguard.arm(True)
print("start ->", engagement.start("Op","ROE",["10.0.0.*"],"N0CALL"))
st=chrome.ChromeState(demo=False, poll_ms=10**7)
st.poll(); print("before:", st.tx(), st.engagement(), "| engine armed", txguard.is_armed(), "active", engagement.info().get("active"))
from palisade_qt.kit import topbar
tb=topbar.TopBar() if mode!="x" else None
def words():
    out={}
    for k,s in tb.slots.items():
        out[k]=(s.value.text(), getattr(s.glyph,"shape",None) or getattr(s.glyph,"_shape",None))
    return out
tb.set_state(st.mode, st.radio(), st.tx(), st.engagement()); print("topbar before:", words())
oa, oi = txguard.is_armed, engagement.info
def boom(*a,**k): raise RuntimeError("x")
txguard.is_armed=boom; engagement.info=boom
st.poll(); print("after raise:", st.tx(), st.engagement(), "| engine armed", oa(), "active", oi().get("active"))
tb.set_state(st.mode, st.radio(), st.tx(), st.engagement()); print("topbar after:", words())
tb.set_state('UNKNOWN', ('ERROR','x'), 'FAULT', ('ERROR','','')); print("topbar garbage:", words())
engagement.info=lambda: None
try:
    st.poll(); print("non-dict: no raise", st.engagement())
except Exception as e: print("non-dict raises:", type(e).__name__, e, "| held value:", st.engagement())
txguard.is_armed=oa; engagement.info=oi
txguard.arm(False); engagement.stop() if hasattr(engagement,"stop") else None
