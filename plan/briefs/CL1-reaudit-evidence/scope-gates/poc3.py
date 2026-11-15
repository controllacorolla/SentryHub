import os, sys, subprocess, time, signal
sys.dont_write_bytecode = True
sys.path.insert(0, "/Users/daltonhayes/SentryHub")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from palisade_qt import shell
# same spawn shape as prowl.py:71 / babel.py:44 / atlas.py:251 (shell=True pipeline, own session)
p = subprocess.Popen("sleep 47 | cat", shell=True, stdout=subprocess.DEVNULL, start_new_session=True)
time.sleep(0.5)
kids = shell.child_pids()
print("direct children:", kids, "pipeline sh pid:", p.pid)
killed = [k for k in kids if k == p.pid and shell._terminate(k)]
time.sleep(0.5)
print("PANIC-style SIGTERM sent to:", killed, "sh exited:", p.poll() is not None)
out = subprocess.run(["pgrep", "-f", "sleep 47"], capture_output=True, text=True).stdout.split()
print("surviving 'sleep 47' pids (the stand-in for rtl_fm):", out)
for x in out:
    try: os.kill(int(x), signal.SIGKILL)
    except OSError: pass
