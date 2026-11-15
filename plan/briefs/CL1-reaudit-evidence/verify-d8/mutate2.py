"""Mutation run for the D8 'SURVIVED' claims. Operates only on the scratch copy in ./base."""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "base2")
PY = os.path.join(HERE, "..", "..", "venv312", "bin", "python")
SHELL = "palisade_qt/shell.py"
PROWL = "palisade_qt/prowl.py"

M = {
 "no_r_key": (SHELL, '''        if low == "r":
            self.open_panel("radios")
            return True
''', ''),
 "no_e_key": (SHELL, '''        if low == "e":
            self.open_panel("engagement")
            return True
''', ''),
 "no_m_key": (SHELL, '''        if low == "m":
            self.topbar.toggle_mute()
            return True
''', ''),
 "no_brackets_prowl_scan": (PROWL, '''            if text in "[]":
                n = self.bank_combo.count()''', '''            if text in "":
                n = self.bank_combo.count()'''),
 "no_brackets_prowl_fm": (PROWL, '''elif self._submode == "FM" and text in "[]":''',
                          '''elif self._submode == "FM" and text in "":'''),
 "no_enter_ack_in_drawer": (SHELL, '''            if overlay is self.alerts_drawer and key in (K.Key_Return, K.Key_Enter) and not typing:
                self.alerts_drawer.ack_selected()
                return True
''', ''),
 "panic_not_with_overlay_open": (SHELL,
   '''if key == QtGui.QKeySequence(PANIC_KEY)[0].key():''',
   '''if key == QtGui.QKeySequence(PANIC_KEY)[0].key() and overlay is None:'''),
 "key_target_any_widget": (SHELL, '''        focus = QtWidgets.QApplication.focusWidget()
        if focus is not None and focus.window() is self:
            return obj is focus
        return obj is self

    def handle_key''', '''        return True

    def handle_key'''),
 "no_modifier_guard": (SHELL, '''        if mods & (K.ControlModifier | K.AltModifier | K.MetaModifier):
            return False
''', ''),
 # controls: mutants the claim says are KILLED
 "CTRL_no_slash": (SHELL, '''        if text == "/":
            self.open_panel("palette")
            return True
''', ''),
 "CTRL_no_panic_key": (SHELL, '''        if key == QtGui.QKeySequence(PANIC_KEY)[0].key():      # works everywhere, even while typing
            self.panic()
            return True
''', ''),
 "CTRL_no_a_key": (SHELL, '''        if low == "a":
            self.open_panel("alerts")
            return True
''', ''),
}

only = sys.argv[1:]
env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
for name, (path, old, new) in M.items():
    if only and name not in only:
        continue
    fp = os.path.join(BASE, path)
    src = open(fp).read()
    if src.count(old) != 1:
        print("MUTANT %-30s NOT APPLIED (matches=%d)" % (name, src.count(old)), flush=True)
        continue
    open(fp, "w").write(src.replace(old, new))
    try:
        r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                            "tests/test_cl1_screen.py", "tests/test_palisade_qt.py"],
                           cwd=BASE, env=env, capture_output=True, text=True, timeout=1500)
        tail = r.stdout.strip().splitlines()
        failed = [l for l in tail if l.startswith("FAILED")]
        print("MUTANT %-30s rc=%d  %s" % (name, r.returncode, tail[-1] if tail else ""), flush=True)
        for f in failed:
            print("     ", f[:170], flush=True)
    finally:
        open(fp, "w").write(src)
