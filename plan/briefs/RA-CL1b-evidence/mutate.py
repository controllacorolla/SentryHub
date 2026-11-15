import os, sys, subprocess, shutil, json, concurrent.futures as cf
S = os.path.dirname(os.path.abspath(__file__)); REPO = "/Users/daltonhayes/SentryHub"
PY = S + "/venv/bin/python"
MUTS = {
 "m1_no_sigkill_escalation": ("palisade_qt/procs.py", "        send(signal.SIGKILL, left)\n", "        pass\n"),
 "m2_no_killpg": ("palisade_qt/procs.py", "                os.killpg(g, sig)\n", "                pass\n"),
 "m3_no_descendants": ("palisade_qt/procs.py", "for p in [r] + descendants(r, run=run) + members:", "for p in [r] + members:"),
 "m4_popup_not_closed": ("palisade_qt/shell.py", "                    popup.close()\n", "                    pass\n"),
 "m5_drawer_no_select_id": ("palisade_qt/panels.py", "        self.select_id(keep)  ", "        pass  #"),
 "m6_trim_drops_unacked": ("palisade_qt/panels.py", "            if self.items[i][\"acked\"]:\n", "            if True:\n"),
 "m7_mute_optimistic": ("palisade_qt/kit/topbar.py", "        self.mute.setChecked(muted is True)\n", "        pass\n"),
 "m8_fault_not_shown": ("palisade_qt/kit/topbar.py", "        if self.audio_fault:\n            self.mute.setText(\"♪!\")", "        if False:\n            self.mute.setText(\"♪!\")"),
 "m9_bench_no_reread": ("palisade_qt/bench_app.py", "        if not self._stopped:\n            self._refresh_gate()", "        pass"),
 "m10_unknown_as_off": ("palisade_qt/chrome.py", "    except Exception:\n        return \"UNKNOWN\"\n    if armed:", "    except Exception:\n        return \"OFF\"\n    if armed:"),
 "m11_panic_no_banner_survivors": ("palisade_qt/procs.py", "    if bad:\n        text +=", "    if False:\n        text +="),
 "m12_mixer_on_gui_thread": ("palisade_qt/kit/audio.py", "        self._q.put((op, arg))\n", "        self._q.put((op, arg)); import time; time.sleep(0.6 if op != 'get' else 0)\n"),
}
def run(name):
    f, old, new = MUTS[name]
    d = os.path.join(S, "mut", name); shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(REPO, d, ignore=shutil.ignore_patterns(".git", "__pycache__", "plan", "renders", "concept"))
    p = os.path.join(d, f); src = open(p).read()
    if old not in src: return name, "PATTERN NOT FOUND"
    open(p, "w").write(src.replace(old, new, 1))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([PY, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests/test_cl1_fix.py", "tests/test_cl1_screen.py"],
                       cwd=d, env=env, capture_output=True, text=True, timeout=900)
    tail = [l for l in r.stdout.splitlines() if l.startswith("FAILED") or "passed" in l or "failed" in l][-2:]
    shutil.rmtree(d, ignore_errors=True)
    return name, ("CAUGHT " if r.returncode else "SURVIVED ") + " | ".join(tail)
with cf.ThreadPoolExecutor(4) as ex:
    res = dict(ex.map(run, MUTS))
print(json.dumps(res, indent=1))
