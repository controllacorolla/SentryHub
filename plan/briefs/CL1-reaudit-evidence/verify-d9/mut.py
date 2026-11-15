import sys, shutil, subprocess, os
W, PY = sys.argv[1], sys.argv[2]
muts = {
 "baseline": [],
 "forge_result_green": [("palisade_qt/forge.py", '(self._tok["warn"] if ok else self._tok["muted"])', '(self._tok["live"] if ok else self._tok["muted"])')],
 "engage_panel_green": [("palisade_qt/panels.py", 'self.eng_msg.setStyleSheet("color:%s;" % self._tok["warn"])', 'self.eng_msg.setStyleSheet("color:%s;" % self._tok["live"])')],
 "slots_green": [("palisade_qt/kit/topbar.py", 'self.slots["tx"].set("ARMED", "square", t["alert"])', 'self.slots["tx"].set("ARMED", "square", t["live"])'),
                 ("palisade_qt/kit/topbar.py", 'self.slots["engagement"].set("ACTIVE", "diamond", t["warn"], scope)', 'self.slots["engagement"].set("ACTIVE", "diamond", t["live"], scope)')],
 "control_forge_card_green": None,
}
for name, edits in muts.items():
    if edits is None: continue
    d = os.path.join(W, "m_" + name)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(os.path.join(W, "tree"), d)
    for f, a, b in edits:
        p = os.path.join(d, f); s = open(p).read()
        assert s.count(a) == 1, (name, f, s.count(a))
        open(p, "w").write(s.replace(a, b))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=os.path.join(W, "home"))
    os.makedirs(env["HOME"], exist_ok=True)
    r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=d, env=env, capture_output=True, text=True)
    print("==", name, "rc", r.returncode); print("\n".join(r.stdout.strip().splitlines()[-6:]))
