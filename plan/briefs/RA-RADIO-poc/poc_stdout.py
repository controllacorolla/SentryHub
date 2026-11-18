import os, sys, time
sys.path.insert(0, sys.argv[1])
os.environ["PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin") + ":" + os.environ["PATH"]
os.environ["FAKE_STATE"] = os.path.abspath("fake_state.txt")
import iqsource
s = iqsource.RtlTcpSource(121_500_000, 2048000).open()
print("argv:", s.proc.stages)
last_sent = None
for n in range(6000):
    hz = 118_000_000 + (n % 760) * 25_000
    s.set_freq(hz); last_sent = hz
    if n % 1000 == 999:
        s.read(0.05); time.sleep(0.3)
        applied = int(open(os.environ["FAKE_STATE"]).read())
        print("retunes sent=%d  rtl_tcp applied=%d  sent=%d  match=%s" % (n+1, applied, hz, applied == hz))
raw, iq = s.read(0.05)
print("IQ still flowing after stall: %d samples, alive=%s" % (iq.size, s.alive()))
s.close()
