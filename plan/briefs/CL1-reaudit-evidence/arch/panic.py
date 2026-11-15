from common import *
import subprocess, signal
h = hub(demo=False)
# spawned exactly as prowl._open_nwr_pipe / babel._open_pipe spawn a decoder pipeline (prowl.py:71, babel.py:44)
proc = subprocess.Popen("sleep 3001 | sleep 3002", shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True)
time.sleep(0.5)
def members():
    out = subprocess.run(["ps", "-axo", "pid,ppid,pgid,command"], capture_output=True, text=True).stdout
    return [l.strip() for l in out.splitlines() if str(proc.pid) == l.split()[2] ]
print("before:", members())
did = h.panic(); pump(500)
print("panic said:", did)
print("shell poll:", proc.poll())
print("after:", members())
try: os.killpg(proc.pid, signal.SIGKILL)
except Exception as e: print("cleanup", e)
time.sleep(0.3); print("cleanup left:", members())
h.close(); pump(200)
