import sys, os, subprocess, shutil
# usage: python3 mutate2.py <worktree> <scratch-dir> [M1 M5 ...]   (runs from a git archive copy, never the worktree)
WT, S = sys.argv[1], sys.argv[2]
M = {
 "M1 B7 requeue call removed": ("palisade_qt/iqworker.py", "                        self._requeue(p)\n", "                        pass\n"),
 "M2 B6 text-mode drain": ("iqsource.py", "stderr_last=subprocess.STDOUT, text=False, bufsize=0)", "stderr_last=subprocess.STDOUT)"),
 "M3 C3 back-off reset removed": ("palisade_qt/iqworker.py", "                    self._fault_n = 0\n", ""),
 "M5 C1 PRISM START retry_now removed": ("palisade_qt/prism.py", "                    w.retry_now()                # RA-RADIOc C1", "                    pass  #"),
 "M6 C1 PROWL Enter retry branch removed": ("palisade_qt/prowl.py", "        if isinstance(w, FastScanWorker) and w.faulted and self._active:", "        if False:"),
 "M7 C1 retry_now does not clear the fault": ("palisade_qt/iqworker.py", "        self._fault_n = 0\n        self._fault = None\n        self.poke()", "        self.poke()"),
 "M8 C2 on_source_closed guard removed": ("palisade_qt/iqworker.py", "        try:\n            self.on_source_closed()\n        except Exception:                                # RA-RADIOc C2: teardown never kills\n            pass ", "        if 1:\n            self.on_source_closed()\n        if 0:\n            pass "),
 "M9 C2 PROWL held-off before finished": ("palisade_qt/prowl.py", "        if w is not None and not self.demo and self._active and not self.swapping() \\\n                and isinstance(w, (ScanWorker, FastScanWorker)) and w.isFinished():", "        if w is not None and getattr(w, 'held_off', False) and self._active:\n            w.set_active(True)\n            return True\n        if w is not None and not self.demo and self._active and not self.swapping() \\\n                and isinstance(w, (ScanWorker, FastScanWorker)) and w.isFinished():"),
 "M10 C4a cancel-path close removed": ("palisade_qt/iqworker.py", "                if src is not None:                      # RA-RADIOc C4: never leave a\n                    try:                                 # half-open rtl_tcp on the dongle\n                        src.close()", "                if False:\n                    try:\n                        src.close()"),
 "M11 C4b requeue unconditional": ("palisade_qt/iqworker.py", "                    if isinstance(e, (iqsource.SourceError, OSError)):\n                        self._requeue(p)", "                    if True:\n                        self._requeue(p)"),
 "M12 retry countdown text removed": ("palisade_qt/iqworker.py", ' + " · retry in %ds" % left', ""),
}
only = sys.argv[3:] 
for name, (f, a, b) in M.items():
    if only and name.split()[0] not in only: continue
    d = os.path.join(S, "mut"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    subprocess.run("git -C %s archive HEAD | tar -x -C %s" % (WT, d), shell=True, check=True)
    p = os.path.join(d, f); s = open(p).read(); assert s.count(a) == 1, (name, s.count(a)); open(p, "w").write(s.replace(a, b, 1))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_radio_sdrpp.py",
                        "--timeout=60", "--timeout-method=thread", "-q", "-rf"], cwd=d, env=env, capture_output=True, text=True)
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAILED")]
    print("%-45s %s | %s" % (name, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:], fails), flush=True)
