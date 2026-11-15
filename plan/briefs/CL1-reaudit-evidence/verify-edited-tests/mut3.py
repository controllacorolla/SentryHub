import sys, shutil, subprocess, os, pathlib
S = pathlib.Path(sys.argv[1]); PY = sys.argv[2]
MUTS = {
 "A_sweep_stop_leaks": ("branch", "palisade_qt/sweep.py",
   "        for w in getattr(self, \"_workers\", []):\n            w.stop()\n            w.quit()\n            w.wait(3000)\n        self._workers = []\n        super().stop()",
   "        super().stop()"),
 "B_bench_tx_always_enabled": ("branch", "palisade_qt/bench_app.py", "self.tx_btn.setEnabled(ok)", "self.tx_btn.setEnabled(True)"),
 "C_sweep_publishes_demo": ("branch", "palisade_qt/sweep.py", "if not msg.get(\"demo\"):", "if True:"),
 "D_sweep_never_publishes": ("branch", "palisade_qt/sweep.py", "if not msg.get(\"demo\"):", "if False:"),
 "E_recon_cards_enabled": ("branch", "palisade_qt/recon.py", "            b.setEnabled(active)\n        self.target.setEnabled(active)", "            b.setEnabled(True)\n        self.target.setEnabled(True)"),
 "F_engage_active_on_refusal": ("branch", "palisade_qt/panels.py", "(\"ACTIVE — \" if ok else \"REFUSED — \") + why", "\"ACTIVE — \" + why"),
 "G_main_recon_stop_leaks": ("main", "palisade_qt/recon.py",
   "        for w in getattr(self, \"_workers\", []):\n            w.stop()\n            w.quit()\n            w.wait(3000)\n        self._workers = []\n        super().stop()",
   "        super().stop()"),
}
only = sys.argv[3:]
for name, (base, path, old, new) in MUTS.items():
    if only and name not in only: continue
    d = S / "mut" / name
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(S / base, d)
    f = d / path; t = f.read_text()
    assert t.count(old) == 1, (name, t.count(old))
    f.write_text(t.replace(old, new))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(S / "home"), PYTHONUNBUFFERED="1")
    out = open(S / ("out_%s.txt" % name), "w")
    subprocess.Popen([PY, "-m", "pytest", "-p", "no:cacheprovider", "-v", "-o", "faulthandler_timeout=240", "tests/test_palisade_qt.py"] + (["tests/test_cl1_screen.py"] if base == "branch" else []), cwd=d, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
