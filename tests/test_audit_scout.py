"""Regression tests for bugs fixed in scout.py during the code audit."""
import threading
import time

import scout


def test_nmap_scan_exposes_proc_so_stop_can_kill_it(monkeypatch):
    real = scout.subprocess.Popen
    monkeypatch.setattr(scout.subprocess, "Popen",
                        lambda cmd, **k: real(["sleep", "30"], **k))   # a silent, slow "nmap"
    procs, sf = [], threading.Event()
    th = threading.Thread(target=scout.nmap_scan,
                          args=("10.0.0.0/24", lambda h: None, lambda t, f: None, sf),
                          kwargs={"procs": procs}, daemon=True)
    th.start()
    end = time.time() + 3
    while not procs and time.time() < end:
        time.sleep(0.02)
    assert procs, "nmap's Popen not exposed: Stop/close can't reach it"
    import suite as S
    S.stop_group(procs[0], grace=0.5)        # what kill_nmap() does
    th.join(5)
    assert not th.is_alive() and procs[0].poll() is not None
