"""Regression tests for bugs fixed in scout.py during the code audit."""
import subprocess
import sys
import threading
import time

import scout


def test_nmap_scan_exposes_proc_so_stop_can_kill_it():
    """Stop / close must reach a running nmap. Since CL2 the scan is gated (netpent.prepare) and
    runs through the executor, which hands back a stoppable process-group handle."""
    import engagement as E
    E.reset()
    try:
        E.start("own lan", "self-owned", ["10.0.0.0/24"], "KD0ABC")
        procs, sf = [], threading.Event()

        def slow_nmap(argv, **kw):            # a silent, slow "nmap"
            return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                    start_new_session=True, stdout=subprocess.PIPE, text=True)
        ok, why = scout.scan_network(lambda h: None, lambda t, f: None, sf, spawner=slow_nmap,
                                     local_net=lambda: "10.0.0.0/24", procs=procs)
        assert ok and procs, "nmap's handle not exposed: Stop/close can't reach it"
        procs[0].stop("test")                  # what kill_nmap() does
        end = time.time() + 5
        while procs[0].running() and time.time() < end:
            time.sleep(0.02)
        assert not procs[0].running() and procs[0].proc.poll() is not None
    finally:
        E.reset()
