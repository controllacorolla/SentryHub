import os, sys, time, subprocess, signal
os.environ["QT_QPA_PLATFORM"]="offscreen"; sys.dont_write_bytecode=True
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from PySide6 import QtWidgets
app=QtWidgets.QApplication([])
from palisade_qt import theme, shell, chrome, panels
import txguard, engagement
engagement.reset(); txguard.reset_session()
def pump(ms):
    t=time.time()
    while time.time()-t<ms/1000: app.processEvents(); time.sleep(0.005)
def alive(pid):
    try: os.kill(pid,0)
    except OSError: return False
    # zombie check
    st=subprocess.run(["ps","-o","stat=","-p",str(pid)],capture_output=True,text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")
hub=shell.PalisadeHub(demo=False, mode="dark"); hub.resize(1280,720); hub.show(); pump(300)
assert hub._list_children is shell.child_pids and hub._kill is shell._terminate
print("children before spawning:", shell.child_pids())
a=subprocess.Popen("sleep 301 | cat", shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
b=subprocess.Popen(["/bin/sh","-c","trap '' TERM; while :; do sleep 1; done"], start_new_session=True)
c=subprocess.Popen(["sleep","302"], start_new_session=True)   # plain argv child (prism.py:77 shape)
time.sleep(0.5)
grp=[int(x) for x in subprocess.run(["pgrep","-g",str(a.pid)],capture_output=True,text=True).stdout.split()]
print("A sh pid",a.pid,"group",grp,"B",b.pid,"C",c.pid,"direct children:",shell.child_pids())
did=hub.panic(); pump(1500)
for p in (a,b,c): p.poll()
print("did:",did)
print("A sh alive:",a.returncode is None,"| A pipeline members alive:",{p:alive(p) for p in grp if p!=a.pid})
print("B (TERM-ignoring) alive:",b.returncode is None,"| C plain child alive:",c.returncode is None)
print("banner:",hub.panic_banner.text())
for p in grp+[b.pid,c.pid]:
    try: os.kill(p, signal.SIGKILL)
    except OSError: pass
engagement.reset(); txguard.reset_session()
hub.close(); pump(300)
