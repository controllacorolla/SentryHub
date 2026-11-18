import sys, os, time
sys.path.insert(0, sys.argv[1]); os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
import iqsource
from palisade_qt.iqworker import TunerWorker
d = sys.argv[2] if len(sys.argv) > 2 else "/tmp"
p = os.path.join(d, "iq_20261118-000000Z_121500000Hz_2048000sps.cu8")
open(p, "wb").write(b"\x80" * 100000); os.chmod(p, 0)
try:
    open(p, "rb").close(); print("NOTE: running as root, chmod ineffective; use missing file instead"); os.remove(p)
except PermissionError: pass
st = []
w = TunerWorker(source="file", file_path=p, audio=False)
w.status.connect(st.append)
w.start()
t = time.monotonic()
while time.monotonic() - t < 3: app.processEvents(); time.sleep(0.02)
print("file source, unreadable/missing file: thread running =", w.isRunning(), "| finished =", w.isFinished())
print("last statuses:", [s.get("sdr", {}).get("text") for s in st][-3:])
# PRISM: START after the thread died
from palisade_qt import prism
pg = prism.PrismApp(demo=False) if hasattr(prism, "PrismApp") else None
pg._worker = w
pg._faulted = True; pg._user_stopped = False
pg._sync_run_btn(); print("PRISM button before:", pg.run_btn.text(), pg.run_btn.property("run"))
pg.run_btn.click()
print("PRISM button after START:", pg.run_btn.text(), pg.run_btn.property("run"), "| worker running:", w.isRunning())
