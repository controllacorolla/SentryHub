"""RA-CL1c mutation harness: copy tree, apply one mutation, run tests/test_cl1_fix2.py."""
import os, shutil, subprocess, sys, tempfile
SRC = sys.argv[1]; PY = sys.argv[2]; only = sys.argv[3:]
M = {
 "m1_no_sigkill": ("palisade_qt/procs.py", "        send(signal.SIGKILL, left)\n", "        pass\n"),
 "m2_no_killpg": ("palisade_qt/procs.py", "                os.killpg(g, sig)\n", "                pass\n"),
 "m3_shell_no_on_panic": ("palisade_qt/shell.py", "                    did += page.on_panic()\n", "                    pass\n"),
 "m4_bench_no_uncheck": ("palisade_qt/bench_app.py", "        self.ack.setChecked(False)          #", "        pass  #"),
 "m5_ackall_everything": ("palisade_qt/panels.py", "return self.store.ack_all(upto_id=self._seen_id)", "return self.store.ack_all()"),
 "m6_seen_never_set_safe": ("palisade_qt/panels.py", "        self._seen_id = self.store.last_id()       #", "        self._seen_id = 10**9  #"),
 "m7_radios_free_on_error": ("palisade_qt/panels.py", "            owner = radio_arbiter.arbiter.owner()\n        except Exception as e:", "            owner = radio_arbiter.arbiter.owner()\n        except ZeroDivisionError as e:"),
 "m8_eng_no_try": ("palisade_qt/panels.py", "            info = _engagement().info()\n            active = bool(info[\"active\"])\n        except Exception as e:", "            info = _engagement().info()\n            active = bool(info[\"active\"])\n        except ZeroDivisionError as e:"),
 "m9_restore_by_row": ("palisade_qt/kit/feed.py", "            if row_key(r, cols) == key:", "            if i == 1:"),
 "m10_no_detail_emit": ("palisade_qt/kit/feed.py", "                self.selected.emit(r)              #", "                pass  #"),
 "m11_atlas_no_fit": ("palisade_qt/atlas.py", "                              fit_viewport=True)", "                              fit_viewport=False)"),
 "m12_atlas_type_back": ("palisade_qt/atlas.py", "[(\"label\", \"CONTACT\"), (\"rng\", \"NM\"), (\"alt\", \"ALT\")]", "[(\"label\", \"CONTACT\"), (\"kind\", \"TYPE\"), (\"rng\", \"NM\"), (\"alt\", \"ALT\")]"),
 "m13_navlabel_hidden": ("palisade_qt/kit/topbar.py", "        self.label.raise_()\n", "        self.label.raise_()\n        self.label.setGeometry(0, 0, 0, 0)\n"),
 "m14_navlabel_14px": ("palisade_qt/theme.py", "QLabel.navlabel {{ color: {muted}; font-size: {status}px; }}", "QLabel.navlabel {{ color: {muted}; font-size: 14px; }}"),
 "m15_state_words_off": ("palisade_qt/chrome.py", " and scope[0].strip().upper() not in STATE_WORDS", ""),
 "m16_no_vscroll_refit": ("palisade_qt/kit/feed.py", "            self._fit.start()\n        return super().eventFilter", "            pass\n        return super().eventFilter"),
 "m17_no_tooltip": ("palisade_qt/kit/feed.py", "if role in (QtCore.Qt.DisplayRole, QtCore.Qt.ToolTipRole):", "if role == QtCore.Qt.DisplayRole:"),
 "m18_no_elide": ("palisade_qt/kit/feed.py", "        self.view.setTextElideMode(QtCore.Qt.ElideRight)\n", "        self.view.setTextElideMode(QtCore.Qt.ElideNone)\n"),
 "m19_radios_takeover_enabled": ("palisade_qt/panels.py", "            self.takeover_btn.setEnabled(False)\n            self._refresh_table()\n            return", "            self.takeover_btn.setEnabled(True)\n            self._refresh_table()\n            return"),
}
for name, (f, a, b) in M.items():
    if only and name not in only: continue
    d = tempfile.mkdtemp(prefix="mut_")
    subprocess.run("git -C %s archive HEAD | tar -x -C %s" % (SRC, d), shell=True, check=True)
    p = os.path.join(d, f); s = open(p).read()
    if s.count(a) != 1:
        print(name, "PATTERN COUNT", s.count(a)); shutil.rmtree(d); continue
    open(p, "w").write(s.replace(a, b))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([PY, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests/test_cl1_fix2.py"],
                       cwd=d, env=env, capture_output=True, text=True)
    last = [l for l in r.stdout.splitlines() if l.strip()][-1:]
    fails = [l.split("::")[1].split(" ")[0] for l in r.stdout.splitlines() if l.startswith("FAILED")]
    print("%-28s %s  %s" % (name, "CAUGHT" if r.returncode else "SURVIVED", (fails or last)), flush=True)
    shutil.rmtree(d)
