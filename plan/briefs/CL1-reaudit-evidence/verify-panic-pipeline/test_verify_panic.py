import os, sys, subprocess, time, signal
sys.path.insert(0, "/Users/daltonhayes/SentryHub/tests"); sys.path.insert(0, "/Users/daltonhayes/SentryHub")
from test_cl1_screen import _isolate, _hub, _key, _pump  # noqa
from PySide6 import QtCore

def _alive(tag):
    return subprocess.run(["pgrep", "-f", tag], capture_output=True, text=True).stdout.split()

def test_real_panic_on_shell_pipeline():
    from palisade_qt import shell
    hub = _hub(demo=False)
    procs = []
    try:
        # prowl.py:71 / babel.py:44 shape
        a = subprocess.Popen("sleep 4711 | cat", shell=True, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
        # atlas.py:251/263 shape (no new session)
        b = subprocess.Popen("sleep 4712 | cat", shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        # control: argv child, no shell
        c = subprocess.Popen(["sleep", "4713"])
        procs = [a, b, c]
        time.sleep(0.5)
        print("\nchild_pids():", shell.child_pids(), "a/b/c:", a.pid, b.pid, c.pid)
        _key(hub, QtCore.Qt.Key_F12)          # the real key, real _list_children/_kill
        time.sleep(0.7)
        print("banner:", hub.panic_banner.text())
        print("sh a exited:", a.poll() is not None, "sh b exited:", b.poll() is not None, "c exited:", c.poll() is not None)
        for t in ("sleep 4711", "sleep 4712", "sleep 4713"):
            print("survivors of", repr(t), _alive(t))
        # the owning worker's own stop (prowl.py:472-476) now skips it because poll() is not None
        print("prowl-style guard 'proc.poll() is None' ->", a.poll() is None)
    finally:
        for t in ("sleep 471",):
            for x in _alive(t):
                try: os.kill(int(x), signal.SIGKILL)
                except OSError: pass
        hub.close(); _pump(150)
