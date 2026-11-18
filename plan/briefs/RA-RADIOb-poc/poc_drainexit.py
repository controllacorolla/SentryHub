import sys, os, time, threading, signal
sys.path.insert(0, sys.argv[1]); os.environ["PATH"] = os.path.join(sys.argv[1], "tests", "fake_bin") + os.pathsep + os.environ["PATH"]
os.environ["FAKE_STATE"] = os.path.join(sys.argv[2], "state")
import iqsource
base = threading.active_count()
s = iqsource.RtlTcpSource(121_500_000, 2048000).open()
print("threads after open:", threading.active_count() - base)
os.kill(s.proc.pid, signal.SIGKILL); time.sleep(0.5)
print("rtl_tcp killed externally -> drain threads left:", threading.active_count() - base)
s.close()
s = iqsource.RtlTcpSource(121_500_000, 2048000).open(); s.close(); time.sleep(0.3)
print("after normal close -> drain threads left:", threading.active_count() - base)
