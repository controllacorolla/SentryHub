from common import *
import subprocess, os, signal
hub=mkhub(demo=False)
hub._list_children=shell.child_pids; hub._kill=shell._terminate      # the REAL seams, on this test process's own children only
def alive(pid):
    try: os.kill(pid,0); return True
    except OSError: return False
# A: shell pipeline like prowl/_open_nwr_pipe (shell=True, start_new_session=True): sh -> sleep | cat
a=subprocess.Popen("sleep 300 | cat", shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
# B: a child that ignores SIGTERM
b=subprocess.Popen(["/bin/sh","-c","trap '' TERM; while :; do sleep 1; done"], start_new_session=True)
time.sleep(0.5)
gc=[int(x) for x in subprocess.run(["pgrep","-g",str(a.pid)],capture_output=True,text=True).stdout.split()]
print("direct children:", shell.child_pids(), " pipeline group members:", gc)
txguard.arm(True)
did=hub.panic(); pump(800)
a.poll(); b.poll()
print("did:", did)
print("sh(A) alive:", a.returncode is None, "| pipeline members alive:", {p:alive(p) for p in gc if p!=a.pid}, "| TERM-ignoring child B alive:", b.returncode is None)
print("banner:", hub.panic_banner.text())
for p in gc+[b.pid]:
    try: os.kill(p, signal.SIGKILL)
    except OSError: pass
hub.close(); pump(300)
